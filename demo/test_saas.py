from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from demo import manage, saas

TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ENVIRONMENT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
AGENT = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
CLOUD = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
DEPLOYMENT = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
ROOT = Path(__file__).resolve().parents[1]


def options() -> dict:
    return {"saas": {
        "enabled": True, "authoring_method": "code_first",
        "tenant_id": TENANT, "environment_id": ENVIRONMENT,
        "publisher": {
            "name": "Synthetic Publisher", "website": "https://publisher.contoso.com",
            "privacy": "https://publisher.contoso.com/privacy",
            "terms": "https://publisher.contoso.com/terms", "studio_prefix": "easm",
        },
        "licenses_confirmed": {
            "m365_copilot": True, "copilot_studio": True, "existing_capacity": True,
        },
    }}


def ready() -> saas.SaaSReadiness:
    return saas.SaaSReadiness(
        settings=saas.SaaSSettings.model_validate(options()["saas"]),
        dataverse_url="https://synthetic.crm.dynamics.com",
        organization_id=CLOUD, checked_at="2026-01-01T00:00:00Z",
    )


def tools_for_preflight() -> Mock:
    tools = Mock()
    tools.toolkit_tenant.return_value = ready().settings.tenant_id
    tools.msagent = Path("native.exe")
    tools.run.side_effect = ["v26.13.0\n", saas.MSAGENT_VERSION]
    tools.mcs.side_effect = [
        {"signedIn": True, "tenantId": TENANT},
        {"environments": [{"environmentId": ENVIRONMENT, "tenantId": TENANT}]},
    ]
    tools.az.return_value = {"tenantId": TENANT}
    tools.get.side_effect = [
        {"value": [{
            "id": ENVIRONMENT, "tenantId": TENANT, "url": ready().dataverse_url,
            "dataverseId": CLOUD,
        }]},
        {"OrganizationId": CLOUD, "UserId": AGENT},
    ]
    return tools


@pytest.mark.parametrize("case", ["missing", "license", "tenant", "environment"])
def test_invalid_preflight_cannot_reach_azure_or_cli(tmp_path: Path, case: str) -> None:
    configuration = options()
    if case == "missing":
        configuration = yaml.safe_load((ROOT / "demo" / "config.yaml").read_text(encoding="utf-8"))
    elif case == "license":
        configuration["saas"]["licenses_confirmed"]["copilot_studio"] = False
    elif case == "tenant":
        configuration["saas"]["tenant_id"] = CLOUD
    else:
        configuration["saas"]["environment_id"] = ""
    azure = Mock()
    with patch("demo.saas.CLITools") as tools, pytest.raises(saas.SaaSError):
        manage.validate(azure, {"tenant_id": TENANT}, configuration, tmp_path, True)
    tools.assert_not_called()
    azure.run.assert_not_called()
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("failure", ["toolkit_tenant", "studio_auth", "env", "dataverse"])
def test_auth_environment_and_database_fail_before_writes(tmp_path: Path, failure: str) -> None:
    tools = tools_for_preflight()
    if failure == "toolkit_tenant":
        tools.toolkit_tenant.return_value = ready().organization_id
    elif failure == "studio_auth":
        tools.mcs.side_effect = [{"signedIn": False, "tenantId": None}]
    elif failure == "env":
        tools.mcs.side_effect = [
            {"signedIn": True, "tenantId": TENANT},
            {"environments": [{"environmentId": ENVIRONMENT, "tenantId": CLOUD}]},
        ]
    else:
        tools.get.side_effect = [{"value": [{
            "id": ENVIRONMENT, "tenantId": TENANT,
        }]}]
    azure = Mock()
    with patch("demo.saas.CLITools", return_value=tools), pytest.raises(saas.SaaSError):
        manage.validate(azure, {"tenant_id": TENANT}, options(), tmp_path, True)
    azure.run.assert_not_called()
    assert all(call.args[1] in ("auth", "env") for call in tools.mcs.call_args_list)


def test_prepared_environment_is_actually_read_not_assumed(tmp_path: Path) -> None:
    tools = tools_for_preflight()
    with patch("demo.saas.CLITools", return_value=tools):
        result = saas.preflight_saas(options(), {"tenant_id": TENANT}, tmp_path)
    assert result and str(result.organization_id) == CLOUD
    version_call = next(call for call in tools.run.call_args_list if call.args[0] == "msagent_version")
    assert version_call.args[1] == [str(tools.msagent), "--version"]
    assert tools.get.call_args_list[0].args[1] == (
        "https://api.powerplatform.com/environmentmanagement/environments?api-version=2024-10-01"
    )
    assert tools.get.call_args_list[-1].args[1].endswith("/api/data/v9.2/WhoAmI")


@pytest.mark.parametrize("problem", ["next_page", "wrong_organization", "wrong_tenant", "missing_dataverse_id"])
def test_environment_preflight_rejects_incomplete_or_inconsistent_results(tmp_path: Path, problem: str) -> None:
    tools = tools_for_preflight()
    environment = {
        "id": ENVIRONMENT, "tenantId": TENANT, "url": ready().dataverse_url,
        "dataverseId": CLOUD,
    }
    if problem == "next_page":
        tools.get.side_effect = [{"value": [environment], "@odata.nextlink": "next-page"}]
    elif problem == "wrong_organization":
        tools.get.side_effect = [
            {"value": [environment]}, {"OrganizationId": AGENT, "UserId": AGENT},
        ]
    else:
        environment["tenantId" if problem == "wrong_tenant" else "dataverseId"] = (
            CLOUD if problem == "wrong_tenant" else ""
        )
        tools.get.side_effect = [{"value": [environment]}]
    with patch("demo.saas.CLITools", return_value=tools), pytest.raises(saas.SaaSError):
        saas.preflight_saas(options(), {"tenant_id": TENANT}, tmp_path)


def test_legacy_options_keep_existing_azure_path(tmp_path: Path) -> None:
    with patch("demo.saas.CLITools") as tools:
        assert saas.preflight_saas({}, {}, tmp_path) is None
        assert saas.deploy_saas({}, {}, {}, tmp_path) is None
    tools.assert_not_called()


def test_saas_failure_reports_safe_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("EASM_AGENT_STATE_DIR", str(tmp_path / "state"))
    setup = tmp_path / "setup.json"
    setup.write_text("{}", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    with patch("demo.manage.AzureCLI"), patch(
        "demo.manage.validate", side_effect=saas.SaaSError("studio_deploy", "안전한 오류 설명"),
    ):
        assert manage.main(["validate", "--setup-file", str(setup), "--lab-config", str(config)]) == 1
    assert "studio_deploy" in capsys.readouterr().err


def test_official_scaffold_is_personal_and_has_no_external_capabilities(tmp_path: Path) -> None:
    project = tmp_path / "private"
    saas.prepare_toolkit(ROOT, project, ready().settings.publisher)
    manifest = json.loads((project / "appPackage" / "manifest.json").read_text(encoding="utf-8"))
    agent = json.loads(
        (project / "appPackage" / "declarativeAgent.json").read_text(encoding="utf-8"),
    )
    assert manifest["developer"]["name"] == "Synthetic Publisher"
    assert manifest["permissions"] == []
    assert not agent.get("capabilities") and not agent.get("actions")
    for path in (project / "env").glob(".env.*"):
        assert "AGENT_SCOPE=personal" in path.read_text(encoding="utf-8")
    lifecycle = yaml.safe_load((project / "m365agents.yml").read_text(encoding="utf-8"))
    assert not lifecycle["publish"]
    assert "Agent Builder UI" in agent["description"]


def test_cli_flags_native_argv_and_redacted_failures(tmp_path: Path) -> None:
    tools = object.__new__(saas.CLITools)
    tools.root, tools.settings = ROOT, ready().settings
    tools.node, tools.toolkit, tools.msagent = "node.exe", tmp_path / "cli.js", tmp_path / "native.exe"
    with patch("demo.saas.subprocess.run") as run, patch.dict(
        "demo.saas.os.environ", {"M365_ACCOUNT_PASSWORD": "never-login", "TEAMS_APP_ID": CLOUD},
    ):
        run.return_value = subprocess.CompletedProcess([], 0, '{"success":true,"schemaVersion":1}', "")
        tools.mcs("read", "auth", "status")
        command = run.call_args.args[0]
        assert command == [str(tools.msagent), "auth", "status", "--json", "--non-interactive"]
        assert run.call_args.kwargs["shell"] is False
        assert run.call_args.kwargs["timeout"] == 600
        assert "M365_ACCOUNT_PASSWORD" not in run.call_args.kwargs["env"]
        assert "TEAMS_APP_ID" not in run.call_args.kwargs["env"]
        tools.atk("read", "auth", "list", "m365")
        assert run.call_args.args[0][-4:] == ["--interactive", "false", "--telemetry", "false"]
        run.return_value = subprocess.CompletedProcess([], 7, "token secret", "account private")
        with pytest.raises(saas.SaaSError, match="exit=7") as error:
            tools.mcs("read", "auth", "status")
        assert "secret" not in str(error.value) and "private" not in str(error.value)


def test_installed_toolkit_packages_official_scaffold_locally(tmp_path: Path) -> None:
    if not shutil.which("node") or not (
        ROOT / ".easm-agent" / "tools" / "m365-automation" / "atk" / "node_modules"
        / "@microsoft" / "m365agentstoolkit-cli" / "cli.js"
    ).is_file():
        pytest.skip("공식 Toolkit의 기존 로컬 설치가 있을 때만 패키징 검증")
    project = tmp_path / "package-only"
    saas.prepare_toolkit(ROOT, project, ready().settings.publisher)
    env = project / "env" / ".env.dev"
    env.write_text(env.read_text(encoding="utf-8").replace(
        "TEAMS_APP_ID=", f"TEAMS_APP_ID={AGENT}",
    ), encoding="utf-8")
    tools = saas.CLITools(ROOT, ready().settings)
    tools.atk("local_package", "package", "--folder", str(project), "--env", "dev")
    packages = list((project / "appPackage" / "build").glob("*.zip"))
    assert len(packages) == 1
    with zipfile.ZipFile(packages[0]) as package:
        manifest = json.loads(package.read("manifest.json"))
        agent = json.loads(package.read("declarativeAgent.json"))
    assert manifest["id"] == AGENT
    assert agent["version"] == "v1.9" and not agent.get("capabilities")


def test_toolkit_guard_blocks_msal_interactive_before_any_login(tmp_path: Path) -> None:
    cli = (
        ROOT / ".easm-agent" / "tools" / "m365-automation" / "atk" / "node_modules"
        / "@microsoft" / "m365agentstoolkit-cli" / "cli.js"
    )
    if not shutil.which("node") or not cli.is_file():
        pytest.skip("공식 Toolkit의 기존 로컬 설치가 있을 때만 MSAL 경계 검증")
    guard = ROOT / "demo" / "m365" / "easm-demo-declarative" / "toolkit-no-login.cjs"
    result = subprocess.run(
        ["node", "-e", (
            "const {createRequire}=require('node:module');"
            "const cli=process.argv[1];const guard=process.argv[2];"
            "require(guard);const {PublicClientApplication}=createRequire(cli)('@azure/msal-node');"
            "PublicClientApplication.prototype.acquireTokenInteractive().then("
            "()=>process.exit(3),e=>{if(!e.message.includes('automatic login is disabled'))"
            "process.exit(4);});"
        ), str(cli), str(guard)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, "로컬 MSAL 로그인 차단 확인 실패"


def test_toolkit_auth_requires_online_output_and_stable_source_backed_tenant(tmp_path: Path) -> None:
    metadata = tmp_path / ".fx" / "account" / "tenantId.cache.appStudio"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(TENANT, encoding="utf-8")
    tools = object.__new__(saas.CLITools)
    with patch("demo.saas.Path.home", return_value=tmp_path), patch.object(tools, "atk") as atk:
        atk.return_value = "Your Microsoft 365 account is: synthetic(Synthetic Tenant)."
        assert str(tools.toolkit_tenant()) == TENANT
        atk.return_value = "Your Microsoft 365 account is: synthetic."
        with pytest.raises(saas.SaaSError):
            tools.toolkit_tenant()
        atk.return_value = "Use atk auth login m365"
        with pytest.raises(saas.SaaSError):
            tools.toolkit_tenant()


class DeployTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.fail: str | None = None
        self.create_count = 0
        self.pushed_count = 2
        self.published_on: str | None = None
        self.missing_published = False
        self.warnings: list[str] | None = None
        self.tamper_source = False

    def atk(self, phase: str, *arguments: str) -> str:
        self.calls.append((phase, arguments))
        if self.fail == phase:
            raise saas.SaaSError(phase, "exit=3")
        if phase == "toolkit_provision":
            project = Path(arguments[arguments.index("--folder") + 1])
            (project / "env" / ".env.dev").write_text(
                f"TEAMS_APP_ID={AGENT}\nM365_TITLE_ID=U_{DEPLOYMENT}\nM365_APP_ID={CLOUD}\n",
                encoding="utf-8",
            )
        return '[INFO] - {"syntheticLaunchPayload":"same-cloud-response"}'

    def mcs(self, phase: str, *arguments: str) -> dict:
        self.calls.append((phase, arguments))
        if self.fail == phase:
            raise saas.SaaSError(phase, "exit=3")
        if phase == "studio_scaffold":
            self.create_count += 1
            self.schema = arguments[arguments.index("--schema-name") + 1]
            directory = Path(arguments[arguments.index("--project") + 1]) / saas.STUDIO_NAME
            directory.mkdir(parents=True)
            source = {
                "displayName": saas.STUDIO_NAME, "schemaName": self.schema,
                "accessControlPolicy": "GroupMembership", "authenticationMode": "Integrated",
                "authenticationTrigger": "Always",
                "configuration": {
                    "recognizer": {"kind": "CLICopilotRecognizer"},
                    "agentSettings": {
                        "model": {"series": "test"},
                        "instructions": {"segments": [{
                            "kind": "StaticSegment",
                            "value": "changed" if self.tamper_source else saas.PROMPT,
                        }]},
                    },
                    "authoringModel": "CliCopilot",
                },
                "template": "cliagent-1.0.0", "language": 1033,
            }
            (directory / "settings.mcs.yml").write_text(yaml.safe_dump(source), encoding="utf-8")
            return {
                "status": "agent-created", "createdFrom": "scaffold", "tenantId": TENANT,
                "environmentId": ENVIRONMENT, "schemaName": self.schema, "agentId": AGENT,
            }
        if phase == "studio_target":
            return {
                "status": "deployment-slot-created", "agentId": AGENT,
                "targetEnvironmentId": ENVIRONMENT, "deploymentId": DEPLOYMENT,
            }
        if phase == "studio_deploy":
            response = {
                "status": "deployment-submitted", "agentId": AGENT, "deploymentId": DEPLOYMENT,
                "targetEnvironmentId": ENVIRONMENT, "schemaName": self.schema,
                "targetMcsAgentId": CLOUD, "pushedComponentCount": self.pushed_count, "published": False,
            }
            if self.warnings is not None:
                response["warnings"] = self.warnings
            return response
        if phase == "studio_local_binding":
            return {"agents": [{
                "agentId": AGENT, "mcsAgentId": CLOUD, "tenantId": TENANT,
                "environmentId": ENVIRONMENT, "mcsSchemaName": self.schema, "description": saas.DESCRIPTION,
            }], "deployments": [{
                "deploymentId": DEPLOYMENT, "agentId": AGENT, "deploymentType": "dev",
                "environmentId": ENVIRONMENT,
            }]}
        return {
            "status": "up-to-date", "agentId": AGENT,
            "environmentId": ENVIRONMENT, "changeCount": 0,
        }

    def get(self, phase: str, url: str, audience: str) -> dict:
        self.calls.append((phase, (url, audience)))
        result = {"botid": CLOUD, "schemaname": self.schema, "name": saas.STUDIO_NAME}
        if not self.missing_published:
            result["publishedon"] = self.published_on
        return result


def run_deploy(tmp_path: Path, tools: DeployTools, *, reconcile: bool = False) -> saas.SaaSReceipt:
    original = saas.prepare_toolkit
    fingerprint = saas.source_fingerprint(ROOT, ready().settings)
    with patch("demo.saas.preflight_saas", return_value=ready()), patch(
        "demo.saas.CLITools", return_value=tools,
    ), patch("demo.saas.prepare_toolkit", side_effect=lambda _, p, publisher: original(
        ROOT, p, publisher,
    )), patch("demo.saas.source_fingerprint", return_value=fingerprint), patch(
        "demo.saas.restrict_directory",
    ):
        result = saas.deploy_saas(
            options(), {"tenant_id": TENANT}, {"lab_id": "synthetic"}, tmp_path,
            **({"reconcile": True} if reconcile else {}),
        )
    assert result is not None
    return result


def test_cloud_identity_and_content_verified_then_resume_without_creation(tmp_path: Path) -> None:
    tools = DeployTools()
    receipt = run_deploy(tmp_path, tools)
    assert receipt.status == "deployed_verified"
    studio = receipt.components["copilot_studio"]
    assert studio.cloud_ids["mcs_agent_id"] == CLOUD
    assert studio.cloud_ids["mcs_agent_id"] != studio.local_agent_id
    assert studio.evidence["cloud_content_up_to_date"] is True
    assert receipt.components["m365_declarative"].authoring_method == "toolkit_declarative_code_first"
    assert "createdIn" not in receipt.model_dump_json()
    first_mutations = [call for call in tools.calls if call[0] in (
        "toolkit_provision", "studio_scaffold", "studio_target", "studio_deploy",
    )]
    run_deploy(tmp_path, tools)
    assert [call for call in tools.calls if call[0] in (
        "toolkit_provision", "studio_scaffold", "studio_target", "studio_deploy",
    )] == first_mutations
    assert tools.create_count == 1
    assert not (tmp_path / "output").exists()


def test_settings_only_studio_deployment_verifies_cloud_content(tmp_path: Path) -> None:
    tools = DeployTools()
    tools.pushed_count = 0
    receipt = run_deploy(tmp_path, tools)
    assert receipt.status == "deployed_verified"
    assert receipt.components["copilot_studio"].evidence["pushed_component_count"] == 0
    assert receipt.components["copilot_studio"].evidence["cloud_content_up_to_date"] is True


@pytest.mark.parametrize("published_on,missing", [
    ("2026-01-01T00:00:00Z", False),
    (None, True),
])
def test_studio_verification_requires_an_unpublished_draft(
    tmp_path: Path, published_on: str | None, missing: bool,
) -> None:
    tools = DeployTools()
    tools.published_on = published_on
    tools.missing_published = missing
    with pytest.raises(saas.SaaSError, match="studio_cloud_verify"):
        run_deploy(tmp_path, tools)


def test_studio_rejects_source_that_differs_from_synthetic_instructions(tmp_path: Path) -> None:
    tools = DeployTools()
    tools.tamper_source = True
    with pytest.raises(saas.SaaSError, match="studio_source_verify"):
        run_deploy(tmp_path, tools)
    assert not any(call[0] == "studio_content_verify" for call in tools.calls)


def test_cloud_pull_cannot_overwrite_original_project_on_drift(tmp_path: Path) -> None:
    class DriftTools(DeployTools):
        def mcs(self, phase: str, *arguments: str) -> dict:
            if phase == "studio_content_verify":
                project = Path(arguments[arguments.index("--project") + 1])
                (project / "drift-marker.txt").write_text("cloud change", encoding="utf-8")
                return {"status": "changes-pulled", "agentId": AGENT,
                        "environmentId": ENVIRONMENT, "changeCount": 1}
            return super().mcs(phase, *arguments)

    with pytest.raises(saas.SaaSError, match="studio_content_verify"):
        run_deploy(tmp_path, DriftTools())
    project = tmp_path / ".easm-agent" / "demo" / "saas" / "synthetic" / "copilot_studio"
    assert not (project / "drift-marker.txt").exists()


def test_failed_studio_with_cloud_id_reconciles_using_reads_only(tmp_path: Path) -> None:
    tools = DeployTools()
    tools.pushed_count = -1
    with pytest.raises(saas.SaaSError, match="studio_deploy"):
        run_deploy(tmp_path, tools)
    mutations = [call for call in tools.calls if call[0] in (
        "toolkit_provision", "studio_scaffold", "studio_target", "studio_deploy",
    )]

    receipt = run_deploy(tmp_path, tools, reconcile=True)

    assert receipt.status == "deployed_verified"
    assert receipt.components["copilot_studio"].evidence["reconciled_after_failed_deploy"] is True
    assert receipt.components["copilot_studio"].evidence["initial_deployment_warnings"] == "not_recorded"
    assert [call for call in tools.calls if call[0] in (
        "toolkit_provision", "studio_scaffold", "studio_target", "studio_deploy",
    )] == mutations


def test_reconcile_does_not_ignore_recorded_deployment_warnings(tmp_path: Path) -> None:
    tools = DeployTools()
    tools.warnings = ["deployment warning"]
    with pytest.raises(saas.SaaSError, match="studio_deploy"):
        run_deploy(tmp_path, tools)
    with pytest.raises(saas.SaaSError, match="reconcile"):
        run_deploy(tmp_path, tools, reconcile=True)


def test_saas_receipt_uses_isolated_state_without_overwriting_old_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = tmp_path / ".easm-agent" / "demo" / "saas" / "synthetic" / "receipt.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("old receipt", encoding="utf-8")
    isolated = tmp_path / "isolated"
    monkeypatch.setenv("EASM_AGENT_STATE_DIR", str(isolated))
    assert run_deploy(tmp_path, DeployTools()).status == "deployed_verified"
    new_receipt = isolated / "demo" / "saas" / "synthetic" / "receipt.json"
    assert new_receipt.is_file()
    assert legacy.read_text(encoding="utf-8") == "old receipt"
    fingerprint = saas.source_fingerprint(ROOT, ready().settings)
    with patch("demo.saas.source_fingerprint", return_value=fingerprint):
        loaded = saas.load_verified_saas_receipt(
            options(), {"tenant_id": TENANT}, {"lab_id": "synthetic"}, tmp_path,
        )
    assert loaded is not None and loaded.status == "deployed_verified"


@pytest.mark.parametrize("phase", ["toolkit_provision", "studio_scaffold", "studio_deploy"])
def test_partial_failures_block_duplicate_creation_on_retry(tmp_path: Path, phase: str) -> None:
    tools = DeployTools()
    tools.fail = phase
    with pytest.raises(saas.SaaSError, match=phase):
        run_deploy(tmp_path, tools)
    file = tmp_path / ".easm-agent" / "demo" / "saas" / "synthetic" / "receipt.json"
    receipt = saas.SaaSReceipt.model_validate_json(file.read_text(encoding="utf-8"))
    assert receipt.status == "failed"
    assert any(component.status == "failed" for component in receipt.components.values())
    calls = len(tools.calls)
    tools.fail = None
    with pytest.raises(saas.SaaSError, match="자동 재생성"):
        run_deploy(tmp_path, tools)
    assert len(tools.calls) == calls


def test_unverified_cloud_response_never_becomes_success(tmp_path: Path) -> None:
    tools = DeployTools()
    tools.fail = "studio_content_verify"
    with pytest.raises(saas.SaaSError, match="studio_content_verify"):
        run_deploy(tmp_path, tools)
    file = tmp_path / ".easm-agent" / "demo" / "saas" / "synthetic" / "receipt.json"
    receipt = saas.SaaSReceipt.model_validate_json(file.read_text(encoding="utf-8"))
    assert receipt.components["copilot_studio"].cloud_ids["mcs_agent_id"] == CLOUD
    assert receipt.status == "failed"


def test_receipt_requires_both_components() -> None:
    with pytest.raises(ValueError):
        saas.SaaSReceipt(
            tenant_id=TENANT, environment_id=ENVIRONMENT, lab_id="synthetic",
            configuration_sha256="synthetic", components={},
        )


def test_collection_requires_verified_receipt_without_admin_reauthentication(tmp_path: Path) -> None:
    with patch("demo.saas.CLITools") as tools, pytest.raises(saas.SaaSError, match="영수증"):
        saas.load_verified_saas_receipt(
            options(), {"tenant_id": TENANT}, {"lab_id": "synthetic"}, tmp_path,
        )
    tools.assert_not_called()
    assert saas.load_verified_saas_receipt({}, {}, {}, tmp_path) is None


def test_default_config_stops_direct_deploy_before_any_azure_call(tmp_path: Path) -> None:
    setup = tmp_path / "setup.json"
    setup.write_text(json.dumps({"tenant_id": TENANT}), encoding="utf-8")
    with patch("demo.manage.ROOT", tmp_path), patch("demo.manage.deploy") as deploy:
        assert manage.main([
            "deploy", "--apply", "--setup-file", str(setup),
            "--lab-config", str(ROOT / "demo" / "config.yaml"),
        ]) == 1
    deploy.assert_not_called()
