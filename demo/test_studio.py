from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from demo import studio

BOT = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
URL = "https://easm-demo-aaaa.crm7.dynamics.com"


class CLI:
    def run(self, *args: str) -> dict[str, Any]:
        return {"accessToken": "token"}


def response(payload: dict[str, Any] | None = None) -> MagicMock:
    item = MagicMock()
    item.json.return_value = payload or {}
    item.__enter__.return_value = item
    return item


def test_publish_skips_an_already_published_draft() -> None:
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.return_value = response({"publishedon": "2026-11-19T00:00:00Z"})
    with patch("demo.studio.requests.Session", return_value=session):
        assert studio.publish_draft(CLI(), URL, BOT) == "2026-11-19T00:00:00Z"
    session.post.assert_not_called()


def test_publish_posts_action_then_waits_for_publication() -> None:
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.side_effect = [response({"publishedon": None}), response({"publishedon": None}),
                               response({"publishedon": "2026-11-19T01:00:00Z"})]
    with patch("demo.studio.requests.Session", return_value=session), patch("demo.studio.time.sleep"):
        assert studio.publish_draft(CLI(), URL, BOT) == "2026-11-19T01:00:00Z"
    assert session.post.call_args.args[0].endswith("/Microsoft.Dynamics.CRM.PvaPublish")


def test_publish_changed_content_waits_for_a_new_publication_timestamp() -> None:
    session = MagicMock()
    session.__enter__.return_value = session
    previous, updated = "2026-11-19T00:00:00Z", "2026-11-19T01:00:00Z"
    session.get.side_effect = [
        response({"publishedon": previous}), response({"publishedon": previous}),
        response({"publishedon": updated}),
    ]
    with patch("demo.studio.requests.Session", return_value=session), patch("demo.studio.time.sleep"):
        assert studio.publish_draft(CLI(), URL, BOT, force=True) == updated
    session.post.assert_called_once()


def test_environment_url_rejects_non_dataverse_hosts() -> None:
    rows = {"value": [{"id": "env", "url": "https://example.invalid"}]}
    with patch("demo.studio.requests.get", return_value=response(rows)), pytest.raises(studio.PublishError):
        studio.environment_url(CLI(), "env")


def test_publish_from_receipt_requires_verified_receipt(tmp_path: Path) -> None:
    path = tmp_path / ".easm-agent" / "demo" / "saas" / "lab" / "receipt.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"lab_id": "lab", "status": "failed"}), encoding="utf-8")
    with pytest.raises(studio.PublishError):
        studio.publish_from_receipt(CLI(), tmp_path, "lab")

