"""승인된 위임 사용자 인벤토리 내보내기만 읽는다. Azure 평가 분모와 분리한다."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from easm_agent.azure import PP_INVENTORY_URL, EvidenceStore, redact
from easm_agent.models import (
    Collection,
    CopilotAgentEvidence,
    CopilotConnectorOperation,
    CopilotEvaluationRead,
    CopilotReview,
    EvidenceModel,
    FieldStatus,
    Issue,
    Reason,
)

ORIGINS: dict[str, Literal["copilot_studio", "agent_builder"]] = {
    "Copilot Studio": "copilot_studio",
    "Microsoft Copilot Agent Builder": "agent_builder",
    "Microsoft 365 Copilot Agent Builder": "agent_builder",
    "Copilot Studio Lite": "agent_builder",
}
MAX_EXPORT_AGE = timedelta(hours=24)
LIMITATION = (
    "공식 관리자 위임 사용자 내보내기 - 파일 해시는 원천 인증 서명이 아님. "
    "V1 제외, 게시 구성 중심, 약 20분 갱신 지연, 기능 종류별 최대 200개. "
    "승인·실효성·사용 이력·라이선스·테넌트 전체 가시성을 증명하지 않음"
)


def classify_created_in(
    created_in: str | None,
) -> Literal["copilot_studio", "agent_builder", "unclassified_copilot"]:
    if created_in is not None:
        for origin, platform in ORIGINS.items():
            if created_in.casefold() == origin.casefold():
                return platform
    return "unclassified_copilot"


class CopilotReviewExport(EvidenceModel):
    schema_version: Literal[1]
    source_type: Literal["official_admin_portal_read"]
    approved: StrictBool
    tenant_id: StrictStr
    tenant_verified: StrictBool
    exported_at: AwareDatetime
    reviews: list[CopilotReview]

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version은 정수여야 합니다.")
        return value


def read_copilot_reviews(path: Path, tenant: str, now: datetime, store: EvidenceStore) -> Collection:
    raw = path.read_bytes()
    export = CopilotReviewExport.model_validate_json(raw)
    if not export.approved or not export.tenant_verified or uuid.UUID(export.tenant_id) != uuid.UUID(tenant):
        raise ValueError("승인된 동일 테넌트 Copilot 검토 화면 증적만 허용합니다.")
    if not export.reviews or export.exported_at > now + timedelta(minutes=5) or any(
        row.observed_at > export.exported_at or now - row.observed_at > MAX_EXPORT_AGE
        for row in export.reviews
    ):
        raise ValueError("Copilot 검토 화면의 최근 관측 시각·내보내기 시각을 확인해야 합니다.")
    identities = [(row.environment_id.lower(), row.agent_id.lower()) for row in export.reviews]
    if len(identities) != len(set(identities)):
        raise ValueError("같은 Agent의 검토 화면 증적이 중복되었습니다.")
    for row in export.reviews:
        row.evidence_refs = []
    ref = store.save("copilot-review-export:" + hashlib.sha256(raw).hexdigest(), {
        "export": redact(export.model_dump(mode="json")),
        "limit": "승인된 실제 작성 화면 관측. 게시 버전·보안 스캔·평가 통과·전체 거버넌스 증명이 아님",
    })
    for row in export.reviews:
        row.evidence_refs = [ref]
    return Collection(collected_at=now, copilot_reviews=export.reviews)


class CopilotInventoryRow(EvidenceModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    agent_id: StrictStr
    environment_id: StrictStr = Field(min_length=1)
    display_name: StrictStr | None
    created_in: StrictStr | None
    created_at: AwareDatetime | None
    last_published_at: AwareDatetime | None
    owner_present: StrictBool | None
    entra_agent_id: StrictStr | None
    blueprint_id: StrictStr | None
    model: StrictStr | None
    authentication: StrictStr | None
    channels: list[StrictStr] | None
    is_quarantined: StrictBool | None
    shared_with_tenant: StrictBool | None
    harness: StrictStr | None = None
    orchestration: StrictStr | None = None
    connector_count: StrictInt | None = Field(default=None, ge=0)
    connector_operation_count: StrictInt | None = Field(default=None, ge=0)
    connector_operations: list[CopilotConnectorOperation] | None = None
    evaluation_read: CopilotEvaluationRead | None = None

    @field_validator("agent_id", "entra_agent_id", "blueprint_id")
    @classmethod
    def canonical_uuid(cls, value: str | None) -> str | None:
        return str(uuid.UUID(value)) if value is not None else None

    @field_validator("environment_id")
    @classmethod
    def environment_identifier(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("환경 식별자는 비어 있거나 공백으로 둘러싸일 수 없습니다.")
        return value

    @model_validator(mode="after")
    def chronological(self) -> CopilotInventoryRow:
        if self.created_at and self.last_published_at and self.created_at > self.last_published_at:
            raise ValueError("게시 시각이 생성 시각보다 이릅니다.")
        return self


class CopilotInventoryExport(EvidenceModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    source_type: Literal["official_admin_read"]
    approved: StrictBool
    command: Literal[
        "https://api.powerplatform.com/resourcequery/resources/query?api-version=2024-10-01"
    ]
    auth_type: Literal["delegated_user"]
    tenant_id: StrictStr
    tenant_verified: StrictBool
    observed_at: AwareDatetime
    exported_at: AwareDatetime
    completed: StrictBool
    object_count: StrictInt | None = Field(ge=0)
    total_records: StrictInt | None = Field(ge=0)
    reason: Reason | None
    failure_code: Literal[
        "permission_denied", "license_missing", "feature_unavailable", "not_found",
        "network_error", "authentication_error", "invalid_response", "error",
    ] | None
    agents: list[CopilotInventoryRow]

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_schema_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version은 정수여야 합니다.")
        return value

    @field_validator("tenant_id")
    @classmethod
    def tenant_uuid(cls, value: str) -> str:
        return str(uuid.UUID(value))

    @model_validator(mode="after")
    def validate_export(self) -> CopilotInventoryExport:
        if not self.approved:
            raise ValueError("승인된 버전 1 내보내기만 허용합니다.")
        if self.observed_at > self.exported_at:
            raise ValueError("관측 시각이 내보내기 시각보다 늦습니다.")
        identifiers = {(row.environment_id.lower(), row.agent_id) for row in self.agents}
        if len(identifiers) != len(self.agents):
            raise ValueError("환경과 에이전트 식별자가 중복되었습니다.")
        for row in self.agents:
            if any(value and value > self.observed_at for value in (
                row.created_at, row.last_published_at,
            )):
                raise ValueError("관측 시각보다 미래의 에이전트 기록입니다.")
            if row.evaluation_read and any(
                run.end_time and run.end_time > self.observed_at for run in row.evaluation_read.runs
            ):
                raise ValueError("관측 시각보다 미래의 Copilot 평가 기록입니다.")
        if self.completed:
            if not self.tenant_verified or self.reason is not None or self.failure_code is not None or (
                self.object_count != len(self.agents) or self.total_records != len(self.agents)
            ):
                raise ValueError("완료된 내보내기의 테넌트·사유·전체 건수가 일치하지 않습니다.")
        elif self.reason is None or self.failure_code is None or self.object_count is not None or (
            self.total_records is not None or self.agents
        ):
            raise ValueError("미완료 내보내기는 명시적 사유와 null 건수, 빈 목록이 필요합니다.")
        if self.failure_code is not None:
            expected_reason = {
                "network_error": "error", "invalid_response": "error",
                "authentication_error": "permission_denied",
            }.get(self.failure_code, self.failure_code)
            if self.reason != expected_reason:
                raise ValueError("실패 사유와 세부 코드가 일치하지 않습니다.")
        return self


def _validated_export(raw: bytes, tenant: str, now: datetime) -> CopilotInventoryExport:
    export = CopilotInventoryExport.model_validate_json(raw)
    if export.tenant_id != str(uuid.UUID(tenant)):
        raise ValueError("Copilot 내보내기 테넌트가 대상과 다릅니다.")
    if export.exported_at > now + timedelta(minutes=5) or (
        now - export.observed_at > MAX_EXPORT_AGE
    ):
        raise ValueError("Copilot 내보내기는 최근 24시간 관측과 현재 시각 확인이 필요합니다.")
    # Apply the same minimization to independently supplied, schema-valid files.
    return CopilotInventoryExport.model_validate_json(
        json.dumps(redact(export.model_dump(mode="json"))),
    )


def load_copilot_export(path: Path, tenant: str, now: datetime) -> CopilotInventoryExport:
    return _validated_export(path.read_bytes(), tenant, now)


def read_copilot_inventory(
    path: Path, tenant: str, now: datetime, store: EvidenceStore,
) -> Collection:
    raw = path.read_bytes()
    export = _validated_export(raw, tenant, now)
    digest = hashlib.sha256(raw).hexdigest()
    ref = store.save("copilot-inventory-export:" + digest, {
        "input_sha256": digest, "export": export.model_dump(mode="json"),
        "verification_limit": LIMITATION,
    })
    result = Collection(collected_at=now, facts={
        "copilot_inventory_requested": True,
        "copilot_inventory_complete": export.completed,
        "copilot_inventory_refs": [ref],
        "copilot_inventory_tenant_ids": [export.tenant_id],
        "copilot_inventory_status": [{
            "completed": export.completed, "reason": export.reason, "evidence_refs": [ref],
            "failure_code": export.failure_code,
            "observed_at": export.observed_at.isoformat(),
        }],
    })
    if not export.completed:
        result.issues.append(Issue(
            collector="copilot_inventory", target=PP_INVENTORY_URL,
            reason=export.reason, detail="별도 관리자 인벤토리 내보내기 미완료: " + export.failure_code,
            required_roles=["Global Reader 또는 AI Reader - 별도 사용자"],
            evidence_refs=[ref],
        ))
        return result
    for row in export.agents:
        values = row.model_dump()
        platform = classify_created_in(row.created_in)
        status = {}
        for name, value in values.items():
            if value is None and name != "last_published_at":
                status[name] = FieldStatus(
                    reason="not_found", detail="공식 인벤토리의 해당 값이 null - 구성 부재/실패로 추론하지 않음",
                )
        if platform == "unclassified_copilot":
            status["platform"] = FieldStatus(
                reason="feature_unavailable", detail="미확인 createdIn 원문 유지 - 도구 출처를 추측하지 않음",
            )
        if platform == "agent_builder":
            for name in ("entra_agent_id", "blueprint_id"):
                values[name] = None
                status[name] = FieldStatus(
                    reason="feature_unavailable", detail="Agent Builder에는 해당 없음 - 실패한 통제 아님",
                )
        if row.harness is not None and row.harness != "Standard" and row.evaluation_read is None:
            status["evaluation_read"] = FieldStatus(
                reason="not_found",
                detail="기본 조회는 Standard 하니스 대상 - 다른 하니스는 별도 읽기 앱으로 실제 GET 확인 필요",
            )
        result.copilot_agents.append(CopilotAgentEvidence(
            **values, platform=platform, field_status=status, evidence_refs=[ref],
        ))
        if row.evaluation_read is not None and not row.evaluation_read.completed:
            assert row.evaluation_read.reason is not None
            result.issues.append(Issue(
                collector="copilot_evaluations", target=row.agent_id,
                reason=row.evaluation_read.reason,
                detail="공식 Copilot 평가 실행 목록의 별도 사용자 읽기 미완료",
                evidence_refs=[ref],
            ))
    return result
