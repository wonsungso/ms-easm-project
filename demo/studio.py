"""Admin-only demo step: publish the code-first Copilot Studio draft so the Power Platform inventory lists it.

The collector never imports this module. Publishing keeps the agent private to the demo environment;
no channel, sharing or tenant-wide catalog setting is changed.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import requests

from easm_agent.paths import state_path

PP_ENVIRONMENTS = "https://api.powerplatform.com/environmentmanagement/environments?api-version=2024-10-01"
HOST = re.compile(r"[a-z0-9-]+\.crm[0-9]*\.dynamics\.com")


class PublishError(RuntimeError):
    pass


def _token(cli: Any, resource: str) -> str:
    return str(cli.run("account", "get-access-token", "--resource", resource)["accessToken"])


def environment_url(cli: Any, environment_id: str) -> str:
    response = requests.get(
        PP_ENVIRONMENTS, headers={"Authorization": "Bearer " + _token(cli, "https://api.powerplatform.com/")},
        timeout=(10, 60), allow_redirects=False,
    )
    with response:
        response.raise_for_status()
        rows = response.json().get("value") or []
    matches = [row for row in rows if str(row.get("id", "")).lower() == environment_id.lower()]
    if len(matches) != 1:
        raise PublishError("승인된 환경을 정확히 하나 확인하지 못했습니다.")
    url = str(matches[0].get("url", "")).rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not HOST.fullmatch(parsed.hostname or "") or parsed.path not in ("", "/"):
        raise PublishError("공용 클라우드 Dataverse 환경 URL이 아닙니다.")
    return url


def publish_draft(cli: Any, url: str, bot_id: str, timeout_seconds: int = 180, *, force: bool = False) -> str:
    """Call the bound PvaPublish action and wait for publishedon; returns the published timestamp."""
    UUID(bot_id)
    base = f"{url}/api/data/v9.2/bots({bot_id})"
    headers = {"Authorization": "Bearer " + _token(cli, url), "Accept": "application/json"}
    with requests.Session() as session:
        session.headers.update(headers)
        current = session.get(base + "?$select=name,publishedon", timeout=(10, 60), allow_redirects=False)
        current.raise_for_status()
        previous = current.json().get("publishedon")
        if previous and not force:
            return str(previous)
        response = session.post(
            base + "/Microsoft.Dynamics.CRM.PvaPublish", json={}, timeout=(10, 120), allow_redirects=False,
        )
        response.raise_for_status()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            polled = session.get(base + "?$select=publishedon", timeout=(10, 60), allow_redirects=False)
            polled.raise_for_status()
            observed = polled.json().get("publishedon")
            if observed and observed != previous:
                return str(observed)
            time.sleep(5)
    raise PublishError("게시 시각을 제한 시간 안에 확인하지 못했습니다.")


def publish_from_receipt(cli: Any, root: Path, lab_id: str) -> str:
    receipt = json.loads(state_path(root, "demo", "saas", lab_id, "receipt.json").read_text(encoding="utf-8"))
    if receipt.get("lab_id") != lab_id or receipt.get("status") != "deployed_verified":
        raise PublishError("검증된 SaaS 영수증이 필요합니다.")
    bot = receipt["components"]["copilot_studio"]["cloud_ids"]["mcs_agent_id"]
    url = environment_url(cli, receipt["environment_id"])
    return publish_draft(cli, url, bot)
