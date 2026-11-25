from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from pptx import Presentation
from pptx.util import Inches
from pydantic import ValidationError

from easm_agent.azure import AccessError, EvidenceStore
from easm_agent.cli import main
from easm_agent.collect import merge
from easm_agent.collect_report_evidence import collect_cost_history
from easm_agent.evaluation import evaluate
from easm_agent.models import (
    Agent365Package,
    Collection,
    CopilotAgentEvidence,
    CostRecord,
    Issue,
    Settings,
    load_criteria,
)
from easm_agent.report import write_reports
from easm_agent.report_backdata import metrics_by_key
from easm_agent.report_evidence import (
    ReportEvidenceExport,
    read_report_evidence,
    supplemental_metrics,
)
from easm_agent.report_pptx import presentation_template_path, shape
from scripts.export_report_evidence import explicit_policy_targets, export_conditional_access

NOW = datetime(2026, 11, 19, tzinfo=UTC)
TENANT = "11111111-1111-4111-8111-111111111111"
ROOT = Path(__file__).parents[1]
pytestmark = pytest.mark.usefixtures("legacy_presentation_template")


def packet() -> dict:
    def dataset(kind: str, code: str, records: list[dict], **extra: object) -> dict:
        return {
            "kind": kind, "code": code, "scope": "synthetic-explicit-scope",
            "source_kind": "official_admin_read", "source_ref": "approved-test-source",
            "observed_at": NOW.isoformat(), "complete": True, "population_complete": True,
            "reason": None, "records": records, **extra,
        }

    return {
        "schema_version": 1, "source_type": "approved_report_evidence", "approved": True,
        "tenant_id": TENANT, "tenant_verified": True, "data_mode": "live",
        "exported_at": NOW.isoformat(),
        "datasets": [
            dataset("creation_approvals", "DM-SY-27", [
                {"subject": f"agent-{month}-{index}", "created_at": f"2026-{month:02}-09T00:00:00Z",
                 "approval_found": index == 0, "approval_id": f"request-{month}" if index == 0 else None,
                 "approved_at": f"2026-{month:02}-08T00:00:00Z" if index == 0 else None}
                for month in range(6, 12) for index in range(2)
            ], source_kind="approval_workflow", period_start="2026-06-01T00:00:00Z", period_end=NOW.isoformat()),
            dataset("registry", "DP-SY-28", [
                {"subject": "agent-a", "owner_present": True, "deployment_scope_present": True},
                {"subject": "agent-b", "owner_present": False, "deployment_scope_present": True},
            ], source_kind="organization_registry", observed_subjects=["agent-a", "agent-b", "agent-c"]),
            dataset("predeployment_evaluations", "BI-SY-29", [
                {"subject": f"deployment-{index}", "version": "v1", "deployed_at": "2026-10-10T00:00:00Z",
                 "evaluation_found": True, "evaluation_version": "v1" if index == 0 else "v2",
                 "evaluation_completed_at": "2026-10-09T00:00:00Z", "evaluation_status": "completed"}
                for index in range(2)
            ]),
            dataset("target_controls", "OE-SY-30", [{"subject": "agent-a", "value": True}]),
            dataset("audit_retention", "OE-SY-31", [
                {"subject": "policy-a", "retention_duration": "SixMonths", "priority": 1},
                {"subject": "policy-b", "retention_duration": "TwelveMonths", "priority": 2},
            ]),
            dataset("usage", "OT-SY-32", [
                {"subject": f"agent-{index}", "created_at": "2026-05-01T00:00:00Z",
                 "coverage_start": "2026-06-01T00:00:00Z", "coverage_end": NOW.isoformat(),
                 "calls_30d": calls30, "calls_90d": calls90}
                for index, (calls30, calls90) in enumerate(((1, 2), (0, 1), (0, 0)))
            ], period_start="2026-06-01T00:00:00Z", period_end=NOW.isoformat()),
            dataset("exposures", "OT-SY-33", [
                {"subject": "case-a", "category": "personal", "severity": "high", "remediation": "remediated"},
                {"subject": "case-b", "category": "financial", "severity": "high", "remediation": "open"},
            ]),
            dataset("cost_history", "OT-SY-34", [
                {"subject": f"bill-{month}", "occurred_at": f"2026-{month:02}-10T00:00:00Z",
                 "amount": 100.0, "attributed_amount": 60.0, "currency": "USD"}
                for month in range(6, 12)
            ], period_start="2026-06-01T00:00:00Z", period_end=NOW.isoformat()),
            dataset("target_controls", "OE-SY-39", [{"subject": "agent-a", "value": False}], source_kind="hr_export"),
        ],
    }


def collection(payload: dict | None = None) -> Collection:
    export = ReportEvidenceExport.model_validate_json(json.dumps(payload or packet()))
    return Collection(collected_at=NOW, report_evidence=export.datasets)


def metrics(data: Collection) -> dict:
    return {row.key: row.value for row in supplemental_metrics(data, load_criteria())}


def test_scoped_report_evidence_computes_matching_history_and_never_changes_existing_grades() -> None:
    data = collection()
    before = evaluate(Collection(collected_at=NOW), load_criteria(), {})
    after = evaluate(data, load_criteria(), {})
    assert [(row.se_code, row.level) for row in before] == [(row.se_code, row.level) for row in after]
    values = metrics(data)
    assert values["approval.match"] == 0.5
    assert values["registry.match"] == pytest.approx(2 / 3)
    assert values["registry.missing"] == values["registry.metadata_missing"] == 1
    assert values["evaluation.predeploy"] == 0.5
    assert values["creation.month.202606.total"] == 2
    assert values["creation.month.202606.approved"] == 1
    assert values["usage.inactive90"] == pytest.approx(1 / 3)
    assert [values[f"usage.{key}.count"] for key in ("active30", "active31_90", "inactive90")] == [1, 1, 1]
    assert values["security.exposure"] == 0.5
    assert values["security.exposure.financial.open"] == 1
    assert values["audit.retention"] == 6 and values["audit.required"] == 12
    assert values["cost.month.202611.attributed"] == 60
    assert values["identity.departed"] == 0


@pytest.mark.parametrize("change", ["unknown_approval", "partial_population", "short_usage"])
def test_unknown_records_periods_and_months_are_not_zero(change: str) -> None:
    payload = packet()
    key = "approval.match"
    if change == "unknown_approval":
        payload["datasets"][0]["records"][0].update(approval_found=None, approval_id=None, approved_at=None)
    elif change == "partial_population":
        payload["datasets"][0]["population_complete"] = False
    else:
        payload["datasets"][5]["records"][0]["coverage_start"] = "2026-11-01T00:00:00Z"
        key = "usage.inactive90"
    assert metrics(collection(payload))[key] is None


def test_month_with_no_cost_records_inside_the_observed_period_is_a_real_zero() -> None:
    payload = packet()
    payload["datasets"][7]["records"].pop()
    assert metrics(collection(payload))["cost.month.202611.total"] == 0.0


@pytest.mark.parametrize("change", ["bool_version", "fake_hr", "future_record", "bad_cost", "duplicate"])
def test_invalid_or_misrepresented_evidence_is_rejected(change: str) -> None:
    payload = packet()
    if change == "bool_version":
        payload["schema_version"] = True
    elif change == "fake_hr":
        payload["datasets"][-1]["source_kind"] = "official_admin_read"
    elif change == "future_record":
        payload["datasets"][0]["records"][0]["created_at"] = (NOW + timedelta(days=1)).isoformat()
    elif change == "bad_cost":
        payload["datasets"][7]["records"][0]["attributed_amount"] = 101
    else:
        payload["datasets"].append(payload["datasets"][0])
    with pytest.raises(ValidationError):
        collection(payload)


def test_import_checks_tenant_age_and_duplicates_before_mutation(tmp_path: Path) -> None:
    path = tmp_path / "approved.json"
    path.write_text(json.dumps(packet()), encoding="utf-8")
    store = EvidenceStore(tmp_path, NOW)
    data = read_report_evidence(path, TENANT, NOW, store)
    original = data.model_dump()
    with pytest.raises(ValueError, match="중복"):
        merge(data, data.model_copy(deep=True))
    assert data.model_dump() == original
    for tenant, instant in ((str(uuid.uuid4()), NOW), (TENANT, NOW + timedelta(days=2))):
        with pytest.raises(ValueError):
            read_report_evidence(path, tenant, instant, store)


def test_reports_compute_metrics_in_memory_to_restore_real_values_without_modifying_template_parts(tmp_path: Path) -> None:
    data = collection()
    findings = evaluate(data, load_criteria(), {})
    workbook = write_reports(data, findings, tmp_path, "fixture")
    book = load_workbook(workbook)
    assert len(book.sheetnames) == 18
    assert metrics_by_key(data, findings, "fixture")["approval.match"].value == 0.5
    assert len(book["8a_수집 Raw 데이터"].tables) == 18
    book.close()
    deck = next(workbook.parent.glob("EASM-report-*.pptx"))
    presentation = Presentation(deck)
    assert shape(presentation.slides[6], 29226).fill.type is not None
    assert shape(presentation.slides[6], 29337).text == "2"
    assert shape(presentation.slides[8], 36182).text == "50%"
    assert shape(presentation.slides[8], 36399).text == "50%"
    assert shape(presentation.slides[9], 37293).text == "$100.00"
    assert "33%" in shape(presentation.slides[9], 40212).text
    assert "Agent 소비 비용" in shape(presentation.slides[9], 36858).text
    assert shape(presentation.slides[9], 37392).text == "식별 60%"
    assert shape(presentation.slides[9], 37063).text == "귀속 불가"
    assert "최근월" in shape(presentation.slides[9], 37107).text
    assert "식별 미확인 월의 회색은 총액" not in shape(presentation.slides[9], 40583).text
    assert "반올림" in shape(presentation.slides[9], 40303).text
    for identifier in (39772, 39945, 40122):
        assert shape(presentation.slides[9], identifier)._element.find(".//{*}spPr/{*}noFill") is None
    legend = shape(presentation.slides[9], 36978)
    assert shape(presentation.slides[9], 37293).top >= legend.top + legend.height + Inches(0.05)
    assert shape(presentation.slides[6], 29376).text == "2026.06"
    assert shape(presentation.slides[9], 37342).text == "2026.06"
    with ZipFile(presentation_template_path()) as source, ZipFile(deck) as result:
        for name in source.namelist():
            if not name.startswith(("ppt/slides/slide", "ppt/notesSlides/notesSlide")):
                assert source.read(name) == result.read(name), name


def test_executive_summary_uses_available_approval_registry_and_risk_evidence(tmp_path: Path) -> None:
    data = collection()
    workbook = write_reports(data, evaluate(data, load_criteria(), {}), tmp_path, "fixture")
    presentation = Presentation(next(workbook.parent.glob("EASM-report-*.pptx")))
    summary, overview = presentation.slides[1], presentation.slides[2]
    table = next(item.table for item in overview.shapes if item.has_table)
    assert "등록부 일치 67%" in shape(presentation.slides[6], 31446).text
    assert "확인 중" in table.cell(1, 1).text
    visible = "\n".join(
        target.text_frame.text for slide in (summary, overview) for target in slide.shapes if target.has_text_frame
    )
    assert "N/A" not in visible and "not_found" not in visible


def test_cost_chart_preserves_observed_totals_when_allocation_is_unknown(tmp_path: Path) -> None:
    payload = packet()
    costs = payload["datasets"][7]["records"]
    costs[0]["attributed_amount"] = None
    costs[1].update(amount=0.0, attributed_amount=0.0)
    costs.pop(3)
    data = collection(payload)
    workbook = write_reports(data, evaluate(data, load_criteria(), {}), tmp_path, "fixture")
    slide = Presentation(next(workbook.parent.glob("EASM-report-*.pptx"))).slides[9]
    assert shape(slide, 37293).text == "$100.00"
    assert shape(slide, 37392).text == "식별 확인 중"
    assert shape(slide, 37063).text == "귀속 불가·식별 미확인"
    assert shape(slide, 37245)._element.find(".//{*}spPr/{*}noFill") is None
    assert shape(slide, 37548).text == "$0.00"
    assert shape(slide, 37657).text == "식별 확인 중"
    assert shape(slide, 37947).text == "식별 60%"
    assert shape(slide, 38133).text == "$0.00"
    assert shape(slide, 38008)._element.find(".//{*}spPr/{*}noFill") is not None
    assert shape(slide, 38070)._element.find(".//{*}spPr/{*}noFill") is not None


def test_cost_chart_identifies_gray_as_total_when_all_allocations_are_unknown(tmp_path: Path) -> None:
    payload = packet()
    for row in payload["datasets"][7]["records"]:
        row["attributed_amount"] = None
    data = collection(payload)
    workbook = write_reports(data, evaluate(data, load_criteria(), {}), tmp_path, "fixture")
    slide = Presentation(next(workbook.parent.glob("EASM-report-*.pptx"))).slides[9]
    assert shape(slide, 37063).text == "총액·식별 미확인"
    assert shape(slide, 37392).text == "식별 확인 중"


def test_usage_chart_does_not_show_a_partial_observation_as_activity(tmp_path: Path) -> None:
    payload = packet()
    payload["datasets"][5]["records"][0]["coverage_start"] = "2026-11-01T00:00:00Z"
    data = collection(payload)
    workbook = write_reports(data, evaluate(data, load_criteria(), {}), tmp_path, "fixture")
    slide = Presentation(next(workbook.parent.glob("EASM-report-*.pptx"))).slides[9]
    for identifier in (39277, 39438, 39603, 39772, 39945, 40122):
        assert shape(slide, identifier)._element.find(".//{*}spPr/{*}noFill") is not None
    assert "사용 현황은" in shape(slide, 39858).text and "N/A" not in shape(slide, 39858).text
    assert shape(slide, 40303).text == ""


def test_cli_refuses_live_report_inputs_with_fixture_before_authentication(tmp_path: Path) -> None:
    with patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("No Azure calls")):
        assert main([
            "collect", "--fixture", str(ROOT / "tests" / "fixtures" / "three_subscriptions.json"),
            "--report-evidence-file", str(tmp_path / "absent.json"), "--output-dir", str(tmp_path / "output"),
        ]) == 1
    assert not (tmp_path / "output").exists()


def test_existing_copilot_and_catalog_sources_supply_additional_controls_with_null_semantics() -> None:
    data = Collection(collected_at=NOW, facts={
        "copilot_inventory_complete": True, "agent365_registry_complete": True,
    }, copilot_agents=[
        CopilotAgentEvidence(
            agent_id="a", environment_id="env", platform="copilot_studio",
            last_published_at=NOW, authentication="Microsoft Entra", owner_present=True,
        ),
        CopilotAgentEvidence(
            agent_id="b", environment_id="env", platform="agent_builder",
            last_published_at=None, authentication="None", owner_present=False,
        ),
    ], agent365_packages=[
        Agent365Package(package_id="a", request_type="publish", request_status="approved"),
        Agent365Package(package_id="b", request_type="publish", request_status="pending"),
        Agent365Package(package_id="c", request_type="access", request_status="approved"),
    ])
    for key in ("copilot.published", "copilot.authentication", "copilot.owner_presence", "catalog.publish_request_approval"):
        assert metrics(data)[key] == 0.5
    data.copilot_agents[0].authentication = "future-unknown-mode"
    data.agent365_packages[0].request_type = "unknownFutureValue"
    assert metrics(data)["copilot.authentication"] is None
    assert metrics(data)["catalog.publish_request_approval"] is None
    data.facts["copilot_inventory_complete"] = False
    data.issues = [Issue(collector="copilot_inventory", target="inventory", reason="permission_denied", detail="Denied")]
    rows = {row.key: row for row in supplemental_metrics(data, load_criteria())}
    assert rows["copilot.published"].value is None
    assert rows["copilot.published"].reason == "permission_denied"


def test_conditional_access_explicit_ids_exclusions_report_only_and_unknown_selectors() -> None:
    agent, policy_id = str(uuid.uuid4()), str(uuid.uuid4())
    policy = {
        "id": policy_id, "state": "enabled",
        "conditions": {"clientApplications": {
            "includeAgentIdServicePrincipals": [agent],
            "excludeAgentIdServicePrincipals": [], "agentIdServicePrincipalFilter": None,
        }},
    }
    assert explicit_policy_targets([{"id": agent}], [policy])[0].value is True
    policy["conditions"]["clientApplications"]["excludeAgentIdServicePrincipals"] = [agent]
    assert explicit_policy_targets([{"id": agent}], [policy])[0].value is False
    policy["conditions"]["clientApplications"]["excludeAgentIdServicePrincipals"] = []
    policy["conditions"]["clientApplications"]["includeAgentIdServicePrincipals"] = ["All"]
    assert explicit_policy_targets([{"id": agent}], [policy])[0].value is None
    policy["conditions"]["clientApplications"]["includeAgentIdServicePrincipals"] = [agent]
    policy["conditions"]["clientApplications"]["agentIdServicePrincipalFilter"] = {"mode": "include", "rule": "unresolved"}
    assert explicit_policy_targets([{"id": agent}], [policy])[0].value is None
    policy["state"] = "enabledForReportingButNotEnforced"
    assert explicit_policy_targets([{"id": agent}], [policy])[0].value is False


def test_conditional_access_permission_denial_is_exported_not_invented_as_zero() -> None:
    with patch("scripts.export_report_evidence.ReaderHTTP") as reader:
        reader.return_value.list_graph.side_effect = AccessError("permission_denied", "Denied")
        export = export_conditional_access(TENANT, object(), approved=True, now=NOW)
    assert export.tenant_verified is False
    assert export.datasets[0].complete is False
    assert export.datasets[0].reason == "permission_denied"
    assert export.datasets[0].records == []


@pytest.mark.parametrize("denied", [False, True])
def test_historical_cost_reuses_read_query_but_never_back_projects_current_allocation(tmp_path: Path, denied: bool) -> None:
    sid = str(uuid.uuid4())
    data = Collection(collected_at=NOW, subscriptions=[sid], facts={"agent_inventory_complete": True})

    def costs(subscription: str, incoming: Collection, *, start: datetime) -> None:
        assert subscription == sid and start == datetime(2026, 6, 1, tzinfo=UTC)
        if denied:
            raise AccessError("permission_denied", "Denied")
        incoming.costs = [CostRecord(
            subscription_id=sid, resource_id=f"/subscriptions/{sid}/providers/ai/example",
            amount=100, currency="USD", usage_date="20260610",
        )]

    with patch("easm_agent.collect_report_evidence.SignalCollector.ai_ids", return_value={"example"}), patch(
        "easm_agent.collect_report_evidence.SignalCollector.costs", side_effect=costs,
    ):
        result = collect_cost_history(object(), data, Settings(), EvidenceStore(tmp_path, NOW), NOW, load_criteria())
    assert result.report_evidence[0].complete is not denied
    if denied:
        assert result.issues[0].reason == "permission_denied"
        assert metrics(result)["cost.history"] is None
    else:
        assert metrics(result)["cost.month.202606.total"] == 100
        assert metrics(result)["cost.month.202606.attributed"] is None
        assert data.costs == []
