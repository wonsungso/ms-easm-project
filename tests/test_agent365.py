from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import unquote

import pytest
from openpyxl import load_workbook
from openpyxl.utils import range_boundaries

from easm_agent.azure import AccessError, EvidenceStore, ReaderHTTP
from easm_agent.collect_agent365 import (
    REGISTRY_URL,
    Agent365Collector,
    crosscheck_agent365,
)
from easm_agent.evaluation import evaluate
from easm_agent.models import (
    DEFAULT_TAGS,
    Agent365Package,
    AgentEvidence,
    Collection,
    EntraAgentIdentity,
    EntraBlueprint,
    Finding,
    load_criteria,
)
from easm_agent.report_excel import write_workbook

NOW = datetime(2026, 11, 9, tzinfo=UTC)
IDENTITY = "11111111-1111-4111-8111-111111111111"
BLUEPRINT = "22222222-2222-4222-8222-222222222222"
SID = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"


def http(rows: list[dict] | None = None) -> Mock:
    value = Mock(spec=ReaderHTTP, store=None, last_ref=None, subscription="")
    value.list_graph.return_value = rows or []
    value.request.side_effect = lambda method, url, scope: {"id": unquote(url.rsplit("/", 1)[1])}
    return value


def snapshot() -> Collection:
    return Collection(
        collected_at=NOW,
        facts={
            "agent365_registry_complete": True, "entra_agents_complete": True,
            "entra_blueprints_complete": True, "agent_inventory_complete": True,
        },
        agent365_packages=[Agent365Package(package_id="package", agent_identity_id=IDENTITY, version="99")],
        entra_agent_identities=[EntraAgentIdentity(identity_id=IDENTITY, blueprint_id=BLUEPRINT)],
        entra_blueprints=[EntraBlueprint(blueprint_id=BLUEPRINT, tags=[
            f"subscriptionId:{SID}", "accountName:account", "projectName:project", "agentName:agent",
        ])],
        agents=[AgentEvidence(
            collected_at=NOW, platform="foundry", agent_id="agent-id", agent_name="agent", agent_version="1",
            subscription_id=SID, detection_confidence="tag",
            resource_id=f"/subscriptions/{SID}/resourceGroups/rg/providers/Microsoft.CognitiveServices/"
            "accounts/account/projects/project/agents/agent",
        )],
    )


def checks(data: Collection) -> dict:
    return {row.se_code: row for row in crosscheck_agent365(data, load_criteria())}


def test_registry_uses_documented_get_and_saves_only_minimal_fields(tmp_path: Path) -> None:
    source = http([{
        "id": "package", "agentIdentityId": IDENTITY, "version": "99",
        "displayName": "resource-agent", "publisher": "Personal Publisher",
        "zipFile": "secret package content", "shortDescription": "private text",
    }])
    store = EvidenceStore(tmp_path, NOW)
    result = Agent365Collector(source, NOW, store).discover()
    source.list_graph.assert_called_once_with(REGISTRY_URL)
    assert result.facts["agent365_registry_complete"] is True
    package = result.agent365_packages[0]
    assert package.agent_identity_id == IDENTITY
    text = Path(package.evidence_refs[0]).read_text(encoding="utf-8")
    assert not any(word in text for word in ("Personal Publisher", "secret package", "private text"))
    saved = json.loads(text)["response"]["value"]
    metadata = saved[0].pop("metadata")
    assert metadata["values"] == {
        "app_id": None, "element_types": None, "manifest_version": None,
        "package_type": None, "supported_hosts": None,
    }
    assert all(status["reason"] == "not_found" for status in metadata["field_status"].values())
    assert saved == [{
        "id": "package", "agentIdentityId": IDENTITY, "version": "99",
        "displayName": "resource-agent", "platform": None, "availableTo": None,
        "deployedTo": None, "isBlocked": None, "createdDateTime": None, "requestStatus": None,
        "governanceMetadata": None, "ownerCount": None,
        "requestType": None, "manifestId": None, "lastModifiedDateTime": None,
    }]
    assert package.field_status["available_to"].reason == "not_found"


def test_unexpected_governance_field_keeps_verified_catalog_and_records_error(tmp_path: Path) -> None:
    source = http([
        {"id": "p1", "agentIdentityId": IDENTITY, "governanceMetadata": {"unexpected": "private value"}},
        {"id": "p2", "governanceMetadata": "ManagedAgent"},
        {"id": "p3", "governanceMetadata": {"agenticType": "HostedAgent"}},
        {"id": "p4", "governanceMetadata": {"agenticType": "Other"}},
    ])
    result = Agent365Collector(source, NOW, EvidenceStore(tmp_path, NOW)).discover()

    assert result.facts["agent365_registry_complete"] is True
    assert len(result.agent365_packages) == 4
    first, second, third, fourth = result.agent365_packages
    assert first.agent_identity_id == IDENTITY
    assert first.governance is None and first.field_status["governance"].reason == "error"
    assert second.governance == "ManagedAgent"
    assert third.governance == "HostedAgent" and "governance" not in third.field_status
    assert fourth.governance is None and fourth.field_status["governance"].reason == "error"
    assert len(result.issues) == 1 and result.issues[0].reason == "error"
    saved = Path(first.evidence_refs[0]).read_text(encoding="utf-8")
    assert "private value" not in saved
    assert json.loads(saved)["response"]["value"][0]["fieldErrors"]["governanceMetadata"] == "error"


@pytest.mark.parametrize("reason", [
    "permission_denied", "license_missing", "feature_unavailable", "error",
])
def test_registry_failure_is_explicit_and_never_complete(reason: str, tmp_path: Path) -> None:
    source = http()
    source.list_graph.side_effect = AccessError(reason, "safe failure")
    result = Agent365Collector(source, NOW, EvidenceStore(tmp_path, NOW)).discover()
    assert result.agent365_packages == []
    assert result.facts["agent365_registry_complete"] is False
    assert result.issues[0].reason == reason
    assert result.issues[0].evidence_refs
    rows = checks(result)
    assert rows["DS-SY-03"].status == "unavailable" and rows["DS-SY-03"].reason == reason
    assert rows["DS-SY-03"].compared is None


@pytest.mark.parametrize("rows", [
    [{"version": "1"}], [{"id": ""}], [{"id": 123}],
    [{"id": "p"}, {"id": "p"}], [{"id": "p", "agentIdentityId": 123}],
    [{"id": "p", "agentIdentityId": "invalid"}], [{"id": "p", "version": 1}],
    [{"id": "p", "isBlocked": 1}], [{"id": "p", "availableTo": []}],
])
def test_malformed_registry_never_becomes_a_match(rows: list[dict]) -> None:
    result = Agent365Collector(http(rows), NOW).discover()
    assert not result.facts["agent365_registry_complete"]
    assert result.issues[0].reason == "error"
    assert result.agent365_packages == []


def test_rejects_raw_registry_capture_before_data_minimization() -> None:
    source = http()
    source.store = Mock()
    with pytest.raises(ValueError, match="최소 필드"):
        Agent365Collector(source, NOW)


def test_opaque_next_links_and_429_retry_use_existing_read_only_client() -> None:
    continuation = REGISTRY_URL + "?$skiptoken=opaque"
    responses = []
    for code, body in (
        (429, {}), (200, {"value": [{"id": "first"}], "@odata.nextLink": continuation}),
        (200, {"value": [{"id": "last", "agentIdentityId": IDENTITY}]}),
        (200, {"id": "first"}), (200, {"id": "last"}),
    ):
        response = Mock(status_code=code, headers={})
        response.json.return_value = body
        responses.append(response)
    session = Mock()
    session.request.side_effect = responses
    credential = Mock()
    credential.get_token.return_value.token = "fixture-token"
    with patch("easm_agent.azure.time.sleep"):
        result = Agent365Collector(ReaderHTTP(credential, session=session), NOW).discover()
    assert [row.package_id for row in result.agent365_packages] == ["first", "last"]
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)
    assert session.request.call_args_list[2].args[1] == continuation


@pytest.mark.parametrize("next_link", [
    REGISTRY_URL, REGISTRY_URL.replace("graph.microsoft.com", "outside.invalid"),
    REGISTRY_URL.replace("/catalog/packages", "/other"), [], 7,
])
def test_invalid_registry_pagination_is_an_explicit_failure(next_link: object) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {"value": [{"id": "p"}], "@odata.nextLink": next_link}
    session = Mock()
    session.request.return_value = response
    result = Agent365Collector(ReaderHTTP(Mock(), session=session), NOW).discover()
    assert result.issues[0].reason == "error"
    assert result.agent365_packages == [] and not result.facts["agent365_registry_complete"]
    assert session.request.call_count == 1


def test_partial_id_crosschecks_do_not_compare_unrelated_fields_or_same_graph_source() -> None:
    result = checks(snapshot())
    assert len(result) == 26
    for code in ("DS-SY-03", "DP-SY-15"):
        assert result[code].status == "partial_match"
        assert result[code].matched == result[code].compared == 1
    for code in set(result) - {"DS-SY-03", "DP-SY-15"}:
        assert result[code].status == "not_comparable"
        assert result[code].matched is None
    assert "다른 필드" in result["BI-SY-12"].detail
    assert "동일 원천" in result["OE-SY-16"].detail and "동일 원천" in result["OE-SY-17"].detail


def test_registry_reference_missing_from_complete_graph_is_mismatch() -> None:
    data = snapshot()
    data.agent365_packages[0].agent_identity_id = OTHER
    result = checks(data)
    assert result["DS-SY-03"].status == "mismatch"
    assert result["DS-SY-03"].mismatched == 1
    assert result["DP-SY-15"].status == "unavailable"


def test_missing_graph_blueprint_field_is_unknown_not_mismatch() -> None:
    data = snapshot()
    data.entra_agent_identities[0].blueprint_id = None
    result = checks(data)["DS-SY-03"]
    assert result.status == "unavailable" and result.unverified == 1 and result.mismatched == 0


@pytest.mark.parametrize("marker", [
    "agent365_registry_complete", "entra_agents_complete", "entra_blueprints_complete", "agent_inventory_complete",
])
def test_incomplete_inventories_cannot_match(marker: str) -> None:
    data = snapshot()
    data.facts.pop(marker)
    assert checks(data)["DP-SY-15"].status == "unavailable"


def test_missing_identity_field_empty_registry_and_unpublished_agents_are_not_failure_proof() -> None:
    data = snapshot()
    data.agent365_packages = [Agent365Package(package_id="without-agent-id")]
    for row in checks(data).values():
        assert row.status != "mismatch"
    data.agent365_packages = []
    assert checks(data)["DS-SY-03"].status == "unavailable"


def test_display_names_are_never_join_keys_and_ambiguous_connections_do_not_match() -> None:
    data = snapshot()
    data.entra_agent_identities[0].display_name = "unrelated name"
    assert checks(data)["DP-SY-15"].status == "partial_match"
    data.entra_agent_identities.append(EntraAgentIdentity(identity_id=OTHER, blueprint_id=BLUEPRINT))
    result = checks(data)["DP-SY-15"]
    assert result.status == "unavailable" and result.unverified == 1


def test_duplicate_graph_id_does_not_create_false_match() -> None:
    data = snapshot()
    data.entra_agent_identities.append(data.entra_agent_identities[0].model_copy())
    assert checks(data)["DS-SY-03"].reason == "error"
    assert checks(data)["DP-SY-15"].status == "unavailable"


def test_report_keeps_grades_and_separates_crosscheck_details(tmp_path: Path) -> None:
    data = snapshot()
    data.agent365_crosschecks = list(checks(data).values())
    finding = Finding(se_code="DS-SY-03", scope="in_scope", level="L5", metric_value=1, rationale="primary grade")
    path = tmp_path / "report.xlsx"
    write_workbook(data, [
        finding,
        Finding(se_code="OE-SY-17", scope="in_scope", level="L5", metric_value=1, rationale="primary role grade"),
    ], path)
    book = load_workbook(path)
    details = book["7. 수집결과 근거"]
    table = next(table for table in details.tables.values() if table.ref.startswith("A3:"))
    rows = {details.cell(row, 1).value: row for row in range(4, range_boundaries(table.ref)[3] + 1)}
    assert details.cell(rows["DS-SY-03"], 10).value == "일부 일치"
    assert "기존 등급 유지" in details.cell(rows["DS-SY-03"], 11).value
    assert details.cell(rows["OE-SY-17"], 10).value == "동일 정보 미제공"
    assert "기존 Azure/Graph API로 평가" in details.cell(rows["OE-SY-17"], 11).value
    assert "평가 제외 아님" in details.cell(rows["OE-SY-17"], 11).value
    assert len(book["8. 수집 Raw 데이터"].tables) == 18
    assert finding.level == "L5"


def graded(data: Collection) -> dict:
    return {row.se_code: row for row in evaluate(data, load_criteria(), DEFAULT_TAGS)}


def test_registry_data_does_not_restore_retired_assessment_items() -> None:
    data = snapshot()
    data.facts["inventory_complete"] = True
    data.agent365_packages = [
        Agent365Package(
            package_id="managed", agent_identity_id=IDENTITY, governance="ManagedAgent", owner_count=1,
            available_to="allowedForSome", deployed_to="acquiredForSome", is_blocked=False,
            created_at=NOW - timedelta(days=3), request_status="approved",
        ),
        Agent365Package(
            package_id="open", governance="Unmanaged", owner_count=0, available_to="allowedForAll",
            deployed_to="acquiredForAll", is_blocked=False, created_at=NOW - timedelta(days=400),
        ),
    ]
    rows = graded(data)
    assert len(rows) == 26


def test_registry_permissions_do_not_change_active_findings() -> None:
    source = http()
    source.list_graph.side_effect = AccessError("license_missing", "Agent 365 license required")
    data = Agent365Collector(source, NOW).discover()
    rows = graded(data)
    assert len(rows) == 26 and set(rows) == load_criteria()["items"].keys()


def test_detail_usage_is_documented_get_and_saves_no_personal_or_agent_content(tmp_path: Path) -> None:
    source = http([{"id": "package /?#", "version": "1"}])
    source.request.side_effect = None
    source.request.return_value = {
        "id": "package /?#", "version": "1",
        "activeUsers": 8, "totalSessions": 21, "totalRunTimeInHours": 1.5,
        "exceptionRate": 2.0, "lastUsedDateTime": "2026-11-08T23:59:00Z",
        "sharedWithUsersAndGroups": [{"resourceId": OTHER, "displayName": "Private Person"}],
        "elementDetails": [{"definition": "private instructions and connection string"}],
        "requestMetadata": {"requestedBy": {"name": "Private Person", "address": "private@example.com"}},
        "longDescription": "private customer information", "token": "private-token",
    }
    data = Agent365Collector(source, NOW, EvidenceStore(tmp_path, NOW)).discover()
    package = data.agent365_packages[0]
    source.request.assert_called_once_with(
        "GET", REGISTRY_URL + "/package%20%2F%3F%23", "https://graph.microsoft.com/.default",
    )
    assert package.detail_complete and data.facts["agent365_details_complete"]
    assert package.active_users_30d == 8 and package.total_sessions_30d == 21
    assert package.total_run_time_hours_30d == 1.5 and package.exception_count_30d == 2.0
    assert package.last_used_at == datetime(2026, 11, 8, 23, 59, tzinfo=UTC)
    assert package.detail_evidence_refs != package.evidence_refs
    text = Path(package.detail_evidence_refs[0]).read_text(encoding="utf-8")
    assert json.loads(text)["response"]["exceptionRate"] == 2.0
    for private in (OTHER, "Private Person", "private instructions", "private customer", "private-token"):
        assert private not in text and private not in data.model_dump_json()


@pytest.mark.parametrize("reason", [
    "permission_denied", "license_missing", "feature_unavailable", "not_found", "error",
])
def test_detail_failure_keeps_catalog_and_other_packages(reason: str, tmp_path: Path) -> None:
    source = http([{"id": "denied"}, {"id": "readable"}])
    source.request.side_effect = [
        AccessError(reason, "private account name and token"),
        {"id": "readable", "activeUsers": 0, "totalSessions": 0,
         "totalRunTimeInHours": 0, "exceptionRate": 0, "lastUsedDateTime": "2026-11-08T00:00:00Z"},
    ]
    data = Agent365Collector(source, NOW, EvidenceStore(tmp_path, NOW)).discover()
    denied, readable = data.agent365_packages
    assert data.facts["agent365_registry_complete"]
    assert not data.facts["agent365_details_complete"] and not denied.detail_complete
    assert denied.active_users_30d is None and denied.exception_count_30d is None
    assert all(denied.field_status[field].reason == reason for field in (
        "active_users_30d", "total_sessions_30d", "total_run_time_hours_30d",
        "exception_count_30d", "last_used_at",
    ))
    assert readable.detail_complete and readable.active_users_30d == readable.total_sessions_30d == 0
    failure = data.issues[0]
    assert failure.collector == "agent365_package_details" and failure.reason == reason
    assert failure.required_roles == ["CopilotPackages.Read.All"]
    assert failure.evidence_refs == denied.detail_evidence_refs
    assert "private account" not in data.model_dump_json()
    assert "private account" not in Path(failure.evidence_refs[0]).read_text(encoding="utf-8")


@pytest.mark.parametrize(("field", "value"), [
    ("activeUsers", True), ("activeUsers", 1.5), ("activeUsers", 2147483648),
    ("totalSessions", "7"), ("totalSessions", -1),
    ("totalRunTimeInHours", float("inf")), ("totalRunTimeInHours", -1),
    ("exceptionRate", float("nan")), ("exceptionRate", True),
    ("exceptionRate", 10 ** 400),
    ("lastUsedDateTime", "yesterday"), ("lastUsedDateTime", "2026-11-08T00:00:00"),
    ("lastUsedDateTime", []),
])
def test_detail_invalid_fields_stay_null_without_losing_valid_metrics(field: str, value: object) -> None:
    from easm_agent.collect_agent365 import DETAIL_FIELDS

    source = http([{"id": "p"}])
    source.request.side_effect = None
    source.request.return_value = {
        "id": "p", "activeUsers": 2, "totalSessions": 9,
        "totalRunTimeInHours": 2.5, "exceptionRate": 3.0,
        "lastUsedDateTime": "2026-11-08T00:00:00Z", field: value,
    }
    data = Agent365Collector(source, NOW).discover()
    package = data.agent365_packages[0]
    invalid = next(name for name, api_field in DETAIL_FIELDS.items() if api_field == field)
    assert getattr(package, invalid) is None and package.field_status[invalid].reason == "error"
    assert all(getattr(package, name) is not None for name in DETAIL_FIELDS if name != invalid)
    assert data.facts["agent365_registry_complete"] and not package.detail_complete
    assert len(data.issues) == 1 and data.issues[0].reason == "error"


@pytest.mark.parametrize("payload", [
    {"id": "different", "activeUsers": 10}, {"id": "p", "version": "changed", "activeUsers": 10},
    [], None,
])
def test_detail_identity_or_version_mismatch_cannot_attach_usage(payload: object) -> None:
    source = http([{"id": "p", "version": "1"}])
    source.request.side_effect = None
    source.request.return_value = payload
    data = Agent365Collector(source, NOW).discover()
    assert data.facts["agent365_registry_complete"]
    assert data.agent365_packages[0].active_users_30d is None
    assert data.issues[0].reason == "error"


def test_missing_detail_fields_and_empty_catalog_do_not_invent_zero_usage() -> None:
    source = http([{"id": "p"}])
    data = Agent365Collector(source, NOW).discover()
    package = data.agent365_packages[0]
    assert package.active_users_30d is package.total_sessions_30d is package.last_used_at is None
    assert package.field_status["active_users_30d"].reason == "not_found"
    assert not package.detail_complete and not data.facts["agent365_details_complete"]
    empty_source = http()
    empty = Agent365Collector(empty_source, NOW).discover()
    empty_source.request.assert_not_called()
    assert not empty.agent365_packages and empty.facts["agent365_registry_complete"]
    empty.facts.update(entra_agents_complete=True, entra_blueprints_complete=True, agent_inventory_complete=True)
    for code in ("DS-SY-03", "DP-SY-15"):
        crosscheck = checks(empty)[code]
        assert crosscheck.compared is crosscheck.matched is None and crosscheck.reason == "not_found"


@pytest.mark.parametrize(("message", "reason"), [
    ("Tenant is not licensed - private account name", "license_missing"),
    ("Forbidden - private account name", "permission_denied"),
])
def test_detail_http_errors_never_persist_raw_graph_error(message: str, reason: str, tmp_path: Path) -> None:
    responses = []
    for code, body in (
        (200, {"value": [{"id": "p"}]}), (403, {"error": {"message": message}}),
    ):
        response = Mock(status_code=code, headers={})
        response.json.return_value = body
        responses.append(response)
    session = Mock()
    session.request.side_effect = responses
    credential = Mock()
    credential.get_token.return_value.token = "private-access-token"
    data = Agent365Collector(
        ReaderHTTP(credential, session=session), NOW, EvidenceStore(tmp_path, NOW),
    ).discover()
    assert data.facts["agent365_registry_complete"]
    assert data.agent365_packages[0].active_users_30d is None
    assert data.issues[0].reason == reason
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)
    assert data.issues[0].target == REGISTRY_URL + "/p"
    text = Path(data.agent365_packages[0].detail_evidence_refs[0]).read_text(encoding="utf-8")
    assert "private account name" not in text and "private-access-token" not in text


@pytest.mark.parametrize("authentication_error", [False, True])
def test_detail_authentication_errors_are_minimized_and_isolated(authentication_error: bool) -> None:
    from azure.core.exceptions import ClientAuthenticationError

    source = http([{"id": "p"}])
    source.request.side_effect = (
        ClientAuthenticationError("private account name") if authentication_error
        else ValueError("private token value")
    )
    data = Agent365Collector(source, NOW).discover()
    assert data.facts["agent365_registry_complete"] and not data.facts["agent365_details_complete"]
    assert data.issues[0].reason == ("permission_denied" if authentication_error else "error")
    assert "private" not in data.model_dump_json()


def test_435_packages_are_sequential_and_partial_fields_do_not_trigger_failure_circuit() -> None:
    source = http([{"id": f"p{i}"} for i in range(435)])
    data = Agent365Collector(source, NOW).discover()
    summary = data.facts["agent365_detail_collection"]
    assert source.request.call_count == 435
    assert all(call.args[0] == "GET" for call in source.request.call_args_list)
    assert summary["candidate_packages"] == summary["attempted_packages"] == 435
    assert summary["partial_packages"] == 435 and summary["failed_packages"] == 0
    assert summary["skipped_packages"] == 0 and summary["stop_cause"] is None
    assert summary["usage_window_days"] == 30
    assert summary["source_period_start"] is summary["source_period_end"] is None
    assert data.facts["agent365_registry_complete"] and not data.facts["agent365_details_complete"]


def test_435_consecutive_failures_are_bounded_and_unattempted_packages_do_not_inherit_denial(
    tmp_path: Path,
) -> None:
    source = http([{"id": f"p{i}"} for i in range(435)])
    source.request.side_effect = AccessError("permission_denied", "private error body")
    store = EvidenceStore(tmp_path, NOW)
    data = Agent365Collector(source, NOW, store).discover()
    summary = data.facts["agent365_detail_collection"]
    assert source.request.call_count == summary["attempted_packages"] == 5
    assert summary["failed_packages"] == 5 and summary["skipped_packages"] == 430
    assert summary["stop_cause"] == "consecutive_failures"
    assert len(data.agent365_packages) == 435 and data.facts["agent365_registry_complete"]
    assert len(data.issues) == 6 and len(store.sources()) == 7
    assert all(p.field_status["active_users_30d"].reason == "permission_denied"
               for p in data.agent365_packages[:5])
    assert all(p.field_status["active_users_30d"].reason == "not_found"
               for p in data.agent365_packages[5:])
    assert len({tuple(p.detail_evidence_refs) for p in data.agent365_packages[5:]}) == 1
    assert all(p.active_users_30d is None for p in data.agent365_packages)
    assert "private error body" not in data.model_dump_json()


def test_435_package_time_budget_stops_new_requests_without_discarding_observations() -> None:
    source = http([{"id": f"p{i}"} for i in range(435)])
    clock = [0.0]

    def request(method: str, url: str, scope: str) -> dict:
        clock[0] += 300
        return {"id": url.rsplit("/", 1)[1], "activeUsers": 7}

    source.request.side_effect = request
    with patch("easm_agent.collect_agent365.time.monotonic", side_effect=lambda: clock[0]):
        data = Agent365Collector(source, NOW).discover()
    summary = data.facts["agent365_detail_collection"]
    assert source.request.call_count == summary["attempted_packages"] == 2
    assert summary["skipped_packages"] == 433 and summary["failed_packages"] == 0
    assert summary["partial_packages"] == 2 and summary["stop_cause"] == "time_budget"
    assert summary["elapsed_seconds"] == 600
    assert [p.active_users_30d for p in data.agent365_packages[:3]] == [7, 7, None]
    assert data.agent365_packages[2].field_status["active_users_30d"].reason == "not_found"


@pytest.mark.parametrize(("code", "retry_after", "attempts", "delays", "stop_cause"), [
    (429, "2", 4, [2, 2, 4], "throttled"),
    (429, "120", 1, [], "throttled"),
    (429, "Thu, 19 Nov 2026 10:00:00 GMT", 1, [], "throttled"),
    (503, "120", 1, [], "service_unavailable"),
])
def test_435_package_service_backoff_stops_remaining_detail_calls(
    code: int, retry_after: str, attempts: int, delays: list[int], stop_cause: str, tmp_path: Path,
) -> None:
    page = Mock(status_code=200, headers={})
    page.json.return_value = {"value": [{"id": f"p{i}"} for i in range(435)]}
    limited = Mock(status_code=code, headers={"Retry-After": retry_after})
    limited.json.return_value = {"error": {"message": "private server body"}}
    session = Mock()
    session.request.side_effect = [page, *[limited for _ in range(attempts)]]
    credential = Mock()
    credential.get_token.return_value.token = "private-access-token"
    store = EvidenceStore(tmp_path, NOW)
    with patch("easm_agent.azure.time.sleep") as sleep:
        data = Agent365Collector(ReaderHTTP(credential, session=session), NOW, store).discover()
    assert [call.args[0] for call in sleep.call_args_list] == delays
    assert session.request.call_count == attempts + 1
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)
    summary = data.facts["agent365_detail_collection"]
    assert summary["stop_cause"] == stop_cause
    assert summary["attempted_packages"] == summary["failed_packages"] == 1
    assert summary["skipped_packages"] == 434 and data.facts["agent365_registry_complete"]
    assert all(p.active_users_30d is None for p in data.agent365_packages)
    for ref in store.sources():
        text = Path(ref.evidence_refs[0]).read_text(encoding="utf-8")
        assert "private server body" not in text and "private-access-token" not in text


def test_successful_package_resets_consecutive_request_failure_count() -> None:
    source = http([{"id": f"p{i}"} for i in range(12)])
    source.request.side_effect = [
        *[AccessError("error", "safe") for _ in range(4)],
        {"id": "p4", "activeUsers": 3},
        *[AccessError("error", "safe") for _ in range(4)],
        {"id": "p9", "activeUsers": 5}, {"id": "p10"}, {"id": "p11"},
    ]
    data = Agent365Collector(source, NOW).discover()
    summary = data.facts["agent365_detail_collection"]
    assert summary["attempted_packages"] == source.request.call_count == 12
    assert summary["failed_packages"] == 8 and summary["skipped_packages"] == 0
    assert data.agent365_packages[4].active_users_30d == 3
    assert data.agent365_packages[9].active_users_30d == 5


def metadata_response() -> dict:
    return {
        "id": "p", "type": "custom", "manifestVersion": "1.1", "appId": OTHER,
        "supportedHosts": ["Teams", "outlook", "sharePoint", "M365"],
        "elementTypes": ["bot", "declarativeAgent", "AgentConnectors", "AgentSkills"],
        "categories": ["Development", "Productivity", "Tools"], "sensitivity": "general",
    }


def test_documented_metadata_reuses_get_and_tracks_catalog_and_detail_provenance(tmp_path: Path) -> None:
    catalog = {key: value for key, value in metadata_response().items()
               if key not in ("categories", "sensitivity")}
    source = http([catalog])
    source.request.side_effect = None
    source.request.return_value = {"id": "p", "categories": ["Tools"], "sensitivity": "general"}
    store = EvidenceStore(tmp_path, NOW)
    data = Agent365Collector(source, NOW, store).discover()
    package = data.agent365_packages[0]
    assert source.list_graph.call_count == source.request.call_count == 1
    assert package.package_type == "custom" and package.manifest_version == "1.1"
    assert package.app_id == OTHER and package.supported_hosts == catalog["supportedHosts"]
    assert package.element_types == catalog["elementTypes"] and package.categories == ["Tools"]
    assert package.category_count == 1 and package.sensitivity == "general" and package.sensitivity_present is True
    assert package.metadata_complete and not package.detail_complete
    assert data.facts["agent365_detail_collection"]["metadata_complete_packages"] == 1
    assert package.metadata_field_sources["package_type"] == "catalog"
    assert package.metadata_evidence_refs["package_type"] == package.evidence_refs
    assert package.metadata_field_sources["categories"] == "detail"
    assert package.metadata_evidence_refs["categories"] == package.detail_evidence_refs
    assert package.metadata_evidence_refs["category_count"] == package.detail_evidence_refs
    assert "package_type" not in package.field_status and "categories" not in package.field_status
    detail = json.loads(Path(package.detail_evidence_refs[0]).read_text(encoding="utf-8"))["response"]
    assert detail["metadata"]["values"]["categories"] == ["Tools"]
    assert "package_type" not in detail["metadata"]["values"]


def test_metadata_privacy_allowlist_discards_free_text_but_preserves_safe_counts(tmp_path: Path) -> None:
    source = http([{"id": "p"}])
    source.request.side_effect = None
    source.request.return_value = {
        "id": "p", "type": "private organization name",
        "manifestVersion": "private api-key=123", "appId": "private@example.com",
        "supportedHosts": ["Teams", "private@example.com"],
        "elementTypes": ["declarativeAgent", "private customer information"],
        "categories": ["Productivity", "Private Person"], "sensitivity": "Private Person",
        "publisher": "Private Publisher", "elementDetails": [{"definition": "private instructions"}],
        "owners": [{"resourceId": IDENTITY}], "longDescription": "private content",
        "activeUsers": 1, "totalSessions": 3, "totalRunTimeInHours": 0.1,
        "exceptionRate": 0, "lastUsedDateTime": "2026-11-08T00:00:00Z",
    }
    store = EvidenceStore(tmp_path, NOW)
    data = Agent365Collector(source, NOW, store).discover()
    package = data.agent365_packages[0]
    assert package.category_count == 2 and package.sensitivity_present is True
    assert package.categories is package.sensitivity is package.package_type is None
    assert package.supported_hosts is package.element_types is package.manifest_version is package.app_id is None
    assert package.field_status["categories"].reason == "feature_unavailable"
    assert package.field_status["app_id"].reason == "error"
    assert package.detail_complete and not package.metadata_complete
    assert data.facts["agent365_registry_complete"] and data.issues[0].reason == "error"
    saved = data.model_dump_json() + "".join(
        Path(entry.evidence_refs[0]).read_text(encoding="utf-8") for entry in store.sources()
    )
    for private in (
        "private organization", "private@example.com", "private api-key",
        "private customer", "Private Person", "Private Publisher", "private instructions", "private content", IDENTITY,
    ):
        assert private not in saved


@pytest.mark.parametrize(("field", "model_field", "value", "reason"), [
    ("type", "package_type", "unknownFutureValue", "feature_unavailable"),
    ("type", "package_type", True, "error"),
    ("manifestVersion", "manifest_version", 2, "error"),
    ("manifestVersion", "manifest_version", "2.0-preview", "feature_unavailable"),
    ("manifestVersion", "manifest_version", "1" * 100, "feature_unavailable"),
    ("appId", "app_id", "not-a-guid", "error"),
    ("supportedHosts", "supported_hosts", ["Teams", {}], "error"),
    ("elementTypes", "element_types", None, "not_found"),
    ("categories", "categories", "Productivity", "error"),
    ("categories", "categories", [1], "error"),
    ("categories", "categories", [""], "error"),
    ("sensitivity", "sensitivity", {"label": "private value"}, "error"),
    ("sensitivity", "sensitivity", "", "not_found"),
    ("sensitivity", "sensitivity", "Confidential", "feature_unavailable"),
])
def test_metadata_missing_invalid_and_unrecognized_values_never_erase_verified_fields(
    field: str, model_field: str, value: object, reason: str,
) -> None:
    source = http([{"id": "p"}])
    source.request.side_effect = None
    source.request.return_value = {**metadata_response(), field: value, "activeUsers": 7}
    data = Agent365Collector(source, NOW).discover()
    package = data.agent365_packages[0]
    assert getattr(package, model_field) is None and package.field_status[model_field].reason == reason
    assert package.active_users_30d == 7 and data.facts["agent365_registry_complete"]
    assert not package.metadata_complete and source.request.call_count == 1
    if model_field not in ("categories", "sensitivity"):
        assert package.categories == ["Development", "Productivity", "Tools"] and package.sensitivity == "general"
    if model_field == "categories":
        assert package.category_count is None
    if model_field == "sensitivity":
        assert package.sensitivity_present is (True if value == "Confidential" else None)


def test_metadata_explicit_detail_null_does_not_restore_stale_catalog_value() -> None:
    source = http([{"id": "p", "type": "custom", "supportedHosts": ["Teams"]}])
    source.request.side_effect = None
    source.request.return_value = {"id": "p", "type": None}
    package = Agent365Collector(source, NOW).discover().agent365_packages[0]
    assert package.package_type is None and package.field_status["package_type"].reason == "not_found"
    assert package.metadata_field_sources["package_type"] == "detail"
    assert package.supported_hosts == ["Teams"] and package.metadata_field_sources["supported_hosts"] == "catalog"


def test_empty_metadata_collections_are_known_empty_without_inventing_policy_effectiveness() -> None:
    source = http([{"id": "p"}])
    source.request.side_effect = None
    source.request.return_value = {
        **metadata_response(), "categories": [], "supportedHosts": [], "elementTypes": [],
    }
    package = Agent365Collector(source, NOW).discover().agent365_packages[0]
    assert package.categories == package.supported_hosts == package.element_types == []
    assert package.category_count == 0 and package.metadata_complete
    old = Agent365Package(package_id="old")
    assert old.categories is old.category_count is old.sensitivity_present is None
    assert old.field_status["categories"].reason == "not_found" and not old.metadata_complete


@pytest.mark.parametrize("reason", ["permission_denied", "license_missing", "error"])
def test_detail_failure_keeps_verified_catalog_metadata_and_marks_unknown_detail_fields(reason: str) -> None:
    source = http([{"id": "p", "type": "external", "manifestVersion": "2.0"}])
    source.request.side_effect = AccessError(reason, "private error body")
    package = Agent365Collector(source, NOW).discover().agent365_packages[0]
    assert package.package_type == "external" and package.manifest_version == "2.0"
    assert package.metadata_field_sources["package_type"] == "catalog"
    assert package.categories is package.category_count is package.sensitivity is None
    assert package.field_status["categories"].reason == package.field_status["sensitivity_present"].reason == reason
    assert package.metadata_field_sources["categories"] == "detail"


def test_protective_stop_keeps_catalog_metadata_and_tracks_unrequested_fields(tmp_path: Path) -> None:
    source = http([{"id": "p", "type": "custom"}])
    with patch("easm_agent.collect_agent365.DETAIL_TIME_BUDGET_SECONDS", 0):
        package = Agent365Collector(source, NOW, EvidenceStore(tmp_path, NOW)).discover().agent365_packages[0]
    source.request.assert_not_called()
    assert package.package_type == "custom" and package.metadata_field_sources["package_type"] == "catalog"
    assert package.categories is None and package.field_status["categories"].reason == "not_found"
    assert package.metadata_field_sources["categories"] == "not_requested"
    assert package.metadata_evidence_refs["categories"] == package.detail_evidence_refs
    assert package.metadata_evidence_refs["package_type"] == package.evidence_refs


def test_metadata_is_embedded_with_field_refs_and_does_not_change_26_grades(tmp_path: Path) -> None:
    from easm_agent.report import normalize_result

    source = http([{"id": "p", "agentIdentityId": IDENTITY}])
    source.request.side_effect = None
    source.request.return_value = metadata_response()
    store = EvidenceStore(tmp_path, NOW)
    data = Agent365Collector(source, NOW, store).discover()
    data.evidence_sources = store.sources()
    data.facts["evidence_directory"] = str(store.path.resolve())
    result = normalize_result(data, [], tmp_path, "live")
    package = result["collection"]["agent365_packages"][0]
    assert all(ref.startswith("evidence:") for refs in package["metadata_evidence_refs"].values() for ref in refs)
    assert all(ref.removeprefix("evidence:") in result["evidence"]
               for refs in package["metadata_evidence_refs"].values() for ref in refs)
    original = snapshot()
    enriched = snapshot()
    enriched.agent365_packages = data.agent365_packages
    assert graded(original) == graded(enriched)


def test_436_packages_collect_metadata_without_additional_requests_or_agent_count_inference() -> None:
    source = http([{"id": f"p{i}"} for i in range(436)])
    source.request.side_effect = lambda method, url, scope: {
        **metadata_response(), "id": url.rsplit("/", 1)[1],
    }
    data = Agent365Collector(source, NOW).discover()
    assert source.request.call_count == len(data.agent365_packages) == 436
    assert data.facts["agent365_detail_collection"]["metadata_complete_packages"] == 436
    assert all(package.metadata_complete for package in data.agent365_packages)
    assert not data.agents and "agent_inventory_complete" not in data.facts


def test_protective_stop_does_not_replace_catalog_metadata_errors_with_unrequested_status() -> None:
    source = http([{"id": "p", "type": "futureType", "appId": "invalid"}])
    with patch("easm_agent.collect_agent365.DETAIL_TIME_BUDGET_SECONDS", 0):
        package = Agent365Collector(source, NOW).discover().agent365_packages[0]
    assert package.field_status["package_type"].reason == "feature_unavailable"
    assert package.field_status["app_id"].reason == "error"
    assert package.metadata_field_sources["package_type"] == package.metadata_field_sources["app_id"] == "catalog"


@pytest.mark.parametrize(("api_field", "field", "label"), [
    ("categories", "categories", "Tools"), ("supportedHosts", "supported_hosts", "Teams"),
    ("elementTypes", "element_types", "bot"),
])
def test_oversized_metadata_arrays_are_not_stored_as_unbounded_report_cells(
    api_field: str, field: str, label: str,
) -> None:
    source = http([{"id": "p"}])
    source.request.side_effect = None
    source.request.return_value = {**metadata_response(), api_field: [label] * 10000}
    package = Agent365Collector(source, NOW).discover().agent365_packages[0]
    assert getattr(package, field) is None and package.field_status[field].reason == "feature_unavailable"
    if field == "categories":
        assert package.category_count == 10000


def test_existing_excel_raw_export_preserves_metadata_values_and_field_evidence(tmp_path: Path) -> None:
    source = http([{"id": "p"}])
    source.request.side_effect = None
    source.request.return_value = metadata_response()
    data = Agent365Collector(source, NOW, EvidenceStore(tmp_path, NOW)).discover()
    path = tmp_path / "metadata.xlsx"
    write_workbook(data, [], path)
    sheet = load_workbook(path)["8. 수집 Raw 데이터"]
    for table in sheet.tables.values():
        first_column, header_row, last_column, _ = range_boundaries(table.ref)
        headers = [sheet.cell(header_row, column).value for column in range(first_column, last_column + 1)]
        if "package_id" in headers and "metadata_evidence_refs" in headers:
            row = {
                header: sheet.cell(header_row + 1, column).value
                for header, column in zip(headers, range(first_column, last_column + 1), strict=True)
            }
            assert row["package_type"] == "custom" and row["sensitivity"] == "general"
            assert json.loads(row["categories"]) == ["Development", "Productivity", "Tools"]
            assert row["category_count"] == 3 and row["sensitivity_present"] is True
            assert json.loads(row["metadata_evidence_refs"])["categories"] == data.agent365_packages[0].detail_evidence_refs
            break
    else:
        pytest.fail("Agent 365 Raw 표에 새 메타데이터·증적 열이 없습니다.")
