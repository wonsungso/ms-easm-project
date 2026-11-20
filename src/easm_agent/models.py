from __future__ import annotations

import sysconfig
import uuid
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

import yaml
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

Reason = Literal["permission_denied", "feature_unavailable", "license_missing", "not_found", "error"]
Platform = Literal["foundry", "langchain", "custom", "other", "manual"]
HOSTED_AGENT_PLATFORMS = ("langchain", "custom")
AZURE_AGENT_PLATFORMS = ("foundry", *HOSTED_AGENT_PLATFORMS)


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldStatus(EvidenceModel):
    reason: Reason
    detail: str


class Usage(EvidenceModel):
    calls: int | None = Field(default=None, ge=0)
    tokens: int | None = Field(default=None, ge=0)


class CopilotAgentEvidence(EvidenceModel):
    agent_id: StrictStr
    environment_id: StrictStr
    platform: Literal["agent_builder", "copilot_studio", "unclassified_copilot"]
    display_name: StrictStr | None = None
    created_in: StrictStr | None = None
    created_at: AwareDatetime | None = None
    last_published_at: AwareDatetime | None = None
    owner_present: StrictBool | None = None
    entra_agent_id: StrictStr | None = None
    blueprint_id: StrictStr | None = None
    model: StrictStr | None = None
    authentication: StrictStr | None = None
    channels: list[StrictStr] | None = None
    is_quarantined: StrictBool | None = None
    shared_with_tenant: StrictBool | None = None
    field_status: dict[str, FieldStatus] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class AgentEvidence(EvidenceModel):
    collected_at: AwareDatetime
    tenant_id: str | None = None
    subscription_id: str | None = None
    resource_group: str | None = None
    platform: Platform
    agent_id: str
    agent_name: str
    agent_version: str | None = None
    resource_id: str | None = None
    hosting_type: str | None = None
    owner: str | None = None
    sponsor: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    model: str | None = None
    model_version: str | None = None
    model_resource_id: str | None = None
    cost_resource_ids: list[str] = Field(default_factory=list)
    tools: list[str] | None = None
    created_at: AwareDatetime | None = None
    deployed_at: AwareDatetime | None = None
    last_used_at: AwareDatetime | None = None
    cost_30d: float | None = None
    currency: str | None = None
    usage_30d: Usage | None = None
    calls_90d: int | None = None
    usage_coverage_start: AwareDatetime | None = None
    evaluated_before_deploy: bool | None = None
    guardrail_applied: bool | None = None
    detection_confidence: Literal["tag", "name_heuristic", "manual"]
    evidence_refs: list[str] = Field(default_factory=list)
    se_codes: list[str] = Field(default_factory=list)
    field_status: dict[str, FieldStatus] = Field(default_factory=dict)

    def mark_unknowns(self, detail: str = "응답에 해당 필드가 없음") -> AgentEvidence:
        for key in type(self).model_fields:
            if getattr(self, key) is None and key not in self.field_status:
                self.field_status[key] = FieldStatus(reason="not_found", detail=detail)
        if self.usage_30d:
            for key in ("calls", "tokens"):
                name = "usage_30d." + key
                if getattr(self.usage_30d, key) is None and name not in self.field_status:
                    self.field_status[name] = FieldStatus(reason="not_found", detail=detail)
        return self

    def unavailable(self, field: str, reason: Reason, detail: str) -> None:
        setattr(self, field, None)
        self.field_status[field] = FieldStatus(reason=reason, detail=detail)


class ModelDeployment(EvidenceModel):
    subscription_id: str
    resource_id: str
    account_id: str
    name: str
    model: str | None
    version: str | None
    format: str | None
    sku: str | None = None
    capacity: int | None = None
    state: str | None = None
    rai_policy: str | None = None
    version_upgrade_option: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class EvaluationRun(EvidenceModel):
    subscription_id: str
    project_id: str
    run_id: str
    status: str | None
    agent_id: str | None = None
    agent_version: str | None = None
    completed_at: AwareDatetime | None = None
    passed_items: int | None = Field(default=None, ge=0)
    failed_items: int | None = Field(default=None, ge=0)
    errored_items: int | None = Field(default=None, ge=0)
    total_items: int | None = Field(default=None, ge=0)
    evidence_refs: list[str] = Field(default_factory=list)


class CostRecord(EvidenceModel):
    subscription_id: str
    resource_id: str
    amount: float
    currency: str
    usage_date: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class SecurityRecommendation(EvidenceModel):
    subscription_id: str
    resource_id: str
    assessment_id: str
    severity: str | None
    status: str | None
    first_evaluation_date: datetime | None = None
    status_change_date: datetime | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class SecureScore(EvidenceModel):
    subscription_id: str
    current: float | None = None
    max: float | None = None
    percentage: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class DefenderPlan(EvidenceModel):
    subscription_id: str
    plan: str
    tier: str | None = None
    sub_plan: str | None = None
    coverage: str | None = None
    extensions: dict[str, bool | None] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class PolicyAssignment(EvidenceModel):
    subscription_id: str
    assignment_id: str
    display_name: str | None = None
    policy_definition_id: str
    scope: str | None = None
    enforcement_mode: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class Budget(EvidenceModel):
    subscription_id: str
    budget_id: str
    amount: float | None = None
    category: str | None = None
    time_grain: str | None = None
    enabled_alerts: int = 0
    forecast_alerts: int = 0
    thresholds: list[float] = Field(default_factory=list)
    actual_alerts: int | None = Field(default=None, ge=0)
    period_start: AwareDatetime | None = None
    period_end: AwareDatetime | None = None
    filters_empty: bool | None = None
    notifications_with_receivers: bool | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class LogSetting(EvidenceModel):
    subscription_id: str
    resource_id: str
    enabled: bool
    workspace_id: str | None = None
    retention_days: int | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class EntraBlueprint(EvidenceModel):
    blueprint_id: str
    display_name: str | None = None
    created_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class EntraAgentIdentity(EvidenceModel):
    identity_id: str
    display_name: str | None = None
    blueprint_id: str | None = None
    created_at: datetime | None = None
    account_enabled: bool | None = None
    owner_count: int | None = None
    sponsor_count: int | None = None
    owners_all_disabled: bool | None = None
    app_roles: list[str] = Field(default_factory=list)
    overprivileged_roles: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class AgentCaPolicy(EvidenceModel):
    policy_id: str
    display_name: str | None = None
    state: str | None = None
    include_all_agents: bool = False
    include_agent_ids: list[str] = Field(default_factory=list)
    exclude_agent_ids: list[str] = Field(default_factory=list)
    uses_agent_filter: bool = False
    agent_risk_levels: list[str] = Field(default_factory=list)
    grant_controls: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class RiskyAgent(EvidenceModel):
    risky_agent_id: str
    risk_level: str | None = None
    risk_state: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class ProposalObservation(EvidenceModel):
    code: str
    subscription_id: str | None = None
    subject: str
    kind: str
    values: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class ProposalFinding(EvidenceModel):
    code: str
    title: str
    area: str = ""
    status: Literal["수집됨", "일부 수집", "수집 불가"]
    metrics: dict[str, Any] = Field(default_factory=dict)
    observation: str
    limit: str
    reason: Reason | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_only: bool = False


class Issue(EvidenceModel):
    subscription_id: str | None = None
    collector: str
    target: str
    reason: Reason
    detail: str
    required_roles: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class Agent365Package(EvidenceModel):
    package_id: str
    manifest_id: str | None = None
    agent_identity_id: str | None = None
    version: str | None = None
    display_name: str | None = None
    platform: str | None = None
    available_to: str | None = None
    deployed_to: str | None = None
    is_blocked: bool | None = None
    created_at: AwareDatetime | None = None
    last_modified_at: AwareDatetime | None = None
    request_status: str | None = None
    request_type: str | None = None
    governance: str | None = None
    owner_count: int | None = Field(default=None, ge=0)
    active_users_30d: StrictInt | None = Field(default=None, ge=0, le=2147483647)
    total_sessions_30d: StrictInt | None = Field(default=None, ge=0, le=2147483647)
    total_run_time_hours_30d: float | None = Field(default=None, ge=0, strict=True, allow_inf_nan=False)
    exception_count_30d: float | None = Field(default=None, ge=0, strict=True, allow_inf_nan=False)
    last_used_at: AwareDatetime | None = None
    package_type: StrictStr | None = None
    manifest_version: StrictStr | None = None
    app_id: StrictStr | None = None
    supported_hosts: list[StrictStr] | None = Field(default=None, max_length=64)
    element_types: list[StrictStr] | None = Field(default=None, max_length=64)
    categories: list[StrictStr] | None = Field(default=None, max_length=64)
    category_count: StrictInt | None = Field(default=None, ge=0)
    sensitivity: StrictStr | None = None
    sensitivity_present: StrictBool | None = None
    metadata_complete: bool = False
    metadata_field_sources: dict[str, Literal["catalog", "detail", "not_requested"]] = Field(default_factory=dict)
    metadata_evidence_refs: dict[str, list[str]] = Field(default_factory=dict)
    detail_complete: bool = False
    detail_evidence_refs: list[str] = Field(default_factory=list)
    field_status: dict[str, FieldStatus] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def mark_missing_metadata(self) -> Agent365Package:
        for field in (
            "package_type", "manifest_version", "app_id", "supported_hosts", "element_types",
            "categories", "category_count", "sensitivity", "sensitivity_present",
        ):
            if getattr(self, field) is None:
                self.field_status.setdefault(
                    field, FieldStatus(reason="not_found", detail="메타데이터 미수집 또는 응답에서 미확인"),
                )
        return self


class Agent365Crosscheck(EvidenceModel):
    se_code: str
    status: Literal["partial_match", "mismatch", "unavailable", "not_comparable"]
    scope: str
    detail: str
    compared: int | None = Field(default=None, ge=0)
    matched: int | None = Field(default=None, ge=0)
    mismatched: int | None = Field(default=None, ge=0)
    unverified: int | None = Field(default=None, ge=0)
    reason: Reason | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class AdminEnvironment(EvidenceModel):
    environment_id: str
    display_name: str | None = None
    environment_type: str | None = None
    protection_level: str | None = None
    region: str | None = None
    field_status: dict[str, FieldStatus] = Field(default_factory=dict)

    @model_validator(mode="after")
    def mark_missing(self) -> AdminEnvironment:
        for field in ("display_name", "environment_type", "protection_level", "region"):
            if getattr(self, field) is None:
                self.field_status.setdefault(
                    field, FieldStatus(reason="not_found", detail="공식 환경 응답에서 값 미확인"),
                )
        return self


class AdminPolicyScope(EvidenceModel):
    scope_type: str | None = None
    environment_ids: list[str] = Field(default_factory=list)


class AdminPortalPage(EvidenceModel):
    url: str
    observed_at: AwareDatetime
    http_status: StrictInt
    state: Literal["empty", "populated"]
    object_count: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_page(self) -> AdminPortalPage:
        if self.http_status != 200 or (self.state == "empty") != (self.object_count == 0):
            raise ValueError("관리 센터 증적은 HTTP 200과 실제 목록·빈 상태의 일치가 필요합니다.")
        return self


class AdminReadResult(EvidenceModel):
    source: Literal[
        "powerplatform.environments", "powerplatform.environment_roles", "powerplatform.dlp_policies",
        "powerplatform.dataverse_roles",
    ]
    command: str
    module_version: str
    scope: str
    completed: StrictBool
    observed_at: AwareDatetime
    object_count: StrictInt | None = Field(default=None, ge=0)
    environments: list[AdminEnvironment] = Field(default_factory=list)
    role_counts: dict[str, StrictInt] = Field(default_factory=dict)
    policies: list[AdminPolicyScope] = Field(default_factory=list)
    portal_pages: list[AdminPortalPage] = Field(default_factory=list)
    reason: Reason | None = None
    detail: str
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_read(self) -> AdminReadResult:
        if self.completed and (self.object_count is None or self.reason is not None):
            raise ValueError("완료된 관리자 조회에는 확인된 건수와 오류 없음이 필요합니다.")
        if not self.completed and (self.reason is None or self.object_count is not None):
            raise ValueError("실패한 관리자 조회는 사유와 null 건수를 유지해야 합니다.")
        if not self.completed and (self.environments or self.role_counts or self.policies):
            raise ValueError("미완료 조회를 완전한 집계나 목록으로 사용할 수 없습니다.")
        if self.role_counts and self.source not in ("powerplatform.environment_roles", "powerplatform.dataverse_roles"):
            raise ValueError("환경별 역할 건수를 다른 명령 결과로 사용할 수 없습니다.")
        if self.policies and self.source != "powerplatform.dlp_policies":
            raise ValueError("정책 범위를 다른 명령 결과로 사용할 수 없습니다.")
        if any(value < 0 for value in self.role_counts.values()):
            raise ValueError("역할 할당 건수는 음수일 수 없습니다.")
        return self


class AdminEvidenceExport(EvidenceModel):
    schema_version: Literal[1]
    source_type: Literal["official_admin_read", "official_admin_portal_read"]
    tenant_id: str
    tenant_verified: StrictBool
    exported_at: AwareDatetime
    reads: list[AdminReadResult] = Field(min_length=1, max_length=3)


class EvidenceSource(EvidenceModel):
    target: str
    evidence_refs: list[str] = Field(default_factory=list)


class AssessmentProvenance(EvidenceModel):
    evaluated_at: AwareDatetime
    origin: Literal["evaluation", "saved_snapshot_reassessment"]
    criteria_snapshot: dict[str, Any]
    criteria_sha256: str
    conventions_snapshot: dict[str, Any]
    conventions_sha256: str
    collector_version: str
    collector_source_sha256: str
    source_result_data_sha256: str | None = None
    hash_scope: str = "SHA-256 of masked snapshot JSON; UTF-8, sorted keys, compact separators"

    @model_validator(mode="after")
    def verify_snapshots(self) -> AssessmentProvenance:
        from easm_agent.provenance import digest

        for field in ("criteria", "conventions"):
            if digest(getattr(self, f"{field}_snapshot")) != getattr(self, f"{field}_sha256"):
                raise ValueError(f"{field} 기준 사본과 해시가 일치하지 않습니다.")
        return self


class TargetAssessment(EvidenceModel):
    subject: str
    status: Literal["compliant", "non_compliant", "unknown", "excluded"] = "unknown"
    observed: dict[str, Any] = Field(default_factory=dict)
    contribution: float | None = None
    reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class AssessmentMeasurement(EvidenceModel):
    numerator: float | None = None
    denominator: float | None = None
    unit: Literal["count", "amount"] = "count"
    currency: str | None = None
    complete: bool
    reason: str | None = None
    targets: list[TargetAssessment] = Field(default_factory=list)


class ReportTarget(EvidenceModel):
    subject: StrictStr = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_:/.-]+$")
    evidence_ids: list[StrictStr] = Field(default_factory=list)


class CreationApprovalRecord(ReportTarget):
    created_at: AwareDatetime
    approval_found: StrictBool | None
    approval_id: StrictStr | None = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_:/.-]+$")
    approved_at: AwareDatetime | None

    @model_validator(mode="after")
    def approval_consistent(self) -> CreationApprovalRecord:
        if self.approval_found is True and (not self.approval_id or self.approved_at is None):
            raise ValueError("매칭된 승인에는 요청 ID·승인 시각이 필요합니다.")
        if self.approval_found is not True and (self.approval_id is not None or self.approved_at is not None):
            raise ValueError("미확인·미매칭 승인을 승인 기록으로 채울 수 없습니다.")
        return self


class RegistryRecord(ReportTarget):
    owner_present: StrictBool | None
    deployment_scope_present: StrictBool | None


class PredeploymentRecord(ReportTarget):
    version: StrictStr = Field(min_length=1)
    deployed_at: AwareDatetime
    evaluation_found: StrictBool | None
    evaluation_version: StrictStr | None
    evaluation_completed_at: AwareDatetime | None
    evaluation_status: Literal["completed", "succeeded", "failed", "error"] | None

    @model_validator(mode="after")
    def evaluation_consistent(self) -> PredeploymentRecord:
        values = (self.evaluation_version, self.evaluation_completed_at, self.evaluation_status)
        if self.evaluation_found is True and any(value is None for value in values):
            raise ValueError("평가 기록에는 버전·완료 시각·상태가 필요합니다.")
        if self.evaluation_found is not True and any(value is not None for value in values):
            raise ValueError("미확인·미확보 평가를 실행 이력으로 채울 수 없습니다.")
        return self


class AgentUsageRecord(ReportTarget):
    created_at: AwareDatetime
    coverage_start: AwareDatetime
    coverage_end: AwareDatetime
    calls_30d: StrictInt | None = Field(ge=0)
    calls_90d: StrictInt | None = Field(ge=0)

    @model_validator(mode="after")
    def usage_consistent(self) -> AgentUsageRecord:
        if self.coverage_start >= self.coverage_end or self.created_at > self.coverage_end:
            raise ValueError("사용 관측 기간·생성 시각이 올바르지 않습니다.")
        if self.calls_30d is not None and self.calls_90d is not None and self.calls_30d > self.calls_90d:
            raise ValueError("30일 호출 수가 90일 호출 수보다 많습니다.")
        return self


class ExposureRecord(ReportTarget):
    category: Literal["national_id", "personal", "legal", "financial", "other"]
    severity: Literal["high", "medium", "low"] | None
    remediation: Literal["remediated", "open"] | None


class AuditRetentionRecord(ReportTarget):
    retention_duration: Literal["ThreeMonths", "SixMonths", "NineMonths", "TwelveMonths", "TenYears"] | None
    priority: StrictInt | None = Field(default=None, ge=0)


class BooleanControlRecord(ReportTarget):
    value: StrictBool | None


class HistoricalCostRecord(ReportTarget):
    occurred_at: AwareDatetime
    amount: float = Field(strict=True, ge=0, allow_inf_nan=False)
    attributed_amount: float | None = Field(default=None, strict=True, ge=0, allow_inf_nan=False)
    currency: StrictStr = Field(pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def attribution_bounded(self) -> HistoricalCostRecord:
        if self.attributed_amount is not None and self.attributed_amount > self.amount:
            raise ValueError("귀속 금액은 전체 금액을 초과할 수 없습니다.")
        return self


class ReportDatasetBase(EvidenceModel):
    scope: StrictStr = Field(min_length=1, max_length=240)
    source_kind: Literal[
        "official_admin_read", "organization_registry", "approval_workflow",
        "deployment_records", "hr_export",
    ]
    source_ref: StrictStr = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.-]+$")
    observed_at: AwareDatetime
    period_start: AwareDatetime | None = None
    period_end: AwareDatetime | None = None
    complete: StrictBool
    population_complete: StrictBool
    reason: Reason | None
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def dataset_consistent(self) -> ReportDatasetBase:
        if self.complete != (self.reason is None):
            raise ValueError("조회 완료와 실패 사유가 일치하지 않습니다.")
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("기간 증적에는 시작·종료 시각이 모두 필요합니다.")
        if self.period_start is not None and self.period_end is not None and (
            self.period_start >= self.period_end or self.period_end > self.observed_at
        ):
            raise ValueError("증적 기간은 관측 시각 이전의 유효한 반개구간이어야 합니다.")
        records = getattr(self, "records", [])
        if len({record.subject for record in records}) != len(records):
            raise ValueError("같은 추가 증적의 대상 ID가 중복되었습니다.")
        return self


class CreationEvidence(ReportDatasetBase):
    kind: Literal["creation_approvals"]
    code: Literal["DM-SE-27"] = "DM-SE-27"
    records: list[CreationApprovalRecord]


class RegistryEvidence(ReportDatasetBase):
    kind: Literal["registry"]
    code: Literal["DP-SE-28"] = "DP-SE-28"
    observed_subjects: list[StrictStr]
    records: list[RegistryRecord]

    @model_validator(mode="after")
    def registry_population(self) -> RegistryEvidence:
        if self.source_kind != "organization_registry" or len(set(self.observed_subjects)) != len(self.observed_subjects):
            raise ValueError("독립 등록부 원천과 중복 없는 관측 인벤토리가 필요합니다.")
        for subject in self.observed_subjects:
            ReportTarget(subject=subject)
        return self


class PredeploymentEvidence(ReportDatasetBase):
    kind: Literal["predeployment_evaluations"]
    code: Literal["BI-SE-29"] = "BI-SE-29"
    records: list[PredeploymentRecord]


class BooleanControlEvidence(ReportDatasetBase):
    kind: Literal["target_controls"]
    code: Literal["OE-SE-30", "OE-SE-39"]
    records: list[BooleanControlRecord]

    @model_validator(mode="after")
    def control_source(self) -> BooleanControlEvidence:
        if self.code == "OE-SE-39" and self.source_kind != "hr_export":
            raise ValueError("재직 여부는 계정 활성 상태가 아닌 별도 인사 대사 증적이 필요합니다.")
        if self.code == "OE-SE-30" and self.source_kind != "official_admin_read":
            raise ValueError("조건부 접근은 해당 정책의 실제 관리자 읽기 증적이 필요합니다.")
        return self


class AuditRetentionEvidence(ReportDatasetBase):
    kind: Literal["audit_retention"]
    code: Literal["OE-SE-31"] = "OE-SE-31"
    records: list[AuditRetentionRecord]


class UsageEvidence(ReportDatasetBase):
    kind: Literal["usage"]
    code: Literal["OT-SE-32"] = "OT-SE-32"
    records: list[AgentUsageRecord]


class ExposureEvidence(ReportDatasetBase):
    kind: Literal["exposures"]
    code: Literal["OT-SE-33"] = "OT-SE-33"
    records: list[ExposureRecord]


class CostHistoryEvidence(ReportDatasetBase):
    kind: Literal["cost_history"]
    code: Literal["OT-SE-34"] = "OT-SE-34"
    records: list[HistoricalCostRecord]


ReportEvidenceDataset = Annotated[
    CreationEvidence | RegistryEvidence | PredeploymentEvidence | BooleanControlEvidence
    | AuditRetentionEvidence | UsageEvidence | ExposureEvidence | CostHistoryEvidence,
    Field(discriminator="kind"),
]


class ReportEvidenceRawRecord(EvidenceModel):
    code: str
    scope: str
    source_kind: str
    source_ref: str
    complete: bool
    population_complete: bool
    observed_at: AwareDatetime
    period_start: AwareDatetime | None
    period_end: AwareDatetime | None
    reason: Reason | None
    values: dict[str, Any]
    evidence_refs: list[str] = Field(default_factory=list)


class Collection(EvidenceModel):
    collected_at: AwareDatetime
    agents: list[AgentEvidence] = Field(default_factory=list)
    copilot_agents: list[CopilotAgentEvidence] = Field(default_factory=list)
    report_evidence: list[ReportEvidenceDataset] = Field(default_factory=list)
    deployments: list[ModelDeployment] = Field(default_factory=list)
    evaluations: list[EvaluationRun] = Field(default_factory=list)
    costs: list[CostRecord] = Field(default_factory=list)
    security: list[SecurityRecommendation] = Field(default_factory=list)
    secure_scores: list[SecureScore] = Field(default_factory=list)
    defender_plans: list[DefenderPlan] = Field(default_factory=list)
    policy_assignments: list[PolicyAssignment] = Field(default_factory=list)
    budgets: list[Budget] = Field(default_factory=list)
    entra_blueprints: list[EntraBlueprint] = Field(default_factory=list)
    entra_agent_identities: list[EntraAgentIdentity] = Field(default_factory=list)
    agent365_packages: list[Agent365Package] = Field(default_factory=list)
    agent365_crosschecks: list[Agent365Crosscheck] = Field(default_factory=list)
    admin_evidence: list[AdminReadResult] = Field(default_factory=list)
    # Legacy result input only; these diagnostics are no longer collected or exported.
    agent_ca_policies: list[AgentCaPolicy] = Field(default_factory=list, exclude=True)
    risky_agents: list[RiskyAgent] = Field(default_factory=list, exclude=True)
    logs: list[LogSetting] = Field(default_factory=list)
    proposal_observations: list[ProposalObservation] = Field(default_factory=list)
    proposals: list[ProposalFinding] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    subscriptions: list[str] = Field(default_factory=list)
    completed_subscriptions: list[str] = Field(default_factory=list)
    resources: list[dict[str, Any]] = Field(default_factory=list)
    evidence_sources: list[EvidenceSource] = Field(default_factory=list)
    assessment_provenance: AssessmentProvenance | None = None
    facts: dict[str, Any] = Field(default_factory=dict)


class Finding(EvidenceModel):
    se_code: str
    scope: str
    metric_value: float | int | None = None
    measurement: AssessmentMeasurement | None = None
    level: Literal["L1", "L2", "L3", "L4", "L5", "N/A"]
    assessment_basis: Literal["criteria", "configuration"] = "criteria"
    configuration_value: float | int | None = Field(default=None, gt=0)
    level_criterion: str | None = None
    rationale: str
    reason: Reason | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    next_step: str | None = None
    interview_level: float | None = Field(default=None, ge=1, le=5)
    gap_flag: bool = False


def timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    from datetime import UTC

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone is required for evidence timestamps")
        return parsed
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value
    raise ValueError("Invalid evidence timestamp")


def try_timestamp(value: object) -> datetime | None:
    try:
        return timestamp(value)
    except (ValueError, TypeError):
        return None


class Collector(Protocol):
    required_roles: tuple[str, ...]

    def discover(self, subscriptions: Sequence[str]) -> Collection: ...


class ProjectSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription_id: str
    resource_id: str
    endpoint: str


CRITERIA_FILE = Path(__file__).resolve().parents[2] / "config" / "criteria.yaml"
DEFAULT_TAGS: dict[str, Any] = {
    "agent_type_key": "agent-type", "langchain_values": ["langchain"],
    "owner_key": "owner", "sponsor_key": "sponsor", "environment_key": "env",
    "cost_center_key": "cost-center", "agent_id_key": "agent-id",
    "model_deployment_key": "model-deployment", "model_resource_key": "model-resource-id",
    "production_values": ["prod", "production"], "name_patterns": ["langchain", "lc-agent"],
}


class AllowedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: str
    format: str = "OpenAI"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str | None = None
    expected_principal_id: str | None = None
    subscriptions: list[str] = Field(default_factory=list)
    workers: int = Field(default=3, ge=1, le=16)
    criteria_file: Path | None = None
    evidence_dir: Path = Path(".easm-agent/evidence")
    foundry_profile: Literal["agents_v1", "classic_v1"] = "agents_v1"
    projects: list[ProjectSettings] = Field(default_factory=list)
    manual_agents: Path | None = None
    admin_evidence_files: list[Path] = Field(default_factory=list)
    copilot_inventory_files: list[Path] = Field(default_factory=list)
    report_evidence_files: list[Path] = Field(default_factory=list)
    report_cost_history: bool = False
    agent365_registry: bool = False
    allowed_models: list[AllowedModel] = Field(default_factory=list)
    tags: dict[str, StrictStr] = Field(default_factory=dict)
    tag_conventions: dict[str, Any] = Field(default_factory=dict)
    model_policy_definition_ids: list[str] = Field(default_factory=list)
    required_retention_days: int | None = None
    internal_security_score_min: float | None = None
    overprivileged_permission_patterns: list[str] = Field(default_factory=list)
    policy_facts: dict[str, Any] = Field(default_factory=dict)
    interview_levels: dict[str, float] = Field(default_factory=dict)
    monitor: dict[str, list[str]] = Field(default_factory=lambda: {
        "calls_metric_candidates": ["AzureOpenAIRequests", "Requests"],
        "token_metric_candidates": [
            "ProcessedPromptTokens", "GeneratedTokens", "InputTokens", "OutputTokens",
        ],
    })

    @model_validator(mode="after")
    def validate_ids(self) -> Settings:
        if any(not key.strip() or not value.strip() for key, value in self.tags.items()):
            raise ValueError("탐지 태그의 key와 value는 비어 있을 수 없습니다.")
        if self.tag_conventions.keys() - DEFAULT_TAGS.keys():
            raise ValueError("지원하지 않는 태그 규약 설정입니다.")
        for key, value in self.tag_conventions.items():
            if isinstance(DEFAULT_TAGS[key], list):
                if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                    raise ValueError("태그 규약의 목록에는 비어 있지 않은 문자열이 필요합니다.")
            elif not isinstance(value, str) or not value.strip():
                raise ValueError("태그 규약에는 비어 있지 않은 문자열이 필요합니다.")
        for field in ("tenant_id", "expected_principal_id"):
            if value := getattr(self, field):
                setattr(self, field, str(uuid.UUID(value)))
        self.subscriptions = list(dict.fromkeys(str(uuid.UUID(sid)) for sid in self.subscriptions))
        if any(not 1 <= value <= 5 for value in self.interview_levels.values()):
            raise ValueError("Interview levels must be between 1 and 5")
        return self


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path.name}: YAML 형식 오류") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: YAML object is required")
    return value


def load_settings(path: Path) -> Settings:
    if not path.is_file():
        return Settings()
    values = load_yaml(path)
    tags = values.get("tags")
    # List-valued selectors distinguish the former convention format from tag filters.
    if isinstance(tags, dict) and tags and tags.keys() <= DEFAULT_TAGS.keys():
        if "tag_conventions" not in values and any(isinstance(value, list) for value in tags.values()):
            values["tag_conventions"] = values.pop("tags")
    return Settings.model_validate(values)


def load_criteria(settings: Settings | None = None) -> dict[str, Any]:
    """작업 폴더·소스·설치본의 기준을 읽고 선택한 고객 입력을 적용한다."""
    if settings is not None and settings.criteria_file is not None:
        path = settings.criteria_file
    elif (Path("config") / "criteria.yaml").is_file():
        path = Path("config") / "criteria.yaml"
    elif CRITERIA_FILE.is_file():
        path = CRITERIA_FILE
    else:
        path = Path(sysconfig.get_path("data")) / "share" / "easm-agent" / "criteria.yaml"
    criteria = load_yaml(path)
    if settings is None:
        return criteria
    if settings.model_policy_definition_ids:
        criteria["model_policy_definition_ids"] = settings.model_policy_definition_ids
    if settings.required_retention_days is not None:
        criteria["required_retention_days"] = settings.required_retention_days
    if settings.internal_security_score_min is not None:
        criteria["internal_security_score_min"] = settings.internal_security_score_min
    if settings.overprivileged_permission_patterns:
        criteria["overprivileged_permission_patterns"] = settings.overprivileged_permission_patterns
        criteria["overprivileged_permissions_sample"] = False
    return criteria


def load_conventions(settings: Settings) -> dict[str, Any]:
    return {**DEFAULT_TAGS, **settings.tag_conventions, "custom_tag_filters": settings.tags}
