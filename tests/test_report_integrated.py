from __future__ import annotations

import json
import re
from copy import copy
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from easm_agent.azure import AccessError
from easm_agent.cli import main
from easm_agent.deck_model import read_assessment
from easm_agent.models import (
    AgentEvidence,
    AssessmentMeasurement,
    Collection,
    Finding,
    Settings,
    TargetAssessment,
    load_criteria,
)
from easm_agent.provenance import assessment_provenance
from easm_agent.report import load_result
from easm_agent.report_excel import refresh_interview_summary, write_workbook
from easm_agent.report_integrated import (
    EXTRACTED_FORMAT,
    GRADES,
    GUIDE,
    INTEGRATED_SHEETS,
    MATRIX,
    PROCESS,
    RAW,
    RAW_GUIDE,
)
from easm_agent.report_interviews import result_cell_updates, write_interview_responses
from easm_agent.report_layout import PLATFORM_COLUMNS, PLATFORM_SHEET, load_report_layout
from easm_agent.report_template import assessment_template_path

NOW = datetime(2026, 11, 23, tzinfo=UTC)
ROOT = Path(__file__).parents[1]


def test_output_uses_reference_dimensions_and_preserves_hidden_metadata(tmp_path: Path):
    path = tmp_path / "layout.xlsx"
    write_workbook(collection(), [], path)
    book = load_workbook(path)
    layout = load_report_layout()
    inverse = {new: old for old, new in PLATFORM_COLUMNS.items()}
    for sheet in book:
        reference = layout[sheet.title]
        assert sheet.sheet_format.defaultRowHeight == reference["default_row_height"]
        for column in range(1, sheet.max_column + 1):
            old = inverse.get(column, column) if sheet.title == PLATFORM_SHEET else column
            expected = reference["columns"].get(get_column_letter(old), {"width": 13})["width"]
            assert sheet.column_dimensions[get_column_letter(column)].width == expected
        last_row = max(sheet.max_row, max(map(int, reference["row_heights"]), default=1))
        for row in range(1, last_row + 1):
            expected = reference["row_heights"].get(str(row), reference["default_row_height"])
            actual = sheet.row_dimensions[row].height
            assert actual == expected, (sheet.title, row)
        if sheet.title in INTEGRATED_SHEETS:
            assert sheet["A2"].font.name == "Microsoft GothicNeo" and sheet["A2"].font.sz == 9
    assert book[RAW].column_dimensions["Q"].hidden
    assert book[GRADES].column_dimensions["U"].hidden
    assert not book["8b_수집이슈 Raw 데이터"].merged_cells.ranges


def collection() -> Collection:
    data = Collection(collected_at=NOW)
    saved_criteria = load_criteria(Settings(criteria_file=ROOT / "tests" / "fixtures" / "resource-criteria.yaml"))
    data.assessment_provenance = assessment_provenance(saved_criteria, {}, "evaluation")
    return data


def test_default_template_preserves_manual_structure_without_publishing_live_results() -> None:
    book = load_workbook(assessment_template_path())
    assert tuple(book.sheetnames) == INTEGRATED_SHEETS
    expected = list(load_criteria()["items"])
    assert [book[GRADES].cell(row, 1).value for row in range(5, 31)] == expected
    assert [book[RAW].cell(row, 1).value for row in range(5, 57, 2)] == expected
    assert all(book[RAW].cell(row, 6).value is None for row in range(5, 57))
    assert all(book[GRADES].cell(row, 21).value is None for row in range(5, 31))
    assert len([
        row for row in book[PROCESS] if re.fullmatch(r"[A-Z]{2}-(?:PR|PE|DA|TE)-\d+", str(row[2].value))
    ]) == 54
    assert all(
        book[name]["A1"].font.name == "Microsoft GothicNeo"
        and book[name]["A1"].font.sz == 14 for name in INTEGRATED_SHEETS
    )
    text = "\n".join(str(cell.value) for sheet in book for row in sheet for cell in row)
    assert not re.search(r"[A-Z]:[\\/]|/subscriptions/|[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", text)
    cached = load_workbook(assessment_template_path(), data_only=True)
    assert cached[GRADES]["C41"].value == 26 and cached[GRADES]["C59"].value == 26
    assert not [(sheet.title, cell.coordinate) for sheet in cached for row in sheet for cell in row
                if cell.data_type == "e"]


def test_same_column_colors_are_uniform_without_changing_values_or_status_styles(tmp_path: Path) -> None:
    path = tmp_path / "report.xlsx"
    write_workbook(collection(), [], path)
    book = load_workbook(path)
    for name, ranges in {
        "1_진단 개요": ("B5:B19", "B23:D30"),
        "1a_플랫폼 기준": ("F5:G11",),
    }.items():
        for region in ranges:
            for column in zip(*book[name][region], strict=True):
                for cell in column:
                    assert cell.font.color == column[0].font.color
                    assert cell.fill == copy(column[0].fill)
    assert book["1_진단 개요"]["B13"].data_type == "f"
    assert book["1_진단 개요"]["B14"].data_type == "f"
    assert book["1a_플랫폼 기준"]["F8"].value is None
    assert book["1_진단 개요"]["B4"].fill.fgColor.rgb == "FFD9D9D9"
    assert book["1a_플랫폼 기준"]["F14"].fill.fgColor.rgb == "FFDDEBF7"
    assert book[MATRIX].conditional_formatting
    for sheet in book.worksheets[14:]:
        for table in sheet.tables.values():
            rows = list(sheet[table.ref])[1:]
            for column in zip(*rows, strict=True):
                for cell in column:
                    assert cell.font.color == column[0].font.color
                    assert cell.fill == copy(column[0].fill)
                    assert cell.fill.patternType is None or cell.fill.fgColor.rgb[-6:] == "FFFFFF"


def test_observed_zero_and_unavailable_have_distinct_inputs_scores_and_audit(tmp_path: Path) -> None:
    data = collection()
    findings = [
        Finding(se_code="DM-SY-01", scope="partial", level="L1", metric_value=0,
                rationale="확인된 부재", measurement=AssessmentMeasurement(
                    numerator=0, denominator=2, complete=True,
                )),
        Finding(se_code="DS-SY-02", scope="partial", level="N/A", reason="permission_denied",
                rationale="관리자 증적 접근 권한 부족",
                measurement=AssessmentMeasurement(complete=False, reason="권한 부족")),
    ]
    path = tmp_path / "report.xlsx"
    write_workbook(data, findings, path)
    with ZipFile(path) as archive:
        comments = [ElementTree.fromstring(archive.read(name)) for name in archive.namelist()
                    if name.startswith("xl/comments/") and name.endswith(".xml")]
    assert comments
    namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    for comment in comments:
        runs = comment.findall(".//s:rPr", namespace)
        assert runs
        assert all(run.find("s:rFont", namespace).get("val") == "Microsoft GothicNeo" for run in runs)
        assert all(run.find("s:sz", namespace).get("val") == "9" for run in runs)
    book = load_workbook(path)
    assert book.active.title == GUIDE
    assert all(view.activeTab == book.index(book[GUIDE]) for view in book.views)
    assert [
        sheet.title for sheet in book
        if any(view.tabSelected for view in sheet.views.sheetView)
    ] == [GUIDE]
    source = load_workbook(assessment_template_path())
    assert book[RAW]["F5"].value == 0 and book[RAW]["F6"].value == 2
    assert book[RAW]["F7"].value is None and book[RAW]["F8"].value is None
    assert book[RAW]["F7"].comment is None
    assert book[RAW]["F5"].fill.fgColor.rgb == "FFFFF2CC"
    assert book[RAW]["F7"].fill.fgColor.rgb == "FFFFF2CC"
    for row in range(5, 57):
        output_font, source_font = book[RAW].cell(row, 6).font, source[RAW].cell(row, 6).font
        assert output_font.name == source_font.name and output_font.sz == source_font.sz
        assert output_font.color.rgb == "FF0070C0"
    cached = load_workbook(path, data_only=True)
    assert cached[GRADES]["K5"].value == 1
    assert cached[GRADES]["K6"].value == "N/A"
    assert cached[PROCESS]["L5"].value is None
    assessment = read_assessment(path)
    assert len(assessment.system_items) == 26 and len(assessment.interview_items) == 54
    assert assessment.system_items[0].score == 1 and assessment.system_items[1].score is None
    for row in range(5, 59):
        for column in (6, 7, 8, 9, 13):
            assert book[PROCESS].cell(row, column).value == source[PROCESS].cell(row, column).value
    assert any("수집 Raw 데이터" in name for name in book.sheetnames)
    assert "권한 부족" in book[GRADES]["M6"].value
    assert book[RAW]["A2"].value == RAW_GUIDE
    assert book[RAW]["G5"].value == "개"
    assert book[RAW]["F5"].number_format == "#,##0"
    assert book[RAW]["I5"].value == datetime(2026, 11, 23, 9)
    assert book[RAW]["I5"].number_format == EXTRACTED_FORMAT
    assert book[RAW]["J5"].value == "EASM 자동화 모듈"
    assert book[RAW]["L2"].value == NOW.isoformat()
    assert len(book[RAW].data_validations.dataValidation) == 0
    assert "조회 권한 부족" in book[RAW]["K7"].value
    assert len(book[RAW]["K5"].value) < 30 and book[RAW]["K5"].comment is None
    assert all(book[RAW].row_dimensions[row].height <= 34 for row in range(5, 57))
    assert book[PROCESS].data_validations.dataValidation
    assert book[RAW]["E5"].value == "역할 할당이 1건 이상 확인된 환경 수"
    assert book[RAW]["E6"].value == "관리자에게 보이는 Power Platform 환경 수"
    assert book[RAW]["E7"].value == "데이터 정책(DLP)이 적용된 환경 수"
    for column in ("I", "J", "K"):
        assert book[RAW][f"{column}5"].alignment.horizontal == "left"
    assert book[RAW]["F5"].alignment.horizontal == "center"
    assert book[RAW]["A5"].border.bottom.style == "thin"
    assert book[RAW]["A6"].border.bottom.style == "medium"
    assert book[RAW]["K6"].border.bottom.style == "medium"
    assert book[RAW]["A4"].border.bottom.style == "medium"


def test_localized_currency_keeps_numeric_measurements_and_machine_units(tmp_path: Path) -> None:
    from easm_agent.report_biz_pptx import workbook_metrics

    path = tmp_path / "currency.xlsx"
    numerator, denominator = .397353333801215, .39795025919
    data = collection()
    write_workbook(data, [Finding(
        se_code="OT-SY-24", scope="partial", level="L4", rationale="수집한 통화별 비용",
        metric_value=numerator/denominator, evidence_refs=["evidence:cost"],
        measurement=AssessmentMeasurement(
            numerator=numerator, denominator=denominator, unit="amount", currency="USD", complete=True,
        ),
    )], path)
    book = load_workbook(path)
    assert book[RAW]["F51"].value == pytest.approx(numerator, rel=0, abs=1e-16)
    assert book[RAW]["F52"].value == pytest.approx(denominator, rel=0, abs=1e-16)
    assert book[RAW]["G51"].value == "미국 달러 (USD)"
    assert book[RAW]["E51"].value == "단일 Agent에 귀속 확인된 비용 금액"
    assert book[RAW]["E52"].value == "동일 통화의 양수 AI 비용 금액"
    assert book[RAW]["M51"].value == "amount" and book[RAW]["N51"].value == "USD"
    assert book[RAW]["L1"].value == "easm_collected_at_utc"
    assert book[RAW]["K51"].comment is None
    assert workbook_metrics(path)["se.OT-SY-24.numerator"].unit == "USD"
    assert workbook_metrics(path)["se.OT-SY-24.numerator"].value == pytest.approx(numerator, rel=0, abs=1e-16)


def test_collection_time_round_trips_kst_and_legacy_utc(tmp_path: Path) -> None:
    from easm_agent.report_biz_pptx import workbook_collected_at

    path = tmp_path / "time.xlsx"
    data = collection()
    data.collected_at = NOW.replace(microsecond=71665)
    write_workbook(data, [], path)
    assert workbook_collected_at(path) == data.collected_at
    book = load_workbook(path)
    book[RAW]["L2"] = None
    book[RAW]["I5"] = datetime(2026, 11, 23, 9)
    book.save(path)
    assert workbook_collected_at(path) == NOW
    book[RAW]["I5"] = data.collected_at.isoformat()
    book.save(path)
    assert workbook_collected_at(path) == data.collected_at
    book[RAW]["I4"] = "추출 일시"
    book[RAW]["I5"] = datetime(2026, 11, 23, 9)
    book.save(path)
    with pytest.raises(ValueError, match="시간대"):
        workbook_collected_at(path)


def test_custom_saved_criteria_and_historical_grades_are_not_regraded(tmp_path: Path) -> None:
    data = collection()
    criteria = load_criteria()
    criteria["items"]["DS-SY-02"]["levels"]["L3"] = "수집 당시 사용자 지정 기준"
    data.assessment_provenance = assessment_provenance(criteria, {}, "saved_snapshot_reassessment")
    path = tmp_path / "historical.xlsx"
    write_workbook(data, [Finding(
        se_code="DS-SY-02", scope="partial", level="L3", rationale="수집 당시 기준",
    )], path)
    book = load_workbook(path)
    assert book[GRADES]["R6"].value == "수집 당시 사용자 지정 기준"
    assert book[RAW]["F7"].value is None
    assert read_assessment(path).system_items[1].score == 3


def test_manual_inputs_apply_evidence_caps_and_survive_deck_refresh(tmp_path: Path) -> None:
    data = collection()
    path = tmp_path / "manual.xlsx"
    write_workbook(data, [], path)
    path.write_bytes(result_cell_updates(path, {
        "F5": 5, "G5": "Y", "H5": "N", "I5": "N", "M5": "고객 확인 입력",
    }, sheet_name=PROCESS))
    before = path.read_bytes()
    assessment = read_assessment(path)
    assert assessment.interview_items[0].score == 3
    refresh_interview_summary(path, data, [])
    updated = load_workbook(path)
    assert updated[PROCESS]["F5"].value == 5
    assert updated[PROCESS]["M5"].value == "고객 확인 입력"
    with ZipFile(path) as after:
        from io import BytesIO
        with ZipFile(BytesIO(before)) as original:
            assert after.read("xl/worksheets/sheet10.xml") == original.read("xl/worksheets/sheet10.xml")


def test_platform_breakdown_reuses_real_identity_and_blueprint_linkage() -> None:
    from easm_agent.models import (
        AgentEvidence,
        CopilotAgentEvidence,
        EntraAgentIdentity,
        EntraBlueprint,
    )
    from easm_agent.report_integrated import identity_platform_map, platform_breakdown

    data = collection()
    data.copilot_agents = [CopilotAgentEvidence(
        agent_id="c1", environment_id="env1", platform="copilot_studio", entra_agent_id="ID-P1",
    )]
    data.agents = [AgentEvidence(
        collected_at=NOW, platform="foundry", agent_id="a1", agent_name="AgentX",
        subscription_id="SUB1",
        resource_id="/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.CognitiveServices"
                     "/accounts/acct1/projects/proj1/agents/AgentX",
        detection_confidence="tag",
    )]
    data.entra_blueprints = [EntraBlueprint(
        blueprint_id="bp1", tags=["agentName:agentx", "projectName:proj1", "accountName:acct1", "subscriptionId:sub1"],
    )]
    data.entra_agent_identities = [
        EntraAgentIdentity(identity_id="ID-P1"),
        EntraAgentIdentity(identity_id="ID-P3", blueprint_id="bp1"),
        EntraAgentIdentity(identity_id="ID-UNMAPPED"),
    ]
    identity_map = identity_platform_map(data)
    assert identity_map == {"id-p1": "P1", "id-p3": "P3"}

    finding = Finding(se_code="DS-SY-03", scope="in_scope", level="L4", metric_value=2 / 3, rationale="테스트",
        measurement=AssessmentMeasurement(numerator=2, denominator=3, complete=True, targets=[
            TargetAssessment(subject="ID-P1", status="compliant"),
            TargetAssessment(subject="ID-P3", status="compliant"),
            TargetAssessment(subject="ID-UNMAPPED", status="non_compliant"),
        ]),
    )
    breakdown = platform_breakdown("DS-SY-03", finding, identity_map)
    assert breakdown["P1"] == (1, 1) and breakdown["P2"] == (0, 0) and breakdown["P3"] == (1, 1)
    assert breakdown["P4"] is None and breakdown["P7"] is None

    power = Finding(se_code="DM-SY-01", scope="partial", level="L5", metric_value=1.0, rationale="테스트",
        measurement=AssessmentMeasurement(numerator=2, denominator=2, complete=True))
    assert platform_breakdown("DM-SY-01", power, {}) == {
        "P1": (2, 2), "P2": (2, 2), "P3": None, "P4": None, "P5": None, "P6": None, "P7": None,
    }
    azure_only = Finding(se_code="BI-SY-09", scope="partial", level="L5", metric_value=1.0, rationale="테스트",
        measurement=AssessmentMeasurement(numerator=1, denominator=1, complete=True))
    breakdown = platform_breakdown("BI-SY-09", azure_only, {})
    assert breakdown["P3"] == (1, 1) and breakdown["P1"] is None and breakdown["P2"] is None


def test_matrix_scope_for_combined_copilot_and_azure_checks() -> None:
    from easm_agent.report_integrated import platform_breakdown, platform_scope

    config = load_criteria(Settings(criteria_file=ROOT / "tests" / "fixtures" / "resource-criteria.yaml"))["items"]["BI-SY-13"]
    finding = Finding(
        se_code="BI-SY-13", scope="partial", level="L2", metric_value=0.5, rationale="test",
        measurement=AssessmentMeasurement(
            complete=True, numerator=2, denominator=4, targets=[
                TargetAssessment(subject="azure", status="compliant", contribution=1),
                TargetAssessment(subject="studio", status="compliant", contribution=1,
                                 observed={"platform": "copilot_studio"}),
                TargetAssessment(subject="builder", status="non_compliant", contribution=0,
                                 observed={"platform": "agent_builder"}),
                TargetAssessment(subject="unknown", status="non_compliant", contribution=0,
                                 observed={"platform": "unclassified_copilot"}),
            ],
        ),
    )
    breakdown = platform_breakdown("BI-SY-13", finding, {}, config)
    assert breakdown["P1"] == (1, 1)
    assert breakdown["P2"] == (0, 1)
    assert breakdown["P3"] == (1, 1)
    assert platform_scope("BI-SY-13", True, config) == {
        "P1": "A", "P2": "A", "P3": "A", "P4": "해당 없음",
        "P5": "해당 없음", "P6": "해당 없음", "P7": "해당 없음",
    }
    assert platform_scope("BI-SY-13", False, config)["P2"] == "X"
    assert platform_scope("BI-SY-13", True)["P2"] == "해당 없음"


def test_matrix_method_uses_evidence_origin_not_file_transport() -> None:
    from easm_agent.models import AdminReadResult
    from easm_agent.report_integrated import platform_scope

    data = collection()
    data.facts["copilot_inventory_complete"] = True
    finding = Finding(
        se_code="BI-SY-09", scope="partial", level="L1", metric_value=0, rationale="test",
        measurement=AssessmentMeasurement(complete=True, numerator=0, denominator=1, targets=[
            TargetAssessment(subject="studio", status="non_compliant", observed={"platform": "copilot_studio"}),
        ]),
    )
    config = load_criteria()["items"]["BI-SY-09"]
    assert platform_scope("BI-SY-09", True, config, finding, data)["P1"] == "A"
    finding.measurement.targets[0].observed["review_source"] = "official_admin_portal_read"
    assert platform_scope("BI-SY-09", True, config, finding, data)["P1"] == "E"
    url = "https://admin.powerplatform.microsoft.com/security/dataprotection/dlp"
    data.admin_evidence = [AdminReadResult(
        source="powerplatform.dlp_policies", command=url, module_version="portal", scope="test",
        completed=True, observed_at=NOW, object_count=0, detail="empty list",
        portal_pages=[{"url": url, "observed_at": NOW, "http_status": 200, "state": "empty", "object_count": 0}],
    )]
    assert platform_scope("DS-SY-02", True, data=data)["P1"] == "E"
    assert platform_scope("DM-SY-01", True, data=data)["P1"] == "A"


def test_generated_export_status_is_not_preserved_after_collection_failure(tmp_path: Path) -> None:
    data = collection()
    success = Finding(
        se_code="BI-SY-09", scope="partial", level="L5", metric_value=1, rationale="test",
        measurement=AssessmentMeasurement(
            complete=True, numerator=1, denominator=1,
            targets=[TargetAssessment(subject="studio", status="compliant", contribution=1,
                                      observed={"platform": "copilot_studio",
                                                "review_source": "official_admin_portal_read"})],
        ),
    )
    row = list(load_criteria()["items"]).index("BI-SY-09") + 8
    first, second = tmp_path / "success.xlsx", tmp_path / "failed.xlsx"
    write_workbook(data, [success], first)
    source = load_workbook(first)
    assert source[MATRIX][f"E{row}"].value == "E"
    assert source[MATRIX][f"AA{row}"].value == "E"
    assert source[MATRIX][f"Z{row}"].value == f'=A{row}&" "&B{row}'
    source.close()
    source = load_workbook(first)
    source[MATRIX][f"Z{row}"] = source[MATRIX][f"AA{row}"].value
    source[MATRIX][f"AA{row}"] = None
    source.save(first)
    source.close()
    failed = Finding(se_code="BI-SY-09", scope="partial", level="N/A", reason="permission_denied",
                     rationale="failed", measurement=AssessmentMeasurement(complete=False))
    write_workbook(data, [failed], second, interview_workbook=first)
    result = load_workbook(second)
    assert result[MATRIX][f"E{row}"].value == "X"
    assert result[MATRIX][f"F{row}"].value == "X"
    assert result[MATRIX][f"Z{row}"].value == f'=A{row}&" "&B{row}'
    result.close()


def test_copilot_details_use_publication_and_actual_target_decisions(tmp_path: Path) -> None:
    from easm_agent.models import CopilotAgentEvidence

    data = collection()
    data.facts["copilot_inventory_complete"] = True
    data.copilot_agents = [
        CopilotAgentEvidence(agent_id="studio", environment_id="env", platform="copilot_studio",
                             last_published_at=NOW, channels=[]),
        CopilotAgentEvidence(agent_id="builder", environment_id="env", platform="agent_builder",
                             last_published_at=NOW, channels=["Microsoft 365 Copilot"]),
    ]
    findings = [Finding(
        se_code=code, scope="partial", level="L5", metric_value=1, rationale="test",
        measurement=AssessmentMeasurement(complete=True, numerator=2, denominator=2, targets=[
            TargetAssessment(subject=agent.agent_id, status="compliant", contribution=1,
                             observed={"platform": agent.platform}) for agent in data.copilot_agents
        ]),
    ) for code in ("BI-SY-13", "OE-SY-19", "DS-SY-05", "BI-SY-10")]
    path = tmp_path / "details.xlsx"
    write_workbook(data, findings, path)
    book = load_workbook(path)
    detail = book["2b_세부 내역"]
    assert [detail[f"B{row}"].value for row in (20, 21, 22, 24)] == [2, 0, 0, 2]
    assert "사용 이력 아님" in detail["A18"].value
    assert "실제 노출·조치 기록 아님" in detail["A26"].value
    assert all(detail[f"B{row}"].value == detail[f"C{row}"].value == 2 for row in range(28, 32))
    assert "C28/B28" in detail["E28"].value
    assert "Agent 중복" in detail["A32"].value
    report = book["7_보고서 산출"]
    assert report["C168"].value == "전체 관측 대상 생성·등록·배포 상태"
    assert report["F169"].value == "2b_세부 내역!B32"
    for row in range(97, 123):
        assert report[f"A{row}"].value == "p.11" and report[f"B{row}"].value == "26개 항목 판정"
    scope = book["7a_보고서 산출(범위·신뢰도)"]
    assert "$Z$8:$Z$33" in scope["B25"].value
    assert scope["A74"].border.left.style == scope["A73"].border.left.style == "thin"
    assert scope["A82"].border.bottom.style == "medium"
    book.close()
    data.copilot_agents[0].channels = None
    write_workbook(data, findings, path)
    book = load_workbook(path)
    assert book["2b_세부 내역"]["B20"].value == 2
    assert "일치" in book["2b_세부 내역"]["F24"].value
    book.close()


def test_foundry_creation_is_reported_without_claiming_publication_or_runtime(tmp_path: Path):
    data = collection()
    data.facts["agent_inventory_complete"] = True
    data.agents = [
        AgentEvidence(collected_at=NOW, platform="foundry", agent_id="created-agent",
                      agent_name="Foundry", detection_confidence="tag", created_at=NOW),
        AgentEvidence(collected_at=NOW, platform="langchain", agent_id="host",
                      agent_name="Host", detection_confidence="tag"),
    ]
    data.exclude_host_candidates()
    path = tmp_path / "states.xlsx"
    write_workbook(data, [], path)
    book = load_workbook(path)
    detail = book["2b_세부 내역"]
    assert detail["H37"].value == "생성·등록 확인" and detail["N37"].value == 1
    assert detail["H38"].value is None and detail["N38"].value is None
    assert detail.column_dimensions["N"].hidden
    assert "채널 게시·실행 성공은 별도" in detail["M37"].value
    assert book["1a_플랫폼 기준"]["G7"].value == 1 and book["1a_플랫폼 기준"]["H7"].value == 0
    assert detail["B20"].value == 1 and detail["B22"].value == 0
    assert "$N$37:$N$37" in book["2a_월별 추이"]["C10"].value


def test_region_breakdown_does_not_assign_azure_population_to_copilot() -> None:
    from easm_agent.report_integrated import platform_breakdown

    finding = Finding(
        se_code="OE-SY-22", scope="partial", level="L5", metric_value=1, rationale="test",
        measurement=AssessmentMeasurement(complete=True, numerator=2, denominator=2, targets=[
            TargetAssessment(subject="azure", status="compliant"),
            TargetAssessment(subject="studio", status="compliant", observed={"platform": "copilot_studio"}),
        ]),
    )
    result = platform_breakdown("OE-SY-22", finding, {}, load_criteria()["items"]["OE-SY-22"])
    assert result["P1"] == (1, 1) and result["P2"] == (0, 0) and result["P3"] == (1, 1)


def test_report_columns_keep_numeric_units_formulas_and_section_headers(tmp_path: Path) -> None:
    path = tmp_path / "report-columns.xlsx"
    write_workbook(collection(), [], path)
    book = load_workbook(path)
    sheet = book["7_보고서 산출"]
    assert sheet.freeze_panes == "A3" and sheet.print_title_rows == "$1:$2"
    assert sheet["G4"].value == "보정 여부" and sheet["G15"].value == "보고서 표기"
    assert sheet["D169"].number_format == "General"
    assert sheet["E169"].value == "건"
    assert sheet["G174"].data_type == "f" and sheet["G174"].number_format == "General"
    assert "L2" in sheet["D174"].value
    assert "F5:F6" in sheet["F134"].value and "F5" in sheet["D134"].value
    assert "K5" in sheet["D97"].value and "H5" in sheet["F97"].value
    assert "26개" in sheet["A12"].value and "20개" not in sheet["A12"].value
    assert "H5" in sheet["F160"].value and "H10" in sheet["F165"].value
    assert sheet["D170"].data_type == "f" and "F14" in sheet["D170"].value
    assert not [(cell.coordinate, cell.value) for row in sheet for cell in row
                if isinstance(cell.value, str) and cell.value.startswith("=") and cell.data_type != "f"]
    book.close()


def test_refreshed_copilot_evidence_date_does_not_relabel_saved_azure_time(tmp_path: Path) -> None:
    data = collection()
    data.facts["copilot_inventory_status"] = [{"observed_at": NOW.replace(hour=12).isoformat()}]
    path = tmp_path / "dates.xlsx"
    write_workbook(data, [Finding(
        se_code="BI-SY-13", scope="partial", level="L5", metric_value=1, rationale="test",
        measurement=AssessmentMeasurement(complete=True, numerator=1, denominator=1),
    )], path)
    book = load_workbook(path)
    codes = list(load_criteria()["items"])
    copilot_row = 5 + codes.index("BI-SY-13") * 2
    azure_row = 5 + codes.index("OT-SY-25") * 2
    assert book[RAW][f"I{copilot_row}"].value == datetime(2026, 11, 23, 21)
    assert book[RAW][f"I{azure_row}"].value == datetime(2026, 11, 23, 9)
    book.close()


def test_builder_unsupported_identity_fields_are_not_marked_automatically_collected() -> None:
    from easm_agent.models import CopilotAgentEvidence, FieldStatus
    from easm_agent.report_integrated import platform_scope

    data = collection()
    data.copilot_agents = [CopilotAgentEvidence(
        agent_id="builder", environment_id="env", platform="agent_builder",
        field_status={"entra_agent_id": FieldStatus(reason="feature_unavailable", detail="not applicable")},
    )]
    assert platform_scope("DS-SY-03", True, data=data)["P2"] == "해당 없음"


def test_matrix_sheet_shows_real_platform_breakdown_and_reconciles_unmapped_identities(tmp_path: Path) -> None:
    from easm_agent.models import (
        AgentEvidence,
        CopilotAgentEvidence,
        EntraAgentIdentity,
        EntraBlueprint,
    )
    from easm_agent.report_integrated import MATRIX

    data = collection()
    data.copilot_agents = [CopilotAgentEvidence(
        agent_id="c1", environment_id="env1", platform="copilot_studio", entra_agent_id="ID-P1",
    )]
    data.agents = [AgentEvidence(
        collected_at=NOW, platform="foundry", agent_id="a1", agent_name="AgentX", subscription_id="SUB1",
        resource_id="/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.CognitiveServices"
                     "/accounts/acct1/projects/proj1/agents/AgentX",
        detection_confidence="tag",
    )]
    data.entra_blueprints = [EntraBlueprint(
        blueprint_id="bp1", tags=["agentName:agentx", "projectName:proj1", "accountName:acct1", "subscriptionId:sub1"],
    )]
    data.entra_agent_identities = [
        EntraAgentIdentity(identity_id="ID-P1"),
        EntraAgentIdentity(identity_id="ID-P3", blueprint_id="bp1"),
        EntraAgentIdentity(identity_id="ID-UNMAPPED"),
    ]
    path = tmp_path / "platform.xlsx"
    write_workbook(data, [Finding(se_code="DS-SY-03", scope="in_scope", level="L4", metric_value=2 / 3,
        rationale="테스트", measurement=AssessmentMeasurement(numerator=2, denominator=3, complete=True, targets=[
            TargetAssessment(subject="ID-P1", status="compliant"),
            TargetAssessment(subject="ID-P3", status="compliant"),
            TargetAssessment(subject="ID-UNMAPPED", status="non_compliant"),
        ]),
    )], path)
    book = load_workbook(path)
    matrix = book[MATRIX]
    assert matrix["E10"].value == "A" and matrix["F10"].value == "A" and matrix["G10"].value == "A"
    assert matrix["H10"].value == "해당 없음"
    assert "P1 1/1 · P2 0/0 · P3 1/1" in matrix["Q10"].value
    assert "미귀속 1건 중 충족 0건" in matrix["Q10"].value
    platform = book["1a_플랫폼 기준"]
    assert platform["M5"].value == (
        "=COUNTIF(INDEX('2c_수집 매트릭스'!$E$8:$K$33,0,"
        "MATCH($A5,'2c_수집 매트릭스'!$E$6:$K$6,0)),\"A\")"
    )
    assert platform["L5"].value == "=M5+N5"
    assert platform["Q5"].value == (
        "=COUNTIF(INDEX('2c_수집 매트릭스'!$E$8:$K$33,0,"
        "MATCH($A5,'2c_수집 매트릭스'!$E$6:$K$6,0)),\"해당 없음\")"
    )
    assert matrix["L10"].value == '=COUNTIF(E10:K10,"A")'


def test_manual_export_and_operator_review_markings_survive_regeneration(tmp_path: Path) -> None:
    data = collection()
    path = tmp_path / "input.xlsx"
    write_workbook(data, [], path)
    book = load_workbook(path)
    # A reviewer manually marks a platform cell as "Export"-verified and another as "운영자 확인".
    book[MATRIX]["H8"] = "E"
    book[MATRIX]["I8"] = "△"
    book.save(path)
    regenerated = tmp_path / "output.xlsx"
    write_workbook(data, [], regenerated, interview_workbook=path)
    matrix = load_workbook(regenerated)[MATRIX]
    assert matrix["H8"].value == "E"
    assert matrix["I8"].value == "△"
    # A platform never manually marked keeps the automated classification (해당 없음 for this code).
    assert matrix["J8"].value == "해당 없음"


def test_sheet_tab_colors_group_overview_sy_interview_and_report_sheets() -> None:
    from easm_agent.report_integrated import format_integrated_workbook

    book = load_workbook(assessment_template_path())
    format_integrated_workbook(book)
    overview = ("0_안내", "1_진단 개요", "1a_플랫폼 기준")
    sy = (RAW, "2a_월별 추이", "2b_세부 내역", "2c_수집 매트릭스", GRADES, "3a_단계 신뢰도")
    interview = (PROCESS, "5_문서 실사", "6_인터뷰 기록")
    report = ("7_보고서 산출", "7a_보고서 산출(범위·신뢰도)")
    colors = {book[name].sheet_properties.tabColor.rgb[-6:] for name in overview}
    assert len(colors) == 1
    sy_colors = {book[name].sheet_properties.tabColor.rgb[-6:] for name in sy}
    interview_colors = {book[name].sheet_properties.tabColor.rgb[-6:] for name in interview}
    report_colors = {book[name].sheet_properties.tabColor.rgb[-6:] for name in report}
    assert len(sy_colors) == 1 and len(interview_colors) == 1 and len(report_colors) == 1
    assert len({*colors, *sy_colors, *interview_colors, *report_colors}) == 4


def test_sample_responses_never_claim_document_or_system_verification(tmp_path: Path) -> None:
    path, filled = tmp_path / "input.xlsx", tmp_path / "sample.xlsx"
    write_workbook(collection(), [], path)
    path.write_bytes(result_cell_updates(path, {
        f"{column}{row}": None for row in range(5, 59) for column in ("F", "G", "H", "I", "M")
    }, sheet_name=PROCESS))
    rows = write_interview_responses(path, filled)
    assert len(rows) == 54
    book = load_workbook(filled)
    assert not book[PROCESS]["G5"].value and not book[PROCESS]["H5"].value
    assert "실측·증적 확인 아님" in book[PROCESS]["M5"].value
    assert all(item.score <= 2 for item in read_assessment(filled).interview_items)


def test_collect_package_and_deck_use_the_new_default_without_azure(tmp_path: Path) -> None:
    fixture = ROOT / "tests" / "fixtures" / "three_subscriptions.json"
    with patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("Azure 호출 금지")):
        assert main(["collect", "--fixture", str(fixture), "--output-dir", str(tmp_path)]) == 0
        result = load_result(tmp_path)
        workbook = next(tmp_path.rglob("AI Agent Governance Readiness*.xlsx"))
        presentation = next(tmp_path.rglob("AI Agent Governance Readiness*.pptx"))
        assert read_assessment(workbook).interview_items[0].score == 4
        assert main(["package", "--output-dir", str(workbook.parent)]) == 0
        assert main(["deck", "--output-dir", str(workbook.parent)]) == 0
    assert presentation.is_file() and result["mode"] == "fixture"
    assert len(read_assessment(workbook).system_items) == 26
    assert len(json.loads(next(tmp_path.rglob("raw-data-*.json")).read_text(encoding="utf-8"))["findings"]) == 26


def test_authentication_failure_outputs_both_reports_and_extractable_values(tmp_path: Path) -> None:
    with patch("easm_agent.cli.DefaultAzureCredential"), patch(
        "easm_agent.cli.collect", side_effect=AccessError("permission_denied", "private token not logged"),
    ):
        assert main(["collect", "--output-dir", str(tmp_path)]) == 2
    workbook = next(tmp_path.rglob("AI Agent Governance Readiness*.xlsx"))
    assert next(tmp_path.rglob("AI Agent Governance Readiness*.pptx")).is_file()
    result = load_result(workbook.parent)
    assert len(result["findings"]) == 26
    assert all(row["level"] == "N/A" and row["reason"] == "permission_denied" for row in result["findings"])
    assert "private token" not in json.dumps(result)
    cached = load_workbook(workbook, data_only=True)
    assert cached["7_보고서 산출"]["J11"].value == 2.6
    assert cached["7_보고서 산출"]["K11"].value == "확인 중"
    values = tmp_path / "values.json"
    assert main(["report-values", "--workbook", str(workbook), "--output", str(values)]) == 0
    assert len(json.loads(values.read_text(encoding="utf-8"))["system_table"]) == 26


def test_unrounded_gap_and_configured_threshold_control_correction() -> None:
    from easm_agent.report_values import build_report_values

    book = load_workbook(assessment_template_path())
    for row, score in enumerate((3, 3, 4, 3, 4, 3, 4, 3, 4), 5):
        book[PROCESS][f"F{row}"] = score
        for column in "GHI":
            book[PROCESS][f"{column}{row}"] = "Y"
    book[GRADES]["U5"] = 2
    values = build_report_values(book)
    assert values.cells["7_보고서 산출", "F5"] == pytest.approx(1.4583333333333)
    assert values.areas["DM"].final == 3.5 and values.areas["DM"].status == "미보정"
    book["1_진단 개요"]["B34"] = 1.4
    assert build_report_values(book).areas["DM"].final == 3.0


def test_explicit_manual_source_and_existing_run_are_preserved(tmp_path: Path) -> None:
    manual = tmp_path / "manual.xlsx"
    manual.write_bytes(result_cell_updates(assessment_template_path(), {"M5": "원본 보존 검증"}, sheet_name=PROCESS))
    inputs = load_workbook(manual)
    inputs["1_진단 개요"]["B34"] = 1.4
    inputs.save(manual)
    with patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("Azure 호출 금지")):
        assert main(["collect", "--fixture", str(ROOT / "tests" / "fixtures" / "three_subscriptions.json"),
                     "--interview-workbook", str(manual), "--output-dir", str(tmp_path)]) == 0
        workbook = next(tmp_path.rglob("AI Agent Governance Readiness*.xlsx"))
        assert main(["package", "--output-dir", str(workbook.parent)]) == 0
    assert load_workbook(workbook)[PROCESS]["M5"].value == "원본 보존 검증"
    assert load_workbook(workbook)["1_진단 개요"]["B34"].value == 1.4
    source, result = load_workbook(manual), load_workbook(workbook)
    for name, first, last, columns in (
        (PROCESS, 5, 58, (6, 7, 8, 9, 13)), ("5_문서 실사", 5, 66, (4, 5, 6, 7, 10)),
        ("6_인터뷰 기록", 5, 16, (1, 2, 3, 4, 5, 6)),
    ):
        for row in range(first, last+1):
            for column in columns:
                assert result[name].cell(row, column).value == source[name].cell(row, column).value


def test_invalid_code_fails_before_output_is_written(tmp_path: Path) -> None:
    path = tmp_path / "invalid.xlsx"
    with pytest.raises(ValueError, match="템플릿에 없는 SY 코드"):
        write_workbook(collection(), [Finding(
            se_code="BAD-SY-99", scope="partial", level="N/A", rationale="잘못된 코드",
        )], path)
    assert not path.exists()
