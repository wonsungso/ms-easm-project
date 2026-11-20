"""별도 관리자 사용자의 기존 Azure CLI 로그인으로 공식 Copilot 인벤토리를 읽는다."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential

from easm_agent.azure import (
    PP_INVENTORY_URL,
    PP_SCOPE,
    AccessError,
    Credential,
    DelegatedReaderCredential,
    ReaderHTTP,
    redact,
)
from easm_agent.collect_copilot import CopilotInventoryExport, CopilotInventoryRow

# Project only documented fields; the service reduces ownerId to a nullable boolean.
PROJECTION = {
    "agent_id": "name",
    "dataverse_agent_id": "properties.name",
    "environment_id": "properties.environmentId",
    "display_name": "properties.displayName",
    "created_in": "properties.createdIn",
    "created_at": "properties.createdAt",
    "last_published_at": "properties.lastPublishedAt",
    "owner_present": "iff(isnull(properties.ownerId), bool(null), isnotempty(properties.ownerId))",
    "entra_agent_id": "properties.entraAgentId",
    "blueprint_id": "properties.entraAgentBlueprintId",
    "model": "properties.model",
    "authentication": "properties.authentication",
    "channels": "properties.channels",
    "is_quarantined": "properties.isQuarantined",
    "shared_with_tenant": "properties.sharedWithViewers.entireTenant",
}


DelegatedCredential = DelegatedReaderCredential


def inventory_pages(http: ReaderHTTP) -> list[CopilotInventoryRow]:
    agents: list[CopilotInventoryRow] = []
    seen_tokens: set[str] = set()
    seen_ids: set[tuple[str, str]] = set()
    skip = None
    expected_total = None
    while True:
        options: dict[str, Any] = {"Top": 1000}
        if skip:
            options["SkipToken"] = skip
        payload = http.request("POST", PP_INVENTORY_URL, PP_SCOPE, {
            "TableName": "PowerPlatformResources",
            "Clauses": [
                {"$type": "where", "FieldName": "type", "Operator": "==",
                 "Values": ["'microsoft.copilotstudio/agents'"]},
                {"$type": "project", "FieldList": [
                    f"{alias} = {expression}" for alias, expression in PROJECTION.items()
                ]},
            ],
            "Options": options,
        })
        count, total, rows = payload.get("count"), payload.get("totalRecords"), payload.get("data")
        truncated, next_token = payload.get("resultTruncated"), payload.get("skipToken")
        if (
            type(count) is not int or count < 0 or type(total) is not int or total < 0
            or not isinstance(rows, list) or count != len(rows)
            or type(truncated) is not int or truncated not in (0, 1)
            or (next_token is not None and not isinstance(next_token, str))
        ):
            raise ValueError("인벤토리 페이지 메타데이터 형식 오류")
        if expected_total is not None and total != expected_total:
            raise ValueError("인벤토리 페이지별 전체 건수 불일치")
        expected_total = total
        is_truncated = truncated == 0
        for row in rows:
            # Validate before saving; extra fields (including PII) are never accepted.
            if isinstance(row, dict):
                row = row.copy()
                dataverse_id = row.pop("dataverse_agent_id", None)
                if dataverse_id is not None:
                    row["agent_id"] = dataverse_id
                if type(row.get("owner_present")) is int and row["owner_present"] in (0, 1):
                    row["owner_present"] = bool(row["owner_present"])
            agent = CopilotInventoryRow.model_validate_json(json.dumps(row))
            identity = (agent.environment_id.lower(), agent.agent_id)
            if identity in seen_ids:
                raise ValueError("인벤토리 에이전트 식별자 중복")
            seen_ids.add(identity)
            agents.append(agent)
        if len(agents) > total:
            raise ValueError("인벤토리 전체 건수 초과")
        if not next_token:
            if is_truncated or len(agents) != total:
                raise ValueError("인벤토리 연속 페이지 누락 또는 전체 건수 불일치")
            return agents
        if not is_truncated or not count or next_token in seen_tokens or len(agents) >= total:
            raise ValueError("인벤토리 연속 페이지 반복 또는 건수 불일치")
        seen_tokens.add(next_token)
        skip = next_token


def export_inventory(
    tenant: str, credential: Credential, *, approved: bool,
) -> CopilotInventoryExport:
    tenant = str(uuid.UUID(tenant))
    if not approved:
        raise ValueError("별도 관리자 읽기 내보내기 승인이 필요합니다.")
    delegated = DelegatedCredential(credential, tenant)
    http = ReaderHTTP(delegated, store=None)
    agents = []
    reason = None
    failure_code = None
    try:
        agents = inventory_pages(http)
    except AccessError as exc:
        reason = exc.reason
        failure_code = "network_error" if str(exc).startswith("network_error") else exc.reason
    except ClientAuthenticationError:
        reason = "permission_denied"
        failure_code = "authentication_error"
    except (ValueError, TypeError, KeyError, OverflowError):
        reason = "error"
        failure_code = "invalid_response"
    finally:
        http.close()
    now = datetime.now(UTC)
    payload = {
        "schema_version": 1, "source_type": "official_admin_read", "approved": True,
        "command": PP_INVENTORY_URL, "auth_type": "delegated_user", "tenant_id": tenant,
        "tenant_verified": delegated.verified, "observed_at": now.isoformat(),
        "exported_at": now.isoformat(), "completed": reason is None,
        "object_count": len(agents) if reason is None else None,
        "total_records": len(agents) if reason is None else None, "reason": reason,
        "failure_code": failure_code,
        "agents": [agent.model_dump(mode="json") for agent in agents] if reason is None else [],
    }
    return CopilotInventoryExport.model_validate_json(json.dumps(redact(payload)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=lambda value: str(uuid.UUID(value)))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approved", action="store_true", required=True,
                        help="별도 관리자 사용자 읽기 내보내기 승인 - 진단 SP에 역할 부여 금지")
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise FileExistsError("기존 내보내기를 덮어쓰지 않습니다.")
        with AzureCliCredential(tenant_id=args.tenant_id) as credential:
            result = export_inventory(args.tenant_id, credential, approved=args.approved)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(result.model_dump_json(indent=2))
        print(f"Copilot 인벤토리 내보내기: 완료={result.completed}; 사유={result.reason}")
        return 0 if result.completed else 2
    except (ValueError, OSError):
        print("Copilot 내보내기 중단 - 응답 - 계정 - 토큰 원문 미출력", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
