"""One reporting population for observed MS agents and connected external agents."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime

from easm_agent.agent365_grading import CONNECTED_PLATFORMS
from easm_agent.models import HOSTED_AGENT_PLATFORMS, Collection, CostHistoryEvidence


@dataclass(frozen=True)
class AgentReportRecord:
    platform: str
    name: str
    identifier_sha256: str
    identifier_kind: str
    owner_present: bool | None
    model: str | None
    version: str | None
    version_kind: str
    published: bool | None
    lifecycle_status: str
    lifecycle_confirmed: bool | None
    lifecycle_basis: str
    created_at: datetime | None
    last_used_at: datetime | None
    region: str | None
    evidence_refs: tuple[str, ...]


def agent_report_records(data: Collection) -> list[AgentReportRecord]:
    records = []
    regions = {resource["id"].casefold(): resource.get("location")
               for resource in data.resources if isinstance(resource.get("id"), str)}
    environment_regions = {
        environment.environment_id.casefold(): environment.region
        for read in data.admin_evidence if read.completed and read.source == "powerplatform.environments"
        for environment in read.environments
    }
    for agent in data.agents:
        if agent.platform in HOSTED_AGENT_PLATFORMS:
            continue
        foundry_registered = agent.platform == "foundry" and bool(agent.agent_id)
        deployed = agent.deployed_at is not None
        records.append(AgentReportRecord(
            platform=agent.platform, name=agent.agent_name,
            identifier_sha256=hashlib.sha256(agent.agent_id.encode()).hexdigest(),
            identifier_kind="Foundry Agent ID" if agent.platform == "foundry" else "자체 호스트 식별자",
            owner_present=bool(agent.owner) if agent.owner is not None else None,
            model=agent.model, version=agent.agent_version, version_kind="Agent 버전", published=None,
            lifecycle_status="생성·등록 확인" if foundry_registered else (
                "배포 기록 확인" if deployed else "호스트 관측·배포 미확인"),
            lifecycle_confirmed=True if foundry_registered or deployed else None,
            lifecycle_basis=(
                "Foundry Agent 생성·등록 확인. 실제 배포·채널 게시·실행 성공은 별도 확인"
                if foundry_registered else "호스트의 배포 기록 기준. 실제 실행 성공은 별도 확인"),
            created_at=agent.created_at, last_used_at=agent.last_used_at,
            region=regions.get((agent.resource_id or agent.model_resource_id or "").casefold()),
            evidence_refs=tuple(agent.evidence_refs),
        ))
    for agent in data.copilot_agents:
        published = True if agent.last_published_at is not None else (
            False if "last_published_at" not in agent.field_status else None)
        records.append(AgentReportRecord(
            platform=agent.platform, name=agent.display_name or agent.agent_id,
            identifier_sha256=hashlib.sha256(agent.agent_id.encode()).hexdigest(),
            identifier_kind="Copilot Bot ID", owner_present=agent.owner_present,
            model=agent.model, version=None, version_kind="게시 시각 별도",
            published=published,
            lifecycle_status="게시 확인" if published is True else (
                "미게시 확인" if published is False else "게시 상태 미확인"),
            lifecycle_confirmed=published,
            lifecycle_basis="Copilot 게시 시각 기준. 실제 실행·활동 기록과 구분",
            created_at=agent.created_at, last_used_at=None,
            region=environment_regions.get(agent.environment_id.casefold()),
            evidence_refs=tuple(agent.evidence_refs),
        ))
    for package in data.agent365_packages:
        if package.platform not in CONNECTED_PLATFORMS:
            continue
        metadata = package.connected_metadata
        records.append(AgentReportRecord(
            platform=package.platform, name=package.display_name or package.package_id,
            identifier_sha256=metadata.source_agent_id_sha256 or "",
            identifier_kind="원본 SourceAgentId", owner_present=(
                package.owner_count > 0 if package.owner_count is not None else None),
            model=metadata.model_identifier, version=metadata.source_version or package.version,
            version_kind="원본 연결 버전" if metadata.source_version else "등록 패키지 버전",
            published=(
                metadata.published_status == "Published" if metadata.published_status is not None else None),
            lifecycle_status="등록·동기화 확인" if metadata.source_agent_id_sha256 else "등록 확인·원본 ID 미확인",
            lifecycle_confirmed=True if metadata.source_agent_id_sha256 else None,
            lifecycle_basis="Agent 365 원본 ID 연결 기준. 원본 Published 상태: "
                + (metadata.published_status or "미확인") + ". 원본 서비스 실행 성공은 별도 확인",
            created_at=metadata.created_at or package.created_at, last_used_at=package.last_used_at,
            region=metadata.region, evidence_refs=tuple(package.detail_evidence_refs or package.evidence_refs),
        ))
    return records


def monthly_inventory_cost(data: Collection) -> dict[str, float | None]:
    """Match observed billing rows to the current inventory, not historical ownership."""
    from easm_agent.api_grading import cost_measurement

    data.exclude_host_candidates()

    measurement = cost_measurement(data, data.agents)
    lookup = {}
    for target in measurement.decisions:
        key = (target.observed.get("resource_id", "").casefold(), target.observed.get("usage_date"),
               target.observed.get("currency"))
        if key in lookup:
            return {}
        lookup[key] = target
    history = next((dataset for dataset in data.report_evidence if isinstance(dataset, CostHistoryEvidence)), None)
    if history is None or not history.complete:
        return {}
    result: dict[str, float | None] = {}
    for record in history.records:
        month = record.occurred_at.astimezone(UTC).strftime("%Y%m")
        target = lookup.get((
            record.evidence_ids[0].casefold() if len(record.evidence_ids) == 1 else "",
            record.occurred_at.astimezone(UTC).strftime("%Y%m%d"), record.currency,
        ))
        valid = (
            measurement.unavailable is None and target is not None
            and math.isclose(target.observed["amount"], record.amount, abs_tol=1e-12)
        )
        if not valid or month in result and result[month] is None:
            result[month] = None
        else:
            result[month] = (result.get(month) or 0.0) + (target.contribution or 0.0)
    return result
