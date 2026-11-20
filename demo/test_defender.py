from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from demo import defender

SID = "11111111-1111-1111-1111-111111111111"


class FakeCLI:
    def __init__(self, cloud_posture: list[dict[str, str]] | None = None) -> None:
        self.state: dict[str, dict[str, Any]] = {
            "AI": {"pricingTier": "Free"},
            "CloudPosture": {"pricingTier": "Free", "extensions": cloud_posture},
        }
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def run(self, *args: str) -> dict[str, Any]:
        method = args[args.index("--method") + 1]
        plan = args[args.index("--url") + 1].split("/pricings/")[1].split("?")[0]
        if method == "put":
            properties = json.loads(args[args.index("--body") + 1])["properties"]
            self.writes.append((plan, properties))
            self.state[plan] = properties
        return {"properties": self.state[plan]}


def test_enable_plans_turns_on_required_plans_and_keeps_other_extensions() -> None:
    cli = FakeCLI([{"name": "ApiPosture", "isEnabled": "True"}])
    record = defender.enable_plans(cli, [SID])
    assert record["subscriptions"][SID]["verified"] is True
    assert cli.state["AI"]["pricingTier"] == "Standard"
    extensions = {item["name"]: item["isEnabled"] for item in cli.state["CloudPosture"]["extensions"]}
    assert extensions == {"ApiPosture": "True", "SensitiveDataDiscovery": "True"}
    assert record["subscriptions"][SID]["before"]["AI"]["tier"] == "Free"


def test_enable_plans_rejects_unverified_result_and_invalid_scope() -> None:
    class Stuck(FakeCLI):
        def run(self, *args: str) -> dict[str, Any]:
            super().run(*args)
            self.state["AI"] = {"pricingTier": "Free"}
            return {"properties": self.state[args[args.index("--url") + 1].split("/pricings/")[1].split("?")[0]]}

    with pytest.raises(RuntimeError, match="검증"):
        defender.enable_plans(Stuck(), [SID])
    with pytest.raises(ValueError, match="구독"):
        defender.enable_plans(FakeCLI(), ["not-a-subscription"])


def test_apply_keeps_first_captured_state_and_revert_restores_it(tmp_path: Path) -> None:
    cli = FakeCLI()
    first = defender.apply(cli, [SID], tmp_path)
    second = defender.apply(cli, [SID], tmp_path)
    assert second["subscriptions"][SID]["before"] == first["subscriptions"][SID]["before"]
    defender.revert(cli, tmp_path)
    assert cli.state["AI"] == {"pricingTier": "Free"}
    assert cli.state["CloudPosture"]["pricingTier"] == "Free"
    assert {"name": "SensitiveDataDiscovery", "isEnabled": "False"} in cli.state["CloudPosture"]["extensions"]


def test_revert_requires_a_record(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        defender.revert(FakeCLI(), tmp_path)
