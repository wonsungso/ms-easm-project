"""Non-grading catalog insights and separately approved connection-screen observations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StrictBool, StrictInt

from easm_agent.azure import EvidenceStore
from easm_agent.models import Collection, EvidenceModel

PORTAL_URL = "https://admin.cloud.microsoft/#/agents/all/connected-platforms"


class ConnectionObservation(EvidenceModel):
    platform: Literal["AmazonBedrock", "SnowflakeAI"]
    connection_label_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["Healthy", "Success", "Failed", "Unknown"]
    last_sync_at: AwareDatetime | None = None
    last_sync_display: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9,: /.-]+$")
    sync_schedule: Literal["Manual"] | None = None
    regions: list[Annotated[str, Field(pattern=r"^[a-z]{2}(?:-[a-z]+)+-\d+$")]] = Field(default_factory=list, max_length=32)
    synchronized_count: StrictInt | None = Field(default=None, ge=0)
    observability_enabled: StrictBool | None = None
    error_present: StrictBool | None = None


class ConnectionExport(EvidenceModel):
    schema_version: Literal[1]
    source_type: Literal["official_admin_portal_read"]
    approved: Literal[True]
    tenant_verified: Literal[True]
    tenant_id: str
    observed_at: AwareDatetime
    source_url: Literal["https://admin.cloud.microsoft/#/agents/all/connected-platforms"]
    connections: list[ConnectionObservation]


def read_connections(path: Path, tenant: str, store: EvidenceStore, now: datetime) -> list[dict]:
    export = ConnectionExport.model_validate_json(path.read_text("utf-8"))
    if export.tenant_id.casefold() != tenant.casefold():
        raise ValueError("Agent 365 연결 화면 증적의 테넌트가 다릅니다.")
    if not now - timedelta(hours=24) <= export.observed_at <= now + timedelta(minutes=2):
        raise ValueError("Agent 365 연결 화면 증적은 최근 24시간 관측이어야 합니다.")
    identities = [row.connection_label_sha256 for row in export.connections]
    if len(set(identities)) != len(identities):
        raise ValueError("Agent 365 연결 화면 증적의 연결이 중복되었습니다.")
    if any(row.last_sync_at and row.last_sync_at > export.observed_at for row in export.connections):
        raise ValueError("동기화 시각이 화면 관측 시각보다 이후입니다.")
    ref = store.save(PORTAL_URL, export.model_dump(mode="json"))
    return [
        {**row.model_dump(mode="json"), "observed_at": export.observed_at.isoformat(),
         "source": "official_admin_portal_read", "collection_method": "E", "evidence_refs": [ref]}
        for row in export.connections
    ]


def connection_groups(data: Collection) -> list[dict]:
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for package in data.agent365_packages:
        metadata = package.connected_metadata
        if metadata.connection_id_sha256 and package.platform:
            groups[(package.platform, metadata.connection_id_sha256)].append(package)
    result = []
    complete = data.facts.get("agent365_registry_complete") is True
    for (platform, connection), packages in sorted(groups.items()):
        source_ids = [package.connected_metadata.source_agent_id_sha256 for package in packages]
        known = [identifier for identifier in source_ids if identifier]
        result.append({
            "platform": platform, "connection_id_sha256": connection,
            "registered_packages": len(packages),
            "unique_source_ids": len(set(known)) if len(known) == len(packages) and complete else None,
            "duplicate_registration_count": len(known) - len(set(known)) if len(known) == len(packages) and complete else None,
            "unknown_source_ids": len(packages) - len(known),
            "regions": sorted({package.connected_metadata.region for package in packages
                               if package.connected_metadata.region}),
            "complete": complete,
            "scope": "확인된 연결 ID의 등록 패키지. 원본 플랫폼 전체 Agent 목록 아님",
            "evidence_refs": sorted({ref for package in packages for ref in package.detail_evidence_refs}),
        })
    return result


def source_duplicates(data: Collection) -> list[dict]:
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for package in data.agent365_packages:
        identifier = package.connected_metadata.source_agent_id_sha256
        if identifier and package.platform:
            groups[(package.platform, identifier)].append(package)
    return [
        {
            "platform": platform, "source_agent_id_sha256": identifier,
            "package_ids": sorted({package.package_id for package in packages}),
            "connection_ids_sha256": sorted({package.connected_metadata.connection_id_sha256
                                            for package in packages if package.connected_metadata.connection_id_sha256}),
            "scope": "확인된 원본 ID의 다중 등록. 전사 고유 Agent 수로 환산하지 않음",
            "evidence_refs": sorted({ref for package in packages for ref in package.detail_evidence_refs}),
        }
        for (platform, identifier), packages in sorted(groups.items()) if len(packages) > 1
    ]


def catalog_changes(current: Collection, previous: Collection | None) -> dict:
    now = current.facts.get("agent365_collected_at", current.collected_at.isoformat())
    unavailable = {"status": "not_comparable", "changes": [], "observed_at": now}
    if previous is None:
        return {**unavailable, "reason": "비교할 이전 등록부 스냅샷 없음"}
    if not (current.facts.get("agent365_registry_complete") is True
            and previous.facts.get("agent365_registry_complete") is True):
        return {**unavailable, "reason": "현재 또는 이전 등록부 조회 미완료"}
    tenant = current.facts.get("agent365_tenant_id")
    if not tenant or tenant != previous.facts.get("agent365_tenant_id"):
        return {**unavailable, "reason": "두 등록부 스냅샷의 동일 테넌트 미확인"}
    changes = []
    before = {package.package_id: package for package in previous.agent365_packages}
    after = {package.package_id: package for package in current.agent365_packages}
    if len(before) != len(previous.agent365_packages) or len(after) != len(current.agent365_packages):
        return {**unavailable, "reason": "등록부 패키지 ID 중복"}
    for identifier in sorted(set(before) | set(after)):
        old, new = before.get(identifier), after.get(identifier)
        package = new or old
        if package is None:
            continue
        refs = sorted(set((old.detail_evidence_refs if old else []) + (new.detail_evidence_refs if new else [])))
        base = {"package_id": identifier, "platform": package.platform, "evidence_refs": refs}
        if old is None or new is None:
            changes.append({**base, "kind": "added_to_catalog" if old is None else "absent_from_catalog"})
            continue
        old_values, new_values = old.model_dump(mode="json"), new.model_dump(mode="json")
        for field in ("version", "available_to", "deployed_to", "is_blocked", "owner_count"):
            left, right = old_values[field], new_values[field]
            if left != right:
                changes.append({
                    **base, "kind": "field_changed" if left is not None and right is not None else "field_observation_changed",
                    "field": field, "before": left, "after": right,
                })
        for field in ("model_identifier", "region", "published_status", "source_version", "source_status"):
            left, right = old_values["connected_metadata"][field], new_values["connected_metadata"][field]
            if left != right:
                changes.append({
                    **base, "kind": "field_changed" if left is not None and right is not None else "field_observation_changed",
                    "field": "connected." + field, "before": left, "after": right,
                })
    return {
        "status": "compared", "previous_observed_at": previous.facts.get(
            "agent365_collected_at", previous.collected_at.isoformat()),
        "observed_at": now, "changes": changes,
        "observed_package_ids": sorted(after),
        "evidence_refs": sorted({
            ref for collection in (previous, current)
            for package in collection.agent365_packages for ref in package.evidence_refs
        }),
        "limit": "목록 제외는 원본 Agent 삭제 증거가 아니며 필드 미확인을 구성 변경으로 해석하지 않음",
    }
