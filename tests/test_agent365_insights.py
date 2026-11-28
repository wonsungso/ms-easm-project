from datetime import UTC, datetime, timedelta

import pytest

from easm_agent.agent365_insights import (
    PORTAL_URL,
    catalog_changes,
    connection_groups,
    read_connections,
    source_duplicates,
)
from easm_agent.azure import EvidenceStore
from easm_agent.models import Agent365Package, Collection, ConnectedAgentMetadata

NOW = datetime(2026, 11, 27, tzinfo=UTC)


def snapshot(packages):
    return Collection(collected_at=NOW, agent365_packages=packages, facts={
        "agent365_tenant_id": "test-tenant", "agent365_registry_complete": True,
    })


def package(identifier, source="a", connection="b"):
    return Agent365Package(package_id=identifier, platform="AmazonBedrock", version="1",
                           connected_metadata=ConnectedAgentMetadata(
                               source_agent_id_sha256=source * 64, connection_id_sha256=connection * 64))


def test_source_duplicates_cross_connections_and_unknown_identity_counts():
    data = snapshot([package("one"), package("two", connection="c"), package("three", source="d")])
    assert len(source_duplicates(data)) == 1
    assert len(source_duplicates(data)[0]["connection_ids_sha256"]) == 2
    groups = connection_groups(data)
    assert groups[0]["registered_packages"] == 2 and groups[0]["unique_source_ids"] == 2
    data.agent365_packages[0].connected_metadata.source_agent_id_sha256 = None
    assert connection_groups(data)[0]["unique_source_ids"] is None


def test_snapshot_diff_distinguishes_configuration_and_observation_changes():
    previous = snapshot([package("same"), package("gone")])
    current = snapshot([package("same"), package("new")])
    current.agent365_packages[0].version = "2"
    current.agent365_packages[0].connected_metadata.region = "ap-northeast-1"
    result = catalog_changes(current, previous)
    assert result["status"] == "compared"
    assert {row["kind"] for row in result["changes"]} == {
        "added_to_catalog", "absent_from_catalog", "field_changed", "field_observation_changed",
    }
    current.facts["agent365_registry_complete"] = False
    assert catalog_changes(current, previous)["status"] == "not_comparable"
    current.facts["agent365_registry_complete"] = True
    current.facts["agent365_tenant_id"] = "another-tenant"
    assert catalog_changes(current, previous)["status"] == "not_comparable"


def test_connection_screen_evidence_checks_tenant_time_and_never_becomes_api_evidence(tmp_path):
    import json

    payload = {
        "schema_version": 1, "source_type": "official_admin_portal_read", "approved": True,
        "tenant_verified": True, "tenant_id": "test-tenant", "observed_at": NOW.isoformat(),
        "source_url": PORTAL_URL, "connections": [{
            "platform": "AmazonBedrock", "connection_label_sha256": "a" * 64,
            "status": "Healthy", "synchronized_count": 2,
        }],
    }
    path = tmp_path / "connections.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    store = EvidenceStore(tmp_path / "evidence", NOW)
    assert read_connections(path, "test-tenant", store, NOW)[0]["collection_method"] == "E"
    with pytest.raises(ValueError, match="테넌트"):
        read_connections(path, "other", store, NOW)
    with pytest.raises(ValueError, match="24시간"):
        read_connections(path, "test-tenant", store, NOW + timedelta(days=2))
