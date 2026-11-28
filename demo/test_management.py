from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from demo import diagnostics as remote
from demo.agents import agent_revision, agent_tools
from demo.auth import GraphCertificates, TemporaryCertificate
from demo.infrastructure import (
    AdminARM,
    configure_diagnostic_reader,
    deployment_parameters,
    plan,
)
from demo.manage import cleanup_main as cleanup
from demo.manage import lab_config_path, main
from easm_agent.models import load_yaml
from easm_agent.paths import state_path

ROOT = Path(__file__).parents[1]


def test_state_directory_override_requires_an_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert state_path(tmp_path, "demo", "lab.json") == tmp_path / ".easm-agent" / "demo" / "lab.json"
    isolated = tmp_path / "isolated"
    monkeypatch.setenv("EASM_AGENT_STATE_DIR", str(isolated))
    assert state_path(tmp_path, "demo", "lab.json") == isolated / "demo" / "lab.json"
    for invalid in ("", "relative-state"):
        monkeypatch.setenv("EASM_AGENT_STATE_DIR", invalid)
        with pytest.raises(ValueError, match="절대 경로"):
            state_path(tmp_path)


def test_management_uses_isolated_state_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    setup = isolated / "setup.json"
    setup.write_text(json.dumps(setup_values()), encoding="utf-8")
    config = isolated / "config.yaml"
    config.write_text("generation: isolated-run\n", encoding="utf-8")
    monkeypatch.setenv("EASM_AGENT_STATE_DIR", str(isolated))
    monkeypatch.setenv("EASM_AGENT_LAB_CONFIG", str(config))
    with patch("demo.manage.ROOT", tmp_path), patch("demo.manage.plan", return_value={}) as build:
        assert main(["plan"]) == 0
    assert build.call_args.args[1] == {"generation": "isolated-run"}
    assert (isolated / "demo").is_dir()
    assert not (tmp_path / ".easm-agent").exists()
    monkeypatch.setenv("EASM_AGENT_LAB_CONFIG", "relative.yaml")
    with pytest.raises(ValueError, match="절대 경로"):
        lab_config_path(tmp_path)


@pytest.mark.parametrize(
    ("arguments", "fail_command", "expected_code", "expected"),
    [
        ([], "", 1, []),
        (["--apply"], "", 0, [
            "validate --prepare-providers", "deploy --apply", "agents", "saas --apply",
        ]),
        (["--apply", "--collect"], "", 0, [
            "validate --prepare-providers", "deploy --apply", "agents", "saas --apply",
            "collect", "verify",
        ]),
        (["--apply", "--collect"], "-m demo.manage deploy --apply", 9, [
            "validate --prepare-providers", "deploy --apply",
        ]),
        (["--apply", "--collect"], "-m demo.manage saas --apply", 9, [
            "validate --prepare-providers", "deploy --apply", "agents", "saas --apply",
        ]),
    ],
)
def test_demo_shell_keeps_collection_opt_in(
    tmp_path: Path, arguments: list[str], fail_command: str, expected_code: int, expected: list[str],
) -> None:
    bash = shutil.which("bash")
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if git_bash.is_file():
            bash = str(git_bash)
    if not bash:
        pytest.skip("Bash가 설치된 개발 환경에서 실행")
    interpreter = tmp_path / "fake-python.sh"
    interpreter.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$EASM_AGENT_TEST_CALLS"\n'
        'if [[ "$*" == "$EASM_AGENT_TEST_FAILURE" ]]; then exit 9; fi\n'
        'if [[ "$*" == "-m demo.manage collect" ]]; then exit 2; fi\n',
        encoding="utf-8",
    )
    interpreter.chmod(0o700)
    calls = tmp_path / "calls.txt"
    result = subprocess.run(
        [bash, (ROOT / "demo" / "run.sh").as_posix(), *arguments],
        env={
            **os.environ, "EASM_AGENT_PYTHON": interpreter.as_posix(),
            "EASM_AGENT_TEST_CALLS": calls.as_posix(), "EASM_AGENT_TEST_FAILURE": fail_command,
        },
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == expected_code, result.stderr
    recorded = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    commands = {
        "agents": "-m demo.agents --apply",
        "verify": "-m demo.diagnostics verify",
    }
    assert recorded == [commands.get(value, "-m demo.manage " + value) for value in expected]


def test_management_cli_routes_cleanup_without_deployment() -> None:
    with patch("demo.manage.cleanup_main", return_value=0) as remove:
        assert main(["cleanup", "--apply", "--confirm-lab-id", "owned"]) == 0
    assert remove.call_args.args[0][-3:] == ["--apply", "--confirm-lab-id", "owned"]


@pytest.mark.parametrize("enabled", [False, True])
def test_demo_collect_passes_optional_agent365_registry_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool,
) -> None:
    from demo.manage import collect_live

    monkeypatch.delenv("EASM_AGENT_STATE_DIR", raising=False)
    lab = {
        "project_id": "project", "project_endpoint": "https://example.test",
        "model": "model", "model_version": "1",
    }
    with patch("demo.manage.ROOT", tmp_path), patch(
        "demo.manage.TemporaryCertificate", side_effect=RuntimeError("stop before authentication"),
    ), pytest.raises(RuntimeError, match="stop before authentication"):
        collect_live(setup_values(), lab, Mock(), {"agent365_registry": enabled})
    settings = load_yaml(tmp_path / ".easm-agent" / "demo" / "lab-collection.yaml")
    assert settings["agent365_registry"] is enabled


def test_demo_collect_rejects_non_boolean_agent365_option(tmp_path: Path) -> None:
    from demo.manage import collect_live

    with patch("demo.manage.ROOT", tmp_path), pytest.raises(ValueError, match="agent365_registry"):
        collect_live(setup_values(), {}, Mock(), {"agent365_registry": "true"})


def test_evaluation_submits_all_three_synthetic_samples(tmp_path: Path) -> None:
    from demo.agents import TEST_CASES, evaluate_agent

    project = MagicMock()
    client = project.get_openai_client.return_value.__enter__.return_value
    client.evals.create.return_value.id = "evaluation"
    client.evals.runs.create.return_value.id = "run"
    run = client.evals.runs.retrieve.return_value
    run.status = "completed"
    run.model_dump.return_value = {"status": "completed"}
    item = Mock()
    item.model_dump.return_value = {"status": "pass"}
    client.evals.runs.output_items.list.return_value = [item]
    with patch("demo.agents.sample_response", side_effect=[
        Mock(status="completed", output_text=answer) for _, answer in TEST_CASES
    ]):
        result = evaluate_agent(project, {"id": "synthetic-agent"}, "1", tmp_path)
    samples = client.evals.runs.create.call_args.kwargs["data_source"]["source"]["content"]
    assert len(samples) == 3
    assert [row["item"]["query"] for row in samples] == [query for query, _ in TEST_CASES]
    assert result["samples"] == samples and result["status"] == "completed"


def test_administrator_sample_waits_for_model_quota() -> None:
    import httpx
    from openai import RateLimitError

    from demo.agents import sample_response

    response = httpx.Response(
        429, request=httpx.Request("POST", "https://example.test/responses"),
        headers={"retry-after": "5"},
    )
    client = Mock()
    client.responses.create.side_effect = [RateLimitError("fixture", response=response, body=None), "real-response"]
    with patch("demo.agents.time.sleep") as sleep:
        assert sample_response(client, input="synthetic", max_output_tokens=32, store=False) == "real-response"
    sleep.assert_called_once_with(5)
    assert client.responses.create.call_count == 2


def test_expected_agent_count_uses_foundry_receipts_not_removed_candidates() -> None:
    from demo.infrastructure import expected_agent_count

    assert expected_agent_count({}) == 1
    assert expected_agent_count({"expected_agent_count": 10, "chatbot_agents": [
        {"agent_id": str(index)} for index in range(8)
    ]}) == 8
    with pytest.raises(ValueError, match="영수증"):
        expected_agent_count({"chatbot_agents": []})








class FakeCLI:
    def __init__(self) -> None:
        self.ids = {"existing-public-certificate"}
        self.calls: list[tuple[str, ...]] = []

    def certificates(self) -> list[dict]:
        self.calls.append(("list",))
        return [{"keyId": key} for key in self.ids]

    def add(self, certificate: object, key_id: str, start: object, end: object) -> None:
        self.calls.append(("add", key_id))
        self.ids.add(key_id)

    def remove(self, key_id: str) -> None:
        self.calls.append(("remove", key_id))
        self.ids.remove(key_id)

    def close(self) -> None:
        pass


def setup_values() -> dict:
    return {
        "tenant_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "client_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "principal_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "subscription_ids": [
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
            "33333333-3333-4333-8333-333333333333",
        ],
    }


def test_certificate_cleanup_preserves_existing_keys_and_parent_environment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path / "temporary"
    directory.mkdir()
    cli = FakeCLI()
    with patch("demo.auth.tempfile.mkdtemp", return_value=str(directory)), patch(
        "demo.auth.restrict_directory",
    ), TemporaryCertificate(setup_values(), registry=cli) as environment:
        private_file = Path(environment["AZURE_CLIENT_CERTIFICATE_PATH"])
        assert private_file.is_file()
        assert environment["AZURE_CLIENT_ID"] == setup_values()["client_id"]
        assert "AZURE_CLIENT_SECRET" not in environment
        assert len(cli.ids) == 2 and "existing-public-certificate" in cli.ids
    assert not directory.exists()
    assert cli.ids == {"existing-public-certificate"}
    assert any(call[0] == "remove" and call[1] != "existing-public-certificate" for call in cli.calls)
    assert "PRIVATE KEY" not in capsys.readouterr().out


def test_certificate_cleanup_also_runs_after_collection_failure(tmp_path: Path) -> None:
    directory = tmp_path / "temporary"
    directory.mkdir()
    cli = FakeCLI()
    with patch("demo.auth.tempfile.mkdtemp", return_value=str(directory)), patch(
        "demo.auth.restrict_directory",
    ), pytest.raises(ValueError, match="fixture collection failure"):
        with TemporaryCertificate(setup_values(), registry=cli):
            raise ValueError("fixture collection failure")
    assert cli.ids == {"existing-public-certificate"}
    assert not directory.exists()


def test_acl_failure_does_not_register_any_credential(tmp_path: Path) -> None:
    directory = tmp_path / "temporary"
    directory.mkdir()
    cli = FakeCLI()
    with patch("demo.auth.tempfile.mkdtemp", return_value=str(directory)), patch(
        "demo.auth.restrict_directory", side_effect=RuntimeError("ACL failure"),
    ), pytest.raises(RuntimeError, match="ACL failure"):
        with TemporaryCertificate(setup_values(), registry=cli):
            pytest.fail("must not enter")
    assert not cli.calls
    assert not directory.exists()


def test_lab_plan_deploys_foundry_only_and_keeps_collection_scope() -> None:
    options = load_yaml(ROOT / "demo" / "config.yaml")
    result = plan(setup_values(), options)
    assert len(result["groups"]) == 1
    assert result["groups"][0]["subscription_id"] == setup_values()["subscription_ids"][0]
    assert result["region"] == options["region"]
    assert result["after_run"] == "retain"
    assert result["capacity"] == 1
    assert result["budget_usd"] == 100
    assert "PRIVATE KEY" not in json.dumps(result)


def test_demo_plan_does_not_require_diagnostic_identity() -> None:
    setup = setup_values()
    setup.pop("client_id")
    setup.pop("principal_id")
    setup["account_name"] = "easmagent-diagnostic"
    options = load_yaml(ROOT / "demo" / "config.yaml")
    result = plan(setup, options)
    assert result == plan(setup, options)
    assert result == plan({**setup, "client_id": setup_values()["client_id"],
                           "principal_id": setup_values()["principal_id"]}, options)
    assert result["groups"][0]["subscription_id"] == setup["subscription_ids"][0]
    with patch("demo.infrastructure.ensure_assignment") as assign:
        from unittest.mock import Mock

        cli = Mock()
        configure_diagnostic_reader(cli, setup, "project")
        cli.run.assert_not_called()
        assign.assert_not_called()


def test_configured_diagnostic_reader_still_validates_role_and_assigns() -> None:
    from unittest.mock import Mock

    cli = Mock()
    cli.run.return_value = [{"name": "reader-role"}]
    setup = setup_values()
    with patch("demo.infrastructure.verify_custom_role") as verify, patch(
        "demo.infrastructure.ensure_assignment",
    ) as assign:
        configure_diagnostic_reader(cli, setup, "project")
    verify.assert_called_once()
    assign.assert_called_once_with(cli, setup["principal_id"], "ServicePrincipal", "project", "reader-role")


def test_fresh_demo_expansion_creates_receipt_parents(tmp_path: Path) -> None:
    from unittest.mock import Mock

    from demo.agents import expand

    demo = tmp_path / ".easm-agent" / "demo"
    demo.mkdir(parents=True)
    (demo.parent / "setup.json").write_text(json.dumps(setup_values()), encoding="utf-8")
    (demo / "lab.json").write_text(json.dumps({"lab_id": "fresh-demo"}), encoding="utf-8")
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "catalog.json").write_text("[]", encoding="utf-8")
    cli = Mock()
    cli.run.return_value = {"tenantId": setup_values()["tenant_id"]}
    with patch("demo.agents.ROOT", tmp_path), patch("demo.agents.AzureCLI", return_value=cli), patch(
        "demo.agents.DefaultAzureCredential", side_effect=RuntimeError("stop before cloud"),
    ), pytest.raises(RuntimeError, match="stop before cloud"):
        expand()
    assert (demo / "chatbot-expansion" / "fresh-demo").is_dir()


def test_new_generation_changes_resource_names_without_changing_approved_scope() -> None:
    options = load_yaml(ROOT / "demo" / "config.yaml")
    original = plan(setup_values(), {key: value for key, value in options.items() if key != "generation"})
    rebuilt = plan(setup_values(), {**options, "generation": "new-run"})
    assert original["lab_id"] != rebuilt["lab_id"]
    assert original["account_name"] != rebuilt["account_name"]
    assert original["groups"] == rebuilt["groups"]
    assert original["region"] == rebuilt["region"]


def test_administrator_arm_blocks_writes_outside_sample_groups() -> None:
    arm = AdminARM(None, ["/subscriptions/fixture/resourceGroups/owned"])
    with pytest.raises(ValueError, match="승인된 리소스 그룹 밖"):
        arm.request("PUT", "/subscriptions/fixture/resourceGroups/foreign/providers/Microsoft.CognitiveServices/accounts/x",
                    "2025-06-01", {})


def test_lab_cli_plan_does_not_construct_azure_cli(tmp_path: Path) -> None:
    settings = tmp_path / "setup.json"
    settings.write_text(json.dumps(setup_values()), encoding="utf-8")
    with patch("demo.manage.AzureCLI", side_effect=AssertionError("no Azure calls")):
        assert main(["plan", "--setup-file", str(settings)]) == 0


def test_cleanup_rejects_missing_confirmation_before_azure(tmp_path: Path) -> None:
    settings = tmp_path / "setup.json"
    settings.write_text(json.dumps(setup_values()), encoding="utf-8")
    with patch("demo.manage.AzureCLI", side_effect=AssertionError("no Azure calls")), pytest.raises(
        ValueError, match="confirm-lab-id",
    ):
        cleanup(["--setup-file", str(settings), "--apply"])


def test_cleanup_dry_run_does_not_delete_owned_groups(tmp_path: Path) -> None:
    from unittest.mock import Mock

    setup = setup_values()
    settings = tmp_path / "setup.json"
    settings.write_text(json.dumps(setup), encoding="utf-8")
    lab = plan(setup, load_yaml(ROOT / "demo" / "config.yaml"))
    cli = Mock()
    cli.run.side_effect = [
        {"tenantId": setup["tenant_id"]},
        *[[{"name": group["name"], "tags": {"easmagent-lab": lab["lab_id"]}}] for group in lab["groups"]],
    ]
    with patch("demo.manage.AzureCLI", return_value=cli):
        assert cleanup(["--setup-file", str(settings)]) == 0
    assert all(call.args[:2] != ("group", "delete") for call in cli.run.call_args_list)


def test_graph_login_setup_without_diagnostic_sp_cannot_modify_certificates() -> None:
    with patch("demo.auth.DefaultAzureCredential"):
        registry = GraphCertificates()
        with patch.object(registry, "request") as request, pytest.raises(ValueError, match="client_id"):
            registry.certificates()
        request.assert_not_called()
        registry.close()


def test_graph_certificate_operations_preserve_all_existing_keys() -> None:
    original = {
        "keyId": "11111111-1111-4111-8111-111111111111",
        "key": "public-existing-certificate", "type": "AsymmetricX509Cert", "usage": "Verify",
    }
    keys = [original.copy()]
    methods = []

    def request(method: str, url: str, **kwargs: object) -> Mock:
        methods.append(method)
        if method == "PATCH":
            keys[:] = kwargs["json"]["keyCredentials"]
            return Mock(status_code=204, content=b"")
        payload = {"value": [{"id": "22222222-2222-4222-8222-222222222222"}]} if url.endswith("/applications") else {
            "keyCredentials": [entry.copy() for entry in keys],
        }
        return Mock(status_code=200, content=b"json", json=Mock(return_value=payload))

    with patch("demo.auth.DefaultAzureCredential"), patch(
        "demo.auth.requests.request", side_effect=request,
    ):
        registry = GraphCertificates("33333333-3333-4333-8333-333333333333")
        certificate = Mock()
        certificate.public_bytes.return_value = b"public-der"
        now = datetime.now(UTC)
        added = "44444444-4444-4444-8444-444444444444"
        registry.add(certificate, added, now, now + timedelta(hours=4))
        assert keys[0] == original
        assert keys[1]["keyId"] == added
        registry.remove(added)
        assert keys == [original]
        assert methods.count("PATCH") == 2
        registry.close()


def test_graph_does_not_replace_unknown_existing_certificate_content() -> None:
    with patch("demo.auth.DefaultAzureCredential"):
        registry = GraphCertificates("33333333-3333-4333-8333-333333333333")
        registry.object_id = "22222222-2222-4222-8222-222222222222"
        with patch.object(registry, "request") as request, pytest.raises(RuntimeError, match="보존할 수 없어"):
            registry.replace([{"keyId": "existing", "key": None}])
        request.assert_not_called()
        registry.close()


def test_codespace_name_cannot_inject_shell() -> None:
    with pytest.raises(ValueError):
        remote.run("name;rm something")


def test_remote_key_is_removed_on_collection_failure(tmp_path: Path) -> None:
    output = tmp_path / ".easm-agent"
    output.mkdir()
    (output / "setup.json").write_text(json.dumps({
        "tenant_id": "tenant", "client_id": "client", "principal_id": "reader",
        "subscription_ids": ["subscription"],
    }), encoding="utf-8")
    (output / "demo").mkdir()
    (output / "demo" / "lab.json").write_text(json.dumps({
        "project_id": "project", "project_endpoint": "https://example.test",
        "model": "model", "model_version": "1",
    }), encoding="utf-8")
    commands = []

    def cli(*args, **kwargs):
        commands.append(args)
        if "mktemp" in args[-1]:
            return subprocess.CompletedProcess(args, 0, "/home/vscode/easm-agent-auth-12345678\n", "")
        if "EASM_COLLECTION_EXIT" in args[-1]:
            raise RuntimeError("fixture remote failure")
        return subprocess.CompletedProcess(args, 0, "", "")

    with patch.object(remote, "ROOT", tmp_path), patch.object(remote, "gh", side_effect=cli), patch.object(
        remote, "TemporaryCertificate",
    ) as certificate:
        certificate.return_value.__enter__.return_value = {"AZURE_CLIENT_CERTIFICATE_PATH": "fixture.pem"}
        with pytest.raises(RuntimeError, match="fixture remote failure"):
            remote.run("approved-codespace")
        certificate.return_value.__exit__.assert_called_once()
    assert any("rm -f /home/vscode/easm-agent-auth-12345678/credential.pem" in cmd[-1] for cmd in commands)


@pytest.mark.parametrize("run_folder", ["", "20261105T010203456789Z/"])
def test_codespace_download_uses_validated_ssh_stream(tmp_path: Path, run_folder: str) -> None:
    output = tmp_path / ".easm-agent"
    output.mkdir()
    (output / "setup.json").write_text(json.dumps({
        "tenant_id": "tenant", "client_id": "client", "principal_id": "reader",
        "subscription_ids": ["subscription"],
    }), encoding="utf-8")
    (output / "demo").mkdir()
    (output / "demo" / "lab.json").write_text(json.dumps({
        "project_id": "project", "project_endpoint": "https://example.test",
        "model": "model", "model_version": "1",
    }), encoding="utf-8")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
    raw = json.dumps({"schema_version": 1}).encode()
    name = "report-20261104T000000Z.xlsx"
    raw_file = "raw-data-20261104T000000Z.json"
    commands = []

    def cli(*args, **kwargs):
        commands.append(args)
        command = args[-1]
        text = ""
        if "mktemp" in command:
            text = "/home/vscode/easm-agent-auth-12345678\n"
        elif "EASM_COLLECTION_EXIT" in command:
            text = "EASM_COLLECTION_EXIT=2\n"
        elif "latest_raw" in command:
            base = "output/" + run_folder
            text = json.dumps([base + name, base + raw_file])
        elif command.startswith("base64 ") and command.endswith(raw_file):
            text = base64.b64encode(raw).decode()
        elif command.startswith("base64 "):
            text = base64.b64encode(buffer.getvalue()).decode()
        return subprocess.CompletedProcess(args, 0, text, "")

    with patch.object(remote, "ROOT", tmp_path), patch.object(remote, "gh", side_effect=cli), patch.object(
        remote, "TemporaryCertificate",
    ) as certificate:
        certificate.return_value.__enter__.return_value = {"AZURE_CLIENT_CERTIFICATE_PATH": "fixture.pem"}
        remote.run("approved-codespace")
    destination = tmp_path / "output" / run_folder.rstrip("/")
    assert (destination / name).read_bytes() == buffer.getvalue()
    assert set(path.name for path in destination.iterdir()) == {name, raw_file}
    proof = json.loads((output / "demo" / "codespace-e2e-verification.json").read_text(encoding="utf-8"))
    assert proof["collection_exit_code"] == 2 and proof["remote_private_key_cleaned"]
    assert any(command[-1].startswith("base64 ") for command in commands)






def test_demo_configuration_yields_mixed_model_allowlist_results() -> None:
    options = load_yaml(ROOT / "demo" / "config.yaml")
    main = (options["model"], options["model_version"])
    extra = options["extra_models"]
    assert extra and all((item["model"], item["version"]) != main for item in extra)
    lab = plan({
        "tenant_id": "t", "account_name": "fixture",
        "subscription_ids": ["11111111-1111-4111-8111-111111111111"] * 3,
    }, options)
    parameters = dict(item.split("=", 1) for item in deployment_parameters(lab, 0))
    assert json.loads(parameters["extraModels"]) == extra
    assert "collect_entra" not in options


def read_bicep(name: str) -> str:
    return (ROOT / "demo" / name).read_text(encoding="utf-8")


def test_foundry_template_attaches_custom_rai_policy_only_to_primary_deployment() -> None:
    text = read_bicep("foundry.bicep")
    assert "Microsoft.CognitiveServices/accounts/raiPolicies@2024-10-01" in text
    assert "basePolicyName: 'Microsoft.DefaultV2'" in text and "contentFilters: [" in text
    model_block = text.split("resource model ", 1)[1].split("@batchSize(1)", 1)[0]
    assert "raiPolicyName: raiPolicyName" in model_block
    assert "    raiPolicy\n" in model_block
    extra_block = text.split("@batchSize(1)", 1)[1].split("resource workspace", 1)[0]
    assert "raiPolicyName" not in extra_block
    assert "\n  dependsOn: [\n    model\n  ]" in extra_block


def test_monitor_template_uses_safe_receiver_and_verified_metrics() -> None:
    text = read_bicep("monitor.bicep")
    assert "Microsoft.Insights/actionGroups@2023-01-01" in text
    assert "Microsoft.Insights/metricAlerts@2018-03-01" in text
    for forbidden in ("emailReceivers", "smsReceivers", "voiceReceivers", "webhookReceivers"):
        assert forbidden not in text
    assert "armRoleReceivers" in text and "43d0d8ad-25c7-4714-9337-8ba259a9fe05" in text
    assert "useCommonAlertSchema: true" in text
    assert "AzureOpenAIAvailabilityRate" in text and "Microsoft.CognitiveServices/accounts" in text
    assert "Http5xx" not in text and "Microsoft.Web/sites" not in text
    assert "actionGroupId: actionGroup.id" in text


def test_policy_template_is_audit_only_builtin_assignment() -> None:
    text = read_bicep("policy.bicep")
    assert "0725b4dd-7e76-479c-a735-68e7ee23d5ca" in text
    assert "enforcementMode: 'DoNotEnforce'" in text
    assert "value: 'Audit'" in text and "[DEMO]" in text


def test_main_template_wires_foundry_monitor_and_policy() -> None:
    text = read_bicep("main.bicep")
    monitor = text.split("module monitor ", 1)[1].split("module policy ", 1)[0]
    assert "if (" not in monitor.split("{", 1)[0] and "scope: group" in monitor
    policy_header = text.split("module policy ", 1)[1].split("{", 1)[0]
    assert "if (" not in policy_header
    assert "module host" not in text
    parameters = dict(item.split("=", 1) for item in deployment_parameters(
        plan(setup_values(), load_yaml(ROOT / "demo" / "config.yaml")), 0,
    ))
    assert not {"workload", "hostName", "modelResourceId"} & parameters.keys()


def test_agent_tools_map_catalog_to_sdk_models() -> None:
    catalog = json.loads((ROOT / "demo" / "catalog.json").read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in catalog}
    function_tool = agent_tools(by_id["privacy-helper"])
    mcp_tool = agent_tools(by_id["onboarding-helper"])
    assert function_tool and function_tool[0].type == "function" and function_tool[0].strict is True
    assert function_tool[0].parameters["required"] == ["text"]
    assert mcp_tool and mcp_tool[0].type == "mcp"
    assert mcp_tool[0].server_label == "mslearn"
    assert mcp_tool[0].server_url == "https://learn.microsoft.com/api/mcp"
    assert mcp_tool[0].require_approval == "always"
    assert agent_tools(by_id["policy-guide"]) is None
    assert agent_revision(by_id["privacy-helper"]) != agent_revision(by_id["policy-guide"])
    with pytest.raises(ValueError):
        agent_tools({"agent_tool": {"type": "unknown"}})
