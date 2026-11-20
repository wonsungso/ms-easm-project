"""Export per-environment Dataverse role-assignment counts without changing settings or exporting people."""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential

from easm_agent.azure import redact
from easm_agent.collect_admin_evidence import DATAVERSE_ROLES_COMMAND, ENVIRONMENTS_URL
from easm_agent.models import AdminEvidenceExport, AdminReadResult

PP_SCOPE = "https://api.powerplatform.com/.default"
HOST = re.compile(r"[a-z0-9-]+\.crm[0-9]*\.dynamics\.com")
# accessmode 0 read-write, 1 administrative, 2 read; 3 support, 4 non-interactive (application) and 5 delegated admin are excluded
INTERACTIVE = {0, 1, 2}
# Dataverse-side roles behind the admin center environment admin (System Administrator) and environment maker lists
ENVIRONMENT_ROLES = {"System Administrator", "Environment Maker"}


def _claims(token: str) -> dict:
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def _get(session: requests.Session, url: str) -> dict:
    response = session.get(url, timeout=(10, 90), allow_redirects=False)
    with response:
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict):
        raise ValueError("응답 형식 오류")
    return body


def count_environment(credential: AzureCliCredential, base: str) -> int:
    """Count enabled interactive users who hold the Environment Admin or Environment Maker equivalent role."""
    parsed = urlparse(base)
    if parsed.scheme != "https" or not HOST.fullmatch(parsed.hostname or "") or parsed.path not in ("", "/"):
        raise ValueError("Dataverse 환경 URL이 공용 클라우드 형식이 아닙니다.")
    base = f"https://{parsed.hostname}"
    token = credential.get_token(base + "/.default").token
    total = 0
    with requests.Session() as session:
        session.headers.update({
            "Authorization": "Bearer " + token, "Accept": "application/json",
            "OData-MaxVersion": "4.0", "OData-Version": "4.0",
        })
        url = (
            base + "/api/data/v9.2/systemusers?$select=accessmode&$filter=isdisabled eq false"
            "&$expand=systemuserroles_association($select=name)"
        )
        seen: set[str] = set()
        while url:
            if url in seen or not url.startswith(base + "/api/data/v9.2/systemusers"):
                raise ValueError("Dataverse pagination 범위 또는 반복 링크 오류")
            seen.add(url)
            body = _get(session, url)
            rows = body.get("value")
            if not isinstance(rows, list):
                raise ValueError("Dataverse 사용자 응답 형식 오류")
            for row in rows:
                roles = {item.get("name") for item in row.get("systemuserroles_association") or [] if isinstance(item, dict)}
                if row.get("accessmode") in INTERACTIVE and roles & ENVIRONMENT_ROLES:
                    total += 1
            link = body.get("@odata.nextLink")
            url = link if isinstance(link, str) else ""
    return total


def export_dataverse_roles(tenant: str) -> AdminEvidenceExport:
    tenant = str(uuid.UUID(tenant))
    now = datetime.now(UTC)
    verified, reason, counts = False, None, {}
    detail = (
        "Dataverse의 System Administrator 또는 Environment Maker 역할을 가진 사용 설정 대화형 사용자 수. 사용자·역할 이름은 내보내지 않음; "
        "응용 프로그램·지원 사용자 제외. 고유 Maker 수나 권한 적정성은 아님"
    )
    try:
        with AzureCliCredential(tenant_id=tenant) as credential, requests.Session() as session:
            token = credential.get_token(PP_SCOPE).token
            claims = _claims(token)
            if claims.get("tid", "").lower() != tenant or not claims.get("scp") or claims.get("idtyp") == "app":
                raise ValueError("별도 관리자 사용자 로그인과 대상 테넌트 확인이 필요합니다.")
            verified = True
            session.headers["Authorization"] = "Bearer " + token
            body = _get(session, ENVIRONMENTS_URL)
            if body.get("@odata.nextlink") or body.get("@odata.nextLink"):
                raise ValueError("환경 목록이 불완전합니다.")
            for row in body.get("value") or []:
                if str(row.get("tenantId", "")).lower() != tenant:
                    raise ValueError("응답 환경의 테넌트를 확인하지 못했습니다.")
                if row.get("url"):
                    counts[str(row["id"])] = count_environment(credential, str(row["url"]))
    except ClientAuthenticationError:
        reason, detail = "permission_denied", "별도 관리자 토큰을 얻지 못함. 토큰·원문 오류 미저장"
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        reason = "permission_denied" if status in (401, 403) else "error"
        detail = f"Dataverse 조회 실패: HTTP {status}"
    except requests.RequestException as exc:
        reason, detail = "error", "Dataverse 조회 실패: " + type(exc).__name__
    observed = datetime.now(UTC)
    ok = reason is None
    return AdminEvidenceExport(
        schema_version=1, source_type="official_admin_read", tenant_id=tenant, tenant_verified=verified,
        exported_at=observed,
        reads=[AdminReadResult(
            source="powerplatform.dataverse_roles", command=DATAVERSE_ROLES_COMMAND,
            module_version="Dataverse Web API v9.2",
            scope="Dataverse-linked environments visible to the administrator; not asserted tenant-wide",
            observed_at=now, completed=ok, object_count=sum(counts.values()) if ok else None,
            role_counts=counts if ok else {}, reason=reason, detail=detail,
        )],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=lambda value: str(uuid.UUID(value)))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise FileExistsError("기존 관리자 내보내기를 덮어쓰지 않습니다.")
        result = export_dataverse_roles(args.tenant_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(redact(result.model_dump(mode="json")), ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(f"Dataverse 역할 건수 내보내기: {args.output}; 완료={result.reads[0].completed}")
        return 0 if result.reads[0].completed else 2
    except (ValueError, KeyError, IndexError, OSError) as exc:
        print(f"Dataverse 역할 내보내기 중단: {type(exc).__name__}. 응답·계정·토큰 원문은 출력하지 않았습니다.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

