"""별도 승인된 관리자 사용자의 읽기 전용 보고서 증적 내보내기."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential

from easm_agent.azure import (
    MSGRAPH,
    MSGRAPH_SCOPE,
    AccessError,
    Credential,
    DelegatedReaderCredential,
    ReaderHTTP,
)
from easm_agent.models import BooleanControlEvidence, BooleanControlRecord, Reason
from easm_agent.report_evidence import ReportEvidenceExport

AGENTS_URL = MSGRAPH + "/v1.0/servicePrincipals/microsoft.graph.agentIdentity?$select=id"
POLICIES_URL = MSGRAPH + "/beta/identity/conditionalAccess/policies?$select=id,state,conditions"


def explicit_policy_targets(agents: list[dict], policies: list[dict]) -> list[BooleanControlRecord]:
    identifiers = [str(uuid.UUID(row["id"])) for row in agents]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("중복 Agent ID")
    policy_ids = [str(uuid.UUID(row["id"])) for row in policies]
    if len(set(policy_ids)) != len(policy_ids):
        raise ValueError("중복 정책 ID")
    records = []
    for identifier in identifiers:
        matched, unresolved = [], []
        for policy, policy_id in zip(policies, policy_ids, strict=True):
            state = policy.get("state")
            if state in ("disabled", "enabledForReportingButNotEnforced"):
                continue
            if state != "enabled":
                unresolved.append(policy_id)
                continue
            conditions = policy.get("conditions")
            if not isinstance(conditions, dict):
                raise ValueError("정책 조건 응답 형식 오류")
            targets = conditions.get("clientApplications")
            if targets is None and isinstance(conditions.get("users"), dict):
                continue
            if not isinstance(targets, dict):
                unresolved.append(policy_id)
                continue
            included = targets.get("includeAgentIdServicePrincipals")
            excluded = targets.get("excludeAgentIdServicePrincipals")
            if (
                not isinstance(included, list) or not all(isinstance(value, str) for value in included)
                or not isinstance(excluded, list) or not all(isinstance(value, str) for value in excluded)
            ):
                unresolved.append(policy_id)
                continue
            if identifier in [value.lower() for value in excluded]:
                continue
            if targets.get("agentIdServicePrincipalFilter"):
                unresolved.append(policy_id)
                continue
            try:
                included_ids = {str(uuid.UUID(value)) for value in included}
                {str(uuid.UUID(value)) for value in excluded}
            except ValueError:
                # "All" and undocumented selectors are not a proven ID match.
                unresolved.append(policy_id)
                continue
            if identifier in included_ids:
                matched.append(policy_id)
            elif any(targets.get(key) for key in ("includeServicePrincipals", "servicePrincipalFilter")):
                unresolved.append(policy_id)
        records.append(BooleanControlRecord(
            subject=identifier, value=True if matched else None if unresolved else False,
            evidence_ids=sorted(set(matched if matched else unresolved)),
        ))
    return records


def export_conditional_access(
    tenant: str, credential: Credential, *, approved: bool, now: datetime | None = None,
) -> ReportEvidenceExport:
    if not approved:
        raise ValueError("별도 관리자 읽기 승인이 필요합니다.")
    delegated = DelegatedReaderCredential(credential, tenant, MSGRAPH_SCOPE)
    http = ReaderHTTP(delegated, store=None)
    records: list[BooleanControlRecord] = []
    reason: Reason | None = None
    try:
        records = explicit_policy_targets(http.list_graph(AGENTS_URL), http.list_graph(POLICIES_URL))
    except AccessError as exc:
        reason = exc.reason
    except ClientAuthenticationError:
        reason = "permission_denied"
    except (ValueError, KeyError, TypeError, AttributeError):
        reason = "error"
    finally:
        http.close()
    instant = now or datetime.now(UTC)
    return ReportEvidenceExport(
        schema_version=1, source_type="approved_report_evidence", approved=True, tenant_id=tenant,
        tenant_verified=delegated.verified, data_mode="live", exported_at=instant,
        datasets=[BooleanControlEvidence(
            kind="target_controls", code="OE-SY-30", source_kind="official_admin_read",
            source_ref="graph-beta-agent-conditional-access",
            scope="조회 가능한 Entra Agent ID 서비스 주체의 명시적 enabled 정책 대상 구성",
            observed_at=instant, complete=reason is None, population_complete=reason is None,
            reason=reason, records=records,
        )],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", action="store_true", help="전체 추가 보고서 증적 JSON Schema 출력 - API 호출 없음")
    parser.add_argument("--tenant-id")
    parser.add_argument("--conditional-access", action="store_true")
    parser.add_argument("--approved", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.schema:
        print(json.dumps(ReportEvidenceExport.model_json_schema(), ensure_ascii=False, indent=2))
        return 0
    if not (args.conditional_access and args.tenant_id and args.approved and args.output):
        parser.error("--conditional-access --tenant-id --approved --output이 필요합니다.")
    try:
        tenant = str(uuid.UUID(args.tenant_id))
        if args.output.exists():
            raise FileExistsError("기존 증적을 덮어쓰지 않습니다.")
        with AzureCliCredential(tenant_id=tenant) as credential:
            export = export_conditional_access(tenant, credential, approved=args.approved)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as target:
            target.write(export.model_dump_json(indent=2))
        print("조건부 접근 읽기: " + ("완료" if export.datasets[0].complete else export.datasets[0].reason))
        return 0 if export.datasets[0].complete else 2
    except (ValueError, OSError) as exc:
        print("내보내기 실패: " + type(exc).__name__ + " - 원문·토큰 미출력", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
