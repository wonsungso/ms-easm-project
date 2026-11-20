from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from easm_agent.azure import (
    PP_INVENTORY_URL,
    PP_SCOPE,
    EvidenceStore,
    ReaderHTTP,
)
from easm_agent.collect import collect, merge
from easm_agent.collect_copilot import (
    CopilotInventoryExport,
    load_copilot_export,
    read_copilot_inventory,
)
from easm_agent.models import Collection, Settings
from scripts.export_copilot_inventory import PROJECTION, export_inventory, inventory_pages

NOW = datetime.now(UTC)
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
BUILDER = "11111111-1111-4111-8111-111111111111"
STUDIO = "22222222-2222-4222-8222-222222222222"
OWNER = "33333333-3333-4333-8333-333333333333"


def row(identifier: str = BUILDER, origin: str = "Microsoft Copilot Agent Builder") -> dict:
    return {
        "agent_id": identifier, "environment_id": "Default-" + TENANT,
        "display_name": "demo", "created_in": origin,
        "created_at": (NOW - timedelta(days=1)).isoformat(), "last_published_at": None,
        "owner_present": True, "entra_agent_id": None, "blueprint_id": None,
        "model": None, "authentication": "Microsoft Entra", "channels": [],
        "is_quarantined": False, "shared_with_tenant": False,
    }


def packet() -> dict:
    return {
        "schema_version": 1, "source_type": "official_admin_read", "approved": True,
        "command": PP_INVENTORY_URL, "auth_type": "delegated_user", "tenant_id": TENANT,
        "tenant_verified": True, "observed_at": NOW.isoformat(), "exported_at": NOW.isoformat(),
        "completed": True, "object_count": 2, "total_records": 2, "reason": None,
        "failure_code": None,
        "agents": [row(), row(STUDIO, "Copilot Studio")],
    }


def write_packet(directory: Path, payload: dict | None = None) -> Path:
    path = directory / "copilot.json"
    path.write_text(json.dumps(payload if payload is not None else packet()), encoding="utf-8")
    return path


def credential(claims: dict | None = None) -> Mock:
    if claims is None:
        claims = {"tid": TENANT, "oid": OWNER, "scp": "user_impersonation", "idtyp": "user"}
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    result = Mock()
    result.get_token.return_value.token = "header." + encoded + ".signature"
    return result


def page(rows: list | None = None, total: int | None = None, skip: str | None = None) -> dict:
    rows = [row()] if rows is None else rows
    return {
        "totalRecords": len(rows) if total is None else total, "count": len(rows),
        "resultTruncated": 0 if skip else 1, "skipToken": skip, "data": rows,
    }


def response(payload: dict, status: int = 200) -> Mock:
    return Mock(status_code=status, headers={}, json=Mock(return_value=payload))


def export_with_responses(responses: list) -> tuple[CopilotInventoryExport, Mock]:
    session = Mock()
    session.request.side_effect = responses
    with patch("easm_agent.azure.requests.Session", return_value=session), patch(
        "easm_agent.azure.time.sleep",
    ):
        result = export_inventory(TENANT, credential(), approved=True)
    return result, session


def test_ingestion_keeps_saas_separate_and_minimizes_evidence(tmp_path: Path) -> None:
    value = packet()
    value["agents"][0]["display_name"] = "demo person@example.invalid"
    path = write_packet(tmp_path, value)
    data = read_copilot_inventory(path, TENANT, NOW, EvidenceStore(tmp_path / "evidence", NOW))
    assert not data.agents and len(data.copilot_agents) == 2
    builder, studio = data.copilot_agents
    assert (builder.platform, studio.platform) == ("agent_builder", "copilot_studio")
    assert builder.owner_present is True and builder.channels == []
    assert builder.entra_agent_id is None and builder.blueprint_id is None
    assert builder.field_status["entra_agent_id"].reason == "feature_unavailable"
    assert studio.field_status["entra_agent_id"].reason == "not_found"
    assert studio.last_published_at is None and "last_published_at" not in studio.field_status
    assert data.facts["copilot_inventory_complete"] is True
    saved = Path(builder.evidence_refs[0]).read_text(encoding="utf-8")
    assert OWNER not in saved and "person@example.invalid" not in saved
    assert "ownerId" not in saved and "createdBy" not in saved


def test_unknown_origin_preserves_raw_value_without_classification(tmp_path: Path) -> None:
    value = packet()
    value["agents"][0]["created_in"] = "AgentBuilder"
    data = read_copilot_inventory(
        write_packet(tmp_path, value), TENANT, NOW, EvidenceStore(tmp_path / "evidence", NOW),
    )
    assert data.copilot_agents[0].platform == "unclassified_copilot"
    assert data.copilot_agents[0].created_in == "AgentBuilder"
    assert data.copilot_agents[0].field_status["platform"].reason == "feature_unavailable"


@pytest.mark.parametrize("origin", [
    "Microsoft 365 Copilot Agent Builder",
    "microsoft 365 copilot agent builder",
    "Copilot Studio Lite",
])
def test_builder_origin_is_classified_case_insensitively(tmp_path: Path, origin: str) -> None:
    value = packet()
    value["agents"][0]["created_in"] = origin
    data = read_copilot_inventory(
        write_packet(tmp_path, value), TENANT, NOW, EvidenceStore(tmp_path / "evidence", NOW),
    )
    assert data.copilot_agents[0].platform == "agent_builder"
    assert data.copilot_agents[0].created_in == origin


@pytest.mark.parametrize(("field", "value"), [
    ("tenant_id", "not-a-uuid"), ("tenant_id", OTHER), ("tenant_verified", False),
    ("approved", False), ("approved", "true"), ("schema_version", True),
    ("source_type", "fixture"), ("auth_type", "app"), ("command", "https://evil.invalid"),
    ("object_count", True), ("object_count", 1), ("total_records", None),
    ("reason", "error"), ("ownerId", OWNER),
    ("exported_at", NOW.replace(tzinfo=None).isoformat()),
    ("exported_at", 1), ("exported_at", (NOW + timedelta(days=1)).isoformat()),
    ("observed_at", (NOW - timedelta(days=2)).isoformat()),
])
def test_export_provenance_fails_closed(tmp_path: Path, field: str, value: object) -> None:
    payload = packet()
    payload[field] = value
    with pytest.raises(ValueError):
        load_copilot_export(write_packet(tmp_path, payload), TENANT, NOW)


@pytest.mark.parametrize(("field", "value"), [
    ("agent_id", "bot-name"), ("environment_id", ""), ("environment_id", " "),
    ("entra_agent_id", OWNER + "bad"), ("blueprint_id", "name"),
    ("created_at", NOW.replace(tzinfo=None).isoformat()), ("created_at", 1),
    ("created_at", (NOW + timedelta(days=1)).isoformat()),
    ("last_published_at", (NOW - timedelta(days=3)).isoformat()),
    ("owner_present", "true"), ("is_quarantined", 0), ("shared_with_tenant", "false"),
    ("channels", "Teams"), ("channels", [1]), ("ownerId", OWNER),
    ("createdBy", OWNER), ("description", "private prompt"),
])
def test_row_schema_rejects_malformed_or_personal_fields(
    tmp_path: Path, field: str, value: object,
) -> None:
    payload = packet()
    payload["agents"][0][field] = value
    with pytest.raises(ValueError):
        load_copilot_export(write_packet(tmp_path, payload), TENANT, NOW)


def test_duplicate_ids_rejected_within_and_between_files(tmp_path: Path) -> None:
    payload = packet()
    payload["agents"][1] = payload["agents"][0].copy()
    payload["agents"][1]["environment_id"] = payload["agents"][0]["environment_id"].upper()
    with pytest.raises(ValueError):
        load_copilot_export(write_packet(tmp_path, payload), TENANT, NOW)
    incoming = read_copilot_inventory(
        write_packet(tmp_path), TENANT, NOW, EvidenceStore(tmp_path / "evidence", NOW),
    )
    target = Collection(collected_at=NOW)
    merge(target, incoming)
    with pytest.raises(ValueError, match="중복"):
        merge(target, incoming)
    assert len(target.copilot_agents) == 2


def test_failed_export_keeps_nulls_and_reason(tmp_path: Path) -> None:
    payload = packet()
    payload.update(
        completed=False, reason="permission_denied", failure_code="permission_denied",
        object_count=None, total_records=None, agents=[], tenant_verified=False,
    )
    data = read_copilot_inventory(
        write_packet(tmp_path, payload), TENANT, NOW, EvidenceStore(tmp_path / "evidence", NOW),
    )
    assert not data.copilot_agents and not data.facts["copilot_inventory_complete"]
    assert data.issues[0].reason == "permission_denied"
    for field, value in (("object_count", 0), ("total_records", 0), ("agents", [row()])):
        broken = {**payload, field: value}
        with pytest.raises(ValueError):
            load_copilot_export(write_packet(tmp_path, broken), TENANT, NOW)


def test_full_pagination_retries_and_projects_no_personal_content() -> None:
    result, session = export_with_responses([
        response({}, 429), response(page(total=2, skip="sensitive-continuation")),
        response(page([row(STUDIO, "Copilot Studio")], total=2)),
    ])
    assert result.completed and result.object_count == result.total_records == 2
    assert result.tenant_verified is True and session.request.call_count == 3
    second_body = session.request.call_args_list[-1].kwargs["json"]
    assert second_body["Options"]["SkipToken"] == "sensitive-continuation"
    assert second_body["TableName"] == "PowerPlatformResources"
    assert second_body["Clauses"][0]["Values"] == ["'microsoft.copilotstudio/agents'"]
    assert PROJECTION["agent_id"] == "name"
    assert PROJECTION["dataverse_agent_id"] == "properties.name"
    projection = second_body["Clauses"][1]["FieldList"]
    assert not any("createdBy" in field or "description" in field for field in projection)
    assert "owner_present" in PROJECTION and "ownerId" not in PROJECTION
    saved = result.model_dump_json()
    assert OWNER not in saved and "sensitive-continuation" not in saved
    assert "ownerId" not in saved and "createdBy" not in saved


def test_sdk_not_truncated_value_accepts_complete_empty_inventory() -> None:
    result, _ = export_with_responses([response({
        "totalRecords": 0, "count": 0, "resultTruncated": 1, "skipToken": None, "data": [],
    })])
    assert result.completed
    assert result.object_count == result.total_records == 0
    assert result.reason is None


@pytest.mark.parametrize(("status", "message", "reason"), [
    (403, "Forbidden", "permission_denied"),
    (403, "Tenant is not licensed for inventory", "license_missing"),
    (401, "not licensed", "permission_denied"),
    (404, "Not found", "feature_unavailable"),
    (500, "Internal failure", "error"),
])
def test_permissions_and_explicit_license_failures_remain_distinct(
    status: int, message: str, reason: str,
) -> None:
    result, _ = export_with_responses([response({"error": {"message": message}}, status)] * 4)
    assert not result.completed and result.reason == reason
    assert result.object_count is None and result.total_records is None and result.agents == []
    assert message not in result.model_dump_json()


def test_network_failure_is_not_permission_or_malformed_response() -> None:
    result, _ = export_with_responses([requests.ConnectionError("sensitive")] * 4)
    assert result.reason == "error" and result.failure_code == "network_error"
    assert "sensitive" not in result.model_dump_json()


@pytest.mark.parametrize("changes", [
    {"count": True}, {"count": "1"}, {"count": 2}, {"totalRecords": False},
    {"totalRecords": 0}, {"data": {}}, {"resultTruncated": True},
    {"resultTruncated": 0, "skipToken": None}, {"skipToken": 123},
    {"resultTruncated": 1, "skipToken": "sensitive"},
])
def test_malformed_pages_emit_incomplete_null_totals(changes: dict) -> None:
    result, _ = export_with_responses([response({**page(), **changes})])
    assert not result.completed and result.reason == "error"
    assert result.failure_code == "invalid_response"
    assert result.object_count is None and result.total_records is None and not result.agents
    assert "sensitive" not in result.model_dump_json()


@pytest.mark.parametrize("pages", [
    [page(total=3, skip="sensitive"), page([row(STUDIO)], total=3, skip="sensitive")],
    [page(total=2, skip="sensitive"), page([row(STUDIO)], total=3)],
    [page(total=2, skip="sensitive"), page(total=2)],
    [page(total=2, skip="sensitive"), page([], total=2)],
    [page(total=2, skip="sensitive"), page([], total=2, skip="another")],
])
def test_pagination_rejects_cycles_duplicates_and_inconsistent_totals(pages: list) -> None:
    result, _ = export_with_responses([response(value) for value in pages])
    assert not result.completed and result.reason == "error" and not result.agents
    assert "sensitive" not in result.model_dump_json()


@pytest.mark.parametrize("claims", [
    {"tid": OTHER, "scp": "user_impersonation", "oid": OWNER},
    {"tid": TENANT, "roles": ["Reader"], "oid": OWNER},
    {"tid": TENANT, "scp": "user_impersonation", "oid": OWNER, "idtyp": "app"},
    {"tid": TENANT, "scp": "", "oid": OWNER},
    {"tid": TENANT, "scp": ["user_impersonation"], "oid": OWNER},
    {"tid": [], "scp": "user_impersonation", "oid": OWNER},
])
def test_non_user_or_wrong_tenant_tokens_fail_before_network(claims: dict) -> None:
    with patch("easm_agent.azure.requests.Session") as session:
        result = export_inventory(TENANT, credential(claims), approved=True)
    session.return_value.request.assert_not_called()
    assert not result.completed and not result.tenant_verified
    assert result.reason == "permission_denied"


@pytest.mark.parametrize("url", [
    PP_INVENTORY_URL.replace("2024-10-01", "2025-01-01"),
    PP_INVENTORY_URL.replace("api.powerplatform.com", "api.powerplatform.com.evil.invalid"),
    PP_INVENTORY_URL.replace("/resources/query", "/resources/delete"),
    PP_INVENTORY_URL + "&extra=1",
])
def test_pp_transport_allowlist_is_exact(url: str) -> None:
    session = Mock()
    with pytest.raises(ValueError):
        ReaderHTTP(credential(), session=session).request("POST", url, PP_SCOPE, {})
    session.request.assert_not_called()


def test_valid_empty_inventory_is_complete_not_error() -> None:
    http = Mock()
    http.request.return_value = page([])
    assert inventory_pages(http) == []


@pytest.mark.parametrize(("flag", "expected"), [(1, True), (0, False), (None, None)])
def test_projected_owner_presence_accepts_boolean_serialization(flag: int | None, expected: bool | None) -> None:
    projected = {**row(), "owner_present": flag}
    result, _ = export_with_responses([response(page([projected]))])
    assert result.completed
    assert result.agents[0].owner_present is expected


@pytest.mark.parametrize(("dataverse_id", "expected"), [(STUDIO, STUDIO), (None, BUILDER)])
def test_dataverse_agent_id_is_preferred_when_present(dataverse_id: str | None, expected: str) -> None:
    projected = {**row(), "dataverse_agent_id": dataverse_id}
    result, _ = export_with_responses([response(page([projected]))])
    assert result.completed
    assert result.agents[0].agent_id == expected
    assert "dataverse_agent_id" not in result.model_dump_json()


def test_invalid_dataverse_agent_id_does_not_fall_back() -> None:
    projected = {**row(), "dataverse_agent_id": "not-a-guid"}
    result, _ = export_with_responses([response(page([projected]))])
    assert not result.completed and result.failure_code == "invalid_response"


def test_unexpected_numeric_owner_presence_is_not_inferred() -> None:
    result, _ = export_with_responses([response(page([{**row(), "owner_present": 2}]))])
    assert not result.completed and result.failure_code == "invalid_response"


def test_extra_server_owner_fields_are_never_saved() -> None:
    result, _ = export_with_responses([response(page([{**row(), "ownerId": OWNER}]))])
    assert not result.completed and result.reason == "error"
    assert OWNER not in result.model_dump_json()


def test_collect_merges_approved_file_without_copilot_api_calls(tmp_path: Path) -> None:
    path = write_packet(tmp_path)
    settings = Settings(
        tenant_id=TENANT, expected_principal_id=OWNER, subscriptions=[OTHER],
        evidence_dir=tmp_path / "evidence", copilot_inventory_files=[path],
    )
    baseline = Collection(collected_at=NOW, completed_subscriptions=[OTHER],
                          facts={"inventory_complete": True})
    with patch("easm_agent.collect.verify_identity"), patch(
        "easm_agent.collect.collect_subscription", return_value=baseline,
    ), patch("easm_agent.collect.EntraCollector") as entra, patch(
        "easm_agent.collect.ReaderHTTP",
    ) as http:
        entra.return_value.discover.return_value = Collection(collected_at=NOW)
        result = collect(settings, credential(), NOW)
    assert len(result.copilot_agents) == 2 and not result.agents
    assert result.facts["copilot_inventory_complete"] is True
    http.return_value.request.assert_not_called()


@pytest.mark.parametrize(("enabled", "status", "reason"), [
    (False, 200, None), (True, 200, None),
    (True, 403, "permission_denied"), (True, 403, "license_missing"),
])
def test_agent365_registry_is_opt_in_minimized_and_preserves_failures(
    tmp_path: Path, enabled: bool, status: int, reason: str | None,
) -> None:
    from easm_agent.collect_agent365 import REGISTRY_URL, Agent365Collector, crosscheck_agent365
    from easm_agent.evaluation import evaluate
    from easm_agent.models import load_conventions, load_criteria

    settings = Settings(
        tenant_id=TENANT, expected_principal_id=OWNER, subscriptions=[OTHER],
        evidence_dir=tmp_path / "evidence", **({"agent365_registry": True} if enabled else {}),
    )
    baseline = Collection(collected_at=NOW, completed_subscriptions=[OTHER],
                          facts={"inventory_complete": True})
    payload = {"value": [{
        "id": "package", "displayName": "registry-agent", "version": "1",
        "owners": [{"id": OWNER, "userPrincipalName": "person@example.invalid"}],
        "shortDescription": "private description",
    }]} if status == 200 else {
        "error": {"message": "Tenant is not licensed" if reason == "license_missing" else "Forbidden"},
    }
    session = Mock()
    session.request.side_effect = [
        response(payload, status), response({"id": "package", "activeUsers": 7}, 200),
    ]
    auth = credential()
    with patch("easm_agent.collect.verify_identity"), patch(
        "easm_agent.collect.collect_subscription", return_value=baseline,
    ), patch("easm_agent.collect.EntraCollector") as entra, patch(
        "easm_agent.azure.requests.Session", return_value=session,
    ), patch("easm_agent.collect.Agent365Collector", wraps=Agent365Collector) as registry, patch(
        "easm_agent.collect.crosscheck_agent365", wraps=crosscheck_agent365,
    ) as crosscheck:
        entra.return_value.discover.return_value = Collection(collected_at=NOW)
        result = collect(settings, auth, NOW)
    if not enabled:
        registry.assert_not_called()
        crosscheck.assert_not_called()
        session.request.assert_not_called()
        assert not result.agent365_packages and not result.agent365_crosschecks
        return
    registry.assert_called_once()
    assert registry.call_args.args[0].store is None
    minimized_store = registry.call_args.args[2]
    assert minimized_store.path.is_relative_to(Path(result.facts["evidence_directory"]))
    assert minimized_store.path != Path(result.facts["evidence_directory"])
    crosscheck.assert_called_once()
    assert session.request.call_count == (2 if reason is None else 1)
    assert session.request.call_args_list[0].args == ("GET", REGISTRY_URL)
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)
    assert auth.get_token.call_args.args == ("https://graph.microsoft.com/.default",)
    assert result.facts["agent365_requested"] is True
    assert result.facts["agent365_registry_complete"] is (reason is None)
    assert len(result.agent365_crosschecks) == 26 and result.evidence_sources
    if reason is None:
        assert len(result.agent365_packages) == 1
        assert result.agent365_packages[0].active_users_30d == 7
        assert result.agent365_packages[0].detail_evidence_refs
        refs = result.agent365_packages[0].evidence_refs
    else:
        assert not result.agent365_packages
        failure = next(row for row in result.issues if row.collector == "agent365_registry")
        assert failure.reason == reason
        assert next(row for row in result.agent365_crosschecks
                    if row.se_code == "DS-SE-03").reason == reason
        refs = failure.evidence_refs
    assert refs
    text = Path(refs[0]).read_text(encoding="utf-8")
    assert OWNER not in text and "person@example.invalid" not in text and "private description" not in text
    without_registry = result.model_copy(deep=True)
    without_registry.agent365_packages = []
    without_registry.agent365_crosschecks = []
    without_registry.issues = [
        row for row in without_registry.issues if row.collector != "agent365_registry"
    ]
    for key in list(without_registry.facts):
        if key.startswith("agent365_"):
            del without_registry.facts[key]
    criteria, conventions = load_criteria(settings), load_conventions(settings)
    assert evaluate(result, criteria, conventions) == evaluate(
        without_registry, criteria, conventions,
    )


@pytest.mark.parametrize("authentication_error", [False, True])
def test_agent365_token_failures_preserve_other_collection_and_minimize_details(
    tmp_path: Path, authentication_error: bool,
) -> None:
    from azure.core.exceptions import ClientAuthenticationError

    settings = Settings(
        tenant_id=TENANT, expected_principal_id=OWNER, subscriptions=[OTHER],
        evidence_dir=tmp_path / "evidence", agent365_registry=True,
    )
    auth = credential()
    auth.get_token.side_effect = (
        ClientAuthenticationError("sensitive account information")
        if authentication_error else ValueError("sensitive account information")
    )
    baseline = Collection(collected_at=NOW, completed_subscriptions=[OTHER],
                          facts={"inventory_complete": True})
    session = Mock()
    with patch("easm_agent.collect.verify_identity"), patch(
        "easm_agent.collect.collect_subscription", return_value=baseline,
    ), patch("easm_agent.collect.EntraCollector") as entra, patch(
        "easm_agent.azure.requests.Session", return_value=session,
    ):
        entra.return_value.discover.return_value = Collection(collected_at=NOW)
        result = collect(settings, auth, NOW)
    session.request.assert_not_called()
    assert result.completed_subscriptions == [OTHER] and result.facts["inventory_complete"]
    assert result.facts["agent365_requested"] is True
    assert result.facts["agent365_registry_complete"] is False
    failure = next(row for row in result.issues if row.collector == "agent365_registry")
    assert failure.reason == ("permission_denied" if authentication_error else "error")
    assert failure.required_roles == ["CopilotPackages.Read.All"]
    assert failure.evidence_refs and result.agent365_crosschecks
    assert "sensitive account information" not in result.model_dump_json()
    assert "sensitive account information" not in Path(failure.evidence_refs[0]).read_text(
        encoding="utf-8",
    )


@pytest.mark.parametrize(("mode", "configured"), [
    ("copilot-only", False), ("copilot-only", True), ("fixture", False), ("fixture", True),
])
def test_agent365_registry_rejects_offline_modes_from_config_and_cli(
    tmp_path: Path, mode: str, configured: bool,
) -> None:
    from easm_agent.cli import main

    config = tmp_path / "settings.json"
    config.write_text(json.dumps({
        "tenant_id": TENANT, "agent365_registry": configured,
        "copilot_inventory_files": [str(write_packet(tmp_path))] if mode == "copilot-only" else [],
        "evidence_dir": str(tmp_path / "evidence"),
    }), encoding="utf-8")
    args = ["collect", "--config", str(config)]
    args += ["--copilot-only"] if mode == "copilot-only" else [
        "--fixture", str(tmp_path / "fixture.json"),
    ]
    if not configured:
        args += ["--agent365-registry"]
    with patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("No Azure auth")), patch(
        "easm_agent.azure.ReaderHTTP.request", side_effect=AssertionError("No API calls"),
    ), patch("easm_agent.cli.write_reports") as write:
        assert main(args) == 1
    write.assert_not_called()
    assert not (tmp_path / "evidence").exists()


def test_collect_fixture_rejects_real_exports_before_authentication(tmp_path: Path) -> None:
    from easm_agent.cli import main

    with patch("easm_agent.cli.DefaultAzureCredential") as auth:
        code = main([
            "collect", "--fixture", str(tmp_path / "fixture.json"),
            "--copilot-inventory-file", str(write_packet(tmp_path)),
        ])
    assert code == 1
    auth.assert_not_called()


@pytest.mark.parametrize("include_license_failure", [False, True])
def test_copilot_only_reports_without_azure_authentication_or_subscriptions(
    tmp_path: Path, include_license_failure: bool, capsys: pytest.CaptureFixture,
) -> None:
    from easm_agent.cli import main

    files = [str(write_packet(tmp_path))]
    if include_license_failure:
        failure = packet()
        failure.update(
            completed=False, reason="license_missing", failure_code="license_missing",
            object_count=None, total_records=None, agents=[],
        )
        failed_path = tmp_path / "failure.json"
        failed_path.write_text(json.dumps(failure), encoding="utf-8")
        files.append(str(failed_path))
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({
        "tenant_id": TENANT.upper(), "copilot_inventory_files": files,
        "evidence_dir": str(tmp_path / "evidence"),
    }), encoding="utf-8")
    with patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("No Azure auth")), patch(
        "easm_agent.cli.collect", side_effect=AssertionError("No Azure collect"),
    ), patch("easm_agent.azure.ReaderHTTP.request", side_effect=AssertionError("No API calls")), patch(
        "easm_agent.cli.write_reports", return_value=tmp_path / "report.xlsx",
    ) as write:
        code = main(["collect", "--copilot-only", "--config", str(config),
                     "--output-dir", str(tmp_path / "output")])
    assert code == (2 if include_license_failure else 0)
    assert "Copilot=2" in capsys.readouterr().out
    data, findings = write.call_args.args[:2]
    assert data.facts["copilot_only"] is True and data.facts["data_mode"] == "live"
    assert data.facts["copilot_inventory_requested"] is True
    assert data.facts["copilot_inventory_complete"] is not include_license_failure
    assert not data.subscriptions and not data.completed_subscriptions and not data.agents
    assert len(data.copilot_agents) == 2
    assert "inventory_complete" not in data.facts and "agent_inventory_complete" not in data.facts
    assert "entra_requested" not in data.facts
    assert len(findings) == 26 and all(row.metric_value is None for row in findings)
    assert all(row.measurement.denominator is None for row in findings)
    assert data.evidence_sources
    assert Path(data.facts["evidence_directory"]).is_dir()
    assert all(Path(ref).is_file() for ref in data.facts["copilot_inventory_refs"])
    if include_license_failure:
        assert data.issues[0].reason == "license_missing"
        assert data.facts["copilot_inventory_status"][1]["reason"] == "license_missing"
        assert data.facts["copilot_inventory_status"][1]["failure_code"] == "license_missing"


@pytest.mark.parametrize("case", [
    "missing_tenant", "missing_file", "fixture", "invalid_tenant", "duplicate", "mismatched_tenant",
])
def test_copilot_only_invalid_inputs_stop_before_authentication_and_reports(
    tmp_path: Path, case: str,
) -> None:
    from easm_agent.cli import main

    path = write_packet(tmp_path)
    values = {"evidence_dir": str(tmp_path / "evidence")}
    config = tmp_path / "settings.json"
    config.write_text(json.dumps(values), encoding="utf-8")
    args = ["collect", "--copilot-only", "--config", str(config)]
    if case != "missing_tenant":
        args += ["--tenant-id", "invalid" if case == "invalid_tenant" else
                 OTHER if case == "mismatched_tenant" else TENANT]
    if case != "missing_file":
        args += ["--copilot-inventory-file", str(path)]
    if case == "fixture":
        args += ["--fixture", str(tmp_path / "fixture.json")]
    elif case == "duplicate":
        args += ["--copilot-inventory-file", str(path)]
    with patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("No Azure auth")), patch(
        "easm_agent.azure.ReaderHTTP.request", side_effect=AssertionError("No API calls"),
    ), patch("easm_agent.cli.write_reports") as write:
        assert main(args) == 1
    write.assert_not_called()


@pytest.mark.parametrize("configured", [False, True])
def test_fixture_rejects_export_files_from_both_config_and_cli(
    tmp_path: Path, configured: bool,
) -> None:
    from easm_agent.cli import main

    path = write_packet(tmp_path)
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({
        "copilot_inventory_files": [str(path)] if configured else [],
    }), encoding="utf-8")
    args = ["collect", "--config", str(config), "--fixture", str(tmp_path / "fixture.json")]
    if not configured:
        args += ["--copilot-inventory-file", str(path)]
    with patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("No Azure auth")), patch(
        "easm_agent.cli.write_reports",
    ) as write:
        assert main(args) == 1
    write.assert_not_called()


def test_copilot_only_cli_dry_run_does_not_claim_azure_or_graph_collection(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    from easm_agent.cli import main

    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"evidence_dir": str(tmp_path / "evidence")}), encoding="utf-8")
    with patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("No Azure auth")), patch(
        "easm_agent.azure.ReaderHTTP.request", side_effect=AssertionError("No API calls"),
    ):
        assert main([
            "collect", "--copilot-only", "--dry-run", "--config", str(config),
            "--tenant-id", TENANT, "--copilot-inventory-file", str(write_packet(tmp_path)),
        ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["copilot_only"] is True and result["mode"] == "live"
    assert result["subscriptions"] == "not_requested"
    assert result["roles"] == [] and result["entra"] is False and result["azure_calls"] is False
    assert not (tmp_path / "evidence").exists()


@pytest.mark.parametrize(("mode", "tenant", "expected"), [
    ("fixture", TENANT, 1), ("live", None, 1), ("live", OTHER, 1), ("live", TENANT, 0),
    ("embedded", TENANT, 0),
])
def test_package_attaches_only_live_same_explicit_tenant_without_network(
    tmp_path: Path, mode: str, tenant: str | None, expected: int,
) -> None:
    from easm_agent.cli import main

    directory = tmp_path / "evidence"
    directory.mkdir()
    embedded = mode == "embedded"
    mode = "live" if embedded else mode
    data = Collection(collected_at=NOW, facts={
        "evidence_directory": "embedded:evidence" if embedded else str(directory), "data_mode": mode,
        "copilot_inventory_tenant_ids": [TENANT],
    })
    source = tmp_path / "raw-data-20261118.json"
    result = {"collection": data.model_dump(mode="json"), "findings": [], "mode": mode}
    args = [
        "package", "--output-dir", str(tmp_path),
        "--copilot-inventory-file", str(write_packet(tmp_path)),
    ]
    if tenant:
        args += ["--tenant-id", tenant]
    with patch("easm_agent.cli.latest_raw", return_value=source), patch(
        "easm_agent.cli.load_result", return_value=result,
    ), patch("easm_agent.cli.write_reports") as write, patch(
        "easm_agent.cli.DefaultAzureCredential",
    ) as auth, patch("easm_agent.azure.requests.Session") as session:
        assert main(args) == expected
    auth.assert_not_called()
    session.assert_not_called()
    if expected == 0:
        saved = write.call_args.args[0]
        assert len(saved.copilot_agents) == 2
        assert saved.facts["copilot_inventory_complete"]
        assert saved.evidence_sources
        from easm_agent.report import normalize_result

        normalized = normalize_result(saved, [], tmp_path, "live")
        assert normalized["evidence"]
        assert all(row["status"] == "attached" for row in normalized["provenance"]["references"])
    else:
        write.assert_not_called()
