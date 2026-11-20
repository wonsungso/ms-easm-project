from __future__ import annotations

import math
import re
import time
import uuid
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote

from azure.core.exceptions import ClientAuthenticationError

from easm_agent.api_grading import agent_has_entra_identity
from easm_agent.azure import MSGRAPH, MSGRAPH_SCOPE, AccessError, EvidenceStore, ReaderHTTP, issue
from easm_agent.models import (
    AZURE_AGENT_PLATFORMS,
    Agent365Crosscheck,
    Agent365Package,
    Collection,
    FieldStatus,
)

REGISTRY_URL = MSGRAPH + "/v1.0/copilot/admin/catalog/packages"
DETAIL_FIELDS = {
    "active_users_30d": "activeUsers",
    "total_sessions_30d": "totalSessions",
    "total_run_time_hours_30d": "totalRunTimeInHours",
    "exception_count_30d": "exceptionRate",
    "last_used_at": "lastUsedDateTime",
}
GOVERNANCE_TYPES = {"PromptAgent", "HostedAgent", "WorkflowAgent", "ManagedAgent", "Unmanaged", "AIApp"}
METADATA_FIELDS = {
    "package_type": "type", "manifest_version": "manifestVersion", "app_id": "appId",
    "supported_hosts": "supportedHosts", "element_types": "elementTypes",
    "categories": "categories", "sensitivity": "sensitivity",
}
DERIVED_METADATA_FIELDS = ("category_count", "sensitivity_present")
ALL_METADATA_FIELDS = (*METADATA_FIELDS, *DERIVED_METADATA_FIELDS)
CATALOG_METADATA_FIELDS = tuple(field for field in METADATA_FIELDS if field not in ("categories", "sensitivity"))
# This is a local privacy allowlist of documented examples, not an API enumeration.
SAFE_METADATA_LABELS = {
    "package_type": frozenset(("microsoft", "external", "shared", "custom")),
    "supported_hosts": frozenset((
        "teams", "outlook", "sharepoint", "word", "excel", "powerpoint", "copilot", "m365",
    )),
    "element_types": frozenset((
        "bot", "bots", "declarativeagent", "customengineagent", "officeaddin", "officeaddins",
        "agentconnectors", "agentskills", "declarativecopilots", "customenginecopilots",
    )),
    "categories": frozenset(("development", "productivity", "tools")),
    "sensitivity": frozenset(("general",)),
}
DETAIL_TIME_BUDGET_SECONDS = 600
DETAIL_FAILURE_LIMIT = 5
STATUS_LABELS = {
    "partial_match": "일부 일치",
    "mismatch": "불일치",
    "unavailable": "미확인",
    "not_comparable": "동일 정보 미제공",
}
LIMITS = {
    "DS-SY-04": "호출 모델 정보와 Azure 배포 버전·업데이트 옵션은 다른 필드",
    "DS-SY-05": "등록부에 Azure 인바운드 경계 설정 없음",
    "DS-SY-06": "등록부에 Foundry MCP require_approval 설정 없음",
    "DS-SY-07": "등록부에 Foundry 전체 외부 도구 URL 선언 없음",
    "BI-SY-09": "등록부에 Foundry 평가 실행 이력 없음",
    "BI-SY-10": "등록부에 Azure 보안 권고 상태 없음",
    "BI-SY-11": "등록부에 Azure 콘텐츠 필터 정책 연결·활성 필터 없음",
    "BI-SY-12": "패키지 version과 Foundry 버전·호스트 런타임은 다른 필드",
    "BI-SY-13": "등록부에 동일 Azure Agent의 owner·sponsor·env·cost-center 전체 없음",
    "BI-SY-14": "등록부에 Azure Policy 리소스별 평가 없음",
    "OE-SY-16": "owners·sponsors는 기존 Graph와 동일 원천, 등록부에 독립 대조 필드 없음",
    "OE-SY-17": "앱 역할은 기존 Graph와 동일 원천, 등록부에 독립 대조 필드 없음",
    "OE-SY-18": "활동 계측과 Azure 진단 설정·workspace 연결은 다른 증거",
    "OE-SY-19": "등록부에 Azure 관리 ID·키 인증·직접 ARM 역할 구성 없음",
    "OE-SY-20": "등록부에 Azure 경보의 실제 대상 범위 없음",
    "OE-SY-21": "등록부에 Azure 작업 그룹·수신자 연결 없음",
    "OE-SY-22": "테넌트 저장 지역과 Azure 리소스 지역·workspace 보존기간은 다른 증거",
    "OT-SY-23": "활동 통계와 Azure 리소스 메트릭 표본은 다른 증거",
    "OT-SY-24": "토큰·활동 통계와 Cost Management 실제 비용은 다른 증거",
    "OT-SY-25": "등록부에 Azure 구독의 Defender for Cloud 플랜 구성 없음",
    "OT-SY-26": "등록부에 Azure 구독 예산·실제/예측 경보 설정 없음",
}


def read_metadata(
    package: Agent365Package, payload: dict[str, Any], source: Literal["catalog", "detail"],
) -> set[str]:
    updated = set()
    fields = CATALOG_METADATA_FIELDS if source == "catalog" else tuple(METADATA_FIELDS)
    for field in fields:
        key = METADATA_FIELDS[field]
        if source == "detail" and key not in payload and package.metadata_field_sources.get(field) == "catalog":
            continue
        value = payload.get(key)
        reason = None
        if value is None:
            reason = "not_found"
        elif field in ("categories", "supported_hosts", "element_types"):
            if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                reason = "error"
        elif not isinstance(value, str):
            reason = "error"
        elif not value.strip():
            reason = "not_found"

        derived = {"categories": "category_count", "sensitivity": "sensitivity_present"}.get(field)
        if derived:
            setattr(package, derived, (len(value) if field == "categories" else True) if reason is None else None)
            package.metadata_field_sources[derived] = source
            package.field_status.pop(derived, None)
            if reason:
                package.field_status[derived] = FieldStatus(
                    reason=reason, detail="공식 분류 필드 누락·형식 오류 - 원문 미저장",
                )
            updated.add(derived)

        if reason is None:
            if field == "app_id":
                try:
                    value = str(uuid.UUID(value))
                except ValueError:
                    reason = "error"
            elif field == "manifest_version":
                if len(value) > 32 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value):
                    reason = "feature_unavailable"
            else:
                values = value if isinstance(value, list) else [value]
                if len(values) > 64 or any(
                    (item if field == "package_type" else item.casefold()) not in SAFE_METADATA_LABELS[field]
                    for item in values
                ):
                    reason = "feature_unavailable"
        setattr(package, field, None if reason else value)
        package.metadata_field_sources[field] = source
        package.field_status.pop(field, None)
        if reason:
            package.field_status[field] = FieldStatus(
                reason=reason,
                detail=(
                    "공식 응답에 필드 없음 또는 빈 값" if reason == "not_found" else
                    "공식 필드 형식 불일치 - 원문 미저장" if reason == "error" else
                    "공식 예시·안전한 기술 형식의 로컬 허용 범위 밖 - 미확인 문자열 미저장"
                ),
            )
        updated.add(field)
    package.metadata_complete = all(
        getattr(package, field) is not None and field not in package.field_status
        for field in METADATA_FIELDS
    )
    return updated


def metadata_projection(package: Agent365Package, fields: set[str]) -> dict[str, Any]:
    return {
        "values": {field: getattr(package, field) for field in sorted(fields)},
        "field_status": {
            field: package.field_status[field].model_dump()
            for field in sorted(fields) if field in package.field_status
        },
        "field_sources": {field: package.metadata_field_sources[field] for field in sorted(fields)},
    }


class Agent365Collector:
    """Read catalog references and documented aggregate usage, never agent content."""

    required_roles = ("CopilotPackages.Read.All",)

    def __init__(self, http: ReaderHTTP, now: datetime, store: EvidenceStore | None = None) -> None:
        if http.store is not None:
            raise ValueError("Agent 365 원본 응답은 최소 필드 선별 전에 저장할 수 없습니다.")
        self.http, self.now, self.store = http, now, store

    def discover(self) -> Collection:
        result = Collection(collected_at=self.now, facts={
            "agent365_requested": True, "agent365_registry_complete": False,
        })
        try:
            rows = self.http.list_graph(REGISTRY_URL)
            packages = []
            seen = set()
            for row in rows:
                identifier = row.get("id")
                if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
                    raise AccessError("error", "Agent 365 패키지 ID 누락·중복 또는 형식 오류")
                seen.add(identifier)
                identity = row.get("agentIdentityId")
                if identity is not None:
                    try:
                        identity = str(uuid.UUID(identity)) if isinstance(identity, str) else None
                    except ValueError as exc:
                        raise AccessError("error", "Agent 365 agentIdentityId 형식 오류") from exc
                    if identity is None:
                        raise AccessError("error", "Agent 365 agentIdentityId 형식 오류")
                version = row.get("version")
                if version is not None and not isinstance(version, str):
                    raise AccessError("error", "Agent 365 패키지 version 형식 오류")
                text_fields = {
                    "display_name": "displayName", "platform": "platform",
                    "available_to": "availableTo", "deployed_to": "deployedTo",
                    "manifest_id": "manifestId", "request_type": "requestType",
                }
                for source in text_fields.values():
                    if row.get(source) is not None and not isinstance(row[source], str):
                        raise AccessError("error", f"Agent 365 {source} 형식 오류")
                if row.get("isBlocked") is not None and type(row["isBlocked"]) is not bool:
                    raise AccessError("error", "Agent 365 isBlocked 형식 오류")
                if row.get("requestStatus") is not None and not isinstance(row["requestStatus"], str):
                    raise AccessError("error", "Agent 365 requestStatus 형식 오류")
                governance = row.get("governanceMetadata")
                # Live responses wrap the documented enum as {"agenticType": "<value>"}; unknown shapes stay errors.
                if (
                    isinstance(governance, dict) and set(governance) == {"agenticType"}
                    and governance["agenticType"] in GOVERNANCE_TYPES
                ):
                    governance = governance["agenticType"]
                invalid_governance = governance is not None and not isinstance(governance, str)
                owners = row.get("owners")
                if owners is not None and not isinstance(owners, list):
                    raise AccessError("error", "Agent 365 owners 형식 오류")
                created = row.get("createdDateTime")
                if created is not None:
                    try:
                        created = datetime.fromisoformat(created.replace("Z", "+00:00")) if isinstance(created, str) else None
                    except ValueError:
                        created = None
                    if created is None or created.tzinfo is None:
                        raise AccessError("error", "Agent 365 createdDateTime 형식 오류")
                modified = row.get("lastModifiedDateTime")
                if modified is not None:
                    try:
                        modified = datetime.fromisoformat(modified.replace("Z", "+00:00")) if isinstance(modified, str) else None
                    except ValueError as exc:
                        raise AccessError("error", "Agent 365 lastModifiedDateTime 형식 오류") from exc
                    if modified is None or modified.tzinfo is None:
                        raise AccessError("error", "Agent 365 lastModifiedDateTime 형식 오류")
                package = Agent365Package(
                    package_id=identifier, agent_identity_id=identity, version=version,
                    display_name=row.get("displayName"), platform=row.get("platform"),
                    available_to=row.get("availableTo"), deployed_to=row.get("deployedTo"),
                    is_blocked=row.get("isBlocked"), created_at=created, request_status=row.get("requestStatus"),
                    governance=None if invalid_governance else governance,
                    owner_count=len(owners) if owners is not None else None,
                    manifest_id=row.get("manifestId"), request_type=row.get("requestType"), last_modified_at=modified,
                )
                read_metadata(package, row, "catalog")
                for field in (
                    "agent_identity_id", "version", *text_fields, "is_blocked", "created_at", "request_status",
                    "governance", "owner_count", "last_modified_at",
                ):
                    if getattr(package, field) is None:
                        package.field_status[field] = FieldStatus(reason="not_found", detail="등록부 응답에 필드 없음")
                if invalid_governance:
                    shape = {dict: "object", list: "array", bool: "boolean"}.get(type(governance), "number")
                    if isinstance(governance, dict):
                        names = sorted(k for k in governance if isinstance(k, str) and re.fullmatch(r"\w{1,40}", k))[:8]
                        shape += f"(키: {', '.join(names)})" if names else ""
                    package.field_status["governance"] = FieldStatus(
                        reason="error",
                        detail=f"문서상 문자열과 응답 형식이 다름 - 응답 형식 {shape}. 원문과 의미를 추측하지 않음",
                    )
                packages.append(package)
            refs = []
            if self.store:
                refs = [self.store.save(REGISTRY_URL, {
                    "value": [
                        {
                            "id": p.package_id, "agentIdentityId": p.agent_identity_id, "version": p.version,
                            "displayName": p.display_name, "platform": p.platform, "availableTo": p.available_to,
                            "deployedTo": p.deployed_to, "isBlocked": p.is_blocked,
                            "createdDateTime": p.created_at.isoformat() if p.created_at else None,
                            "requestStatus": p.request_status, "governanceMetadata": p.governance,
                            "requestType": p.request_type, "manifestId": p.manifest_id,
                            "lastModifiedDateTime": p.last_modified_at.isoformat() if p.last_modified_at else None,
                            "ownerCount": p.owner_count,
                            "metadata": metadata_projection(p, set(p.metadata_field_sources)),
                            **({"fieldErrors": {"governanceMetadata": "error"}}
                               if p.field_status.get("governance")
                               and p.field_status["governance"].reason == "error" else {}),
                        }
                        for p in packages
                    ],
                    "pagination_complete": True,
                    "projection": "package identity/name/version/platform/access/deployment/block/request/"
                    "governance state, owner count, creation time and allowlisted metadata only; owner identities, publisher, "
                    "descriptions, member IDs and agent content omitted",
                })]
            for package in packages:
                package.evidence_refs = refs
                package.metadata_evidence_refs = {
                    field: refs for field in package.metadata_field_sources
                }
            result.agent365_packages = packages
            result.facts["agent365_registry_complete"] = True
            result.facts["agent365_registry_refs"] = refs
            malformed = sum(
                package.field_status.get("governance") is not None
                and package.field_status["governance"].reason == "error"
                for package in packages
            )
            if malformed:
                self.http.last_ref = refs[0] if refs else None
                result.issues.append(issue(
                    self.http, "agent365_registry", REGISTRY_URL,
                    AccessError(
                        "error", f"governanceMetadata {malformed}건의 문서상 문자열 형식 불일치 - "
                        "해당 필드는 null, 목록 페이지는 완료",
                    ), (),
                ))
        except AccessError as exc:
            self.http.last_ref = (
                self.store.save(REGISTRY_URL, {"reason": exc.reason, "detail": str(exc)})
                if self.store else None
            )
            result.issues.append(issue(
                self.http, "agent365_registry", REGISTRY_URL, exc, self.required_roles,
            ))
        self.collect_details(result)
        return result

    def collect_details(self, result: Collection) -> None:
        """Keep per-package usage failures independent of the completed catalog."""
        started = time.monotonic()
        attempted = failures = consecutive_failures = 0
        stop_cause = None
        skipped = []
        for package in result.agent365_packages:
            for field in DETAIL_FIELDS:
                setattr(package, field, None)
                package.field_status.pop(field, None)
            package.detail_complete = False
            package.detail_evidence_refs = []
            package.metadata_complete = False
            for field in ALL_METADATA_FIELDS:
                if package.metadata_field_sources.get(field) in ("detail", "not_requested"):
                    setattr(package, field, None)
                    package.metadata_field_sources.pop(field, None)
                    package.metadata_evidence_refs.pop(field, None)
                    package.field_status[field] = FieldStatus(reason="not_found", detail="새 상세 조회에서 재확인 필요")
            if stop_cause is None and time.monotonic() - started >= DETAIL_TIME_BUDGET_SECONDS:
                stop_cause = "time_budget"
            if stop_cause is not None:
                skipped.append(package)
                for field in DETAIL_FIELDS:
                    package.field_status[field] = FieldStatus(
                        reason="not_found",
                        detail=f"상세 수집 보호 중단으로 미조회 ({stop_cause}) - 대상의 실패·0으로 추정하지 않음",
                    )
                for field in ALL_METADATA_FIELDS:
                    status = package.field_status.get(field)
                    if getattr(package, field) is None and not (
                        package.metadata_field_sources.get(field) == "catalog"
                        and status and status.reason in ("error", "feature_unavailable")
                    ):
                        package.field_status[field] = FieldStatus(
                            reason="not_found", detail="상세 수집 보호 중단으로 메타데이터 미조회",
                        )
                        package.metadata_field_sources[field] = "not_requested"
                continue
            target = REGISTRY_URL + "/" + quote(package.package_id, safe="")
            error = None
            metadata_updated: set[str] = set()
            attempted += 1
            try:
                if package.package_id in (".", ".."):
                    raise AccessError("error", "패키지 ID 경로 형식 오류")
                payload = self.http.request("GET", target, MSGRAPH_SCOPE)
                if not isinstance(payload, dict) or payload.get("id") != package.package_id:
                    raise AccessError("error", "패키지 상세 응답 ID 불일치")
                if (
                    package.version is not None and payload.get("version") is not None
                    and payload["version"] != package.version
                ):
                    raise AccessError("error", "목록과 상세 패키지 버전 불일치")
                consecutive_failures = 0
                metadata_updated = read_metadata(package, payload, "detail")
                for field, source in DETAIL_FIELDS.items():
                    value = payload.get(source)
                    if value is None:
                        package.field_status[field] = FieldStatus(
                            reason="not_found", detail="공식 상세 응답에 필드 없음 - 0으로 추정하지 않음",
                        )
                        continue
                    try:
                        if field == "last_used_at":
                            value = (
                                datetime.fromisoformat(value.replace("Z", "+00:00"))
                                if isinstance(value, str) else None
                            )
                            valid = value is not None and value.tzinfo is not None
                        elif field in ("active_users_30d", "total_sessions_30d"):
                            valid = type(value) is int and 0 <= value <= 2147483647
                        else:
                            valid = (
                                type(value) in (int, float) and value >= 0
                                and math.isfinite(value)
                            )
                    except (ValueError, OverflowError):
                        valid = False
                    if valid:
                        setattr(package, field, value)
                    else:
                        package.field_status[field] = FieldStatus(
                            reason="error", detail="공식 상세 필드 형식·범위 불일치 - 원문 미저장",
                        )
                package.detail_complete = not any(
                    field in package.field_status for field in DETAIL_FIELDS
                )
                if any(
                    package.field_status[field].reason == "error"
                    for field in (*DETAIL_FIELDS, *metadata_updated) if field in package.field_status
                ):
                    error = AccessError("error", "일부 상세 사용 지표·메타데이터 형식 오류 - 검증된 필드만 유지")
            except (AccessError, ClientAuthenticationError, ValueError, TypeError, KeyError) as exc:
                failures += 1
                consecutive_failures += 1
                if isinstance(exc, AccessError) and exc.status_code == 429:
                    stop_cause = "throttled"
                elif isinstance(exc, AccessError) and exc.status_code in (500, 502, 503, 504):
                    stop_cause = "service_unavailable"
                elif consecutive_failures >= DETAIL_FAILURE_LIMIT:
                    stop_cause = "consecutive_failures"
                reason = (
                    exc.reason if isinstance(exc, AccessError) else
                    "permission_denied" if isinstance(exc, ClientAuthenticationError) else "error"
                )
                error = AccessError(reason, "패키지 상세 읽기 실패 - 응답·인증 오류 원문 미저장")
                for field in DETAIL_FIELDS:
                    package.field_status[field] = FieldStatus(reason=reason, detail=str(error))
                for field in ALL_METADATA_FIELDS:
                    if getattr(package, field) is None:
                        package.field_status[field] = FieldStatus(reason=reason, detail=str(error))
                        package.metadata_field_sources[field] = "detail"
                        metadata_updated.add(field)
            refs = []
            if self.store:
                refs = [self.store.save(target, {
                    "id": package.package_id,
                    **{
                        source: (
                            value.isoformat() if isinstance(value, datetime) else value
                        )
                        for field, source in DETAIL_FIELDS.items()
                        for value in (getattr(package, field),)
                    },
                    "field_status": {
                        field: package.field_status[field].model_dump()
                        for field in DETAIL_FIELDS if field in package.field_status
                    },
                    "detail_complete": package.detail_complete,
                    "metadata": metadata_projection(package, metadata_updated),
                    "metadata_complete": package.metadata_complete,
                    "projection": "documented package aggregate usage and allowlisted metadata only; no users, contacts, "
                    "audiences, element definitions, descriptions or request metadata",
                    **({"reason": error.reason, "detail": str(error)} if error else {}),
                })]
            package.detail_evidence_refs = refs
            for field in metadata_updated:
                package.metadata_evidence_refs[field] = refs
            if error:
                self.http.last_ref = refs[0] if refs else None
                result.issues.append(issue(
                    self.http, "agent365_package_details", target, error, self.required_roles,
                ))
        complete = sum(package.detail_complete for package in result.agent365_packages)
        summary = {
            "candidate_packages": len(result.agent365_packages),
            "attempted_packages": attempted,
            "failed_packages": failures,
            "complete_packages": complete,
            "partial_packages": attempted - failures - complete,
            "skipped_packages": len(skipped),
            "stop_cause": stop_cause,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "time_budget_seconds": DETAIL_TIME_BUDGET_SECONDS,
            "consecutive_failure_limit": DETAIL_FAILURE_LIMIT,
            "usage_window_days": 30,
            "source_period_start": None,
            "source_period_end": None,
            "metadata_complete_packages": sum(package.metadata_complete for package in result.agent365_packages),
        }
        result.facts["agent365_detail_collection"] = summary
        if skipped:
            refs = [self.store.save(REGISTRY_URL, {
                "evidence_type": "local_detail_collection_summary",
                **summary, "skipped_package_ids": [package.package_id for package in skipped],
                "reason": "not_found",
                "detail": "보호 중단으로 요청하지 않은 대상 - 권한·라이선스·활동 부재로 단정하지 않음",
            })] if self.store else []
            for package in skipped:
                package.detail_evidence_refs = refs
                for field in ALL_METADATA_FIELDS:
                    if package.metadata_field_sources.get(field) == "not_requested":
                        package.metadata_evidence_refs[field] = refs
            result.facts["agent365_detail_collection_refs"] = refs
            self.http.last_ref = refs[0] if refs else None
            result.issues.append(issue(
                self.http, "agent365_package_details", REGISTRY_URL,
                AccessError("not_found", f"상세 수집 보호 중단 ({stop_cause}): {len(skipped)}개 미조회"),
                self.required_roles,
            ))
        result.facts["agent365_details_complete"] = all(
            package.detail_complete for package in result.agent365_packages
        ) if result.facts.get("agent365_registry_complete") else False


def crosscheck_agent365(data: Collection, criteria: dict[str, Any]) -> list[Agent365Crosscheck]:
    records = []
    for code in criteria["items"]:
        if code in LIMITS:
            records.append(Agent365Crosscheck(
                se_code=code, status="not_comparable", scope="공개 등록 정보",
                detail=LIMITS[code] + ". 기존 등급 유지",
            ))
            continue
        if code not in ("DS-SY-03", "DP-SY-15"):
            records.append(Agent365Crosscheck(
                se_code=code, status="not_comparable", scope="공개 등록 정보",
                detail="이 항목의 독립 비교 필드가 검증되지 않음. 기존 등급 유지",
            ))
            continue
        record = Agent365Crosscheck(
            se_code=code, status="unavailable", scope=(
                "등록부 agentIdentityId와 Graph Agent ID·Blueprint 참조의 연결"
                if code == "DS-SY-03" else
                "명시적 Blueprint 태그로 식별된 Azure Agent와 등록부 agentIdentityId의 연결"
            ), detail="등급 조건 전체가 아닌 명시적 ID 연결만 대조. 기존 등급 유지",
        )
        refs = set(data.facts.get("agent365_registry_refs", []))
        refs.update(ref for package in data.agent365_packages for ref in package.evidence_refs)
        registry_issues = [item for item in data.issues if item.collector == "agent365_registry"]
        refs.update(ref for item in registry_issues for ref in item.evidence_refs)
        record.evidence_refs = sorted(refs)
        if not data.facts.get("agent365_registry_complete"):
            record.reason = registry_issues[0].reason if registry_issues else "not_found"
            record.detail += " - 등록부 전체 조회 미완료"
        elif not all(data.facts.get(key) for key in ("entra_agents_complete", "entra_blueprints_complete")):
            record.reason = next((
                item.reason for item in data.issues
                if item.collector in ("entra_agents", "entra_blueprints")
            ), "not_found")
            record.detail += " - 기존 Graph 목록 조회 미완료"
        else:
            identities = {item.identity_id.lower(): item for item in data.entra_agent_identities}
            blueprints = {item.blueprint_id.lower(): item for item in data.entra_blueprints}
            if len(identities) != len(data.entra_agent_identities) or len(blueprints) != len(data.entra_blueprints):
                record.reason = "error"
                record.detail += " - 기존 Graph 목록에 중복 ID가 있어 연결을 확정하지 않음"
                records.append(record)
                continue
            registered = {p.agent_identity_id.lower() for p in data.agent365_packages if p.agent_identity_id}
            if code == "DS-SY-03":
                compared = len(registered)
                matched = sum(
                    identifier in identities
                    and (identities[identifier].blueprint_id or "").lower() in blueprints
                    for identifier in registered
                )
                unverified = sum(
                    identifier in identities and not identities[identifier].blueprint_id
                    for identifier in registered
                )
                mismatched = compared - matched - unverified
                record.compared, record.matched = compared, matched
                record.mismatched, record.unverified = mismatched, unverified
                refs.update(ref for item in data.entra_agent_identities for ref in item.evidence_refs)
                refs.update(ref for item in data.entra_blueprints for ref in item.evidence_refs)
                record.status = "mismatch" if mismatched else "partial_match" if matched else "unavailable"
            elif not data.facts.get("agent_inventory_complete"):
                record.reason = "not_found"
                record.detail += " - Azure Agent 전체 조회 미완료"
            else:
                agents = [a for a in data.agents if a.platform in AZURE_AGENT_PLATFORMS]
                matched = 0
                for agent in agents:
                    matches = [
                        identity for identity in identities.values()
                        if (identity.blueprint_id or "").lower() in blueprints
                        and agent_has_entra_identity(agent, [blueprints[identity.blueprint_id.lower()]])
                    ]
                    if len(matches) == 1 and matches[0].identity_id.lower() in registered:
                        matched += 1
                        refs.update(agent.evidence_refs)
                        refs.update(matches[0].evidence_refs)
                        refs.update(blueprints[matches[0].blueprint_id.lower()].evidence_refs)
                record.compared, record.matched, record.mismatched = len(agents), matched, 0
                record.unverified = len(agents) - matched
                record.status = "partial_match" if matched else "unavailable"
                record.detail += " - 미게시·연결 모호·자료 부족은 불일치로 단정하지 않음"
            if record.status == "unavailable" and not record.reason:
                record.reason = "not_found"
                record.detail += " - 비교 가능한 등록 ID 연결 없음"
            if record.compared == 0:
                record.compared = record.matched = record.mismatched = record.unverified = None
            record.evidence_refs = sorted(refs)
        records.append(record)
    return records
