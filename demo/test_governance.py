from __future__ import annotations

import json
import os
import shutil
import site
import subprocess
import sys
import uuid
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from demo.governance import (
    CHECK_NAMES,
    GovernanceEngine,
    GovernancePolicy,
    run_self_test,
)


@pytest.fixture
def work_directory():
    directory = Path(".easm-agent") / ("governance-tests-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


@pytest.fixture
def policy() -> GovernancePolicy:
    return GovernancePolicy.from_environment({"AZURE_OPENAI_ENDPOINT": "https://model.example/"})


@pytest.mark.parametrize("endpoint", [
    "http://model.example", "https://model.example.evil", "https://model.example@evil.example",
    "https://model.example?secret=test", "https://model.example/#fragment",
    "https://model.example:8443", "https://model.example/other",
    "https://model.example/../", "https://model.example/%2e", "https://model.example\\evil",
    "https://model.example:invalid", "https://user:password@model.example",
])
def test_external_endpoint_is_deny_by_default(policy: GovernancePolicy, endpoint: str) -> None:
    with pytest.raises(PermissionError):
        policy.require_endpoint(endpoint)


def test_exact_endpoint_and_empty_policy(policy: GovernancePolicy) -> None:
    assert policy.require_endpoint("https://MODEL.example:443/") == "https://MODEL.example:443/"
    with pytest.raises(PermissionError):
        GovernancePolicy.from_environment({}).require_endpoint("https://model.example")


def test_approval_is_actor_bound_one_time_and_expiring(policy: GovernancePolicy) -> None:
    engine = GovernanceEngine(policy)
    action_id = engine.propose("human-a", "synthetic-ready")
    with pytest.raises(PermissionError):
        engine.execute("human-a", action_id)
    assert not engine._records
    with pytest.raises(PermissionError):
        engine.decide("human-b", action_id, True)
    with pytest.raises(ValueError):
        engine.decide("human-a", action_id, "true")
    engine.decide("human-a", action_id, True)
    assert engine.execute("human-a", action_id) == "synthetic-ready"
    with pytest.raises(PermissionError):
        engine.execute("human-a", action_id)
    engine._actions[action_id].expires_at = 0
    with pytest.raises(PermissionError):
        engine.execute("human-a", action_id)
    assert not engine._records and not engine._actions


def test_denial_is_final_and_arbitrary_values_never_written(policy: GovernancePolicy) -> None:
    engine = GovernanceEngine(policy)
    with pytest.raises(ValueError):
        engine.propose("human-a", "customer-secret")
    action_id = engine.propose("human-a", "synthetic-reviewed")
    engine.decide("human-a", action_id, False)
    with pytest.raises(PermissionError):
        engine.decide("human-a", action_id, True)
    with pytest.raises(PermissionError):
        engine.execute("human-a", action_id)
    assert not engine._records
    engine.clear()
    assert not engine._actions


def test_action_capacity_is_bounded(policy: GovernancePolicy) -> None:
    engine = GovernanceEngine(policy)
    for _ in range(256):
        engine.propose("human-a", "synthetic-ready")
    with pytest.raises(ValueError):
        engine.propose("human-a", "synthetic-ready")
    engine.clear()


def test_report_is_deterministic_nonsecret_and_cleans_state(policy: GovernancePolicy) -> None:
    report = run_self_test(policy)
    assert report == run_self_test(policy)
    assert report.passed and set(report.checks) == CHECK_NAMES and all(report.checks.values())
    serialized = report.model_dump_json()
    assert "model.example" not in serialized and "human-a" not in serialized
    assert report.approval_actor == "synthetic_test_fixture_not_human_approval"
    assert report.scope == "local_runtime_controls_not_foundry_service"
    assert run_self_test(GovernancePolicy.from_environment({})).passed


def test_standalone_deployed_import_needs_no_collector_package_or_network(work_directory: Path) -> None:
    for dependency in (
        "flask", "azure.ai.projects", "azure.identity", "langchain",
        "langchain_core", "langchain_openai", "openai", "pydantic",
    ):
        try:
            available = find_spec(dependency) is not None
        except ModuleNotFoundError:
            available = False
        if not available:
            pytest.skip(f"Demo runtime dependency is not installed in this interpreter: {dependency}")
    directory = work_directory / "deployed"
    directory.mkdir()
    for name in ("app.py", "governance.py", "catalog.json", "chat.html"):
        shutil.copyfile(Path("demo") / name, directory / name)
    script = r'''
import builtins
import json
import socket
import sys
from pathlib import Path

excluded = {Path(value).resolve() for value in json.loads(sys.argv[2])}
sys.path = [value for value in sys.path if Path(value).resolve() not in excluded]
# Add dependency directories directly, without processing editable-install .pth files.
sys.path.extend(json.loads(sys.argv[1]))
sys.path.insert(0, ".")
assert all(Path(value).resolve() not in excluded for value in sys.path)
original_import = builtins.__import__
collector_only = {"easm_agent", "demo", "yaml"}

def guarded_import(name, *args, **kwargs):
    if name.split(".")[0] in collector_only:
        raise AssertionError("Deployed runtime imported a collector-only package: " + name)
    return original_import(name, *args, **kwargs)

def blocked_network(*args, **kwargs):
    raise AssertionError("Standalone import or health attempted a network connection")

builtins.__import__ = guarded_import
socket.socket.connect = blocked_network
socket.socket.connect_ex = blocked_network
socket.create_connection = blocked_network
import governance
# Existing LangChain runtime dependencies import PyYAML; governance itself must not.
collector_only.remove("yaml")
import app
with app.app.test_client() as client:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json["governance"]["passed"]
    assert response.json["smoke_status"] == "not_requested"
    print(json.dumps({"health": response.status_code, "standalone": True, "network": False}))
'''
    environment = dict(os.environ)
    environment.update({
        "EASMAGENT_SMOKE_ON_START": "false",
        "AZURE_OPENAI_ENDPOINT": "https://synthetic.invalid",
        "AZURE_AI_PROJECT_ENDPOINT": "",
    })
    environment.pop("PYTHONPATH", None)
    dependency_directories = {
        str(Path(value).resolve())
        for value in [*site.getsitepackages(), site.getusersitepackages()]
        if Path(value).is_dir()
    }
    dependencies = list(dict.fromkeys(
        str(Path(value).resolve()) for value in sys.path
        if value and str(Path(value).resolve()) in dependency_directories
    ))
    excluded = [str(Path.cwd().resolve()), str((Path.cwd() / "src").resolve())]
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, json.dumps(dependencies), json.dumps(excluded)],
        cwd=directory, env=environment,
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"health": 200, "standalone": True, "network": False}


def test_app_control_paths_are_real_and_auth_protected(monkeypatch: pytest.MonkeyPatch) -> None:
    chat = pytest.importorskip("demo.app", exc_type=ImportError)
    monkeypatch.setenv("EASMAGENT_CHAT_ALLOWED_OIDS", "allowed-user,other-user")
    monkeypatch.setenv("EASMAGENT_LOCAL_AGENT", "langchain-tools")
    monkeypatch.delenv("WEBSITE_HOSTNAME", raising=False)
    chat.governance.clear()
    headers = {
        "X-MS-CLIENT-PRINCIPAL-ID": "allowed-user", "Origin": "http://localhost",
        "X-EASMAgent-Chat": "1",
    }
    try:
        with chat.app.test_client() as client:
            assert client.post("/api/governance/actions", json={"value": "synthetic-ready"}).status_code == 403
            assert client.post(
                "/api/governance/actions", json={"value": "synthetic-ready"},
                headers=headers | {"Origin": "https://foreign.example"},
            ).status_code == 403
            proposed = client.post(
                "/api/governance/actions", json={"value": "synthetic-ready"}, headers=headers,
            )
            assert proposed.status_code == 201 and proposed.json["status"] == "pending"
            action_id = proposed.json["action_id"]
            with chat.app.test_request_context(headers=headers):
                assert chat.synthetic_record.invoke({"action_id": action_id}).startswith("denied:")
            decision = "/api/governance/actions/" + action_id + "/decision"
            assert client.post(decision, json={"approved": True}, headers=headers | {
                "X-MS-CLIENT-PRINCIPAL-ID": "other-user",
            }).status_code == 403
            assert client.post(decision, json={"approved": "true"}, headers=headers).status_code == 400
            assert client.post(decision, json={"approved": True}, headers=headers).status_code == 200
            with chat.app.test_request_context(headers=headers):
                assert chat.synthetic_record.invoke({"action_id": action_id}) == "demo evidence: synthetic-ready"
                assert chat.synthetic_record.invoke({"action_id": action_id}).startswith("denied:")
            with patch.object(chat, "invoke_agent", side_effect=AssertionError("No model call")):
                health = client.get("/health")
            assert health.status_code == 200 and health.json["governance"]["passed"]
            assert "allowed-user" not in health.text and action_id not in health.text
        assert chat.synthetic_record.invoke({"action_id": action_id}).startswith("denied:")
    finally:
        chat.governance.clear()


@pytest.mark.parametrize("platform,setting", [
    ("langchain", "AZURE_OPENAI_ENDPOINT"), ("foundry", "AZURE_AI_PROJECT_ENDPOINT"),
])
def test_app_endpoint_gate_precedes_credentials_and_model(
    monkeypatch: pytest.MonkeyPatch, platform: str, setting: str,
) -> None:
    chat = pytest.importorskip("demo.app", exc_type=ImportError)
    monkeypatch.setenv(setting, "https://unlisted.synthetic.invalid")
    with patch.object(chat, "DefaultAzureCredential", side_effect=AssertionError("No credential call")):
        with pytest.raises(PermissionError):
            chat.invoke_agent({"platform": platform}, [])


def test_real_langchain_construction_registers_execution_but_not_approval(
    monkeypatch: pytest.MonkeyPatch, policy: GovernancePolicy,
) -> None:
    chat = pytest.importorskip("demo.app", exc_type=ImportError)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://model.example")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "synthetic-model")
    monkeypatch.setattr(chat, "governance", GovernanceEngine(policy))
    message = SimpleNamespace(
        type="ai", content="synthetic-answer", usage_metadata={"input_tokens": 1, "output_tokens": 2},
    )
    with (
        patch.object(chat, "DefaultAzureCredential"),
        patch.object(chat, "get_bearer_token_provider"),
        patch.object(chat, "AzureChatOpenAI") as model,
        patch.object(chat, "create_agent") as create,
    ):
        create.return_value.invoke.return_value = {"messages": [message]}
        result = chat.invoke_agent({"platform": "langchain", "tools": True, "instructions": "synthetic"}, [])
    assert result == ("synthetic-answer", 1, 2)
    assert model.call_args.kwargs["azure_endpoint"] == "https://model.example"
    assert {tool.name for tool in create.call_args.kwargs["tools"]} == {"governance_scope", "synthetic_record"}
