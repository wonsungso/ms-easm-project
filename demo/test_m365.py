from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from demo.m365 import main, verify
from easm_agent.azure import PP_INVENTORY_URL

TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BUILDER = "11111111-1111-4111-8111-111111111111"
STUDIO = "22222222-2222-4222-8222-222222222222"


def export_file(directory: Path, *, published: bool = False, complete: bool = True) -> Path:
    now = datetime.now(UTC)
    rows = [{
        "agent_id": identifier, "environment_id": "environment",
        "created_in": origin, "display_name": "demo", "created_at": (now - timedelta(days=1)).isoformat(),
        "last_published_at": now.isoformat() if published else None, "owner_present": True,
        "entra_agent_id": None, "blueprint_id": None, "model": None, "authentication": None,
        "channels": None, "is_quarantined": None, "shared_with_tenant": None,
    } for identifier, origin in (
        (BUILDER, "Microsoft Copilot Agent Builder"), (STUDIO, "Copilot Studio"),
    )]
    value = {
        "schema_version": 1, "source_type": "official_admin_read", "approved": True,
        "command": PP_INVENTORY_URL, "auth_type": "delegated_user", "tenant_id": TENANT,
        "tenant_verified": True, "observed_at": now.isoformat(), "exported_at": now.isoformat(),
        "completed": complete, "object_count": 2 if complete else None,
        "total_records": 2 if complete else None,
        "reason": None if complete else "permission_denied",
        "failure_code": None if complete else "permission_denied",
        "agents": rows if complete else [],
    }
    path = directory / "inventory.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_plan_explains_manual_saas_creation_without_deployment(capsys: pytest.CaptureFixture) -> None:
    assert main(["plan"]) == 0
    text = capsys.readouterr().out
    assert "SaaS" in text and "Bicep" in text and "직접 생성" in text
    assert "진단 SP" in text and "Global Reader" in text


def test_exact_two_types_verify_but_swapped_ids_do_not(tmp_path: Path) -> None:
    path = export_file(tmp_path)
    assert verify(path, TENANT, BUILDER, STUDIO)["status"] == "verified"
    assert verify(path, TENANT, STUDIO, BUILDER)["status"] == "not_ready"
    assert verify(path, TENANT, BUILDER, BUILDER)["status"] == "not_ready"
    assert verify(path, TENANT, BUILDER, STUDIO, require_published=True)["status"] == "not_ready"
    path = export_file(tmp_path, published=True)
    assert verify(path, TENANT, BUILDER, STUDIO, require_published=True)["status"] == "verified"


@pytest.mark.parametrize("origin", ["microsoft 365 copilot agent builder", "Copilot Studio Lite"])
def test_builder_origin_verifies_case_insensitively(tmp_path: Path, origin: str) -> None:
    path = export_file(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["agents"][0]["created_in"] = origin
    path.write_text(json.dumps(value), encoding="utf-8")
    assert verify(path, TENANT, BUILDER, STUDIO)["status"] == "verified"


def test_environment_ambiguity_requires_exact_environment(tmp_path: Path) -> None:
    path = export_file(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["agents"].append({**value["agents"][0], "environment_id": "another"})
    value.update(object_count=3, total_records=3)
    path.write_text(json.dumps(value), encoding="utf-8")
    assert verify(path, TENANT, BUILDER, STUDIO)["status"] == "not_ready"
    assert verify(path, TENANT, BUILDER, STUDIO,
                  agent_builder_environment_id="another")["status"] == "verified"


def test_incomplete_or_invalid_export_never_verifies(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = export_file(tmp_path, complete=False)
    assert verify(path, TENANT, BUILDER, STUDIO)["status"] == "not_ready"
    args = [
        "verify", "--inventory-file", str(path), "--tenant-id", TENANT,
        "--agent-builder-id", BUILDER, "--copilot-studio-id", STUDIO,
    ]
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "not_ready"
    path.write_text("{}", encoding="utf-8")
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "not_ready"


def test_mismatched_tenant_is_not_ready(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert main([
        "verify", "--inventory-file", str(export_file(tmp_path)),
        "--tenant-id", BUILDER, "--agent-builder-id", BUILDER, "--copilot-studio-id", STUDIO,
    ]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "not_ready"
