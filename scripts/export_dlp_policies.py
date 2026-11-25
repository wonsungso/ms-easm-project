"""Export minimal DLP policy scopes through the documented admin connector API."""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential

from easm_agent.azure import (
    BAP_DLP_URL,
    BAP_SCOPE,
    AccessError,
    Credential,
    DelegatedReaderCredential,
    ReaderHTTP,
)
from easm_agent.models import AdminEvidenceExport, AdminPolicyScope, AdminReadResult


def policy_scopes(http: ReaderHTTP) -> list[AdminPolicyScope]:
    url = BAP_DLP_URL
    seen_urls: set[str] = set()
    seen_policies: set[str] = set()
    result: list[AdminPolicyScope] = []
    while url:
        if url in seen_urls:
            raise ValueError("DLP 정책 페이지 링크가 반복되었습니다.")
        seen_urls.add(url)
        body = http.request("GET", url, BAP_SCOPE)
        rows = body.get("value")
        if not isinstance(rows, list):
            raise ValueError("DLP 정책 목록 형식을 확인할 수 없습니다.")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("DLP 정책 응답 형식 오류")
            name, scope, environments = row.get("name"), row.get("environmentType"), row.get("environments")
            if not isinstance(name, str) or not name or name.lower() in seen_policies:
                raise ValueError("DLP 정책 ID 누락·중복")
            seen_policies.add(name.lower())
            if not isinstance(scope, str) or not scope or not isinstance(environments, list):
                raise ValueError("DLP 정책의 필수 적용 범위 필드 미확인")
            ids: list[str] = []
            for environment in environments:
                if (
                    not isinstance(environment, dict) or not isinstance(environment.get("name"), str)
                    or not environment["name"]
                ):
                    raise ValueError("DLP 정책 환경 식별자 미확인")
                ids.append(environment["name"])
            result.append(AdminPolicyScope(scope_type=scope, environment_ids=ids))
        next_link = body.get("nextLink")
        if next_link is not None and not isinstance(next_link, str):
            raise ValueError("DLP 정책 페이지 링크 형식 오류")
        if next_link:
            parsed = urlparse(next_link)
            if (
                parsed.scheme != "https" or parsed.netloc != "api.bap.microsoft.com"
                or parsed.path != "/providers/PowerPlatform.Governance/v1/policies"
            ):
                raise ValueError("DLP 정책 페이지 범위 이탈")
        url = next_link or ""
    return result


def export_policies(tenant: str, credential: Credential) -> AdminEvidenceExport:
    tenant = str(uuid.UUID(tenant))
    delegated = DelegatedReaderCredential(credential, tenant, BAP_SCOPE)
    http = ReaderHTTP(delegated)
    now = datetime.now(UTC)
    policies: list[AdminPolicyScope] = []
    reason = None
    detail = "공식 ListPoliciesV2의 전체 페이지 적용 범위만 확인. 커넥터 분류·차단 효과·정책 승인 증명 아님"
    try:
        policies = policy_scopes(http)
    except AccessError as exc:
        reason, detail = exc.reason, "DLP API 읽기 실패: " + str(exc)
    except ClientAuthenticationError:
        reason, detail = "permission_denied", "DLP API 위임 사용자 토큰 확인 실패 - 원문·토큰 미저장"
    except (ValueError, KeyError, TypeError):
        reason, detail = "error", "DLP API 응답·필드·페이지 완전성 미확인 - 원문 미저장"
    finally:
        http.close()
    return AdminEvidenceExport(
        schema_version=1, source_type="official_admin_read", tenant_id=tenant,
        tenant_verified=delegated.verified, exported_at=datetime.now(UTC),
        reads=[AdminReadResult(
            source="powerplatform.dlp_policies", command=BAP_DLP_URL,
            module_version="BAP ListPoliciesV2; official PowerShell module 2.0.220 endpoint contract",
            scope="authenticated administrator-visible DLP policies; no filters; not asserted tenant-wide",
            observed_at=now, completed=reason is None, reason=reason,
            object_count=len(policies) if reason is None else None,
            policies=policies if reason is None else [], detail=detail,
        )],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=lambda value: str(uuid.UUID(value)))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--approved", required=True, action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise FileExistsError("기존 DLP 내보내기를 덮어쓰지 않습니다.")
        with AzureCliCredential(tenant_id=args.tenant_id) as credential:
            packet = export_policies(args.tenant_id, credential)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(packet.model_dump_json(indent=2))
        print(f"DLP API 내보내기: 완료={packet.reads[0].completed}; 사유={packet.reads[0].reason}")
        return 0 if packet.reads[0].completed else 2
    except (ValueError, OSError):
        print("DLP 내보내기 중단 - 계정·토큰·응답 원문 미출력", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
