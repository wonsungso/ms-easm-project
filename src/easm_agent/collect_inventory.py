from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from easm_agent.azure import (
    ARM,
    GRAPH_URL,
    AccessError,
    ReaderHTTP,
    rejects_broad_permissions,
)
from easm_agent.models import AgentEvidence, Collection

RESOURCE_TYPES = (
    "microsoft.cognitiveservices/accounts", "microsoft.cognitiveservices/accounts/projects",
    "microsoft.cognitiveservices/accounts/deployments",
    "microsoft.operationalinsights/workspaces",
)


class InventoryCollector:
    required_roles = ("Reader",)

    def __init__(self, http: ReaderHTTP, now: datetime) -> None:
        self.http = http
        self.now = now

    def discover(self, subscriptions: Sequence[str]) -> Collection:
        result = Collection(collected_at=self.now, subscriptions=list(subscriptions))
        for sid in subscriptions:
            scope = f"/subscriptions/{sid}"
            permissions = self.http.list_arm(
                ARM + scope + "/providers/Microsoft.Authorization/permissions?api-version=2022-04-01"
            )
            if rejects_broad_permissions(permissions):
                raise AccessError("permission_denied", "광범위 쓰기 권한 탐지; 진단 Reader 계정으로 실행해야 함")
            types = ",".join(f"'{value}'" for value in RESOURCE_TYPES)
            query = (
                f"Resources | where type in~ ({types}) "
                "| project id,name,type,kind,resourceGroup,subscriptionId,location,tags,"
                "properties=pack('endpoint',properties.endpoint,'endpoints',properties.endpoints,"
                "'defaultHostName',properties.defaultHostName,'retentionInDays',properties.retentionInDays,"
                "'customerId',properties.customerId,'serverFarmId',properties.serverFarmId)"
            )
            options: dict[str, Any] = {"resultFormat": "objectArray", "$top": 1000}
            seen = set()
            scope_refs = []
            while True:
                page = self.http.request("POST", GRAPH_URL, body={
                    "subscriptions": [sid], "query": query, "options": options,
                })
                if self.http.last_ref:
                    scope_refs.append(self.http.last_ref)
                rows = page.get("data")
                if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                    raise AccessError("error", "Resource Graph data 배열 형식 불일치")
                for row in rows:
                    if row.get("subscriptionId", "").lower() != sid:
                        raise AccessError("error", "요청 구독 밖 Resource Graph 응답")
                    result.facts.setdefault("inventory_evidence", []).append({
                        "resource_id": row["id"],
                        "evidence_refs": [self.http.last_ref] if self.http.last_ref else [],
                    })
                result.resources.extend(rows)
                continuation = page.get("$skipToken")
                if not continuation:
                    if str(page.get("resultTruncated", "false")).lower() == "true":
                        raise AccessError("error", "Resource Graph 결과 잘림; 연속 토큰 없음")
                    break
                if continuation in seen:
                    raise AccessError("error", "Resource Graph 페이지 토큰 반복")
                seen.add(continuation)
                options["$skipToken"] = continuation
            result.facts.setdefault("inventory_scope_evidence", []).append({
                "subscription_id": sid, "complete": True, "evidence_refs": scope_refs,
            })
            result.completed_subscriptions.append(sid)
        result.facts["inventory_complete"] = True
        return result


class ManualCollector:
    required_roles: tuple[str, ...] = ()

    def __init__(self, path: Path, now: datetime) -> None:
        self.path, self.now = path, now

    def discover(self, subscriptions: Sequence[str]) -> Collection:
        result = Collection(collected_at=self.now)
        with self.path.open(encoding="utf-8-sig", newline="") as stream:
            for number, row in enumerate(csv.DictReader(stream), 2):
                values = {key: value for key, value in row.items() if value not in ("", None)}
                if values.get("platform", "manual") not in ("manual", "other"):
                    raise ValueError(f"{self.path.name}:{number}: manual/other 플랫폼만 허용")
                for key in ("tags", "tools", "usage_30d", "field_status", "evidence_refs", "se_codes",
                            "cost_resource_ids"):
                    if key in values:
                        values[key] = json.loads(values[key])
                values.setdefault("platform", "manual")
                values.setdefault("collected_at", self.now)
                values.setdefault("detection_confidence", "manual")
                values.setdefault("evidence_refs", [str(self.path.resolve()) + f"#row-{number}"])
                try:
                    result.agents.append(AgentEvidence.model_validate(values).mark_unknowns(
                        "수동 등록 파일에 값이 없음; Azure API로 보완하지 않음",
                    ))
                except ValidationError as exc:
                    raise ValueError(f"{self.path.name}:{number}: 공통 스키마 검증 실패") from exc
        return result
