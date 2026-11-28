from datetime import UTC, datetime
from pathlib import Path

import pytest

from easm_agent.agent365_grading import connected_targets
from easm_agent.collect_agent365 import read_connected_metadata
from easm_agent.models import Agent365Package, Collection, Settings, load_criteria
from easm_agent.report_excel import write_workbook
from easm_agent.report_integrated import platform_breakdown, platform_scope


def resource_criteria():
    return load_criteria(Settings(criteria_file=Path(__file__).parent / "fixtures" / "resource-criteria.yaml"))


def connected():
    return Collection(
        collected_at=datetime.now(UTC), facts={"agent365_registry_complete": True},
        agent365_packages=[Agent365Package(
            package_id="external-one", platform="AmazonBedrock", version="1.0",
            available_to="allowedForAll", is_blocked=False, owner_count=0,
            evidence_refs=["catalog-ref"],
        )],
    )


def test_known_catalog_zero_is_not_source_ownership_or_activity():
    data = connected()
    targets = connected_targets(data, "BI-SY-13", "owner_record")
    assert targets[0].status == "non_compliant"
    assert targets[0].observed["catalog_owner_count"] == 0
    assert targets[0].observed["subject_unit"] == "synchronized_package"
    activity = connected_targets(data, "OT-SY-23", None)[0]
    assert activity.status == "excluded" and activity.contribution is None
    data.agent365_packages[0].owner_count = None
    assert connected_targets(data, "BI-SY-13", "owner_record")[0].status == "unknown"


def test_version_and_access_record_do_not_infer_original_controls():
    data = connected()
    assert connected_targets(data, "BI-SY-12", "version_record")[0].status == "compliant"
    assert connected_targets(data, "DS-SY-05", "access_record")[0].status == "compliant"
    data.facts["agent365_registry_complete"] = False
    assert connected_targets(data, "DS-SY-05", "access_record")[0].status == "unknown"
    with pytest.raises(ValueError):
        connected_targets(data, "DS-SY-05", "model")


def test_external_records_are_visible_without_26_fabricated_grades(tmp_path):
    from openpyxl import load_workbook

    from easm_agent.evaluation import evaluate

    data = connected()
    findings = evaluate(data, resource_criteria(), {})
    assert len(findings) == 26
    source = next(row for row in findings if row.se_code == "OT-SY-23")
    assert platform_scope("OT-SY-23", False, {}, source, data)["P5"] == "해당 없음"
    from easm_agent.models import AssessmentMeasurement, Finding, TargetAssessment

    record = Finding(
        se_code="BI-SY-12", scope="partial", level="L5", rationale="catalog",
        measurement=AssessmentMeasurement(numerator=1, denominator=1, complete=True, targets=[
            TargetAssessment(subject="external", status="compliant", observed={"platform": "AmazonBedrock"}),
        ]),
    )
    breakdown = platform_breakdown("BI-SY-12", record, {}, resource_criteria()["items"]["BI-SY-12"])
    assert breakdown["P5"] == (1, 1) and breakdown["P3"] == (0, 0)
    path = tmp_path / "report.xlsx"
    write_workbook(data, findings, path)
    book = load_workbook(path)
    assert book["1a_플랫폼 기준"]["F9"].value == 1
    assert book["1a_플랫폼 기준"]["B10"].value == "Snowflake Cortex Agents"
    assert book["1a_플랫폼 기준"]["I9"].value is None
    assert book["2c_수집 매트릭스"]["I30"].value == "해당 없음"


def test_connected_definition_adds_only_supported_measurements():
    import json

    data = connected()
    package = data.agent365_packages[0]
    package.detail_read_completed = True
    package.detail_evidence_refs = ["detail-ref"]
    package.connected_metadata = read_connected_metadata({"elementDetails": [{
        "elementType": "AgentMetadatas",
        "elements": [{"definition": json.dumps({
            "SourceAgentId": "agent-sample",
            "SourceIds": {
                "ConnectionId": "11111111-1111-1111-1111-111111111111",
                "mac.modelInfo": "amazon.nova-lite-v1:0", "mac.region": "ap-northeast-2",
            },
            "Instructions": "private-person@example.com; secret=do-not-save",
        })}],
    }]})
    for code, check in (
        ("DS-SY-04", "source_model_record"),
        ("DP-SY-15", "source_identity_record"),
        ("OE-SY-22", "source_region_record"),
    ):
        target = connected_targets(data, code, check)[0]
        assert target.status == "compliant" and target.evidence_refs == ["detail-ref"]
    assert "private-person" not in package.model_dump_json()
    assert "agent-sample" not in package.model_dump_json()
    assert connected_targets(data, "DS-SY-07", "agent_endpoint_https")[0].status == "excluded"
    package.platform = "SnowflakeAI"
    assert connected_targets(data, "DS-SY-04", "source_model_record")[0].status == "excluded"
    package.detail_read_completed = False
    assert connected_targets(data, "DP-SY-15", "source_identity_record")[0].status == "unknown"


def test_connected_endpoint_denominator_counts_endpoints_not_packages():
    import json

    data = connected()
    package = data.agent365_packages[0]
    package.platform = "SnowflakeAI"
    package.detail_read_completed = True
    package.connected_metadata = read_connected_metadata({"elementDetails": [{
        "elementType": "AgentMetadatas",
        "elements": [{"definition": json.dumps({
            "SourceIds": {},
            "AgentEndpoints": [
                {"EndpointUrl": "https://safe.example/api?token=do-not-save"},
                {"EndpointUrl": "http://other.example/api"},
            ],
        })}],
    }]})
    targets = connected_targets(data, "DS-SY-07", "agent_endpoint_https")
    assert len(targets) == 2
    assert [target.contribution for target in targets] == [1, 0]
    assert len({target.subject for target in targets}) == 2
    assert "do-not-save" not in package.model_dump_json()
    data.facts["agent365_registry_complete"] = False
    assert connected_targets(data, "DS-SY-07", "agent_endpoint_https")[0].status == "unknown"


@pytest.mark.parametrize("definition", ["not json", '{"SourceIds": []}', "{}"])
def test_connected_schema_changes_remain_unknown_without_payload_storage(definition):
    metadata = read_connected_metadata({"elementDetails": [{
        "elementType": "AgentMetadatas", "elements": [{"definition": definition}],
    }]})
    assert metadata.model_identifier is None and metadata.endpoint_https is None
    assert metadata.field_status["source_agent_id_sha256"].reason == "error"


def test_publication_and_source_identity_remain_distinct_from_entra_and_running_state(tmp_path):
    import json

    from openpyxl import load_workbook

    from easm_agent.azure import redact
    from easm_agent.evaluation import evaluate

    data = connected()
    package = data.agent365_packages[0]
    package.detail_read_completed = True
    package.connected_metadata = read_connected_metadata({"elementDetails": [{
        "elementType": "AgentMetadatas", "elements": [{"definition": json.dumps({
            "SourceIds": {"mac.agentId": "source-sample", "mac.version": "1",
                          "mac.externalStatus": "READY", "mac.agentSubType": "AgentCore"},
            "SourceAgentId": "source-sample", "PublishedStatus": "Published",
            "CreatedDateTime": "2026-11-26T01:00:00Z",
            "Instructions": "private instructions", "ManagedBy": "private@example.com",
        })}],
    }]})
    assert package.connected_metadata.published_status == "Published"
    assert package.connected_metadata.content_presence["Instructions_present"] is True
    assert package.connected_metadata.created_at is not None
    serialized = package.model_dump_json()
    assert "private instructions" not in serialized and "private@example.com" not in serialized
    assert "source-sample" not in serialized
    assert Agent365Package.model_validate(redact(package.model_dump(mode="json"))).connected_metadata == package.connected_metadata
    path = tmp_path / "report.xlsx"
    write_workbook(data, evaluate(data, resource_criteria(), {}), path)
    book = load_workbook(path)
    platform = book["1a_플랫폼 기준"]
    assert platform["I9"].value == 1
    assert platform["J9"].value == "미제공" and platform["G9"].value == 1 and platform["H9"].value == 0
    details = book["2b_세부 내역"]
    assert details["H37"].value == "등록·동기화 확인"
    assert details["D37"].value == package.connected_metadata.source_agent_id_sha256
    assert book["2_SE 원천데이터"].max_row == 56
    package.connected_metadata = read_connected_metadata({})
    assert package.connected_metadata.published_status is None
