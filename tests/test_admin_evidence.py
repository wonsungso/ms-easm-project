from __future__ import annotations

import base64
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError

from easm_agent.azure import EvidenceStore
from easm_agent.cli import main
from easm_agent.collect_admin_evidence import (
    DATAVERSE_ROLES_COMMAND,
    ENVIRONMENTS_URL,
    read_admin_evidence,
)
from easm_agent.models import AdminEvidenceExport, Collection, Finding
from easm_agent.report import load_result, write_reports
from easm_agent.report_excel import write_workbook
from scripts.export_admin_environments import export_environments

NOW = datetime(2026, 11, 9, tzinfo=UTC)
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ROOT = Path(__file__).parents[1]


def packet() -> dict:
    return {
        "schema_version": 1, "source_type": "official_admin_read", "tenant_id": TENANT,
        "tenant_verified": True, "exported_at": NOW.isoformat(),
        "reads": [{
            "source": "powerplatform.environments", "command": ENVIRONMENTS_URL,
            "module_version": "API 2024-10-01", "scope": "administrator-visible environments",
            "completed": True, "observed_at": NOW.isoformat(), "object_count": 1,
            "environments": [{
                "environment_id": "environment-id", "display_name": "demo-environment",
                "environment_type": "Sandbox", "protection_level": "Basic",
            }], "detail": "subset, not tenant-wide approval evidence",
        }],
    }


def ingest(tmp_path: Path, payload: dict) -> Collection:
    path = tmp_path / "admin.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return read_admin_evidence(path, TENANT, NOW, EvidenceStore(tmp_path / "evidence", NOW))


def power_platform_packet() -> dict:
    value = packet()
    value["reads"][0].update(object_count=3, environments=[
        {"environment_id": "Default-" + TENANT, "environment_type": "Default", "protection_level": "Basic"},
        {"environment_id": "env-prod", "environment_type": "Production", "protection_level": "Standard"},
        {"environment_id": "env-dev", "environment_type": "Sandbox", "protection_level": "Standard"},
    ])
    value["reads"].append({
        "source": "powerplatform.environment_roles", "command": "Get-AdminPowerAppEnvironmentRoleAssignment",
        "module_version": "2.0.220", "scope": "role assignments", "completed": True,
        "observed_at": NOW.isoformat(), "object_count": 3,
        "role_counts": {"Default-" + TENANT: 0, "env-prod": 2, "ENV-DEV": 1}, "detail": "counts only",
    })
    value["reads"].append({
        "source": "powerplatform.dlp_policies", "command": "Get-AdminDlpPolicy",
        "module_version": "2.0.220", "scope": "policies", "completed": True,
        "observed_at": NOW.isoformat(), "object_count": 2, "detail": "scopes only",
        "policies": [
            {"scope_type": "OnlyEnvironments", "environment_ids": ["env-prod"]},
            {"scope_type": "ExceptEnvironments", "environment_ids": ["env-dev"]},
        ],
    })
    return value


def graded(data: Collection) -> dict:
    from easm_agent.evaluation import evaluate
    from easm_agent.models import DEFAULT_TAGS, load_criteria

    return {row.se_code: row for row in evaluate(data, load_criteria(), DEFAULT_TAGS)}


def test_admin_receipt_records_provenance_and_scores_power_platform_environments(tmp_path: Path) -> None:
    data = ingest(tmp_path, power_platform_packet())
    assert all(Path(read.evidence_refs[0]).is_file() for read in data.admin_evidence)
    rows = graded(data)
    assert (rows["BI-SY-08"].level, rows["BI-SY-08"].measurement.numerator) == ("L2", 2)
    assert (rows["DM-SY-01"].level, rows["DM-SY-01"].measurement.numerator) == ("L2", 2)
    assert (rows["DS-SY-02"].level, rows["DS-SY-02"].measurement.numerator) == ("L2", 2)
    assert rows["DS-SY-02"].measurement.targets[0].observed["environment_type"] == "Default"
    path = tmp_path / "report.xlsx"
    write_workbook(data, list(rows.values()), path)
    book = load_workbook(path)
    sheet = book["6. 수집 결과"]
    sheet_rows = {sheet.cell(row, 2).value: row for row in range(5, 90)}
    for code in ("DM-SY-01", "DS-SY-02", "BI-SY-08"):
        assert sheet.cell(sheet_rows[code], 7).value == "수집됨"
        assert sheet.cell(sheet_rows[code], 13).value == 2
    assert len(book["8. 수집 Raw 데이터"].tables) == 18


@pytest.mark.parametrize("change", ["tenant", "unverified", "command", "duplicate", "count", "future", "role_sum", "policy_count"])
def test_admin_receipts_fail_closed(tmp_path: Path, change: str) -> None:
    value = power_platform_packet() if change in ("role_sum", "policy_count") else packet()
    if change == "role_sum":
        value["reads"][1]["object_count"] = 5
    elif change == "policy_count":
        value["reads"][2]["object_count"] = 5
    elif change == "tenant":
        value["tenant_id"] = OTHER
    elif change == "unverified":
        value["tenant_verified"] = False
    elif change == "command":
        value["reads"][0]["command"] = "Set-TenantSettings"
    elif change == "duplicate":
        value["reads"].append(value["reads"][0].copy())
    elif change == "count":
        value["reads"][0]["object_count"] = 0
    elif change == "future":
        value["exported_at"] = (NOW + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError):
        ingest(tmp_path, value)


@pytest.mark.parametrize("change", ["false_success", "false_zero", "personal_fields", "boolean_count", "incomplete"])
def test_admin_record_schema_rejects_success_shaped_fallbacks(change: str) -> None:
    value = packet()
    read = value["reads"][0]
    if change == "false_success":
        read["object_count"] = None
    elif change == "false_zero":
        read.update(completed=False, reason="permission_denied")
    elif change == "personal_fields":
        read["user_principal_name"] = "person@example.invalid"
    elif change == "boolean_count":
        read["object_count"] = True
    elif change == "incomplete":
        read.update(completed=False, reason="error", object_count=None)
    with pytest.raises(ValidationError):
        AdminEvidenceExport.model_validate(value)


def test_failed_read_keeps_null_not_zero_and_does_not_hide_other_success(tmp_path: Path) -> None:
    value = packet()
    value["reads"].append({
        "source": "powerplatform.environment_roles", "command": "Get-AdminPowerAppEnvironmentRoleAssignment",
        "module_version": "not_installed", "scope": "unavailable", "completed": False,
        "observed_at": NOW.isoformat(), "object_count": None, "reason": "feature_unavailable",
        "detail": "official module unavailable",
    })
    data = ingest(tmp_path, value)
    rows = graded(data)
    assert rows["BI-SY-08"].level == "L1" and rows["BI-SY-08"].metric_value == 0
    assert rows["DM-SY-01"].level == "N/A" and rows["DM-SY-01"].metric_value is None
    assert rows["DM-SY-01"].reason == "feature_unavailable"
    assert rows["DS-SY-02"].level == "N/A" and rows["DS-SY-02"].reason == "not_found"


def portal_packet() -> dict:
    value = packet()
    value["source_type"] = "official_admin_portal_read"
    origin = "https://admin.powerplatform.microsoft.com"
    common = {
        "module_version": "Power Platform admin center (browser)",
        "scope": "approved administrator browser read", "completed": True,
        "observed_at": NOW.isoformat(), "detail": "counts and policy scopes only",
    }

    def page(url: str, count: int) -> dict:
        return {
            "url": url, "observed_at": NOW.isoformat(), "http_status": 200,
            "state": "populated" if count else "empty", "object_count": count,
        }

    role_url = origin + "/manage/environments/environment/environment-id/roles/"
    value["reads"] = [
        {
            **common, "source": "powerplatform.environment_roles",
            "command": origin + "/manage/environments", "object_count": 1,
            "role_counts": {"environment-id": 1},
            "portal_pages": [page(role_url + "environmentadmin", 0), page(role_url + "environmentmaker", 1)],
        },
        {
            **common, "source": "powerplatform.dlp_policies",
            "command": origin + "/security/dataprotection/dlp", "object_count": 0,
            "policies": [], "portal_pages": [page(origin + "/security/dataprotection/dlp", 0)],
        },
    ]
    return value


def test_portal_receipt_grades_actual_assignments_and_explicit_empty_policies(tmp_path: Path) -> None:
    data = ingest(tmp_path, packet())
    portal = ingest(tmp_path, portal_packet())
    data.admin_evidence.extend(portal.admin_evidence)
    rows = graded(data)
    assert (rows["DM-SY-01"].level, rows["DM-SY-01"].metric_value) == ("L5", 1)
    assert (rows["DS-SY-02"].level, rows["DS-SY-02"].metric_value) == ("L1", 0)
    saved = json.loads(Path(portal.admin_evidence[0].evidence_refs[0]).read_text(encoding="utf-8"))
    assert "official_admin_portal_read" in json.dumps(saved)
    assert portal.admin_evidence[0].command != "Get-AdminPowerAppEnvironmentRoleAssignment"


@pytest.mark.parametrize("change", ["origin", "missing_view", "count", "http_error", "false_empty", "future", "source"])
def test_portal_receipts_reject_unverified_or_incomplete_views(tmp_path: Path, change: str) -> None:
    value = portal_packet()
    pages = value["reads"][0]["portal_pages"]
    if change == "origin":
        pages[0]["url"] = pages[0]["url"].replace("admin.powerplatform.microsoft.com", "example.invalid")
    elif change == "missing_view":
        pages.pop()
    elif change == "count":
        pages[1]["object_count"] = 2
    elif change == "http_error":
        pages[0]["http_status"] = 403
    elif change == "false_empty":
        pages[1]["state"] = "empty"
    elif change == "future":
        pages[0]["observed_at"] = (NOW + timedelta(minutes=1)).isoformat()
    elif change == "source":
        value["source_type"] = "official_admin_read"
        value["reads"][0]["command"] = "Get-AdminPowerAppEnvironmentRoleAssignment"
    with pytest.raises(ValueError):
        ingest(tmp_path, value)


def test_portal_unqueried_environment_is_not_scored_as_zero(tmp_path: Path) -> None:
    value = packet()
    value["reads"][0]["environments"].append({"environment_id": "unqueried"})
    value["reads"][0]["object_count"] = 2
    data = ingest(tmp_path, value)
    data.admin_evidence.extend(ingest(tmp_path, portal_packet()).admin_evidence)
    row = graded(data)["DM-SY-01"]
    assert row.level == "N/A" and row.metric_value is None


def test_powershell_unqueried_environment_is_not_scored_as_zero(tmp_path: Path) -> None:
    value = power_platform_packet()
    value["reads"][1]["role_counts"].pop("Default-" + TENANT)
    rows = graded(ingest(tmp_path, value))
    row = rows["DM-SY-01"]
    assert row.level == "N/A" and row.metric_value is None and row.reason == "not_found"
    assert row.measurement is not None and not row.measurement.complete
    assert row.measurement.reason == "일부 환경의 역할 할당 조회 범위 미확인"
    assert [target.status for target in row.measurement.targets] == [
        "unknown", "compliant", "compliant",
    ]
    assert rows["DS-SY-02"].level == "L2" and rows["BI-SY-08"].level == "L2"


def test_dataverse_role_counts_cover_environments_the_cmdlet_does_not_return(tmp_path: Path) -> None:
    value = power_platform_packet()
    value["reads"][1]["role_counts"].pop("Default-" + TENANT)
    value["reads"][1]["object_count"] = 3
    data = ingest(tmp_path, value)
    assert graded(data)["DM-SY-01"].level == "N/A"
    extra = packet()
    extra["reads"] = [{
        "source": "powerplatform.dataverse_roles",
        "command": DATAVERSE_ROLES_COMMAND,
        "module_version": "Dataverse Web API v9.2", "scope": "Dataverse-linked environments",
        "completed": True, "observed_at": NOW.isoformat(), "object_count": 1,
        "role_counts": {"Default-" + TENANT: 1}, "detail": "counts only",
    }]
    data.admin_evidence.extend(ingest(tmp_path, extra).admin_evidence)
    row = graded(data)["DM-SY-01"]
    assert row.level == "L5" and row.metric_value == 1


def test_dataverse_source_needs_its_own_command_and_cannot_stand_alone_with_wrong_counts(tmp_path: Path) -> None:
    value = packet()
    value["reads"] = [{
        "source": "powerplatform.dataverse_roles", "command": "Get-AdminPowerAppEnvironmentRoleAssignment",
        "module_version": "x", "scope": "x", "completed": True, "observed_at": NOW.isoformat(),
        "object_count": 1, "role_counts": {"env": 1}, "detail": "x",
    }]
    with pytest.raises(ValueError):
        ingest(tmp_path, value)
    value["reads"][0]["command"] = DATAVERSE_ROLES_COMMAND
    value["reads"][0]["object_count"] = 5
    with pytest.raises(ValueError):
        ingest(tmp_path, value)


@pytest.mark.parametrize("recorded_mode,requested_mode", [("fixture", "fixture"), ("live", "fixture")])
def test_package_rejects_fixture_admin_import_before_writing_evidence(
    tmp_path: Path, recorded_mode: str, requested_mode: str,
) -> None:
    data = Collection(collected_at=NOW)
    with patch("easm_agent.cli.latest_raw", return_value=tmp_path / "raw.json"), patch(
        "easm_agent.cli.load_result", return_value={
            "collection": data.model_dump(mode="json"), "findings": [], "mode": recorded_mode,
        },
    ), patch("easm_agent.cli.read_admin_evidence") as read:
        assert main([
            "package", "--output-dir", str(tmp_path), "--mode", requested_mode,
            "--admin-evidence-file", str(tmp_path / "admin.json"),
        ]) == 1
        read.assert_not_called()


def test_package_requires_existing_evidence_root(tmp_path: Path) -> None:
    data = Collection(collected_at=NOW, facts={"evidence_directory": str(tmp_path / "missing")})
    with patch("easm_agent.cli.latest_raw", return_value=tmp_path / "raw.json"), patch(
        "easm_agent.cli.load_result", return_value={
            "collection": data.model_dump(mode="json"), "findings": [], "mode": "live",
        },
    ), patch("easm_agent.cli.read_admin_evidence") as read:
        assert main([
            "package", "--output-dir", str(tmp_path), "--tenant-id", TENANT,
            "--admin-evidence-file", str(tmp_path / "admin.json"),
        ]) == 1
        read.assert_not_called()


def test_package_enriches_portable_embedded_evidence_without_regrading(tmp_path: Path) -> None:
    data = Collection(collected_at=NOW, facts={"evidence_directory": str(tmp_path / "old-evidence")})
    finding = Finding(se_code="DS-SY-04", level="L5", scope="partial", metric_value=1, rationale="original")
    workbook = write_reports(data, [finding], tmp_path / "output")
    before = load_result(workbook.parent)
    assert before["collection"]["facts"]["evidence_directory"] == "embedded:evidence"
    path = tmp_path / "admin.json"
    path.write_text(json.dumps(packet()), encoding="utf-8")
    assert main([
        "package", "--output-dir", str(workbook.parent), "--tenant-id", TENANT,
        "--admin-evidence-file", str(path),
    ]) == 0
    after = load_result(workbook.parent)
    assert after["findings"] == before["findings"]
    assert len(after["collection"]["admin_evidence"]) == len(after["evidence"]) == 1
    assert after["provenance"]["unattached_evidence"] == []
    assert not (workbook.parent / "evidence").exists()
    assert sorted(path.name for path in workbook.parent.iterdir()) == sorted(
        [workbook.name, f"EASM-report-{workbook.parent.name}.pptx", f"raw-data-{workbook.parent.name}.json"])
    assert main(["package", "--output-dir", str(workbook.parent)]) == 0
    assert len(load_result(workbook.parent)["evidence"]) == 1


def test_package_reassess_grades_defender_protection_from_saved_collection(tmp_path: Path) -> None:
    from easm_agent.models import DefenderPlan

    sid = "11111111-1111-4111-8111-111111111111"
    data = Collection(
        collected_at=NOW, subscriptions=[sid], facts={
            "evidence_directory": str(tmp_path / "old-evidence"), "inventory_complete": True,
            "defender_plans_complete_subscriptions": [sid],
        },
        defender_plans=[
            DefenderPlan(subscription_id=sid, plan="AI", tier="Standard", extensions={"AIPromptEvidence": True}),
            DefenderPlan(subscription_id=sid, plan="CloudPosture", tier="Standard",
                         extensions={"SensitiveDataDiscovery": True}),
        ],
    )
    workbook = write_reports(data, [], tmp_path / "output")
    assert main([
        "package", "--output-dir", str(workbook.parent), "--tenant-id", TENANT, "--reassess",
    ]) == 0
    after = load_result(workbook.parent)
    row = next(item for item in after["findings"] if item["se_code"] == "OT-SY-25")
    assert row["level"] == "L5" and row["metric_value"] == 1
    assert after["collection"]["assessment_provenance"]["origin"] == "saved_snapshot_reassessment"
    assert after["collection"]["assessment_provenance"]["source_result_data_sha256"]
    sheet = load_workbook(next(workbook.parent.glob("report-*.xlsx")))["6. 수집 결과"]
    rows = {sheet.cell(row, 2).value: row for row in range(5, 90)}
    assert sheet.cell(rows["OT-SY-25"], 7).value == "수집됨"
    assert "민감 데이터 검색 활성 1개 구독" in sheet.cell(rows["OT-SY-25"], 10).value
    assert sheet.cell(rows["OT-SY-25"], 13).value == 5


def token(tenant: str = TENANT, app: bool = False) -> str:
    claims = {"tid": tenant, "idtyp": "app" if app else "user"}
    if not app:
        claims["scp"] = "user_impersonation"
    part = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return "header." + part + ".signature"


def test_environment_export_uses_only_get_and_minimizes_real_api_fields() -> None:
    credential = Mock()
    credential.get_token.return_value.token = token()
    response = Mock(status_code=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.json.return_value = {"value": [{
        "id": "env", "tenantId": TENANT, "type": "Default", "protectionLevel": "Basic",
        "createdBy": {"name": "Private Person"}, "url": "https://private.invalid",
    }]}
    session = Mock()
    session.headers = {}
    session.get.return_value = response
    with patch("scripts.export_admin_environments.AzureCliCredential") as factory, patch(
        "scripts.export_admin_environments.requests.Session",
    ) as sessions:
        factory.return_value.__enter__.return_value = credential
        sessions.return_value.__enter__.return_value = session
        result = export_environments(TENANT)
    assert result.tenant_verified and result.reads[0].object_count == 1
    assert result.reads[0].environments[0].display_name is None
    assert "Private Person" not in result.model_dump_json() and "private.invalid" not in result.model_dump_json()
    session.get.assert_called_once()
    assert session.get.call_args.args[0] == ENVIRONMENTS_URL
    assert not session.post.called


@pytest.mark.parametrize("tenant,app", [(OTHER, False), (TENANT, True)])
def test_environment_export_rejects_wrong_tenant_or_diagnostic_app(tenant: str, app: bool) -> None:
    credential = Mock()
    credential.get_token.return_value.token = token(tenant, app)
    with patch("scripts.export_admin_environments.AzureCliCredential") as factory:
        factory.return_value.__enter__.return_value = credential
        with pytest.raises(ValueError):
            export_environments(TENANT)


def run_ps_export(tmp_path: Path, *, login: str = "Interactive") -> tuple[subprocess.CompletedProcess, dict]:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if not executable:
        pytest.skip("PowerShell unavailable")
    script = str(ROOT / "scripts" / "export_admin_evidence.ps1").replace("'", "''")
    output = str(tmp_path / "powerplatform.json").replace("'", "''")
    code = f"""
    function Import-Module {{}}
    function Get-Module {{ [pscustomobject]@{{ Version = [version]'2.0.220' }} }}
    function Add-PowerAppsAccount {{
        [CmdletBinding()] param($Endpoint, $TenantID, $UseSystemBrowser)
        if ([bool]$UseSystemBrowser -ne ('{login}' -eq 'Browser')) {{ throw 'unexpected login mode' }}
    }}
    function Get-AdminPowerAppEnvironmentRoleAssignment {{
        [pscustomobject]@{{ RoleName = 'fixture-role'; EnvironmentName = 'env-a' }},
        [pscustomobject]@{{ RoleName = 'fixture-role'; EnvironmentName = 'env-a' }},
        [pscustomobject]@{{ RoleName = 'fixture-role'; EnvironmentName = 'env-b' }}
    }}
    function Get-AdminDlpPolicy {{
        [pscustomobject]@{{ DisplayName = 'fixture-policy'; FilterType = 'include'; Environments = @(
            [pscustomobject]@{{ name = 'env-a'; id = '/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments/env-a' }}) }},
        [pscustomobject]@{{ DisplayName = 'second'; FilterType = 'none'; Environments = $null }}
    }}
    & '{script}' -TenantId '{TENANT}' -Service PowerPlatform -OutputPath '{output}' -Login {login}
    exit $LASTEXITCODE
    """
    completed = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", code],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert (tmp_path / "powerplatform.json").is_file(), completed.stderr
    return completed, json.loads((tmp_path / "powerplatform.json").read_text(encoding="utf-8-sig"))


@pytest.mark.parametrize("login", ["Interactive", "Browser"])
def test_power_platform_export_keeps_only_counts_and_policy_scopes(tmp_path: Path, login: str) -> None:
    completed, value = run_ps_export(tmp_path, login=login)
    assert completed.returncode == 0, completed.stderr
    export = AdminEvidenceExport.model_validate(value)
    reads = {read.source: read for read in export.reads}
    assert export.tenant_verified and {source: read.object_count for source, read in reads.items()} == {
        "powerplatform.environment_roles": 3, "powerplatform.dlp_policies": 2,
    }
    assert reads["powerplatform.environment_roles"].role_counts == {"env-a": 2, "env-b": 1}
    assert [(row.scope_type, row.environment_ids) for row in reads["powerplatform.dlp_policies"].policies] == [
        ("OnlyEnvironments", ["env-a"]), ("AllEnvironments", []),
    ]
    assert "fixture-role" not in json.dumps(value) and "fixture-policy" not in json.dumps(value)


def test_power_platform_device_code_is_recorded_as_unavailable_not_success(tmp_path: Path) -> None:
    completed, value = run_ps_export(tmp_path, login="DeviceCode")
    assert completed.returncode == 2
    export = AdminEvidenceExport.model_validate(value)
    assert not export.tenant_verified
    assert all(not read.completed and read.reason == "feature_unavailable" and read.object_count is None
               for read in export.reads)

