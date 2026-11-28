"""별도 관리자 사용자의 기존 Azure CLI 로그인으로 공식 Copilot 인벤토리를 읽는다."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential, DeviceCodeCredential

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
from easm_agent.models import CopilotConnectorOperation, CopilotEvaluationRead, CopilotEvaluationRun

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
    "harness": "properties.harness",
    "orchestration": "properties.orchestration",
    "connector_count": "properties.capabilitiesCounts.distinctPowerPlatformConnectors",
    "connector_operation_count": "properties.capabilitiesCounts.distinctPowerPlatformConnectorsOperations",
    "raw_connectors": "properties.powerPlatformConnectors",
}


DelegatedCredential = DelegatedReaderCredential


def read_empty_evaluations_cli(
    executable: Path, project: Path, tenant: str, agent: CopilotInventoryRow,
) -> CopilotEvaluationRead:
    def read(*args: str) -> dict:
        process = subprocess.run(
            [str(executable), *args, "--json", "--non-interactive"],
            capture_output=True, text=True, encoding="utf-8", check=False, timeout=120,
        )
        if process.returncode:
            raise ValueError("공식 CLI 평가 읽기 실패")
        result = json.loads(process.stdout)
        if result.get("success") is not True or result.get("schemaVersion") != 1:
            raise ValueError("공식 CLI 평가 응답 형식 오류")
        return result

    try:
        auth = read("auth", "status")
        if auth.get("signedIn") is not True or auth.get("tenantId", "").casefold() != tenant.casefold():
            raise ValueError("공식 CLI 읽기 테넌트 불일치")
        local = read("agent", "show", "--project", str(project), "--agent-name", agent.display_name or "")
        bindings = [
            row for row in local.get("agents", [])
            if row.get("mcsAgentId", "").casefold() == agent.agent_id.casefold()
            and row.get("environmentId", "").casefold() == agent.environment_id.casefold()
            and row.get("tenantId", "").casefold() == tenant.casefold()
        ]
        if len(bindings) != 1:
            raise ValueError("공식 CLI 평가 대상 연결 불일치")
        result = read(
            "agent", "eval", "list", "--project", str(project), "--agent-id", bindings[0]["agentId"],
            "--environment-id", agent.environment_id,
        )
        if result.get("status") != "evaluations-listed" or result.get("truncated") is not False or (
            result.get("mcsAgentId", "").casefold() != agent.agent_id.casefold()
            or result.get("environmentId", "").casefold() != agent.environment_id.casefold()
        ):
            raise ValueError("공식 CLI 평가 목록의 범위·완전성 불일치")
        if result.get("runs") != []:
            return CopilotEvaluationRead(completed=False, reason="feature_unavailable")
        return CopilotEvaluationRead(completed=True, runs=[])
    except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired):
        return CopilotEvaluationRead(completed=False, reason="error")


def connector_operations(payload: Any) -> list[CopilotConnectorOperation] | None:
    if payload is None:
        return None
    if not isinstance(payload, list) or len(payload) > 200:
        raise ValueError("Copilot 커넥터 목록의 형식·크기 오류")
    result = []
    for connector in payload:
        if not isinstance(connector, dict) or not isinstance(connector.get("operations"), list):
            raise ValueError("Copilot 커넥터 작업 목록 형식 오류")
        for operation in connector["operations"]:
            if not isinstance(operation, dict) or len(result) >= 200:
                raise ValueError("Copilot 커넥터 작업의 형식·크기 오류")
            result.append(CopilotConnectorOperation.model_validate({
                "connector_id": connector.get("connectorId"),
                "operation_id": operation.get("operationId"),
                **{field: operation.get(source) for field, source in (
                    ("is_enabled", "isEnabled"), ("requires_end_user_consent", "requiresEndUserConsent"),
                    ("connection_provider", "connectionProvider"), ("when_can_be_used", "whenCanBeUsed"),
                )},
            }))
    return result


def read_evaluations(http: ReaderHTTP, agent: CopilotInventoryRow) -> CopilotEvaluationRead:
    url = (
        "https://api.powerplatform.com/copilotstudio/environments/"
        + quote(agent.environment_id, safe="") + "/bots/" + agent.agent_id
        + "/api/makerevaluation/testruns?api-version=2024-10-01"
    )
    try:
        payload = http.request("GET", url, PP_SCOPE)
        rows = payload.get("value")
        if not isinstance(rows, list) or payload.get("@odata.nextLink") or payload.get("@odata.nextlink"):
            raise ValueError("Copilot 평가 목록 응답 또는 페이지 완전성 미확인")
        runs = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Copilot 평가 실행 응답 형식 오류")
            identifier = str(uuid.UUID(row["id"]))
            if identifier in seen:
                raise ValueError("Copilot 평가 실행 ID 중복")
            seen.add(identifier)
            runs.append(CopilotEvaluationRun.model_validate_json(json.dumps({
                "run_id": identifier, "state": row.get("state"),
                "end_time": row.get("endTime"), "total_test_cases": row.get("totalTestCases"),
            })))
        return CopilotEvaluationRead(completed=True, runs=runs)
    except AccessError as exc:
        return CopilotEvaluationRead(completed=False, reason=exc.reason)
    except ClientAuthenticationError:
        return CopilotEvaluationRead(completed=False, reason="permission_denied")
    except (ValueError, TypeError, KeyError):
        return CopilotEvaluationRead(completed=False, reason="error")


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
                if "raw_connectors" in row:
                    row["connector_operations"] = [
                        item.model_dump(mode="json") for item in operations
                    ] if (operations := connector_operations(row.pop("raw_connectors"))) is not None else None
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
    tenant: str, credential: Credential, *, approved: bool, include_evaluations: bool = False,
    evaluation_credential: Credential | None = None,
    evaluation_cli: Path | None = None, evaluation_project: Path | None = None,
) -> CopilotInventoryExport:
    tenant = str(uuid.UUID(tenant))
    if not approved:
        raise ValueError("별도 관리자 읽기 내보내기 승인이 필요합니다.")
    delegated = DelegatedCredential(credential, tenant)
    http = ReaderHTTP(delegated, store=None)
    evaluation_http = (
        ReaderHTTP(DelegatedCredential(evaluation_credential, tenant), store=None)
        if include_evaluations and evaluation_credential is not None else http
    )
    agents = []
    reason = None
    failure_code = None
    try:
        agents = inventory_pages(http)
        if include_evaluations:
            for agent in agents:
                if agent.harness == "Standard" or evaluation_credential is not None:
                    agent.evaluation_read = read_evaluations(evaluation_http, agent)
                    if evaluation_cli is not None and evaluation_project is not None and (
                        not agent.evaluation_read.completed and agent.evaluation_read.reason == "permission_denied"
                    ):
                        agent.evaluation_read = read_empty_evaluations_cli(
                            evaluation_cli, evaluation_project, tenant, agent,
                        )
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
        if evaluation_http is not http:
            evaluation_http.close()
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
    parser.add_argument("--include-evaluations", action="store_true",
                        help="기존 평가 목록만 GET 조회 - 새 평가 실행 없음")
    parser.add_argument("--evaluation-client-id", type=lambda value: str(uuid.UUID(value)),
                        help="MakerOperations.Read가 구성된 별도 사용자 위임 읽기 앱 - 기기 코드 로그인")
    parser.add_argument("--evaluation-cli", type=Path, help="이미 인증된 공식 msagent 실행 파일")
    parser.add_argument("--evaluation-project", type=Path, help="평가 대상과 연결된 기존 msagent 작업 사본")
    args = parser.parse_args(argv)
    if args.evaluation_client_id and not args.include_evaluations:
        parser.error("--evaluation-client-id에는 --include-evaluations가 필요합니다.")
    if bool(args.evaluation_cli) != bool(args.evaluation_project) or (
        args.evaluation_cli and not args.include_evaluations
    ):
        parser.error("CLI 평가 읽기는 --include-evaluations·--evaluation-cli·--evaluation-project가 함께 필요합니다.")
    try:
        if args.output.exists():
            raise FileExistsError("기존 내보내기를 덮어쓰지 않습니다.")
        with ExitStack() as stack:
            credential = stack.enter_context(AzureCliCredential(tenant_id=args.tenant_id))
            evaluation_credential = stack.enter_context(DeviceCodeCredential(
                tenant_id=args.tenant_id, client_id=args.evaluation_client_id,
            )) if args.evaluation_client_id else None
            result = export_inventory(
                args.tenant_id, credential, approved=args.approved, include_evaluations=args.include_evaluations,
                evaluation_credential=evaluation_credential,
                evaluation_cli=args.evaluation_cli, evaluation_project=args.evaluation_project,
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(result.model_dump_json(indent=2))
        failed_evaluations = sum(
            agent.evaluation_read is not None and not agent.evaluation_read.completed for agent in result.agents
        )
        print(
            f"Copilot 인벤토리 내보내기: 완료={result.completed}; 사유={result.reason}; "
            f"별도 평가 읽기 실패={failed_evaluations}"
        )
        return 0 if result.completed and not failed_evaluations else 2
    except (ValueError, OSError):
        print("Copilot 내보내기 중단 - 응답 - 계정 - 토큰 원문 미출력", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
