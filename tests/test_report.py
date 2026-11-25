from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

from easm_agent.cli import main
from easm_agent.models import (
    Agent365Package,
    AgentEvidence,
    AssessmentMeasurement,
    Collection,
    CopilotAgentEvidence,
    CostRecord,
    EvaluationRun,
    EvidenceSource,
    FieldStatus,
    Finding,
    Issue,
    LogSetting,
    TargetAssessment,
)
from easm_agent.report import (
    digest,
    json_bytes,
    latest_raw,
    load_result,
    presentation_name,
    raw_name,
    report_name,
    write_reports,
)
from easm_agent.report_backdata import metrics_by_key, report_metrics
from easm_agent.report_excel import presentation_evidence_rows, write_workbook
from easm_agent.report_template import CRITERIA_SHEET, RESULT_SHEET

ROOT = Path(__file__).parents[1]
EXTRA_SHEETS = [
    "수집결과 근거", "수집 Raw 데이터", "수집이슈 Raw 데이터", "필드누락사유",
]
SHEETS = [
    "1. 모델 구조", "2. 질문 및 확인사항", "3. 성숙도 정의", CRITERIA_SHEET, "5. 점수 산정 방식",
    RESULT_SHEET, *[f"{index}. {title}" for index, title in enumerate(EXTRA_SHEETS, 7)],
]
TITLES = {title: f"{index}. {title}" for index, title in enumerate(EXTRA_SHEETS, 7)}
SECRETS = (
    "secret-value", "nested-secret", "facts-secret", "private-person", "private-sponsor",
    "private-owner", "someone@example.invalid", "do-not-export", "api-key-in-evidence",
)
NO_AZURE = patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("no Azure calls"))
pytestmark = pytest.mark.usefixtures("legacy_report_template", "legacy_presentation_template")


def sample() -> Collection:
    when = datetime(2026, 11, 3, tzinfo=UTC)
    return Collection(
        collected_at=when, subscriptions=["000123"],
        agents=[AgentEvidence(
            collected_at=when, platform="manual", agent_id="000001", agent_name="테스트 Agent",
            subscription_id="000123", detection_confidence="manual",
            owner="private-person", sponsor="private-sponsor", cost_30d=0, guardrail_applied=False,
            tags={"secret": "secret-value", "access_token": "nested-secret",
                  "contact": "someone@example.invalid"},
            evidence_refs=[r"C:\evidence\20261103\raw.json"],
        )],
        evaluations=[EvaluationRun(
            subscription_id="000123", project_id="000456", run_id="000789", status="failed",
            passed_items=0, failed_items=3, errored_items=2, total_items=5,
        )],
        costs=[CostRecord(subscription_id="000123", resource_id="000456", amount=0, currency="USD")],
        logs=[LogSetting(subscription_id="000123", resource_id="000456", enabled=False, retention_days=0)],
        issues=[Issue(collector=name, target="000123", reason="permission_denied", detail="조회 권한 없음")
                for name in ("cost", "logs")],
        facts={"api_key": "facts-secret", "nested": {"owner": "private-owner"}},
    )


def finding(**changes: object) -> Finding:
    values = {"se_code": "BI-SY-09", "scope": "partial", "metric_value": 0, "level": "N/A",
              "reason": "permission_denied", "rationale": "근거가 부족합니다.",
              "next_step": "조회 권한을 확인하세요.", **changes}
    return Finding.model_validate(values)


def test_audit_summary_and_target_table_do_not_promote_pending_results(tmp_path: Path) -> None:
    from easm_agent.provenance import assessment_provenance

    data = sample()
    data.assessment_provenance = assessment_provenance(
        {"grading_profile": "api_configuration_v1", "threshold": 0.8}, {}, "saved_snapshot_reassessment",
    )
    pending = finding(measurement=AssessmentMeasurement(
        complete=False, reason="권한 부족", targets=[
            TargetAssessment(subject="project", reason="필수 값 미확인", evidence_refs=["missing-source"]),
        ],
    ))
    path = tmp_path / "audit.xlsx"
    write_workbook(data, [pending], path)
    book = load_workbook(path)
    summary = book[RESULT_SHEET]
    assert "등급 산정 0개" in summary["B2"].value
    assert "조직 전체 거버넌스 성숙도" in summary["B3"].value
    assert "새 API 수집 아님" in summary["B3"].value
    details = book[TITLES["수집결과 근거"]]
    table = next(table for table in details.tables.values() if table.tableColumns[1].name == "확인 상태")
    _, first, _, _ = range_boundaries(table.ref)
    assert details.cell(first + 1, 2).value == "미확인"
    columns = {details.cell(first, column).value: column for column in range(1, 10)}
    assert details.cell(first + 1, columns["계산 기여값"]).value is None
    values = [str(cell.value) for row in details for cell in row]
    assert data.assessment_provenance.criteria_sha256 in values
    assert any("numerator" in value and "null" in value for value in values)


def test_presentation_evidence_keeps_unavailable_and_distinct_metrics_separate(tmp_path: Path) -> None:
    from easm_agent.models import load_criteria
    from easm_agent.provenance import assessment_provenance

    rows = [
        finding(
            se_code="DS-SY-02", level="L1", reason=None, metric_value=0,
            measurement=AssessmentMeasurement(numerator=0, denominator=2, complete=True),
        ),
        finding(
            se_code="BI-SY-08", level="N/A", reason="permission_denied",
            metric_value=None, measurement=AssessmentMeasurement(complete=False, reason="권한 부족"),
        ),
        finding(
            se_code="BI-SY-09", level="L5", reason=None, metric_value=1,
            measurement=AssessmentMeasurement(numerator=1, denominator=1, complete=True),
        ),
    ]
    path = tmp_path / "report.xlsx"
    data = sample()
    data.assessment_provenance = assessment_provenance(load_criteria(), {}, "evaluation")
    write_workbook(data, rows, path)
    sheet = load_workbook(path)[TITLES["수집결과 근거"]]
    table = next(t for t in sheet.tables.values() if t.tableColumns[0].name == "원본 PPT 항목")
    _, first, last_column, last = range_boundaries(table.ref)
    headers = [sheet.cell(first, col).value for col in range(1, last_column + 1)]
    entries = {
        values[0]: dict(zip(headers, values, strict=True))
        for values in sheet.iter_rows(
            min_row=first + 1, max_row=last, max_col=last_column, values_only=True,
        )
    }
    assert len(entries) == 20
    assert entries["DS-SY-04"]["지표 값"] == "0.00%"
    assert entries["DS-SY-04"]["확인 상태"] == "수집됨"
    assert entries["BI-SY-07"]["지표 값"] is None
    assert entries["BI-SY-07"]["확인 상태"] == "판정 보류"
    assert entries["BI-SY-07"]["사유 코드"] == "permission_denied"
    assert "조회 권한 부족" in entries["BI-SY-07"]["보류 사유·범위 차이"]
    assert entries["BI-SY-08"]["지표 값"] is None
    assert entries["BI-SY-08"]["확인 상태"] == "판정 보류"
    assert entries["BI-SY-08"]["사유 코드"] == "feature_unavailable"


def test_presentation_evidence_requires_the_original_metric_and_complete_measurement() -> None:
    from easm_agent.models import load_criteria
    from easm_agent.provenance import assessment_provenance

    data = sample()
    result = finding(
        se_code="DS-SY-02", level="L5", reason=None, metric_value=1,
        measurement=AssessmentMeasurement(numerator=1, denominator=1, complete=True),
    )
    def row() -> dict:
        return next(
            item for item in presentation_evidence_rows(data, [result])
            if item["원본 PPT 항목"] == "DS-SY-04"
        )
    assert row()["지표 값"] is None
    assert row()["사유 코드"] == "not_found"
    criteria = load_criteria()
    criteria["items"]["DS-SY-02"]["metric"] = "other"
    data.assessment_provenance = assessment_provenance(criteria, {}, "evaluation")
    assert row()["지표 값"] is None
    criteria["items"]["DS-SY-02"]["metric"] = "data_policy_environment_ratio"
    data.assessment_provenance = assessment_provenance(criteria, {}, "evaluation")
    result.measurement = AssessmentMeasurement(numerator=1, denominator=1, complete=False)
    assert row()["지표 값"] is None


@pytest.mark.parametrize("complete,unknown", [(True, False), (False, False), (True, True)])
def test_copilot_backdata_never_turns_unknown_platforms_into_zero_counts(
    tmp_path: Path, complete: bool, unknown: bool,
) -> None:
    data = sample()
    data.facts["copilot_inventory_complete"] = complete
    if not complete:
        data.issues.append(Issue(
            collector="copilot_inventory", target="approved-export", reason="license_missing",
            detail="명시적 라이선스 오류",
        ))
    data.copilot_agents = [
        CopilotAgentEvidence(
            agent_id="11111111-1111-4111-8111-111111111111", environment_id="test-environment",
            platform="agent_builder", owner_present=False,
            evidence_refs=["evidence:copilot-source"],
        ),
        CopilotAgentEvidence(
            agent_id="22222222-2222-4222-8222-222222222222", environment_id="test-environment",
            platform="unclassified_copilot" if unknown else "copilot_studio", owner_present=True,
            evidence_refs=["evidence:copilot-source"],
        ),
    ]
    path = tmp_path / "copilot.xlsx"
    write_workbook(data, [], path)
    values = metrics_by_key(data, [], "fixture")
    count = values["inventory.agent_builder"]
    assert count.value == (1 if complete and not unknown else None)
    assert count.status == ("observed" if complete and not unknown else "unavailable")
    assert count.evidence_refs == ["evidence:copilot-source"]
    if not complete:
        assert count.reason == "license_missing"
    assert values["copilot.owner_missing"].value == (1 if complete else None)
    assert values["creation.history"].value is None
    assert values["security.exposure"].reason == "feature_unavailable"
    assert values["run.mode"].value == "fixture"


def test_report_scale_uses_snapshot_thresholds_without_rounding_them(tmp_path: Path) -> None:
    from easm_agent.models import load_criteria
    from easm_agent.provenance import assessment_provenance

    criteria = load_criteria()
    for config in criteria["items"].values():
        for rule in config["rules"]:
            if rule["level"] == "L3":
                rule["when"]["coverage"]["gte"] = 0.825
    data = sample()
    data.assessment_provenance = assessment_provenance(criteria, {}, "evaluation")
    path = tmp_path / "custom-scale.xlsx"
    write_workbook(data, [], path)
    values = metrics_by_key(data, [], "fixture")
    assert values["criteria.L3.text"].value == "82.5%<=p<90%"


def test_studio_zero_is_an_inventory_response_not_a_tenant_absence_claim() -> None:
    data = sample()
    data.facts["copilot_inventory_complete"] = True
    data.copilot_agents = [CopilotAgentEvidence(
        agent_id="builder", environment_id="env", platform="agent_builder",
    )]
    metrics = {row.key: row for row in report_metrics(data, [], "fixture")}
    assert metrics["inventory.agent_builder"].value == 1
    assert metrics["inventory.copilot_studio"].value == 0
    assert "테넌트 전체 Agent 부재 판정이 아닙니다" in metrics["inventory.copilot_studio"].limitation
    assert "Dataverse 초안·미게시" in metrics["inventory.copilot_studio"].limitation


def test_backdata_preserves_measurement_counts_without_inventing_business_impacts() -> None:
    from easm_agent.models import load_criteria
    from easm_agent.provenance import assessment_provenance

    data = sample()
    data.assessment_provenance = assessment_provenance(load_criteria(), {}, "evaluation")
    rows = [finding(
        se_code="DS-SY-02", level="L1", reason=None, metric_value=0,
        measurement=AssessmentMeasurement(numerator=0, denominator=2, complete=True),
        evidence_refs=["evidence:measurement"],
    ), finding(
        se_code="BI-SY-08", level="N/A", reason="permission_denied",
        measurement=AssessmentMeasurement(numerator=0, denominator=2, complete=False),
    )]
    values = {row.key: row for row in report_metrics(data, rows, "fixture")}
    assert values["se.DS-SY-02.numerator"].value == 0
    assert values["se.DS-SY-02.denominator"].value == 2
    assert values["se.DS-SY-02.denominator"].evidence_refs == ["evidence:measurement"]
    assert values["se.BI-SY-08.numerator"].value is None
    assert values["se.BI-SY-08.denominator"].reason == "permission_denied"
    assert values["business.loss_amount"].value is None
    assert values["business.roi"].reason == "feature_unavailable"


def test_backdata_preserves_all_source_evidence_references() -> None:
    data = sample()
    empty = {row.key: row for row in report_metrics(data, [], "fixture")}["run.evidence_sources"]
    assert empty.value is None
    assert empty.reason == "not_found"

    refs = [f"evidence:{index:064x}" for index in range(542)]
    data.evidence_sources = [
        EvidenceSource(target="first", evidence_refs=refs),
        EvidenceSource(target="second", evidence_refs=[refs[0]]),
    ]
    source = metrics_by_key(data, [], "fixture")["run.evidence_sources"]
    assert source.value == 542
    assert source.evidence_refs == refs


def test_package_usage_backdata_is_per_package_not_a_tenant_sum_and_preserves_field_errors() -> None:
    data = sample()
    data.agent365_packages = [
        Agent365Package(
            package_id="one", manifest_id="same-agent", active_users_30d=7, total_sessions_30d=0,
            exception_count_30d=2.0, last_used_at=data.collected_at,
            detail_evidence_refs=["evidence:package-one"],
            field_status={"exception_count_30d": FieldStatus(reason="error", detail="형식 오류")},
        ),
        Agent365Package(
            package_id="two", manifest_id="same-agent", active_users_30d=7,
            detail_evidence_refs=["evidence:package-two"],
            field_status={"total_sessions_30d": FieldStatus(reason="permission_denied", detail="조회 거부")},
        ),
    ]
    values = {row.key: row for row in report_metrics(data, [], "fixture")}
    assert values["catalog.package.1.active_users_30d"].value == 7
    assert values["catalog.package.2.active_users_30d"].value == 7
    assert values["catalog.package.1.total_sessions_30d"].value == 0
    assert values["catalog.package.2.total_sessions_30d"].value is None
    assert values["catalog.package.2.total_sessions_30d"].reason == "permission_denied"
    assert values["catalog.package.1.exception_count_30d"].reason == "error"
    assert "형식 오류" in values["catalog.package.1.exception_count_30d"].limitation
    assert values["catalog.package.1.last_used_at"].value == data.collected_at.isoformat()
    assert values["catalog.package.1.active_users_30d"].evidence_refs == ["evidence:package-one"]
    assert values["catalog.usage.active_users_30d"].value is None
    assert "중복" in values["catalog.usage.active_users_30d"].limitation
    assert "90일" in values["catalog.usage.scope"].limitation
    data.agent365_packages.append(data.agent365_packages[0].model_copy())
    values = {row.key: row for row in report_metrics(data, [], "fixture")}
    assert values["catalog.package.1.active_users_30d"].value is None
    assert values["catalog.package.3.active_users_30d"].reason == "error"


def test_metadata_backdata_preserves_field_sources_types_null_reasons_and_exact_evidence() -> None:
    fields = {
        "package_type": "custom", "manifest_version": "1.1",
        "app_id": "11111111-1111-4111-8111-111111111111",
        "supported_hosts": ["Teams"], "element_types": ["declarativeAgent"],
        "categories": ["Tools"], "category_count": 1,
        "sensitivity": "general", "sensitivity_present": True,
    }
    refs = {field: ["evidence:" + field] for field in fields}
    package = Agent365Package(
        package_id="one", **fields,
        metadata_field_sources=dict.fromkeys(fields, "catalog"), metadata_evidence_refs=refs,
        detail_evidence_refs=["evidence:unrelated-usage"],
        field_status={"manifest_version": FieldStatus(reason="error", detail="형식 검증 실패")},
    )
    data = sample()
    data.agent365_packages = [package, Agent365Package(
        package_id="two", app_id=fields["app_id"], package_type="custom", category_count=0,
        sensitivity_present=False,
        metadata_field_sources={
            "package_type": "catalog", "app_id": "not_requested",
            "category_count": "detail", "sensitivity_present": "detail",
        },
        metadata_evidence_refs={
            "category_count": ["evidence:empty-categories"], "sensitivity_present": ["evidence:empty-sensitivity"],
        },
        field_status={"sensitivity": FieldStatus(reason="feature_unavailable", detail="자유 문자열 미보존")},
    )]
    metrics = {row.key: row for row in report_metrics(data, [], "fixture")}
    prefix = "catalog.package.1.metadata."
    for field in fields:
        assert metrics[prefix + field].evidence_refs == refs[field]
        assert metrics[prefix + field + ".source"].value == "catalog"
        assert metrics[prefix + field + ".source"].evidence_refs == refs[field]
        assert "고유 Agent 수" in metrics[prefix + field].limitation
    for field in ("supported_hosts", "element_types", "categories"):
        assert json.loads(metrics[prefix + field].value) == fields[field]
    assert metrics[prefix + "sensitivity_present"].value == "true"
    assert "민감도 레이블 적용·정책 실효성" in metrics[prefix + "sensitivity_present"].limitation
    assert metrics[prefix + "manifest_version"].value is None
    assert metrics[prefix + "manifest_version"].reason == "error"
    assert metrics[prefix + "app_id"].value == fields["app_id"]
    prefix = "catalog.package.2.metadata."
    assert metrics[prefix + "category_count"].value == 0
    assert metrics[prefix + "sensitivity_present"].value == "false"
    assert metrics[prefix + "supported_hosts"].value is None
    assert metrics[prefix + "supported_hosts"].reason == "not_found"
    assert metrics[prefix + "sensitivity"].reason == "feature_unavailable"
    assert metrics[prefix + "package_type"].value is None  # The source alone is not field evidence.
    assert metrics[prefix + "package_type.source"].value == "catalog"
    assert metrics[prefix + "app_id"].value is None  # The source records a skipped read.
    assert metrics[prefix + "app_id.source"].value == "not_requested"
    data.agent365_packages.append(package.model_copy(deep=True))
    metrics = {row.key: row for row in report_metrics(data, [], "fixture")}
    assert metrics["catalog.package.1.metadata.package_type"].value is None
    assert metrics["catalog.package.3.metadata.package_type"].reason == "error"


def test_436_catalog_detail_references_complete_excel_ppt_and_recover_all_links(tmp_path: Path) -> None:
    from pptx import Presentation

    from easm_agent.report_pptx import presentation_template_path

    data = sample()
    root = tmp_path / "evidence"
    root.mkdir()
    data.facts["evidence_directory"] = str(root)
    data.facts["agent365_registry_complete"] = True
    for number in range(436):
        source = root / f"{number}.json"
        source.write_text(json.dumps({
            "package": number, "activeUsers": 0, "token": "do-not-export",
            "contact": "someone@example.invalid",
        }), encoding="utf-8")
        # Per-source records let normalization attach every masked payload independently.
        data.facts[f"detail_source_{number}"] = {"evidence_refs": [str(source)]}
        data.agent365_packages.append(Agent365Package(
            package_id=f"package-{number}", active_users_30d=0,
            detail_evidence_refs=[str(source)],
            field_status={"last_used_at": FieldStatus(reason="not_found", detail="필드 없음")},
        ))
    first = data.agent365_packages[0]
    first.package_type = "custom"
    first.field_status.pop("package_type", None)
    first.metadata_field_sources["package_type"] = "detail"
    first.metadata_evidence_refs["package_type"] = first.detail_evidence_refs.copy()
    with NO_AZURE:
        path = write_reports(data, [finding()], tmp_path / "reports", "fixture")
    result = load_result(path.parent)
    expected = sorted({
        ref for package in result["collection"]["agent365_packages"]
        for ref in package["detail_evidence_refs"]
    })
    assert len(expected) == 436
    assert len(json.dumps(expected, ensure_ascii=False)) == 33572
    for ref in expected:
        identifier = ref.removeprefix("evidence:")
        assert digest(result["evidence"][identifier]) == identifier
        assert any(row["id"] == identifier and row["status"] == "attached"
                   for row in result["provenance"]["references"])
    book = load_workbook(path)
    assert not any("Backdata" in name or "증적 색인" in name for name in book.sheetnames)
    metrics = metrics_by_key(
        Collection.model_validate(result["collection"]),
        [Finding.model_validate(row) for row in result["findings"]], "fixture",
    )
    keys = [key for key in metrics if key.startswith("catalog.usage.")]
    assert len(keys) == 6
    for key in keys:
        assert metrics[key].evidence_refs == expected
    assert metrics["catalog.package.1.metadata.package_type"].value == "custom"
    metadata_refs = result["collection"]["agent365_packages"][0]["metadata_evidence_refs"]["package_type"]
    assert len(metadata_refs) == 1 and metadata_refs[0] in expected
    assert metrics["catalog.package.1.metadata.package_type"].evidence_refs == metadata_refs
    assert metrics["catalog.package.1.metadata.package_type.source"].value == "detail"
    assert metrics["catalog.package.1.metadata.package_type.source"].evidence_refs == metadata_refs
    assert metrics["catalog.package.2.metadata.package_type"].value is None
    assert metrics["catalog.package.2.metadata.package_type"].reason == "not_found"
    assert metrics["catalog.package.1.active_users_30d"].value == 0
    assert metrics["catalog.package.1.last_used_at"].value is None
    assert metrics["catalog.package.1.last_used_at"].reason == "not_found"
    assert metrics["catalog.usage.active_users_30d"].value is None
    assert metrics["catalog.usage.active_users_30d"].reason == "feature_unavailable"

    assert all(
        len(cell.value) <= 32767 for sheet in book for row in sheet for cell in row
        if isinstance(cell.value, str)
    )
    assert not any(secret in str(cell.value) for secret in SECRETS
                   for sheet in book for row in sheet for cell in row)
    book.close()
    deck = next(path.parent.glob("EASM-report-*.pptx"))
    presentation = Presentation(deck)
    assert len(presentation.slides) == 12
    notes = presentation.slides[9].notes_slide.notes_text_frame.text
    assert all(ref in notes for ref in expected)
    assert result["findings"][0]["level"] == "N/A"
    assert result["findings"][0]["reason"] == "permission_denied"
    with ZipFile(presentation_template_path()) as template, ZipFile(deck) as rendered:
        assert set(template.namelist()) == set(rendered.namelist())
        assert all(template.read(name) == rendered.read(name) for name in template.namelist()
                   if not name.startswith(("ppt/slides/slide", "ppt/notesSlides/notesSlide")))


def prepared(tmp_path: Path, mode: str = "live") -> tuple[Collection, Path, Path, Path]:
    """Write a report whose evidence reference points at a real file below the evidence root."""
    output = tmp_path / "output"
    root = tmp_path / "evidence" / "run"
    root.mkdir(parents=True)
    source = root / "response.json"
    source.write_text(json.dumps({
        "api_key": "api-key-in-evidence", "value": 2, "email": "someone@example.invalid",
        "response": {"status": "completed", "value": None},
    }), encoding="utf-8")
    data = sample()
    data.agents[0].evidence_refs = [str(source.resolve())]
    data.facts["evidence_directory"] = str(root)
    rows = [finding(evidence_refs=[str(source.resolve())])]
    workbook = write_reports(data, rows, output, mode)
    return data, output, source, workbook


def record(sheet: Worksheet, row: int = 2) -> dict:
    header = 4 if sheet.title == RESULT_SHEET else 3 if sheet.title == TITLES["수집결과 근거"] else 1
    if sheet.title == RESULT_SHEET and row == 2:
        row = next(number for number in range(5, sheet.max_row + 1) if sheet.cell(number, 9).value is not None)
    elif header == 3 and row == 2:
        row = 4
    return {sheet.cell(header, col).value: sheet.cell(row, col) for col in range(1, sheet.max_column + 1)}


def records(sheet: Worksheet) -> list[dict]:
    return [record(sheet, row) for row in range(
        4 if sheet.title == TITLES["수집결과 근거"] else 2, sheet.max_row + 1,
    )]


def raw_bounds(book, title: str) -> tuple[Worksheet, tuple[int, int, int, int]]:
    sheet = book[TITLES["수집 Raw 데이터"]]
    label = "구성 관측" if title == "제안 Raw 데이터" else title.removesuffix(" Raw 데이터")
    heading = next(cell.row for cell in sheet["A"] if str(cell.value).startswith(label + " - "))
    table = next(table for table in sheet.tables.values() if range_boundaries(table.ref)[1] == heading + 1)
    return sheet, range_boundaries(table.ref)


def raw_record(book, title: str) -> dict:
    sheet, (_, header, last_column, _) = raw_bounds(book, title)
    return {sheet.cell(header, column).value: sheet.cell(header + 1, column)
            for column in range(1, last_column + 1)}


def xml_text(path: Path) -> str:
    with ZipFile(path) as archive:
        return "".join(archive.read(name).decode() for name in archive.namelist() if name.endswith(".xml"))


def all_cells(book):
    return [cell for sheet in book.worksheets[5:] for row in sheet.iter_rows() for cell in row]


# --- CLI and raw_data.json ---

def test_fixture_cli_is_offline_and_writes_only_workbook_and_raw_data(tmp_path: Path) -> None:
    with NO_AZURE:
        assert main([
            "collect", "--config", str(ROOT / "config" / "custom-config.yaml"),
            "--fixture", str(ROOT / "tests" / "fixtures" / "three_subscriptions.json"),
            "--output-dir", str(tmp_path),
        ]) == 0
    runs = list(tmp_path.iterdir())
    assert len(runs) == 1 and runs[0].is_dir()
    assert re.fullmatch(r"\d{8}T\d{12}Z(?:-\d+)?", runs[0].name)
    names = sorted(path.name for path in runs[0].iterdir())
    assert len(names) == 3
    assert names == sorted([
        f"raw-data-{runs[0].name}.json", f"report-{runs[0].name}.xlsx", f"EASM-report-{runs[0].name}.pptx",
    ])
    result = load_result(tmp_path)
    assert result["mode"] == "fixture"
    agents = result["collection"]["agents"]
    assert len(agents) == 3 and len(result["findings"]) == 26
    assert {
        "collected_at", "tenant_id", "subscription_id", "resource_group", "platform",
        "agent_id", "agent_name", "resource_id", "hosting_type", "owner", "sponsor",
        "tags", "model", "tools", "created_at", "last_used_at", "cost_30d", "usage_30d",
        "evaluated_before_deploy", "guardrail_applied", "detection_confidence", "evidence_refs",
        "se_codes", "field_status",
    } <= set(agents[0])


def test_raw_data_keeps_machine_contract_and_manifest_matches_files(tmp_path: Path) -> None:
    data, output, source, workbook = prepared(tmp_path)
    before = data.model_dump(mode="json")
    assert workbook.parent.parent == output and workbook.name == report_name(data, workbook.parent.name)
    deck = workbook.parent / presentation_name(data, workbook.parent.name)
    assert {path.name for path in workbook.parent.iterdir()} == {
        workbook.name, deck.name, raw_name(data, workbook.parent.name),
    }
    assert workbook.stem.removeprefix("report-") == workbook.parent.name
    assert latest_raw(output).stem.removeprefix("raw-data-") == workbook.parent.name
    assert load_result(output)["collection"]["collected_at"] == data.model_dump(mode="json")["collected_at"]
    result = load_result(output)
    assert set(result) == {
        "schema_version", "collection", "findings", "mode", "evidence", "provenance", "manifest",
    }
    row = result["findings"][0]
    assert (row["level"], row["reason"], row["scope"]) == ("N/A", "permission_denied", "partial")
    manifest = result["manifest"]
    assert manifest["credentials_included"] is False and manifest["mode"] == "live"
    payload, deck_payload = workbook.read_bytes(), deck.read_bytes()
    assert manifest["files"] == [
        {"path": workbook.name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
        {"path": deck.name, "bytes": len(deck_payload), "sha256": hashlib.sha256(deck_payload).hexdigest()},
    ]
    rest = {key: value for key, value in result.items() if key != "manifest"}
    assert manifest["data_sha256"] == hashlib.sha256(json_bytes(rest)).hexdigest()
    assert data.model_dump(mode="json") == before and source.exists()


def test_load_result_rejects_missing_or_unsupported_files(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_result(tmp_path)
    (tmp_path / "raw-data-20261104T000000Z.json").write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    with pytest.raises(ValueError, match="스키마"):
        load_result(tmp_path)


def test_packaged_findings_keep_their_codes_and_metrics(tmp_path: Path) -> None:
    write_reports(sample(), [
        finding(se_code="OE-SY-18", level="L3", metric_value=365),
        finding(se_code="OE-SY-19", level="L2", metric_value=0.5),
    ], tmp_path)
    result = load_result(tmp_path)
    assert [(row["se_code"], row["metric_value"]) for row in result["findings"]] == [
        ("OE-SY-18", 365), ("OE-SY-19", 0.5),
    ]


# --- evidence attachment and provenance ---

def test_attached_evidence_is_masked_embedded_and_referenced_by_hash(tmp_path: Path) -> None:
    data, output, source, workbook = prepared(tmp_path)
    result = load_result(output)
    identifier, payload = next(iter(result["evidence"].items()))
    assert len(result["evidence"]) == 1 and identifier == digest(payload)
    assert payload["api_key"] == "[REDACTED]" and payload["response"] == {"status": "completed", "value": None}
    assert result["collection"]["agents"][0]["evidence_refs"] == ["evidence:" + identifier]
    assert result["findings"][0]["evidence_refs"] == ["evidence:" + identifier]
    assert result["collection"]["facts"]["evidence_directory"] == "embedded:evidence"
    assert result["provenance"]["unattached_evidence"] == []
    assert result["provenance"]["references"][0]["reference"] == "evidence:" + identifier
    assert result["provenance"]["references"][0]["reference_sha256"] == hashlib.sha256(
        str(source.resolve()).encode("utf-8"),
    ).hexdigest()
    book = load_workbook(workbook)
    assert json.loads(raw_record(book, "Agent Raw 데이터")["evidence_refs"].value) == ["evidence:" + identifier]
    values = [c.value for sheet in book for row in sheet.iter_rows()
              for c in row if isinstance(c.value, str)]
    assert not any(str(source) in value for value in values)


def test_unsafe_missing_or_unsupported_references_are_reported_as_unattached(tmp_path: Path) -> None:
    data, output, source, _ = prepared(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text('{"password": "never"}', encoding="utf-8")
    text = source.parent / "note.txt"
    text.write_text("{}", encoding="utf-8")
    bad = [str(outside), str(text), str(source.parent / "missing.json"), "fixture://missing",
           "../outside.json", "%2e%2e/outside.json", "//server/share/e.json", "file:///C:/s.json"]
    data.agents[0].evidence_refs.extend(bad)
    workbook = write_reports(data, [], output)
    result = load_result(output)
    missing = result["provenance"]["unattached_evidence"]
    assert {item["reference"] for item in missing} == set(bad)
    assert all(item["status"] == "not_found" and "파일 확인불가" in item["detail"] for item in missing)
    assert len(result["evidence"]) == 1 and "never" not in json.dumps(result)
    refs = json.loads(raw_record(load_workbook(workbook), "Agent Raw 데이터")["evidence_refs"].value)
    assert refs == result["collection"]["agents"][0]["evidence_refs"]
    assert len(refs) == len(bad) + 1


def test_symlink_evidence_is_never_embedded(tmp_path: Path) -> None:
    data, output, source, _ = prepared(tmp_path)
    link = source.parent / "alias.json"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlink permission unavailable")
    data.agents[0].evidence_refs = [str(link)]
    write_reports(data, [], tmp_path / "linked")
    result = load_result(tmp_path / "linked")
    assert result["evidence"] == {}
    assert len(result["provenance"]["unattached_evidence"]) == 1


def test_cached_evidence_is_replayed_after_source_files_are_gone(tmp_path: Path) -> None:
    data, output, source, _ = prepared(tmp_path)
    first = load_result(output)
    source.unlink()
    write_reports(data, [], output)
    again = load_result(output)
    assert again["evidence"] == first["evidence"]
    assert again["collection"]["agents"][0]["evidence_refs"] == first["collection"]["agents"][0]["evidence_refs"]
    assert again["provenance"]["unattached_evidence"] == []


def test_new_evidence_content_replaces_previous_cache(tmp_path: Path) -> None:
    data, output, source, _ = prepared(tmp_path)
    old = next(iter(load_result(output)["evidence"]))
    source.write_text('{"response": {"new": true}}', encoding="utf-8")
    write_reports(data, [], output)
    result = load_result(output)
    assert list(result["evidence"].values()) == [{"response": {"new": True}}]
    assert old not in result["evidence"]


# --- package CLI ---

def test_package_cli_rebuilds_workbook_from_raw_data_without_azure_or_evidence(tmp_path: Path) -> None:
    _, output, source, workbook = prepared(tmp_path)
    before = load_result(output)
    source.unlink()
    workbook.unlink()
    with NO_AZURE:
        assert main(["package", "--output-dir", str(output)]) == 0
    after = load_result(output)
    for key in ("collection", "findings", "evidence", "provenance", "mode"):
        assert after[key] == before[key]
    assert {path.name for path in workbook.parent.iterdir()} == {
        workbook.name, latest_raw(output).name, presentation_name(before["collection"], workbook.parent.name),
    }
    assert list(output.iterdir()) == [workbook.parent]
    assert latest_raw(output).name == f"raw-data-{workbook.parent.name}.json"
    assert after["manifest"]["files"][0]["sha256"] == hashlib.sha256(workbook.read_bytes()).hexdigest()
    assert json.loads(raw_record(load_workbook(workbook), "Agent Raw 데이터")["evidence_refs"].value) == (
        after["collection"]["agents"][0]["evidence_refs"]
    )


def test_package_cli_rejects_mode_mismatch_and_missing_raw_data(tmp_path: Path) -> None:
    _, output, _, workbook = prepared(tmp_path, "fixture")
    payload = workbook.read_bytes()
    with NO_AZURE:
        assert main(["package", "--output-dir", str(output), "--mode", "live"]) == 1
        assert workbook.read_bytes() == payload
        assert main(["package", "--output-dir", str(tmp_path / "empty")]) == 1
        assert main(["package", "--output-dir", str(output), "--mode", "fixture"]) == 0
    assert load_result(output)["mode"] == "fixture"


# --- atomic output ---

def test_failed_replace_preserves_existing_files_and_leaves_no_pending_files(tmp_path: Path) -> None:
    data, output, _, _ = prepared(tmp_path)
    (output / "unrelated.txt").write_bytes(b"keep")
    originals = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    data.agents[0].agent_name = "new name"
    with patch("easm_agent.report.os.replace", side_effect=OSError("locked")), pytest.raises(OSError):
        write_reports(data, [], output)
    assert {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()} == originals
    assert not [path for path in output.rglob("*") if "pending" in path.name]


def test_failed_replace_on_first_write_leaves_empty_output(tmp_path: Path) -> None:
    output = tmp_path / "fresh"
    with patch("easm_agent.report.os.replace", side_effect=OSError("locked")), pytest.raises(OSError):
        write_reports(sample(), [], output)
    assert list(output.iterdir()) == []


def test_repeated_collection_timestamp_creates_distinct_runs_without_overwrite(tmp_path: Path) -> None:
    data = sample()
    first = write_reports(data, [], tmp_path)
    original = first.read_bytes()
    data.agents[0].agent_name = "second run"
    second = write_reports(data, [], tmp_path)
    assert first.parent != second.parent and first.name != second.name
    assert first.stem.removeprefix("report-") == first.parent.name
    assert second.stem.removeprefix("report-") == second.parent.name
    assert first.read_bytes() == original
    assert latest_raw(tmp_path).parent == second.parent
    assert load_result(first.parent)["collection"]["agents"][0]["agent_name"] == "테스트 Agent"
    assert load_result(second.parent)["collection"]["agents"][0]["agent_name"] == "second run"


def test_run_collision_uses_sequence_and_latest_discovery_is_numeric(tmp_path: Path) -> None:
    from easm_agent.report import create_run_directory

    fixed = datetime(2026, 11, 5, 1, 2, 3, 456789, tzinfo=UTC)
    with patch("easm_agent.report.datetime", wraps=datetime) as clock:
        clock.now.return_value = fixed
        runs = [create_run_directory(tmp_path) for _ in range(12)]
    for run in runs:
        (run / raw_name(sample())).write_text("{}", encoding="utf-8")
    assert len(set(runs)) == 12
    assert runs[-1].name.endswith("-11")
    assert latest_raw(tmp_path).parent == runs[-1]


def test_new_report_names_match_run_stamp_including_collision_suffix(tmp_path: Path) -> None:
    fixed = datetime(2026, 11, 5, 1, 2, 3, 456789, tzinfo=UTC)
    with patch("easm_agent.report.datetime", wraps=datetime) as clock:
        clock.now.return_value = fixed
        first = write_reports(sample(), [], tmp_path)
        second = write_reports(sample(), [], tmp_path)
    assert second.parent.name == first.parent.name + "-1"
    for path in (first, second):
        assert path.name == f"report-{path.parent.name}.xlsx"
        assert latest_raw(path.parent).name == f"raw-data-{path.parent.name}.json"
    assert latest_raw(tmp_path).parent == second.parent


def test_downloaded_microsecond_raw_file_can_be_found_in_flat_folder(tmp_path: Path) -> None:
    path = tmp_path / "raw-data-20261105T010203456789Z-10.json"
    path.write_text("{}", encoding="utf-8")
    assert latest_raw(tmp_path) == path


def test_latest_raw_supports_legacy_files_without_searching_unrelated_folders(tmp_path: Path) -> None:
    legacy = tmp_path / "raw-data-20261104T000000Z.json"
    legacy.write_text("{}", encoding="utf-8")
    ignored = tmp_path / "unrelated"
    ignored.mkdir()
    (ignored / "raw-data-20990101T000000Z.json").write_text("{}", encoding="utf-8")
    assert latest_raw(tmp_path) == legacy
    current = tmp_path / "20261105T000000000001Z"
    current.mkdir()
    (current / "raw-data-20200101T000000Z.json").write_text("{}", encoding="utf-8")
    assert latest_raw(tmp_path).parent == current


def test_package_rebuilds_explicit_legacy_directory_without_nesting(tmp_path: Path) -> None:
    path = write_reports(sample(), [], tmp_path, new_run=False)
    with NO_AZURE:
        assert main(["package", "--output-dir", str(tmp_path)]) == 0
    assert set(tmp_path.iterdir()) == {
        path, tmp_path / raw_name(sample()), tmp_path / presentation_name(sample()),
    }


# --- workbook structure ---

def test_workbook_sheets_tables_borders_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    write_workbook(sample(), [finding()], path)
    book = load_workbook(path)
    assert book.sheetnames == SHEETS
    for sheet in book.worksheets[6:]:
        assert sheet.freeze_panes == (
            "A3" if sheet.title == TITLES["수집 Raw 데이터"] else
            "A4" if sheet.title == TITLES["수집결과 근거"] else "A2"
        )
        assert len(sheet.tables) == (
            18 if sheet.title == TITLES["수집 Raw 데이터"] else
            6 if sheet.title == TITLES["수집결과 근거"] else 1
        )
        # Excel repairs a file that has both a table and a sheet-level autoFilter on one range.
        assert not sheet.auto_filter.ref
        assert all(
            cell.font.name == "Arial"
            and cell.hyperlink is None for row in sheet for cell in row if cell.value is not None
        )
        assert all(cell.font.size == 10 for row in sheet for cell in row if cell.value is not None)
        assert sheet.sheet_view.zoomScale == 80
        for table in sheet.tables.values():
            _, header, last_column, last_row = range_boundaries(table.ref)
            columns = [column.name for column in table.tableColumns]
            assert columns == [sheet.cell(header, column).value for column in range(1, last_column + 1)]
            assert len(set(columns)) == len(columns) and all(isinstance(value, str) for value in columns)
            assert sheet.cell(header, 1).fill.fgColor.rgb == "00D9D9D9"
            for row in sheet.iter_rows(min_row=header, max_row=last_row, max_col=last_column):
                for cell in row:
                    for side in ("left", "right", "top", "bottom"):
                        outer = (
                            (side == "left" and cell.column == 1)
                            or (side == "right" and cell.column == last_column)
                            or (side == "top" and cell.row == header)
                            or (side == "bottom" and cell.row == last_row)
                        )
                        if sheet.title == TITLES["수집결과 근거"] and (cell.row > header or side == "right"):
                            outer = False
                        assert getattr(cell.border, side).style == ("medium" if outer else "thin")
    validations = book[RESULT_SHEET].data_validations.dataValidation
    assert len(validations) == 1
    assert validations[0].type == "whole" and validations[0].operator == "between"
    assert validations[0].formula1 == "1" and validations[0].formula2 == "5"
    assert validations[0].allow_blank is True
    assert validations[0].showErrorMessage is True and "M5" in validations[0].sqref
    checklist = book[RESULT_SHEET]
    assert checklist["M4"].value == "평가 점수\n(1~5)" and checklist["B4"].value == "No"
    assert checklist["I4"].font.bold is True
    assert checklist.freeze_panes == "G5" and checklist.auto_filter.ref == "B4:N84"
    assert all(checklist.cell(row, 13).alignment.horizontal == "center" for row in range(4, 85))
    for row in range(5, checklist.max_row + 1):
        if "-SY-" in str(checklist.cell(row, 2).value):
            assert checklist.row_dimensions[row].height == 150
    proposals = book[TITLES["수집결과 근거"]]
    assert proposals.row_dimensions[4].height == 60 and proposals["F4"].fill.patternType is None
    assert "수집된 설정·값·건수" in proposals["A1"].value
    assert all("개선 제안 목록이 아님" not in str(cell.value) for cell in all_cells(book))
    assert all(proposals.cell(3, column).comment for column in range(1, 10))


def test_workbook_values_keep_types_and_checklist_labels(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    write_workbook(sample(), [finding()], path)
    book = load_workbook(path)
    agent = raw_record(book, "Agent Raw 데이터")
    assert set(AgentEvidence.model_fields) <= agent.keys()
    assert (agent["agent_id"].value, agent["agent_id"].data_type, agent["agent_id"].number_format) == (
        "000001", "s", "@")
    assert (agent["cost_30d"].value, agent["cost_30d"].data_type) == (0, "n")
    assert (agent["guardrail_applied"].value, agent["guardrail_applied"].data_type) == (False, "b")
    assert agent["calls_90d"].value is None
    raw = json.loads(agent["원본 JSON"].value)
    assert raw["cost_30d"] == 0 and raw["calls_90d"] is None and raw["guardrail_applied"] is False
    assert raw["owner"].startswith("identity-") and raw["tags"]["secret"] == "[REDACTED]"
    logs = raw_record(book, "로그 Raw 데이터")
    assert (logs["retention_days"].value, logs["enabled"].data_type) == (0, "b")
    evaluation = raw_record(book, "평가 Raw 데이터")
    assert [evaluation[k].value for k in ("passed_items", "failed_items", "errored_items")] == [0, 3, 2]
    checklist = record(book[RESULT_SHEET])
    assert (checklist["판정"].value, checklist["지표"].value) == ("판정 보류", "0.00%")
    assert "원인" not in checklist and checklist["평가 점수\n(1~5)"].value is None
    assert "조회 권한 부족" in checklist["근거"].value
    assert len(records(book[TITLES["수집이슈 Raw 데이터"]])) == 2
    assert next(iter(raw_record(book, "모델배포 Raw 데이터").values())).value.startswith("수집된 데이터 없음")


def test_missing_metric_is_not_converted_to_zero_and_null_differs_from_zero(tmp_path: Path) -> None:
    data = sample()
    data.agents[0].unavailable("model", "permission_denied", "관리자가 조회 역할을 확인해야 합니다.")
    data.evaluations[0].failed_items = None
    path = tmp_path / "null.xlsx"
    write_workbook(data, [finding(se_code="DS-SY-04", metric_value=None)], path)
    book = load_workbook(path)
    assert record(book[RESULT_SHEET])["지표"].value == "확인 자료 없음 - 분모 확인 안됨"
    evaluation = raw_record(book, "평가 Raw 데이터")
    assert evaluation["failed_items"].value is None and evaluation["passed_items"].value == 0
    missing = records(book[TITLES["필드누락사유"]])
    model = next(row for row in missing if row["field"].value == "model")
    assert model["reason"].value == "permission_denied" and "조회 역할" in model["설명"].value
    calls = next(row for row in missing if row["field"].value == "calls_90d")
    assert calls["reason"].value == "not_found" and "원본 값이 null" in calls["설명"].value
    assert not any(row["field"].value in ("cost_30d", "guardrail_applied") for row in missing)


def test_result_categories_do_not_hide_partial_collection_or_failed_queries(tmp_path: Path) -> None:
    path = tmp_path / "categories.xlsx"
    write_workbook(sample(), [
        finding(),
        finding(se_code="DS-SY-04", metric_value=None),
    ], path)
    sheet = load_workbook(path)[RESULT_SHEET]
    rows = {sheet.cell(row, 2).value: row for row in range(5, sheet.max_row + 1)}
    assert {sheet.cell(row, 7).value for row in range(5, sheet.max_row + 1)} == {
        "수집됨", "수집하지 않음", "인터뷰 필요",
    }
    assert sheet.cell(rows["BI-SY-09"], 7).value == "수집됨"
    assert "일부 수집" in sheet.cell(rows["BI-SY-09"], 10).value
    assert sheet.cell(rows["DS-SY-04"], 7).value == "수집하지 않음"
    assert "조회 권한 부족" in sheet.cell(rows["DS-SY-04"], 10).value
    assert sheet.cell(rows["DS-SY-04"], 13).value is None
    assert sheet.cell(rows["DM-PR-01"], 7).value == "인터뷰 필요"
    assert sheet.cell(rows["DM-PR-01"], 13).value is None
    assert sheet.cell(rows["DM-SY-01"], 13).value is None


def test_merged_raw_preserves_evidence_references_without_a_reference_sheet(tmp_path: Path) -> None:
    data = sample()
    for field in ("agents", "evaluations", "costs", "logs"):
        for item in getattr(data, field):
            item.evidence_refs = ["fixture://" + field]
    path = tmp_path / "raw.xlsx"
    write_workbook(data, [], path)
    book = load_workbook(path)
    assert not any("증거참조" in title or "읽는법" in title for title in book.sheetnames)
    for field, title in (
        ("agents", "Agent Raw 데이터"), ("evaluations", "평가 Raw 데이터"),
        ("costs", "비용 Raw 데이터"), ("logs", "로그 Raw 데이터"),
    ):
        original = json.loads(raw_record(book, title)["원본 JSON"].value)
        assert original["evidence_refs"] == ["fixture://" + field]


def test_empty_collection_has_placeholder_rows_without_fabricated_zero_values(tmp_path: Path) -> None:
    path = tmp_path / "empty.xlsx"
    write_workbook(Collection(collected_at=datetime(2026, 11, 3, tzinfo=UTC)), [], path)
    book = load_workbook(path)
    for title in ("Agent Raw 데이터", "평가 Raw 데이터"):
        sheet, (_, header, last_column, last_row) = raw_bounds(book, title)
        assert "수집된 데이터 없음" in sheet.cell(header + 1, 1).value
        assert all(cell.value != 0 for row in sheet.iter_rows(
            min_row=header + 1, max_row=last_row, max_col=last_column,
        ) for cell in row)
    for title in ("수집이슈 Raw 데이터",):
        sheet = book[TITLES[title]]
        assert sheet.tables and "수집된 데이터 없음" in sheet["A2"].value
        assert all(cell.value != 0 for row in sheet.iter_rows(min_row=2) for cell in row)


# --- zip level safety, masking and limits ---

@pytest.mark.parametrize("text", [
    '=HYPERLINK("https://example.invalid","click")', "+SUM(1,2)", "-1+2", "@SUM(1,2)",
])
def test_user_strings_never_become_formulas_or_external_links(tmp_path: Path, text: str) -> None:
    data = sample()
    data.agents[0].agent_name = data.agents[0].agent_id = text
    data.agents[0].evidence_refs = [text]
    data.costs[0].amount = -12.5
    path = tmp_path / "book.xlsx"
    write_workbook(data, [finding(rationale=text, next_step=text)], path)
    book = load_workbook(path)
    agent = raw_record(book, "Agent Raw 데이터")
    assert agent["agent_name"].value == text and agent["agent_name"].data_type == "s"
    assert record(book[RESULT_SHEET])["근거"].value.endswith("판정 근거: " + text)
    assert json.loads(raw_record(book, "Agent Raw 데이터")["evidence_refs"].value) == [text]
    amount = raw_record(book, "비용 Raw 데이터")["amount"]
    assert amount.value == -12.5 and amount.data_type == "n"
    for cell in all_cells(book):
        assert cell.data_type != "f"
        if cell.hyperlink is not None:
            assert cell.parent.title == RESULT_SHEET and cell.column == 11
            assert cell.hyperlink.target is None
            assert cell.hyperlink.location.startswith("'7. 수집결과 근거'!A")
    with ZipFile(path) as archive:
        names = archive.namelist()
        assert not any("externalLink" in name or "vbaProject" in name for name in names)
        sheets = [
            archive.read(f"xl/worksheets/sheet{index}.xml").decode()
            for index in range(6, len(SHEETS) + 1)
        ]
    assert len(sheets) == len(SHEETS) - 5 and not any(re.search(r"<f[\s>/]", xml) for xml in sheets)


def test_secrets_tokens_emails_and_owners_never_reach_any_output_file(tmp_path: Path) -> None:
    _, output, _, workbook = prepared(tmp_path)
    raw = latest_raw(output).read_text(encoding="utf-8")
    xml = xml_text(workbook)
    for secret in SECRETS:
        assert secret not in raw and secret not in xml
    assert "[REDACTED]" in raw and "identity-" in raw


def test_oversized_strings_fail_explicitly_without_creating_output(tmp_path: Path) -> None:
    data = sample()
    data.agents[0].agent_name = "가" * 32768
    with pytest.raises(ValueError, match="Excel 셀 길이 오류.*32768"):
        write_workbook(data, [], tmp_path / "too-long.xlsx")
    assert not (tmp_path / "too-long.xlsx").exists()
    with pytest.raises(ValueError, match="Excel 셀 길이 오류"):
        write_reports(data, [], tmp_path / "output")
    assert not list((tmp_path / "output").glob("*.xlsx")) and not list((tmp_path / "output").glob("raw-data-*.json"))
