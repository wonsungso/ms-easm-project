from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from demo.agents import agent_revision
from demo.samples import (
    STUDIO_SAMPLES,
    SampleConfig,
    configuration,
    studio_samples,
    wait_for_studio_inventory,
)


def config(tmp_path: Path) -> SampleConfig:
    return SampleConfig(
        tenant_id="tenant", project_id="/subscriptions/sub/providers/ai/account/projects/project",
        project_endpoint="https://example.services.ai.azure.com/api/projects/project",
        model_deployment="model", studio_environment_id="env", msagent_executable=tmp_path / "msagent.exe",
    )


def test_foundry_revision_tracks_observable_definition_changes():
    entry = {"instructions": "synthetic", "description": "", "model_deployment": "model"}
    assert agent_revision(entry) == agent_revision(dict(entry))
    assert agent_revision(entry) != agent_revision({**entry, "description": "described"})
    assert agent_revision(entry) != agent_revision({**entry, "model_deployment": "other"})
    assert agent_revision({"instructions": "base"}) == "chatbot-v2"


def test_configuration_rejects_wrong_administrator_before_writing(tmp_path: Path):
    state = tmp_path / ".easm-agent"
    state.mkdir()
    (state / "setup.json").write_text('{"tenant_id":"approved"}', encoding="utf-8")
    cli = Mock()
    cli.run.return_value = {"tenantId": "other"}
    target = tmp_path / "config.json"
    with pytest.raises(RuntimeError, match="테넌트"):
        configuration(target, tmp_path, cli)
    assert not target.exists()


def test_existing_studio_receipts_reuse_identity_instead_of_creating_duplicate_agents(tmp_path: Path):
    import json

    directory = tmp_path / "receipts"
    directory.mkdir()
    identifiers = {
        spec["id"]: f"00000000-0000-4000-8000-{index:012d}"
        for index, spec in enumerate(STUDIO_SAMPLES, 1)
    }
    for spec in STUDIO_SAMPLES:
        (directory / ("studio-" + spec["id"] + ".json")).write_text(json.dumps({
            "local_agent_id": identifiers[spec["id"]], "deployment_id": identifiers[spec["id"]],
            "environment_id": "env", "schema_name": "easm_sample_" + spec["id"] + "_lab",
        }), encoding="utf-8")
    calls = []
    cli = MagicMock()

    def deploy(root, configuration, phase, *args):
        calls.append((phase, args))
        assert phase == "studio_deploy"
        identifier = args[args.index("--agent-id") + 1]
        return {"targetMcsAgentId": identifier, "pushedComponentCount": 0}

    cli.run.side_effect = [
        {"name": spec["name"], "schemaname": "easm_sample_" + spec["id"] + "_lab", "publishedon": "observed"}
        for spec in STUDIO_SAMPLES
    ]
    with patch("demo.samples.studio_command", side_effect=deploy), patch(
        "demo.samples.publish_draft", return_value="observed",
    ):
        result = studio_samples(config(tmp_path), tmp_path, "lab", "https://example.crm.dynamics.com", directory, cli)
    assert {row["agent_id"] for row in result} == set(identifiers.values())
    assert len(calls) == 3


def test_collection_waits_for_the_exact_new_studio_ids(tmp_path: Path):
    observed = Mock(agent_id="new", environment_id="env")
    credential = MagicMock()
    http = Mock()
    with patch("demo.samples.AzureCliCredential", return_value=credential), patch(
        "demo.samples.ReaderHTTP", return_value=http,
    ), patch("demo.samples.DelegatedReaderCredential"), patch(
        "demo.samples.inventory_pages", side_effect=[[], [observed]],
    ) as inventory, patch("demo.samples.time.sleep"):
        wait_for_studio_inventory(config(tmp_path), {"new"})
    assert inventory.call_count == 2
    http.close.assert_called_once()
