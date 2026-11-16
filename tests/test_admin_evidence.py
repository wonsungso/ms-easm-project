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
    ENVIRONMENTS_URL,
    admin_observations,
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


def test_admin_receipt_records_scope_and_provenance_without_assigning_grades(tmp_path: Path) -> None:
    data = ingest(tmp_path, packet())
    read = data.admin_evidence[0]
    assert read.completed and read.object_count == 1
    assert Path(read.evidence_refs[0]).is_file()
    observations = {item.code: item for item in admin_observations(data)}
    assert observations["DM-SY-02"].status == observations["BI-SY-10"].status == "일부 수집"
    assert all(item.evidence_only for item in observations.values())
    path = tmp_path / "report.xlsx"
    original = Finding(se_code="DS-SY-06", level="L5", scope="partial", metric_value=1, rationale="original")
    write_workbook(data, [original], path)
    book = load_workbook(path)
    sheet = book["6. 수집 결과"]
    rows = {sheet.cell(row, 2).value: row for row in range(5, 90)}
    for code in ("DM-SY-02", "BI-SY-10"):
        assert sheet.cell(rows[code], 7).value == "일부 수집"
        assert sheet.cell(rows[code], 9).value == "판정 보류" and sheet.cell(rows[code], 13).value is None
    assert sheet.cell(rows["DS-SY-06"], 13).value == 5 and original.level == "L5"
    assert len(book["8. 수집 Raw 데이터"].tables) == 16
    assert data.proposals == []


@pytest.mark.parametrize("change", ["tenant", "unverified", "command", "duplicate", "count", "future"])
def test_admin_receipts_fail_closed(tmp_path: Path, change: str) -> None:
    value = packet()
    if change == "tenant":
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
    row = next(item for item in admin_observations(data) if item.code == "DM-SY-02")
    assert row.status == "일부 수집" and row.reason == "feature_unavailable"
    assert row.metrics["powerplatform.environment_roles"]["object_count"] is None


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
    finding = Finding(se_code="DS-SY-06", level="L5", scope="partial", metric_value=1, rationale="original")
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
    assert (workbook.parent / "evidence").is_dir()


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
    row = next(item for item in after["findings"] if item["se_code"] == "OT-SY-30")
    assert row["level"] == "L5" and row["metric_value"] == 1
    assert after["collection"]["assessment_provenance"]["origin"] == "saved_snapshot_reassessment"
    assert after["collection"]["assessment_provenance"]["source_result_data_sha256"]
    sheet = load_workbook(next(workbook.parent.glob("report-*.xlsx")))["6. 수집 결과"]
    rows = {sheet.cell(row, 2).value: row for row in range(5, 90)}
    assert sheet.cell(rows["OT-SY-30"], 7).value == "수집됨"
    assert "민감 데이터 검색 활성 1개 구독" in sheet.cell(rows["OT-SY-30"], 10).value
    assert sheet.cell(rows["OT-SY-30"], 13).value == 5


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
    function Get-AdminPowerAppEnvironmentRoleAssignment {{ [pscustomobject]@{{ RoleName = 'fixture-role' }} }}
    function Get-AdminDlpPolicy {{ [pscustomobject]@{{ DisplayName = 'fixture-policy' }}, [pscustomobject]@{{ DisplayName = 'second' }} }}
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
def test_power_platform_export_keeps_only_object_counts(tmp_path: Path, login: str) -> None:
    completed, value = run_ps_export(tmp_path, login=login)
    assert completed.returncode == 0, completed.stderr
    export = AdminEvidenceExport.model_validate(value)
    assert export.tenant_verified and {read.source: read.object_count for read in export.reads} == {
        "powerplatform.environment_roles": 1, "powerplatform.dlp_policies": 2,
    }
    assert "fixture-role" not in json.dumps(value) and "fixture-policy" not in json.dumps(value)


def test_power_platform_device_code_is_recorded_as_unavailable_not_success(tmp_path: Path) -> None:
    completed, value = run_ps_export(tmp_path, login="DeviceCode")
    assert completed.returncode == 2
    export = AdminEvidenceExport.model_validate(value)
    assert not export.tenant_verified
    assert all(not read.completed and read.reason == "feature_unavailable" and read.object_count is None
               for read in export.reads)
