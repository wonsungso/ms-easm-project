from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from openpyxl import load_workbook

from easm_agent.agent365_grading import REGISTRY_CHECKS, registry_targets
from easm_agent.agent365_insights import catalog_changes
from easm_agent.collect_agent365 import crosscheck_agent365
from easm_agent.deck_model import read_assessment
from easm_agent.evaluation import evaluate
from easm_agent.models import (
    Agent365Package,
    Collection,
    ConnectedAgentMetadata,
    Issue,
    load_criteria,
)
from easm_agent.report_backdata import metrics_by_key
from easm_agent.report_excel import write_workbook
from easm_agent.report_integrated import MATRIX, RAW, platform_breakdown, platform_scope
from easm_agent.report_story import DeckData

NOW = datetime(2026, 11, 27, 8, tzinfo=UTC)
def criteria():
    return load_criteria()


def collection():
    external = Agent365Package(
        package_id="external", platform="AmazonBedrock", package_type="lob",
        element_types=["AgentMetadatas"], owner_count=0, is_blocked=False,
        available_to="allowedForAll", deployed_to="acquiredForNone",
        created_at=NOW - timedelta(days=1), last_modified_at=NOW - timedelta(hours=1),
        detail_read_completed=True, evidence_refs=["catalog"], detail_evidence_refs=["detail"],
        audience_counts={key: 0 for key in criteria()["registry_audience_fields"]},
        audience_type_counts={key: {"user": 0, "group": 0} for key in criteria()["registry_audience_fields"]},
        connected_metadata=ConnectedAgentMetadata(
            registration_type="ConnectedPlatform", registration_provider="AWSBedrock", origin_store="BedrockAgentCore",
            published_status="Published", content_presence={"Instructions_present": True},
        ),
    )
    microsoft = external.model_copy(deep=True, update={
        "package_id": "ms", "platform": "Foundry", "description_present": False, "owner_count": 1,
        "connected_metadata": ConnectedAgentMetadata(),
    })
    data = Collection(
        collected_at=NOW, agent365_packages=[
            external, microsoft,
            external.model_copy(deep=True, update={"package_id": "tool", "element_types": ["AgentSkills"]}),
            external.model_copy(deep=True, update={"package_id": "store", "platform": "Not Available"}),
        ],
        facts={"agent365_registry_complete": True, "agent365_tenant_id": "same",
               "agent365_collected_at": NOW.isoformat()},
    )
    prior = data.model_copy(deep=True)
    prior.facts["agent365_collected_at"] = (NOW - timedelta(hours=2)).isoformat()
    for package in prior.agent365_packages:
        package.evidence_refs = ["previous-catalog"]
    data.facts["agent365_comparison"] = catalog_changes(data, prior)
    return data


def test_common_checks_replace_native_population_and_keep_ownership_separate():
    data, config = collection(), criteria()
    findings = {finding.se_code: finding for finding in evaluate(data, config, {})}
    assert len(findings) == 26 and config["grading_profile"] == data.facts["grading_profile"]
    inventory = findings["DM-SY-01"].measurement
    assert inventory.complete and inventory.numerator == inventory.denominator == 2
    assert len(inventory.targets) == 3 and inventory.targets[-1].status == "excluded"
    assert findings["BI-SY-13"].metric_value == findings["OE-SY-16"].metric_value == .5
    metadata = findings["BI-SY-13"].measurement.targets[0]
    owner = findings["OE-SY-16"].measurement.targets[0]
    assert metadata.status == "compliant" and owner.status == "non_compliant"
    assert "owner" not in metadata.observed and owner.observed["catalog_owner_count"] == 0
    for code in REGISTRY_CHECKS:
        scope = platform_scope(code, findings[code].measurement.complete, config["items"][code], findings[code], data)
        assert scope["P3"] == scope["P5"] == "A"
        assert scope["P1"] == "해당 없음"
    assert platform_breakdown("DM-SY-01", findings["DM-SY-01"], {}, config["items"]["DM-SY-01"])["P3"] == (1, 1)
    crosschecks = {row.se_code: row for row in crosscheck_agent365(data, config)}
    for code in REGISTRY_CHECKS:
        assert crosschecks[code].status == "not_comparable"
        assert crosschecks[code].scope == "Agent 365 공통 등록부 본평가"


@pytest.mark.parametrize("field,value", [("owner_count", None), ("is_blocked", None), ("description_present", None)])
def test_missing_fields_never_become_zero_or_a_success(field, value):
    data, config = collection(), criteria()
    microsoft = data.agent365_packages[1]
    setattr(microsoft, field, value)
    code = {"owner_count": "OE-SY-16", "is_blocked": "BI-SY-10", "description_present": "BI-SY-13"}[field]
    finding = next(finding for finding in evaluate(data, config, {}) if finding.se_code == code)
    assert finding.level == "N/A" and finding.measurement.numerator is finding.measurement.denominator is None
    scope = platform_scope(code, False, config["items"][code], finding, data)
    assert scope["P3"] == "X" and scope["P5"] == "A"


@pytest.mark.parametrize("invalid", ["first_snapshot", "stale_comparison", "missing_current_proof"])
def test_changes_require_two_completed_matching_api_snapshots(invalid):
    data, config = collection(), criteria()
    if invalid == "first_snapshot":
        data.facts["agent365_comparison"] = catalog_changes(data, None)
    elif invalid == "stale_comparison":
        data.facts["agent365_comparison"]["observed_at"] = (NOW - timedelta(minutes=5)).isoformat()
    else:
        data.facts["agent365_comparison"]["observed_package_ids"] = []
    targets = registry_targets(data, "OE-SY-18", config)
    assert all(target.status == "unknown" and target.contribution is None for target in targets[:2])


def test_timestamps_are_metadata_evidence_not_runtime_usage():
    data, config = collection(), criteria()
    target = registry_targets(data, "OT-SY-23", config)[0]
    assert target.status == "compliant" and "active_users_30d" not in target.observed
    data.agent365_packages[0].last_modified_at = None
    assert registry_targets(data, "OT-SY-23", config)[0].status == "unknown"
    data.agent365_packages[0].last_modified_at = NOW + timedelta(hours=1)
    assert registry_targets(data, "OT-SY-23", config)[0].status == "non_compliant"


@pytest.mark.parametrize("reason", ["permission_denied", "license_missing"])
def test_default_assessment_surfaces_registry_access_failures(reason):
    data = collection()
    data.agent365_packages = []
    data.facts["agent365_registry_complete"] = False
    data.issues = [Issue(collector="agent365_registry", target="catalog", reason=reason, detail="Read unavailable")]
    findings = {row.se_code: row for row in evaluate(data, criteria(), {})}
    for code in REGISTRY_CHECKS:
        assert findings[code].reason == reason and findings[code].level == "N/A"
        assert findings[code].measurement.numerator is findings[code].measurement.denominator is None


def test_default_profile_is_self_contained_and_validates_common_checks():
    current = load_criteria()
    assert current["grading_profile"] == "agent365_registry" and "extends" not in current
    assert len(current["items"]) == 26 and len(current["report_items"]) == 13
    assert current["items"]["DM-SY-01"]["registry_check"] == "inventory"
    invalid = deepcopy(current)
    invalid["items"]["DM-SY-01"]["registry_check"] = "unsupported"
    with pytest.raises(ValueError, match="정의"):
        evaluate(collection(), invalid, {})


def test_report_uses_current_labels_api_time_and_real_platform_breakdown(tmp_path):
    data, config = collection(), criteria()
    data.collected_at = NOW - timedelta(hours=3)
    findings = evaluate(data, config, {})
    path = tmp_path / "registry.xlsx"
    write_workbook(data, findings, path)
    book = load_workbook(path)
    assert book[RAW]["D5"].value == config["items"]["DM-SY-01"]["title"]
    assert book[RAW]["F5"].value == book[RAW]["F6"].value == 2
    assert book[RAW]["I5"].value == NOW.replace(tzinfo=None) + timedelta(hours=9)
    assert "Agent 365" in book[RAW]["H5"].value and "Power Platform" not in book[RAW]["H5"].value
    assert book[MATRIX]["E8"].value == "해당 없음" and book[MATRIX]["G8"].value == book[MATRIX]["I8"].value == "A"
    assert "환경 공통" not in book[MATRIX]["Q8"].value
    metrics = metrics_by_key(data, findings, "live")
    assert metrics["criteria.profile"].value == "agent365_registry"
    assert metrics["se.DM-SY-01"].value == 1
    story = DeckData(read_assessment(path), metrics, data)
    assert story.label("BI-SY-13") == "설명·실행 지침"
    assert "1/2" in story.fact("BI-SY-13") and "담당자" not in story.fact("BI-SY-13")
