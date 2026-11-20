"""Admin-only demo step: enable the Defender for Cloud plans that the OT-SE-25 evidence reads.

The collector only reads Microsoft.Security/pricings. This module is an approved administrator
action for the demo subscriptions and is never imported by the collector.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from easm_agent.paths import state_path

API_VERSION = "2024-01-01"
PRICINGS = "https://management.azure.com/subscriptions/{sid}/providers/Microsoft.Security/pricings/{plan}"
SENSITIVE_EXTENSION = "SensitiveDataDiscovery"
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def _extensions(properties: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"name": str(item["name"]), "isEnabled": str(item.get("isEnabled", "False"))}
        for item in properties.get("extensions") or [] if isinstance(item, dict) and item.get("name")
    ]


def _read(cli: Any, sid: str, plan: str) -> dict[str, Any]:
    return cli.run("rest", "--method", "get", "--url", PRICINGS.format(sid=sid, plan=plan) + "?api-version=" + API_VERSION)


def _put(cli: Any, sid: str, plan: str, properties: dict[str, Any]) -> dict[str, Any]:
    return cli.run(
        "rest", "--method", "put", "--url", PRICINGS.format(sid=sid, plan=plan) + "?api-version=" + API_VERSION,
        "--body", json.dumps({"properties": properties}),
    )


def enable_plans(cli: Any, subscription_ids: list[str]) -> dict[str, Any]:
    """Set AI and CloudPosture to Standard and SensitiveDataDiscovery on; keep other extension states."""
    if not subscription_ids or any(not GUID.fullmatch(value) for value in subscription_ids):
        raise ValueError("승인된 구독 ID 목록이 필요합니다.")
    record: dict[str, Any] = {"applied_at": datetime.now(UTC).isoformat(), "subscriptions": {}}
    for sid in subscription_ids:
        before = {plan: (_read(cli, sid, plan).get("properties") or {}) for plan in ("AI", "CloudPosture")}
        state = {plan: {
            "tier": props.get("pricingTier"), "extensions": _extensions(props),
        } for plan, props in before.items()}
        # Defender CSPM's tier must be Standard before the extension list is returned.
        _put(cli, sid, "AI", {"pricingTier": "Standard"})
        extensions = {item["name"]: item for item in _extensions(before["CloudPosture"])}
        extensions[SENSITIVE_EXTENSION] = {"name": SENSITIVE_EXTENSION, "isEnabled": "True"}
        _put(cli, sid, "CloudPosture", {"pricingTier": "Standard", "extensions": list(extensions.values())})
        after = {plan: (_read(cli, sid, plan).get("properties") or {}) for plan in ("AI", "CloudPosture")}
        enabled = {item["name"]: item["isEnabled"].lower() == "true" for item in _extensions(after["CloudPosture"])}
        if (
            after["AI"].get("pricingTier") != "Standard"
            or after["CloudPosture"].get("pricingTier") != "Standard"
            or enabled.get(SENSITIVE_EXTENSION) is not True
        ):
            raise RuntimeError("Defender 플랜 변경 후 읽기 검증에 실패했습니다.")
        record["subscriptions"][sid] = {"before": state, "verified": True}
    return record


def revert_plans(cli: Any, record: dict[str, Any]) -> None:
    """Restore the tiers and extension states captured by enable_plans."""
    for sid, row in record["subscriptions"].items():
        if not GUID.fullmatch(sid):
            raise ValueError("복원 기록의 구독 ID가 올바르지 않습니다.")
        for plan in ("CloudPosture", "AI"):
            previous = row["before"][plan]
            properties: dict[str, Any] = {"pricingTier": previous["tier"] or "Free"}
            if plan == "CloudPosture" and previous["extensions"]:
                properties["extensions"] = previous["extensions"]
            elif plan == "CloudPosture":
                properties["extensions"] = [{"name": SENSITIVE_EXTENSION, "isEnabled": "False"}]
            _put(cli, sid, plan, properties)


def record_path(root: Path) -> Path:
    return state_path(root, "demo", "defender.json")


def apply(cli: Any, subscription_ids: list[str], root: Path) -> dict[str, Any]:
    path = record_path(root)
    previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"subscriptions": {}}
    record = enable_plans(cli, subscription_ids)
    # Keep the first captured state so a repeated apply can still restore the original configuration.
    for sid, row in previous["subscriptions"].items():
        if sid in record["subscriptions"]:
            record["subscriptions"][sid]["before"] = row["before"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def revert(cli: Any, root: Path) -> None:
    path = record_path(root)
    if not path.is_file():
        raise FileNotFoundError("복원할 Defender 플랜 기록이 없습니다.")
    revert_plans(cli, json.loads(path.read_text(encoding="utf-8")))
