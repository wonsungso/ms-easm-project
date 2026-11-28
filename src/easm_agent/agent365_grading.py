"""Platform-specific assessment of documented connected-agent catalog records."""

from __future__ import annotations

from typing import Any

from easm_agent.models import Collection, TargetAssessment, try_timestamp

REGISTRY_PROFILE = "agent365_registry"
REGISTRY_PROFILES = (REGISTRY_PROFILE, "agent365_registry_v2")
REGISTRY_CHECKS = {
    "DM-SY-01": "inventory", "DS-SY-03": "provenance", "BI-SY-08": "lifecycle",
    "BI-SY-10": "block", "BI-SY-13": "metadata", "BI-SY-14": "distribution",
    "OE-SY-16": "owner", "OE-SY-17": "audience", "OE-SY-18": "changes", "OT-SY-23": "timestamps",
}

CONNECTED_PLATFORMS = {"AmazonBedrock": "P5", "SnowflakeAI": "P6"}
CHECKS = {
    "DS-SY-04": "source_model_record",
    "DS-SY-05": "access_record",
    "DS-SY-07": "agent_endpoint_https",
    "BI-SY-12": "version_record",
    "BI-SY-13": "owner_record",
    "DP-SY-15": "source_identity_record",
    "OE-SY-22": "source_region_record",
}
PROVIDERS = {
    "source_model_record": {"AmazonBedrock"},
    "source_region_record": {"AmazonBedrock"},
    "agent_endpoint_https": {"SnowflakeAI"},
}


def registry_targets(data: Collection, code: str, criteria: dict[str, Any]) -> list[TargetAssessment]:
    check = criteria["items"][code]["registry_check"]
    if check != REGISTRY_CHECKS.get(code):
        raise ValueError(f"{code}: 지원하지 않는 공통 등록부 점검 {check}")
    platforms = criteria["registry_platforms"]
    agent_types = set(criteria["registry_agent_element_types"])
    now = try_timestamp(data.facts.get("agent365_collected_at"))
    comparison = data.facts.get("agent365_comparison", {})
    previous_at = try_timestamp(comparison.get("previous_observed_at"))
    compared_at = try_timestamp(comparison.get("observed_at"))
    entries = []
    for package in data.agent365_packages:
        if package.platform not in platforms:
            continue
        refs = list(package.evidence_refs)
        metadata = package.connected_metadata
        external = package.platform in CONNECTED_PLATFORMS
        observed: dict[str, Any] = {
            "platform": platforms[package.platform], "catalog_platform": package.platform,
            "source": "agent365_registry", "subject_unit": "registered_agent_package", "registry_check": check,
        }
        value: bool | None = None
        reason = "공통 등록부 항목의 필수 API 필드 미확인"
        element_types = package.element_types
        if element_types is not None and not agent_types.intersection(kind.casefold() for kind in element_types):
            entries.append(TargetAssessment(
                subject=package.package_id, status="excluded", observed=observed,
                reason="명시적으로 확인된 비 Agent 패키지 - 도구·앱을 Agent로 채점하지 않음", evidence_refs=refs,
            ))
            continue
        if check == "inventory":
            created = try_timestamp(package.created_at)
            observed.update(package_id_present=bool(package.package_id), created_at=created)
            value = bool(package.package_id and package.platform) if created is not None else None
        elif check == "provenance":
            observed.update(package_type=package.package_type, registration_type=metadata.registration_type,
                            registration_provider=metadata.registration_provider, origin_store=metadata.origin_store)
            if package.package_type in criteria["registry_package_types"]:
                value = True
                if external:
                    refs.extend(package.detail_evidence_refs)
                    value = True if all((metadata.registration_type, metadata.registration_provider,
                                         metadata.origin_store)) else None
        elif check == "lifecycle":
            observed.update(published_status=metadata.published_status, deployed_to=package.deployed_to)
            if external:
                refs.extend(package.detail_evidence_refs)
                value = True if metadata.published_status in criteria["registry_published_statuses"] else None
            else:
                value = True if package.deployed_to in criteria["registry_acquire_statuses"] else None
        elif check == "block":
            observed["is_blocked"] = package.is_blocked
            value = True if type(package.is_blocked) is bool else None
        elif check == "metadata":
            refs.extend(package.detail_evidence_refs)
            present = metadata.content_presence.get("Instructions_present") if external else package.description_present
            observed["instruction_present" if external else "description_present"] = present
            value = present if type(present) is bool else None
        elif check == "distribution":
            observed.update(deployed_to=package.deployed_to,
                            acquire_count=package.audience_counts.get("acquireUsersAndGroups"))
            if package.deployed_to in criteria["registry_acquire_statuses"]:
                value = True
                if package.deployed_to == "acquiredForSome":
                    refs.extend(package.detail_evidence_refs)
                    count = package.audience_counts.get("acquireUsersAndGroups")
                    value = count > 0 if count is not None else None
        elif check == "owner":
            observed["catalog_owner_count"] = package.owner_count
            value = package.owner_count > 0 if package.owner_count is not None else None
            if value is False:
                reason = "등록부 소유자 0개 - 책임 주체 미지정"
        elif check == "audience":
            refs.extend(package.detail_evidence_refs)
            observed.update(audience_counts=package.audience_counts, audience_type_counts=package.audience_type_counts)
            values = []
            for field in criteria["registry_audience_fields"]:
                count, types = package.audience_counts.get(field), package.audience_type_counts.get(field)
                values.append(
                    count == types["user"] + types["group"]
                    if count is not None and types is not None and set(types) == {"user", "group"} else None
                )
            value = all(values) if None not in values else None
        elif check == "changes":
            refs.extend(comparison.get("evidence_refs", []))
            observed.update(previous_observed_at=previous_at, observed_at=compared_at,
                            comparison_status=comparison.get("status"))
            value = True if (
                comparison.get("status") == "compared" and now is not None and compared_at == now
                and previous_at is not None and previous_at < now
                and package.package_id in comparison.get("observed_package_ids", [])
                and comparison.get("evidence_refs")
            ) else None
            reason = "동일 테넌트의 완료된 이전·현재 API 스냅샷 비교 또는 대상별 비교 근거 미확인"
        elif check == "timestamps":
            created, modified = try_timestamp(package.created_at), try_timestamp(package.last_modified_at)
            observed.update(created_at=created, last_modified_at=modified, collected_at=now)
            value = created <= modified <= now if all((created, modified, now)) else None
            if value is False:
                reason = "생성·수정·API 관측 시각의 순서 불일치"
        detail_needed = check in ("metadata", "audience") or external and check in ("provenance", "lifecycle") \
            or check == "distribution" and package.deployed_to == "acquiredForSome"
        if not package.evidence_refs or detail_needed and (
            not package.detail_read_completed or not package.detail_evidence_refs
        ):
            value, reason = None, "항목의 직접 API 조회 완료·증적 참조 미확인"
        if element_types is None:
            value, reason = None, "Agent 종류 필드 미확인 - 앱·도구와 구분 불가"
        if data.facts.get("agent365_registry_complete") is not True:
            value, reason = None, "Agent 365 목록 수집 미완료"
        entries.append(TargetAssessment(
            subject=package.package_id, observed=observed,
            status="compliant" if value is True else "non_compliant" if value is False else "unknown",
            contribution=int(value) if value is not None else None,
            reason=None if value is True else reason,
            evidence_refs=sorted(set(refs)),
        ))
    return entries


def connected_targets(data: Collection, code: str, check: str | None) -> list[TargetAssessment]:
    if check is not None and check != CHECKS.get(code):
        raise ValueError(f"{code}: 지원되지 않는 외부 플랫폼 점검 분기 {check}")
    entries = []
    for package in data.agent365_packages:
        if package.platform not in CONNECTED_PLATFORMS:
            continue
        active_check = check if package.platform in PROVIDERS.get(check, CONNECTED_PLATFORMS) else None
        observed: dict[str, Any] = {
            "platform": package.platform,
            "source": "agent365_catalog",
            "subject_unit": "synchronized_package",
        }
        refs = package.evidence_refs
        metadata = package.connected_metadata
        value: bool | None = None
        reason = "Agent 365 API가 이 항목의 필수 구성·기록 필드를 제공하지 않음"
        if active_check in ("source_model_record", "source_identity_record", "source_region_record", "agent_endpoint_https"):
            refs = package.detail_evidence_refs
            observed["metadata_profile"] = "connected_definition_v1"
            observed["subject_unit"] = "synchronized_package"
            reason = "Agent 365 연결 정의의 필수 필드 미확인"
            if package.detail_read_completed:
                if active_check == "source_model_record":
                    observed["source_model_identifier"] = metadata.model_identifier
                    value = True if metadata.model_identifier else None
                elif active_check == "source_region_record":
                    observed["source_region"] = metadata.region
                    value = True if metadata.region else None
                elif active_check == "source_identity_record":
                    observed.update(
                        source_agent_id_sha256=metadata.source_agent_id_sha256,
                        connection_id_sha256=metadata.connection_id_sha256,
                    )
                    value = True if metadata.source_agent_id_sha256 and metadata.connection_id_sha256 else None
                elif metadata.endpoint_https is not None and data.facts.get("agent365_registry_complete") is True:
                    for index, compliant in enumerate(metadata.endpoint_https):
                        entries.append(TargetAssessment(
                            subject=f"{package.package_id}#endpoint-{index + 1}",
                            observed={**observed, "subject_unit": "agent_endpoint", "https_without_userinfo": compliant},
                            status="compliant" if compliant else "non_compliant",
                            contribution=int(compliant),
                            reason=None if compliant else "Agent endpoint HTTPS·URL 인증정보 없음 조건 미충족",
                            evidence_refs=refs,
                        ))
                    continue
        elif active_check == "access_record":
            observed.update(available_to=package.available_to, is_blocked=package.is_blocked)
            if package.available_to in ("allowedForAll", "allowedForSome", "allowedForNone") \
                    and type(package.is_blocked) is bool:
                value = True
            reason = "Agent 365 접근·차단 구성 필드 미확인"
        elif active_check == "version_record":
            observed["catalog_version"] = package.version
            value = bool(package.version) if package.version is not None else None
            reason = "Agent 365 등록 버전 필드 미확인"
        elif active_check == "owner_record":
            observed["catalog_owner_count"] = package.owner_count
            value = package.owner_count > 0 if package.owner_count is not None else None
            reason = "Agent 365 등록부 소유자 수 미확인"
        if active_check and data.facts.get("agent365_registry_complete") is not True:
            value, reason = None, "Agent 365 목록 수집 미완료"
        status = "excluded" if active_check is None else (
            "compliant" if value is True else "non_compliant" if value is False else "unknown"
        )
        entries.append(TargetAssessment(
            subject=package.package_id, observed=observed, status=status,
            contribution=int(value) if value is not None else None,
            reason=reason if value is None else "등록부 소유자 없음" if value is False else None,
            evidence_refs=refs,
        ))
    return entries
