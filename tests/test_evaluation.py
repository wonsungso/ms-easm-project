from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Literal

import pytest

from easm_agent.api_grading import Measurement, measurements
from easm_agent.collect_admin_evidence import ENVIRONMENTS_URL
from easm_agent.evaluation import evaluate, matches, readiness
from easm_agent.models import (
    DEFAULT_TAGS,
    AdminEnvironment,
    AdminPolicyScope,
    AdminReadResult,
    Agent365Package,
    AgentEvidence,
    Budget,
    Collection,
    CopilotAgentEvidence,
    CopilotEvaluationRead,
    CopilotEvaluationRun,
    CopilotReview,
    DefenderPlan,
    EntraAgentIdentity,
    EntraBlueprint,
    EvaluationRun,
    EvidenceSource,
    Issue,
    LogSetting,
    ModelDeployment,
    ProposalObservation,
    Settings,
)
from easm_agent.models import (
    load_criteria as read_criteria,
)


@cache
def load_criteria() -> dict:
    return read_criteria(Settings(criteria_file=Path(__file__).parent / "fixtures" / "resource-criteria.yaml"))


NOW = datetime(2026, 11, 9, tzinfo=UTC)
SID = "11111111-1111-4111-8111-111111111111"
ACCOUNT = f"/subscriptions/{SID}/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/ai"
PROJECT = ACCOUNT + "/projects/p"
BLUEPRINT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CODES = list(load_criteria()["items"])
POWER_PLATFORM_CODES = ("DM-SY-01", "DS-SY-02", "BI-SY-08")


def grade(data: Collection, criteria: dict | None = None, facts: dict | None = None) -> dict:
    return {row.se_code: row for row in evaluate(data, criteria or load_criteria(), DEFAULT_TAGS, facts)}


@pytest.mark.parametrize("platform", ["langchain", "custom"])
def test_host_candidates_are_excluded_from_all_assessment_targets(data: Collection, platform: str) -> None:
    data.agents[0].platform = platform
    host_id = data.agents[0].agent_id
    results = grade(data)
    assert data.agents == []
    assert data.facts["excluded_host_candidates"]["count"] == 1
    assert all(
        target.subject != host_id and host_id not in target.observed.get("matching_agent_ids", [])
        for finding in results.values() for target in finding.measurement.targets
    )


def test_cost_completeness_excludes_only_confirmed_empty_inventory_scopes():
    data = Collection(collected_at=NOW, subscriptions=[SID, "empty"],
                      completed_subscriptions=[SID, "empty"], facts={
        "inventory_complete": True, "cost_complete_subscriptions": [SID],
        "signal_scope_exclusions": [{"collector": "cost", "subscription_id": "empty", "status": "excluded"}],
    })
    config = {"complete_subscriptions": ["cost_complete_subscriptions"]}
    assert readiness(data, config) is None
    data.resources.append({"subscriptionId": "empty", "type": "Microsoft.CognitiveServices/accounts",
                           "kind": "AIServices"})
    assert readiness(data, config) is not None


def test_control_evidence_is_specific_and_target_decisions_reconcile(data: Collection) -> None:
    data.entra_agent_identities[0].evidence_refs = ["unrelated-role-definition"]
    data.evidence_sources = [
        EvidenceSource(target="https://graph.microsoft.com/v1.0/servicePrincipals/microsoft.graph.agentIdentity",
                       evidence_refs=["identity-list"]),
        EvidenceSource(target="https://graph.microsoft.com/v1.0/applications/microsoft.graph.agentIdentityBlueprint",
                       evidence_refs=["blueprint-list"]),
        EvidenceSource(target="https://example.invalid/unrelated", evidence_refs=["unrelated-query"]),
    ]
    for row in data.proposal_observations:
        row.evidence_refs = [f"source:{row.code}"]
    data.costs[0].evidence_refs = ["cost-query"]
    results = grade(data)
    assert set(results["DS-SY-03"].evidence_refs) == {"identity-list", "blueprint-list"}
    assert results["DS-SY-06"].evidence_refs == ["source:DS-SY-06"]
    assert "cost-query" not in results["DS-SY-06"].evidence_refs
    assert results["DS-SY-06"].measurement.targets[0].observed == {"require_approval": "always"}
    for result in results.values():
        measurement = result.measurement
        assert measurement is not None
        if not measurement.complete:
            assert measurement.numerator is measurement.denominator is None
            continue
        assert measurement.numerator / measurement.denominator == result.metric_value
        assert sum(target.contribution or 0 for target in measurement.targets) == measurement.numerator
        if measurement.unit == "count":
            assert sum(target.status != "excluded" for target in measurement.targets) == measurement.denominator
    amount = results["OT-SY-24"].measurement
    assert amount.unit == "amount" and amount.currency == "USD"
    assert amount.numerator == amount.denominator == 10


def test_incomplete_measurement_keeps_null_counts_and_missing_targets(data: Collection) -> None:
    data.proposal_observations = [row for row in data.proposal_observations if row.code != "DS-SY-05"]
    result = grade(data)["DS-SY-05"]
    assert result.level == "N/A" and result.metric_value is None
    assert result.measurement.numerator is result.measurement.denominator is None
    assert not result.measurement.complete
    assert result.measurement.targets[0].subject == ACCOUNT.lower()
    assert result.measurement.targets[0].status == "unknown"


def test_evaluation_snapshots_criteria_and_detects_later_tampering(data: Collection) -> None:
    from copy import deepcopy

    from easm_agent.models import AssessmentProvenance
    from easm_agent.provenance import digest

    criteria = deepcopy(load_criteria())
    evaluate(data, criteria, DEFAULT_TAGS, provenance_origin="saved_snapshot_reassessment")
    provenance = data.assessment_provenance
    assert provenance.origin == "saved_snapshot_reassessment"
    assert digest(provenance.criteria_snapshot) == provenance.criteria_sha256
    before = provenance.criteria_sha256
    criteria["workspace_retention_target_days"] = 365
    assert provenance.criteria_snapshot["workspace_retention_target_days"] == 90
    assert provenance.criteria_sha256 == before
    altered = provenance.model_dump(mode="json")
    altered["criteria_snapshot"]["workspace_retention_target_days"] = 365
    with pytest.raises(ValueError, match="해시"):
        AssessmentProvenance.model_validate(altered)


@pytest.fixture
def data() -> Collection:
    criteria = load_criteria()
    value = Collection(
        collected_at=NOW, subscriptions=[SID],
        resources=[{"id": ACCOUNT, "subscriptionId": SID, "type": "microsoft.cognitiveservices/accounts",
                    "kind": "AIServices", "location": "westus2"}],
        agents=[AgentEvidence(
            collected_at=NOW, platform="foundry", agent_id="agent", agent_name="agent", agent_version="1",
            subscription_id=SID, resource_id=PROJECT, model_resource_id=ACCOUNT, detection_confidence="tag",
            tags={"owner": "team", "sponsor": "team", "env": "prod", "cost-center": "engineering"},
        )],
        deployments=[ModelDeployment(
            subscription_id=SID, resource_id=ACCOUNT + "/deployments/m", account_id=ACCOUNT, name="m",
            model="gpt", version="1", format="OpenAI", version_upgrade_option="NoAutoUpgrade", rai_policy="safe",
        )],
        evaluations=[EvaluationRun(subscription_id=SID, project_id=PROJECT, run_id="run", status="completed")],
        entra_blueprints=[EntraBlueprint(blueprint_id=BLUEPRINT, tags=[
            f"subscriptionId:{SID}", "accountName:ai", "projectName:p", "agentName:agent",
        ])],
        entra_agent_identities=[EntraAgentIdentity(
            identity_id="identity", blueprint_id=BLUEPRINT, account_enabled=True,
            owner_count=1, sponsor_count=1, owners_all_disabled=False,
        )],
        logs=[LogSetting(subscription_id=SID, resource_id=ACCOUNT, enabled=True,
                         workspace_id="/workspace", retention_days=90)],
        budgets=[Budget(
            subscription_id=SID, budget_id="/budget", amount=100, category="Cost", time_grain="Monthly",
            actual_alerts=1, forecast_alerts=1, enabled_alerts=2, thresholds=[80, 90],
            period_start=NOW - timedelta(days=1), period_end=NOW + timedelta(days=30),
            filters_empty=True, notifications_with_receivers=True,
        )],
        facts={
            "inventory_complete": True, "agent_inventory_complete": True,
            "deployment_inventory_complete": True, "entra_blueprints_complete": True,
            "entra_agents_complete": True, "agent365_registry_complete": True,
            "copilot_inventory_complete": True,
            "evaluation_complete_projects": [PROJECT], "foundry_project_ids": [PROJECT],
            "resource_metrics": [{"resource_id": ACCOUNT, "metrics": [{"timeseries": [{"data": [{"total": 0}]}]}]}],
        },
    )
    from easm_agent.models import CostRecord, SecurityRecommendation

    value.costs = [CostRecord(subscription_id=SID, resource_id=ACCOUNT, amount=10, currency="USD", usage_date="20261109")]
    value.defender_plans = defender_plans()
    value.agent365_packages = [registry_package(IDENTITY_ID)]
    value.admin_evidence = power_platform_reads()
    value.security = [SecurityRecommendation(subscription_id=SID, resource_id=ACCOUNT,
                                            assessment_id="/assessment", severity="Low", status="Healthy")]
    entries = [
        ("DS-SY-05", "ai_account", {"public_network_access": "Disabled", "approved_private_endpoints": 1}),
        ("DS-SY-06", "agent_tools", {"mcp_approval_modes": ["always"]}),
        ("DS-SY-07", "tool_endpoints", {"endpoint_https": [True]}),
        ("BI-SY-11", "ai_account", {"enabled_policy_names": ["safe"], "policy_filter_enabled": {"safe": True}}),
        ("BI-SY-14", "policy_resource", {"state": "Compliant"}),
        ("OE-SY-19", "ai_account", {
            "identity_type": "SystemAssigned", "principal_count": 1,
            "privileged_assignments": 0, "local_auth_disabled": True,
        }),
        ("OE-SY-20", "metricalerts", {
            "kind": "metricalerts", "targets_ai": True, "target_ids": [ACCOUNT],
            "enabled": True, "action_group_resolved": True,
        }),
    ]
    value.proposal_observations = [
        ProposalObservation(code=code, subscription_id=SID, subject=ACCOUNT, kind=kind,
                            values=fields, evidence_refs=["fixture://api"])
        for code, kind, fields in entries
    ]
    for config in criteria["items"].values():
        for key in config.get("complete_subscriptions", []):
            value.facts[key] = [SID]
    return value


def test_copilot_inventory_adds_platform_specific_checks(data: Collection) -> None:
    data.copilot_agents = [
        CopilotAgentEvidence(agent_id="studio", environment_id="env", platform="copilot_studio",
                             owner_present=True, authentication="Microsoft Entra", evidence_refs=["studio-ref"]),
        CopilotAgentEvidence(agent_id="builder", environment_id="env", platform="agent_builder",
                             owner_present=False, authentication="None", evidence_refs=["builder-ref"]),
    ]
    results = grade(data)
    for code in ("BI-SY-13", "OE-SY-19"):
        measurement = results[code].measurement
        assert measurement.complete
        assert (measurement.numerator, measurement.denominator) == (2, 3)
        assert results[code].level == "L2"
        assert "studio-ref" in results[code].evidence_refs
        assert [row.status for row in measurement.targets[-2:]] == ["compliant", "non_compliant"]


def test_copilot_model_access_security_and_publishing_use_real_configuration(data: Collection) -> None:
    data.copilot_agents = [CopilotAgentEvidence(
        agent_id="builder", environment_id="env", platform="agent_builder",
        model="Microsoft 365 Copilot", orchestration="Generative", harness="Copilot Chat",
        authentication="Microsoft Entra", shared_with_tenant=False,
        last_published_at=NOW, connector_count=0, connector_operation_count=0, connector_operations=[],
        owner_present=True, evidence_refs=["copilot-ref"],
    )]
    results = grade(data)
    for code in ("DS-SY-04", "DS-SY-05", "BI-SY-10", "BI-SY-12"):
        result = results[code]
        assert result.metric_value == 1
        assert result.measurement.denominator == 2
        assert result.measurement.targets[-1].observed["platform"] == "agent_builder"
    for code in ("DP-SY-15", "BI-SY-09", "DS-SY-06"):
        assert results[code].measurement.denominator == 1
        assert results[code].measurement.targets[-1].status == "excluded"
    data.copilot_agents[0].authentication = "None"
    data.copilot_agents[0].last_published_at = None
    for code in ("DS-SY-05", "BI-SY-10", "BI-SY-12"):
        result = grade(data)[code]
        assert result.metric_value == 0.5
        assert result.measurement.targets[-1].status == "non_compliant"


@pytest.mark.parametrize(("harness", "platform"), [
    ("Standard", "copilot_studio"), ("GitHub Copilot", "copilot_studio"), ("Copilot Chat", "agent_builder"),
])
def test_standard_copilot_empty_completed_evaluation_read_is_known_absence(
    data: Collection, harness: str, platform: Literal["copilot_studio", "agent_builder"],
) -> None:
    data.copilot_agents = [CopilotAgentEvidence(
        agent_id="studio", environment_id="env", platform=platform, harness=harness,
        evaluation_read=CopilotEvaluationRead(completed=True, runs=[]), evidence_refs=["evaluation-ref"],
    )]
    result = grade(data)["BI-SY-09"]
    assert result.metric_value == 0.5
    assert (result.measurement.numerator, result.measurement.denominator) == (1, 2)
    data.copilot_agents[0].evaluation_read = CopilotEvaluationRead(completed=False, reason="permission_denied")
    data.issues.append(Issue(collector="copilot_evaluations", target="studio", reason="permission_denied",
                             detail="read failed"))
    result = grade(data)["BI-SY-09"]
    assert result.reason == "permission_denied" and result.metric_value is None
    assert result.measurement.targets[-1].status == "unknown"


def test_nonstandard_review_absence_is_measured_but_does_not_override_completed_run(data: Collection) -> None:
    identifier = "22222222-2222-4222-8222-222222222222"
    data.copilot_agents = [CopilotAgentEvidence(
        agent_id=identifier, environment_id="env", platform="copilot_studio", harness="GitHub Copilot",
        evidence_refs=["inventory-ref"],
    )]
    data.copilot_reviews = [CopilotReview(
        agent_id=identifier, environment_id="env", state="authoring", observed_at=NOW,
        source_url=f"https://copilotstudio.microsoft.com/environments/env/agents/{identifier}",
        warning_count=2, evaluation_run_missing=True, channel_configuration_missing=True,
        evidence_refs=["review-ref"],
    )]
    result = grade(data)["BI-SY-09"]
    assert (result.measurement.numerator, result.measurement.denominator) == (1, 2)
    assert result.measurement.targets[-1].status == "non_compliant"
    assert result.measurement.targets[-1].observed["review_source"] == "official_admin_portal_read"
    assert "review-ref" in result.evidence_refs
    data.copilot_agents[0].evaluation_read = CopilotEvaluationRead(completed=True, runs=[])
    result = grade(data)["BI-SY-09"]
    assert result.measurement.targets[-1].status == "non_compliant"
    assert "review_source" not in result.measurement.targets[-1].observed
    assert "review-ref" not in result.evidence_refs
    data.copilot_agents[0].evaluation_read = CopilotEvaluationRead(
        completed=True, runs=[CopilotEvaluationRun(run_id=identifier, state="Completed", end_time=NOW)],
    )
    result = grade(data)["BI-SY-09"]
    assert result.metric_value is None and result.measurement.targets[-1].status == "unknown"


def test_copilot_missing_or_truncated_connector_fields_are_not_zero(data: Collection) -> None:
    data.copilot_agents = [CopilotAgentEvidence(
        agent_id="builder", environment_id="env", platform="agent_builder",
        authentication="Microsoft Entra", shared_with_tenant=False,
        connector_count=201, connector_operation_count=201, connector_operations=[],
    )]
    for code in ("DS-SY-06", "BI-SY-10"):
        result = grade(data)[code]
        assert result.metric_value is None
        assert result.measurement.numerator is result.measurement.denominator is None
        assert result.measurement.targets[-1].status == "unknown"


def test_copilot_region_requires_exact_environment_evidence(data: Collection) -> None:
    data.admin_evidence[0].environments[0].region = "canadaeast"
    data.copilot_agents = [CopilotAgentEvidence(
        agent_id="builder", environment_id="env-1", platform="agent_builder", evidence_refs=["copilot-ref"],
    )]
    result = grade(data)["OE-SY-22"]
    assert result.metric_value == 1 and result.measurement.denominator == 2
    assert result.measurement.targets[-1].observed["environment_region"] == "canadaeast"
    assert "fixture://admin" in result.evidence_refs
    data.copilot_agents[0].environment_id = "different-environment"
    result = grade(data)["OE-SY-22"]
    assert result.metric_value is None and result.measurement.targets[-1].status == "unknown"


def test_copilot_inventory_failure_or_unknown_never_scores_as_zero(data: Collection) -> None:
    data.copilot_agents = [
        CopilotAgentEvidence(agent_id="studio", environment_id="env", platform="copilot_studio",
                             owner_present=None, authentication="unrecognized"),
    ]
    for code in ("BI-SY-13", "OE-SY-19"):
        finding = grade(data)[code]
        assert finding.level == "N/A" and finding.metric_value is None
        assert finding.measurement.targets[-1].status == "unknown"
    data.copilot_agents = []
    data.facts["copilot_inventory_complete"] = False
    data.issues.append(Issue(collector="copilot_inventory", target="inventory", reason="permission_denied",
                             detail="no access"))
    for code in ("BI-SY-13", "OE-SY-19"):
        finding = grade(data)[code]
        assert finding.reason == "permission_denied" and finding.metric_value is None


def test_saved_criteria_without_copilot_checks_keeps_original_measurements(data: Collection) -> None:
    from copy import deepcopy

    criteria = deepcopy(load_criteria())
    for code in ("BI-SY-13", "OE-SY-19"):
        item = criteria["items"][code]
        item.pop("copilot_inventory_check")
        item["collectors"].remove("copilot_inventory")
        item["complete_flags"].remove("copilot_inventory_complete")
    data.copilot_agents = [
        CopilotAgentEvidence(agent_id="builder", environment_id="env", platform="agent_builder",
                             owner_present=False, authentication="None"),
    ]
    results = grade(data, criteria)
    for code in ("BI-SY-13", "OE-SY-19"):
        assert results[code].metric_value == 1
        assert results[code].measurement.denominator == 1


IDENTITY_ID = "identity"


def registry_package(identity: str | None = None, name: str = "package", **changes: object) -> Agent365Package:
    values = {
        "package_id": name, "agent_identity_id": identity, "governance": "ManagedAgent", "owner_count": 1,
        "available_to": "allowedForSome", "deployed_to": "acquiredForSome", "is_blocked": False,
        "created_at": NOW - timedelta(days=5), "request_status": "approved", "evidence_refs": ["fixture://registry"],
    }
    return Agent365Package(**{**values, **changes})


def power_platform_reads(*, managed: bool = True, with_role: bool = True, covered: bool = True) -> list[AdminReadResult]:
    base = {"module_version": "2.0.220", "scope": "fixture", "completed": True, "observed_at": NOW,
            "detail": "fixture", "evidence_refs": ["fixture://admin"]}
    return [
        AdminReadResult(source="powerplatform.environments", command=ENVIRONMENTS_URL, object_count=1,
                        environments=[AdminEnvironment(environment_id="env-1", environment_type="Production",
                                                       protection_level="Standard" if managed else "Basic")], **base),
        AdminReadResult(source="powerplatform.environment_roles", command="Get-AdminPowerAppEnvironmentRoleAssignment",
                        object_count=1 if with_role else 0, role_counts={"env-1": int(with_role)}, **base),
        AdminReadResult(source="powerplatform.dlp_policies", command="Get-AdminDlpPolicy", object_count=1,
                        policies=[AdminPolicyScope(scope_type="AllEnvironments" if covered else "OnlyEnvironments",
                                                   environment_ids=[] if covered else ["other"])], **base),
    ]


def defender_plans(
    sid: str = SID, *, ai_tier: str | None = "Standard", cspm_tier: str | None = "Standard",
    discovery: bool | None = True,
) -> list[DefenderPlan]:
    extensions = {} if discovery is None else {"SensitiveDataDiscovery": discovery}
    return [
        DefenderPlan(subscription_id=sid, plan="AI", tier=ai_tier, extensions={"AIPromptEvidence": True},
                     evidence_refs=["fixture://defender"]),
        DefenderPlan(subscription_id=sid, plan="CloudPosture", tier=cspm_tier, extensions=extensions,
                     evidence_refs=["fixture://defender"]),
    ]


def test_complete_api_snapshot_grades_all_26_controls_without_qualitative_inputs(data: Collection) -> None:
    rows = grade(data)
    assert len(rows) == 26
    assert all(row.level == "L5" and row.metric_value == 1 for row in rows.values()), {
        code: (row.level, row.reason) for code, row in rows.items() if row.level != "L5"
    }
    assert all(row.reason is None and row.assessment_basis == "criteria" for row in rows.values())
    assert data.facts["grading_profile"] == "api_configuration_v1"




@pytest.mark.parametrize("reason", ["permission_denied", "license_missing", "error"])
def test_agent365_registry_failures_do_not_affect_remaining_items(data: Collection, reason: str) -> None:
    from easm_agent.collect_agent365 import crosscheck_agent365
    from easm_agent.models import Issue

    before = {code: row.model_dump() for code, row in grade(data).items()}
    data.issues.append(Issue(
        collector="agent365_registry", target="tenant", reason=reason, detail="registry unavailable",
    ))
    data.facts["agent365_registry_complete"] = False
    data.agent365_crosschecks = crosscheck_agent365(data, load_criteria())
    after = grade(data)
    assert {c: r.model_dump() for c, r in after.items()} == before
    assert len(after) == 26


def test_power_platform_items_use_their_own_ratios(data: Collection) -> None:
    data.admin_evidence = power_platform_reads(managed=False, with_role=False, covered=False)
    data.agent365_packages = [
        registry_package(IDENTITY_ID, "a"),
        registry_package(None, "b", governance="Unmanaged", owner_count=0, available_to="allowedForAll",
                         request_status="pending"),
    ]
    rows = grade(data)
    for code in ("BI-SY-08", "DM-SY-01", "DS-SY-02"):
        assert (rows[code].level, rows[code].measurement.numerator, rows[code].measurement.denominator) == ("L1", 0, 1)
    assert len(rows) == 26


def test_removed_registry_items_are_absent_without_registry_data(data: Collection) -> None:
    data.agent365_packages = []
    data.facts["agent365_registry_complete"] = False
    rows = grade(data)
    assert len(rows) == 26


@pytest.mark.parametrize("changes,level", [
    ({}, "L5"),
    ({"ai_tier": "Free"}, "L1"),
    ({"cspm_tier": "Free", "discovery": False}, "L1"),
    ({"discovery": False}, "L1"),
])
def test_sensitive_data_protection_requires_ai_plan_cspm_and_discovery(
    data: Collection, changes: dict, level: str,
) -> None:
    data.defender_plans = defender_plans(**changes)
    row = grade(data)["OT-SY-25"]
    assert row.level == level
    assert row.measurement.denominator == 1 and row.evidence_refs == ["fixture://defender"]
    assert row.measurement.targets[0].observed["prompt_evidence"] is True


@pytest.mark.parametrize("plans", [
    [],
    defender_plans(ai_tier=None),
    defender_plans(discovery=None),
    defender_plans(ai_tier="Free", discovery=None),
    defender_plans(cspm_tier="Free", discovery=None),
    defender_plans(ai_tier=None, cspm_tier="Free"),
    defender_plans()[:1],
])
def test_missing_defender_plan_fields_are_unknown_not_l1(data: Collection, plans: list[DefenderPlan]) -> None:
    data.defender_plans = plans
    row = grade(data)["OT-SY-25"]
    assert row.level == "N/A" and row.metric_value is None and row.reason == "not_found"
    assert row.measurement.numerator is None and row.measurement.denominator is None


def test_missing_required_fields_remain_unknown_even_when_another_field_fails(data: Collection) -> None:
    data.deployments[0].model = ""
    data.deployments[0].version = None
    data.entra_agent_identities[0].owner_count = 0
    data.entra_agent_identities[0].sponsor_count = None
    network = next(row for row in data.proposal_observations if row.code == "DS-SY-05")
    network.values["public_network_access"] = "Enabled"
    network.values["approved_private_endpoints"] = None

    rows = grade(data)
    for code in ("DS-SY-04", "DS-SY-05", "OE-SY-16"):
        assert rows[code].level == "N/A" and rows[code].metric_value is None


@pytest.mark.parametrize("good,level", [(0, "L1"), (1, "L2"), (8, "L3"), (9, "L4"), (10, "L5")])
def test_real_api_field_combinations_reach_every_level_for_all23_controls(
    data: Collection, good: int, level: str,
) -> None:
    from copy import deepcopy

    snapshot = Collection(collected_at=NOW)
    for index in range(10):
        complete = index < good
        sid = f"{index + 1:08}-1111-4111-8111-111111111111"
        account = f"/subscriptions/{sid}/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/ai{index}"
        project = account + "/projects/p"
        blueprint = f"blueprint-{index}"
        snapshot.subscriptions.append(sid)
        snapshot.resources.append({
            "id": account, "subscriptionId": sid, "type": "microsoft.cognitiveservices/accounts",
            "kind": "AIServices", "location": "westus2",
        })
        agent = data.agents[0].model_copy(deep=True, update={
            "subscription_id": sid, "resource_id": project, "model_resource_id": account,
            "agent_id": f"agent-{index}", "agent_name": f"agent-{index}",
            "agent_version": "1" if complete else "",
        })
        if not complete:
            agent.tags.pop("cost-center")
        snapshot.agents.append(agent)
        snapshot.entra_blueprints.append(EntraBlueprint(blueprint_id=blueprint, tags=[
            f"subscriptionId:{sid}", f"accountName:ai{index}", "projectName:p", f"agentName:agent-{index}",
        ]))
        snapshot.entra_agent_identities.append(data.entra_agent_identities[0].model_copy(update={
            "identity_id": f"identity-{index}", "blueprint_id": blueprint if complete else "not-collected",
            "owner_count": 1 if complete else 0,
            "app_roles": [] if complete else ["Data.Write.All"],
            "overprivileged_roles": [] if complete else ["Data.Write.All"],
        }))
        snapshot.deployments.append(data.deployments[0].model_copy(update={
            "subscription_id": sid, "account_id": account, "resource_id": account + "/deployments/m",
            "version": "1" if complete else "", "rai_policy": "safe" if complete else "missing",
        }))
        snapshot.evaluations.append(data.evaluations[0].model_copy(update={
            "subscription_id": sid, "project_id": project, "run_id": f"run-{index}",
            "status": "completed" if complete else "failed",
        }))
        snapshot.security.append(data.security[0].model_copy(update={
            "subscription_id": sid, "resource_id": account, "assessment_id": f"/assessment/{index}",
            "status": "Healthy" if complete else "Unhealthy",
        }))
        snapshot.logs.append(data.logs[0].model_copy(update={
            "subscription_id": sid, "resource_id": account, "enabled": complete,
        }))
        snapshot.budgets.append(data.budgets[0].model_copy(update={
            "subscription_id": sid, "budget_id": f"/budget/{index}", "forecast_alerts": 1 if complete else 0,
        }))
        snapshot.costs.append(data.costs[0].model_copy(update={
            "subscription_id": sid, "resource_id": account if complete else f"/shared-workspace/{index}",
        }))
        snapshot.defender_plans.extend(defender_plans(sid, ai_tier="Standard" if complete else "Free"))
        for original in data.proposal_observations:
            row = original.model_copy(deep=True, update={"subscription_id": sid, "subject": account})
            field_values = deepcopy(row.values)
            if row.code == "DS-SY-05":
                field_values["public_network_access"] = "Disabled" if complete else "Enabled"
            elif row.code == "DS-SY-06":
                field_values["mcp_approval_modes"] = ["always" if complete else "never"]
            elif row.code == "DS-SY-07":
                field_values["endpoint_https"] = [complete]
            elif row.code == "BI-SY-14":
                field_values["state"] = "Compliant" if complete else "NonCompliant"
            elif row.code == "OE-SY-19":
                field_values["principal_count"] = 1 if complete else 0
            elif row.code == "OE-SY-20":
                field_values.update({"enabled": complete, "target_ids": [account], "action_group_resolved": complete})
            row.values = field_values
            snapshot.proposal_observations.append(row)
    snapshot.agent365_packages = [
        registry_package(
            f"identity-{index}" if index < good else None, f"package-{index}",
            **({} if index < good else {
                "governance": "Unmanaged", "owner_count": 0, "available_to": "allowedForAll",
                "request_status": "pending",
            }),
        )
        for index in range(10)
    ]
    env_ids = [f"env-{index}" for index in range(10)]
    reads = power_platform_reads()
    reads[0].environments = [
        AdminEnvironment(environment_id=env, environment_type="Production",
                         protection_level="Standard" if index < good else "Basic")
        for index, env in enumerate(env_ids)
    ]
    reads[0].object_count = 10
    reads[1].role_counts = {env: int(index < good) for index, env in enumerate(env_ids)}
    reads[1].object_count = good
    reads[2].policies = [AdminPolicyScope(scope_type="OnlyEnvironments", environment_ids=env_ids[:good])]
    snapshot.admin_evidence = reads
    snapshot.facts = {
        "inventory_complete": True, "agent_inventory_complete": True, "deployment_inventory_complete": True,
        "copilot_inventory_complete": True,
        "entra_blueprints_complete": True, "entra_agents_complete": True, "agent365_registry_complete": True,
        "foundry_project_ids": [run.project_id for run in snapshot.evaluations],
        "evaluation_complete_projects": [run.project_id for run in snapshot.evaluations],
        "resource_metrics": [
            {"resource_id": row["id"], "metrics": [{"timeseries": [{"data": [{"total": 0}]}]}]
             if index < good else []}
            for index, row in enumerate(snapshot.resources)
        ],
    }
    for config in load_criteria()["items"].values():
        for key in config.get("complete_subscriptions", []):
            snapshot.facts[key] = snapshot.subscriptions
    rows = grade(snapshot)
    assert len(rows) == 26
    for code, row in rows.items():
        assert row.metric_value == pytest.approx(good / 10), (code, row.rationale)
        assert row.level == level, (code, row.rationale)


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("ratio,level", [
    (0, "L1"), (0.01, "L2"), (0.7999, "L2"), (0.8, "L3"),
    (0.8999, "L3"), (0.9, "L4"), (0.9999, "L4"), (1, "L5"),
])
def test_exact_thresholds_for_every_control(
    data: Collection, code: str, ratio: float, level: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from easm_agent import evaluation

    original = measurements(data, load_criteria(), DEFAULT_TAGS)
    original[code] = Measurement(total=10000, compliant=ratio * 10000, detail="Boundary API measurement")
    monkeypatch.setattr(evaluation, "measurements", lambda *args: original)
    row = grade(data)[code]
    assert row.level == level and row.metric_value == pytest.approx(ratio)
    assert row.level_criterion == load_criteria()["items"][code]["levels"][level]


@pytest.mark.parametrize("code", [code for code in CODES if load_criteria()["items"][code].get("collectors")])
def test_related_collection_error_prevents_any_level(data: Collection, code: str) -> None:
    collector = load_criteria()["items"][code]["collectors"][0]
    data.issues.append(Issue(collector=collector, target="fixture", reason="permission_denied", detail="Denied API"))
    row = grade(data)[code]
    assert row.level == "N/A" and row.metric_value is None and row.reason == "permission_denied"


@pytest.mark.parametrize("code", CODES)
def test_empty_denominator_is_not_success_or_l1(
    data: Collection, code: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from easm_agent import evaluation

    original = measurements(data, load_criteria(), DEFAULT_TAGS)
    original[code] = Measurement(unavailable="대상 없음")
    monkeypatch.setattr(evaluation, "measurements", lambda *args: original)
    row = grade(data)[code]
    assert row.level == "N/A" and row.metric_value is None and row.reason == "not_found"


@pytest.mark.parametrize("code", CODES)
def test_completeness_markers_cannot_be_omitted(data: Collection, code: str) -> None:
    config = load_criteria()["items"][code]
    if code in POWER_PLATFORM_CODES:
        data.admin_evidence = [row.model_copy(update={"completed": False, "reason": "error", "object_count": None,
                                                      "environments": [], "role_counts": {}, "policies": []})
                               for row in data.admin_evidence]
        assert grade(data)[code].level == "N/A"
        return
    data.facts["inventory_complete"] = False
    data.facts["entra_agents_complete"] = data.facts["entra_blueprints_complete"] = False
    for flag in config.get("complete_flags", []):
        data.facts[flag] = False
    assert grade(data)[code].level == "N/A"
    if config.get("complete_subscriptions"):
        data.facts["inventory_complete"] = True
        data.facts[config["complete_subscriptions"][0]] = []
        assert grade(data)[code].level == "N/A"


def test_ten_blueprints_and_ten_linked_identities_receive_level5(data: Collection) -> None:
    data.entra_blueprints = [EntraBlueprint(blueprint_id=f"blueprint-{i}") for i in range(10)]
    data.entra_agent_identities = [EntraAgentIdentity(identity_id=f"id-{i}", blueprint_id=f"blueprint-{i}")
                                    for i in range(10)]
    row = grade(data)["DS-SY-03"]
    assert row.level == "L5" and row.metric_value == 1
    data.entra_agent_identities[0].blueprint_id = "outside"
    assert grade(data)["DS-SY-03"].level == "L4"
    data.entra_agent_identities[1].blueprint_id = None
    assert grade(data)["DS-SY-03"].level == "L3"


@pytest.mark.parametrize("field,value", [
    ("period_end", NOW - timedelta(seconds=1)), ("period_start", NOW + timedelta(days=1)),
    ("filters_empty", False), ("amount", 0), ("actual_alerts", 0),
    ("forecast_alerts", 0), ("notifications_with_receivers", False),
])
def test_budget_must_be_effective_and_include_both_notification_types(
    data: Collection, field: str, value: object,
) -> None:
    setattr(data.budgets[0], field, value)
    row = grade(data)["OT-SY-26"]
    assert row.level == "L1" and row.metric_value == 0


def test_missing_budget_fields_are_unknown_not_zero(data: Collection) -> None:
    data.budgets[0].period_end = None
    assert grade(data)["OT-SY-26"].level == "N/A"
    data.budgets = []
    assert grade(data)["OT-SY-26"].level == "L1"


def test_model_unknown_update_option_does_not_count_as_configured(data: Collection) -> None:
    data.deployments[0].version_upgrade_option = None
    assert grade(data)["DS-SY-04"].level == "N/A"
    data.deployments[0].version_upgrade_option = "unrecognized"
    assert grade(data)["DS-SY-04"].level == "L1"


def test_mcp_never_custom_and_missing_modes_are_not_always(data: Collection) -> None:
    tool = next(row for row in data.proposal_observations if row.code == "DS-SY-06")
    tool.values["mcp_approval_modes"] = ["never"]
    assert grade(data)["DS-SY-06"].level == "L1"
    tool.values["mcp_approval_modes"] = ["custom"]
    assert grade(data)["DS-SY-06"].level == "L1"
    tool.values["mcp_approval_modes"] = [None]
    assert grade(data)["DS-SY-06"].level == "N/A"
    tool.values["mcp_approval_modes"] = []
    assert grade(data)["DS-SY-06"].level == "N/A"


def test_cost_shared_resources_are_not_attributed_twice(data: Collection) -> None:
    data.agents.append(data.agents[0].model_copy(update={"agent_id": "other"}))
    assert grade(data)["OT-SY-24"].metric_value == 0
    data.costs[0].amount = 0
    assert grade(data)["OT-SY-24"].level == "N/A"
    data.costs[0].amount = -1
    assert grade(data)["OT-SY-24"].level == "N/A"


def test_not_applicable_recommendations_and_unknown_fields_do_not_mean_healthy(data: Collection) -> None:
    data.security[0].status = "NotApplicable"
    assert grade(data)["BI-SY-10"].level == "N/A"
    data.security[0].status = None
    assert grade(data)["BI-SY-10"].level == "N/A"


def test_missing_filter_configuration_is_unknown_not_disabled(data: Collection) -> None:
    row = next(row for row in data.proposal_observations if row.code == "BI-SY-11")
    row.values["policy_filter_enabled"] = {"safe": None}
    assert grade(data)["BI-SY-11"].level == "N/A"
    row.values["policy_filter_enabled"] = {"safe": False}
    assert grade(data)["BI-SY-11"].level == "L1"


def test_noncompliance_and_exemption_are_not_perfect_policy_coverage(data: Collection) -> None:
    row = next(row for row in data.proposal_observations if row.code == "BI-SY-14")
    row.values["state"] = "NonCompliant"
    assert grade(data)["BI-SY-14"].level == "L1"
    row.values["state"] = "Unknown"
    assert grade(data)["BI-SY-14"].level == "N/A"


def test_missing_owner_counts_and_unresolved_role_names_are_unknown(data: Collection) -> None:
    data.entra_agent_identities[0].owner_count = None
    data.entra_agent_identities[0].app_roles = ["unresolved:abc"]
    assert grade(data)["OE-SY-16"].level == grade(data)["OE-SY-17"].level == "N/A"


def test_fully_linked_blueprint_must_have_actual_agent_identity_for_azure_link(data: Collection) -> None:
    data.entra_agent_identities[0].blueprint_id = "other"
    assert grade(data)["DP-SY-15"].level == "L1"


def test_metric_zero_is_observed_but_missing_timeseries_is_not(data: Collection) -> None:
    assert grade(data)["OT-SY-23"].level == "L5"
    data.facts["resource_metrics"][0]["metrics"] = []
    assert grade(data)["OT-SY-23"].level == "L1"
    data.facts["resource_metrics"] = []
    assert grade(data)["OT-SY-23"].level == "N/A"


def test_configuration_name_count_does_not_prove_a_network_boundary(data: Collection) -> None:
    row = next(row for row in data.proposal_observations if row.code == "DS-SY-05")
    row.values["public_network_access"] = "Enabled"
    assert grade(data)["DS-SY-05"].level == "L1"
    row.values["public_network_access"] = "Disabled"
    row.values["approved_private_endpoints"] = None
    assert grade(data)["DS-SY-05"].level == "N/A"


def test_qualitative_facts_cannot_elevate_api_grades(data: Collection) -> None:
    with pytest.raises(ValueError, match="policy_facts"):
        grade(data, facts={"major_type_blueprints_defined": {"value": True, "evidence_refs": ["file"]}})


def test_rules_reject_unknown_operator_and_missing_values() -> None:
    assert not matches({}, {"coverage": {"eq": 0}})
    assert matches({"coverage": 0}, {"coverage": {"eq": 0}})
    with pytest.raises(ValueError, match="Unknown criteria operator"):
        matches({"coverage": 1}, {"coverage": {"unknown": 1}})


def test_all_criteria_have_exactly_api_metrics_and_exhaustive_level_definitions() -> None:
    criteria = load_criteria()
    assert len(criteria["items"]) == 26
    assert "configuration_grading" not in criteria
    for config in criteria["items"].values():
        assert list(config["levels"]) == ["L1", "L2", "L3", "L4", "L5"]
        assert all(set(rule["when"]) == {"coverage"} for rule in config["rules"])
        for value in (0, 0.001, 0.79, 0.8, 0.89, 0.9, 0.99, 1):
            assert sum(matches({"coverage": value}, rule["when"]) for rule in config["rules"]) == 1
