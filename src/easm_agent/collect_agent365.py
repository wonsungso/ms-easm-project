from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from easm_agent.api_grading import agent_has_entra_identity
from easm_agent.azure import MSGRAPH, AccessError, EvidenceStore, ReaderHTTP, issue
from easm_agent.models import (
    AZURE_AGENT_PLATFORMS,
    Agent365Crosscheck,
    Agent365Package,
    Collection,
    FieldStatus,
)

REGISTRY_URL = MSGRAPH + "/v1.0/copilot/admin/catalog/packages"
STATUS_LABELS = {
    "partial_match": "일부 일치",
    "mismatch": "불일치",
    "unavailable": "미확인",
    "not_comparable": "동일 정보 미제공",
}
LIMITS = {
    "DS-SY-06": "호출 모델 정보와 Azure 배포 버전·업데이트 옵션은 다른 필드",
    "DS-SY-07": "등록부에 Azure 인바운드 경계 설정 없음",
    "DS-SY-08": "등록부에 Foundry MCP require_approval 설정 없음",
    "DS-SY-09": "등록부에 Foundry 전체 외부 도구 URL 선언 없음",
    "BI-SY-11": "등록부에 Foundry 평가 실행 이력 없음",
    "BI-SY-12": "등록부에 Azure 보안 권고 상태 없음",
    "BI-SY-13": "등록부에 Azure 콘텐츠 필터 정책 연결·활성 필터 없음",
    "BI-SY-14": "패키지 version과 Foundry 버전·호스트 런타임은 다른 필드",
    "BI-SY-15": "등록부에 동일 Azure Agent의 owner·sponsor·env·cost-center 전체 없음",
    "BI-SY-16": "등록부에 Azure Policy 리소스별 평가 없음",
    "OE-SY-20": "owners·sponsors는 기존 Graph와 동일 원천, 등록부에 독립 대조 필드 없음",
    "OE-SY-21": "앱 역할은 기존 Graph와 동일 원천, 등록부에 독립 대조 필드 없음",
    "OE-SY-22": "활동 계측과 Azure 진단 설정·workspace 연결은 다른 증거",
    "OE-SY-23": "등록부에 Azure 관리 ID·키 인증·직접 ARM 역할 구성 없음",
    "OE-SY-24": "등록부에 Azure 경보의 실제 대상 범위 없음",
    "OE-SY-25": "등록부에 Azure 작업 그룹·수신자 연결 없음",
    "OE-SY-26": "테넌트 저장 지역과 Azure 리소스 지역·workspace 보존기간은 다른 증거",
    "OT-SY-28": "활동 통계와 Azure 리소스 메트릭 표본은 다른 증거",
    "OT-SY-29": "토큰·활동 통계와 Cost Management 실제 비용은 다른 증거",
    "OT-SY-30": "등록부에 Azure 구독의 Defender for Cloud 플랜 구성 없음",
    "OT-SY-31": "등록부에 Azure 구독 예산·실제/예측 경보 설정 없음",
}


class Agent365Collector:
    """Read published registry references, not runtime SDK telemetry or agent content."""

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
                }
                for source in text_fields.values():
                    if row.get(source) is not None and not isinstance(row[source], str):
                        raise AccessError("error", f"Agent 365 {source} 형식 오류")
                if row.get("isBlocked") is not None and type(row["isBlocked"]) is not bool:
                    raise AccessError("error", "Agent 365 isBlocked 형식 오류")
                if row.get("requestStatus") is not None and not isinstance(row["requestStatus"], str):
                    raise AccessError("error", "Agent 365 requestStatus 형식 오류")
                if row.get("governanceMetadata") is not None and not isinstance(row["governanceMetadata"], str):
                    raise AccessError("error", "Agent 365 governanceMetadata 형식 오류")
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
                package = Agent365Package(
                    package_id=identifier, agent_identity_id=identity, version=version,
                    display_name=row.get("displayName"), platform=row.get("platform"),
                    available_to=row.get("availableTo"), deployed_to=row.get("deployedTo"),
                    is_blocked=row.get("isBlocked"), created_at=created, request_status=row.get("requestStatus"),
                    governance=row.get("governanceMetadata"),
                    owner_count=len(owners) if owners is not None else None,
                )
                for field in (
                    "agent_identity_id", "version", *text_fields, "is_blocked", "created_at", "request_status",
                    "governance", "owner_count",
                ):
                    if getattr(package, field) is None:
                        package.field_status[field] = FieldStatus(reason="not_found", detail="등록부 응답에 필드 없음")
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
                            "ownerCount": p.owner_count,
                        }
                        for p in packages
                    ],
                    "pagination_complete": True,
                    "projection": "package identity/name/version/platform/access/deployment/block/request/"
                    "governance state, owner count and creation time only; owner identities, publisher, "
                    "descriptions, member IDs and agent content omitted",
                })]
            for package in packages:
                package.evidence_refs = refs
            result.agent365_packages = packages
            result.facts["agent365_registry_complete"] = True
            result.facts["agent365_registry_refs"] = refs
        except AccessError as exc:
            self.http.last_ref = (
                self.store.save(REGISTRY_URL, {"reason": exc.reason, "detail": str(exc)})
                if self.store else None
            )
            result.issues.append(issue(
                self.http, "agent365_registry", REGISTRY_URL, exc, self.required_roles,
            ))
        return result


def crosscheck_agent365(data: Collection, criteria: dict[str, Any]) -> list[Agent365Crosscheck]:
    records = []
    for code in criteria["items"]:
        if code in LIMITS:
            records.append(Agent365Crosscheck(
                se_code=code, status="not_comparable", scope="공개 등록 정보",
                detail=LIMITS[code] + ". 기존 등급 유지",
            ))
            continue
        if code not in ("DS-SY-05", "DP-SY-19"):
            records.append(Agent365Crosscheck(
                se_code=code, status="not_comparable", scope="공개 등록 정보",
                detail="이 항목의 독립 비교 필드가 검증되지 않음. 기존 등급 유지",
            ))
            continue
        record = Agent365Crosscheck(
            se_code=code, status="unavailable", scope=(
                "등록부 agentIdentityId와 Graph Agent ID·Blueprint 참조의 연결"
                if code == "DS-SY-05" else
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
            if code == "DS-SY-05":
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
            record.evidence_refs = sorted(refs)
        records.append(record)
    return records
