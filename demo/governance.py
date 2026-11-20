from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

POLICY_REVISION = "demo-governance-v1"
RUNTIME_REVISION = "chatbot-governance-v1"
SYNTHETIC_VALUES = frozenset({"synthetic-ready", "synthetic-reviewed"})
CHECK_NAMES = frozenset({
    "endpoint_allowed", "endpoint_denied", "endpoint_credentials_denied",
    "unapproved_denied", "wrong_actor_denied", "rejected_denied",
    "approved_executed", "replay_denied", "expired_denied", "state_cleaned",
})


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(),
    ).hexdigest()


def endpoint_key(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.port not in (None, 443)
        or "\\" in url or "%" in url or any(char.isspace() for char in url)
        or any(part in (".", "..") for part in parsed.path.split("/"))
    ):
        raise ValueError("HTTPS endpoint without credentials, query or ambiguous path is required")
    return "https://" + parsed.hostname.lower() + parsed.path.rstrip("/")


@dataclass(frozen=True)
class GovernancePolicy:
    endpoints: frozenset[str]

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> GovernancePolicy:
        # These server-owned settings are the explicit allowlist, never request/model input.
        return cls(frozenset(
            endpoint_key(environment[key])
            for key in ("AZURE_OPENAI_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT")
            if environment.get(key)
        ))

    def require_endpoint(self, url: str) -> str:
        try:
            allowed = endpoint_key(url) in self.endpoints
        except ValueError:
            allowed = False
        if not allowed:
            raise PermissionError("External endpoint is not explicitly allowed")
        return url

    @property
    def fingerprint(self) -> str:
        return digest({"revision": POLICY_REVISION, "endpoints": sorted(self.endpoints)})


@dataclass
class PendingAction:
    actor: str
    value: str
    expires_at: float
    decision: Literal["pending", "approved", "denied"] = "pending"


class GovernanceEngine:
    """Only disposable synthetic memory is writable. Approval is not an LLM tool."""

    def __init__(self, policy: GovernancePolicy) -> None:
        self.policy = policy
        self._actions: dict[str, PendingAction] = {}
        self._records: dict[str, str] = {}
        self._lock = threading.Lock()

    def _prune(self) -> None:
        now = time.monotonic()
        for action_id in list(self._actions):
            if self._actions[action_id].expires_at <= now:
                self._actions.pop(action_id)
                self._records.pop(action_id, None)

    def propose(self, actor: str, value: str) -> str:
        if not actor or value not in SYNTHETIC_VALUES:
            raise ValueError("An authenticated actor and a predefined synthetic value are required")
        with self._lock:
            self._prune()
            if len(self._actions) >= 256:
                raise ValueError("Synthetic pending-action capacity reached")
            action_id = secrets.token_hex(16)
            self._actions[action_id] = PendingAction(
                hashlib.sha256(actor.encode()).hexdigest(), value, time.monotonic() + 300,
            )
            return action_id

    def _owned(self, actor: str, action_id: str) -> PendingAction:
        self._prune()
        action = self._actions.get(action_id)
        if not actor or action is None or action.actor != hashlib.sha256(actor.encode()).hexdigest():
            raise PermissionError("Action unavailable for this actor")
        return action

    def decide(self, actor: str, action_id: str, approved: bool) -> None:
        if type(approved) is not bool:
            raise ValueError("An explicit human approve/deny decision is required")
        with self._lock:
            action = self._owned(actor, action_id)
            if action.decision != "pending":
                raise PermissionError("Decision is already final")
            action.decision = "approved" if approved else "denied"

    def execute(self, actor: str, action_id: str) -> str:
        with self._lock:
            action = self._owned(actor, action_id)
            if action.decision != "approved" or action_id in self._records:
                raise PermissionError("One-time human approval is required")
            self._records[action_id] = action.value
            return action.value

    def clear(self) -> None:
        with self._lock:
            self._actions.clear()
            self._records.clear()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SelfTestReport(StrictModel):
    demo_evidence: Literal[True] = True
    scope: Literal["local_runtime_controls_not_foundry_service"] = (
        "local_runtime_controls_not_foundry_service"
    )
    approval_actor: Literal["synthetic_test_fixture_not_human_approval"] = (
        "synthetic_test_fixture_not_human_approval"
    )
    policy_revision: str = POLICY_REVISION
    runtime_revision: str = RUNTIME_REVISION
    code_sha256: str
    policy_sha256: str
    configured_endpoint_count: int = Field(ge=0)
    checks: dict[str, bool]
    passed: bool


def runtime_code_digest(directory: Path | None = None) -> str:
    directory = directory or Path(__file__).parent
    return digest({
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in ("app.py", "governance.py", "catalog.json")
    })


def run_self_test(policy: GovernancePolicy, *, code_sha256: str | None = None) -> SelfTestReport:
    engine = GovernanceEngine(policy)
    checks: dict[str, bool] = {}

    def denied(operation: Any) -> bool:
        try:
            operation()
        except PermissionError:
            return True
        return False

    try:
        if policy.endpoints:
            allowed = sorted(policy.endpoints)[0]
            checks["endpoint_allowed"] = policy.require_endpoint(allowed) == allowed
        else:
            # A separate, explicitly synthetic fixture tests the same allow branch.
            fixture = GovernancePolicy(frozenset({"https://synthetic.invalid"}))
            checks["endpoint_allowed"] = fixture.require_endpoint(
                "https://synthetic.invalid",
            ) == "https://synthetic.invalid"
        checks["endpoint_denied"] = denied(
            lambda: policy.require_endpoint("https://unlisted.synthetic.invalid"),
        )
        checks["endpoint_credentials_denied"] = denied(
            lambda: policy.require_endpoint("https://user:password@synthetic.invalid"),
        )
        action_id = engine.propose("synthetic-actor", "synthetic-ready")
        checks["unapproved_denied"] = denied(lambda: engine.execute("synthetic-actor", action_id))
        checks["wrong_actor_denied"] = denied(
            lambda: engine.decide("synthetic-other", action_id, True),
        )
        engine.decide("synthetic-actor", action_id, False)
        checks["rejected_denied"] = denied(lambda: engine.execute("synthetic-actor", action_id))
        action_id = engine.propose("synthetic-actor", "synthetic-reviewed")
        engine.decide("synthetic-actor", action_id, True)
        checks["approved_executed"] = engine.execute(
            "synthetic-actor", action_id,
        ) == "synthetic-reviewed"
        checks["replay_denied"] = denied(lambda: engine.execute("synthetic-actor", action_id))
        action_id = engine.propose("synthetic-actor", "synthetic-ready")
        engine._actions[action_id].expires_at = 0
        checks["expired_denied"] = denied(lambda: engine.execute("synthetic-actor", action_id))
    finally:
        engine.clear()
    checks["state_cleaned"] = not engine._actions and not engine._records
    return SelfTestReport(
        code_sha256=code_sha256 or runtime_code_digest(), policy_sha256=policy.fingerprint,
        configured_endpoint_count=len(policy.endpoints),
        checks=checks, passed=set(checks) == CHECK_NAMES and all(checks.values()),
    )
