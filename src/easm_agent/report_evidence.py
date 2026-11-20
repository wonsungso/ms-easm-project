"""Collect approved, scoped evidence for report controls beyond the Azure API profile."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, StrictBool, field_validator, model_validator

from easm_agent.azure import EvidenceStore, redact
from easm_agent.models import (
    AuditRetentionEvidence,
    BooleanControlEvidence,
    Collection,
    CostHistoryEvidence,
    CreationEvidence,
    EvidenceModel,
    ExposureEvidence,
    Issue,
    PredeploymentEvidence,
    Reason,
    RegistryEvidence,
    ReportEvidenceDataset,
    UsageEvidence,
)


class ReportEvidenceExport(EvidenceModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    source_type: Literal["approved_report_evidence"]
    approved: StrictBool
    tenant_id: str
    tenant_verified: StrictBool
    data_mode: Literal["live", "fixture"]
    exported_at: AwareDatetime
    datasets: list[ReportEvidenceDataset]

    @field_validator("schema_version", mode="before")
    @classmethod
    def schema_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("추가 증적 schema_version은 정수여야 합니다.")
        return value

    @field_validator("tenant_id")
    @classmethod
    def tenant_uuid(cls, value: str) -> str:
        return str(uuid.UUID(value))

    @model_validator(mode="after")
    def export_consistent(self) -> ReportEvidenceExport:
        if not self.approved or not self.datasets or (
            not self.tenant_verified and any(dataset.complete for dataset in self.datasets)
        ):
            raise ValueError("추가 System Evidence에는 승인·테넌트 확인·원천 데이터가 필요합니다.")
        if len({dataset.code for dataset in self.datasets}) != len(self.datasets):
            raise ValueError("추가 System Evidence 코드가 중복되었습니다.")
        for dataset in self.datasets:
            if dataset.observed_at > self.exported_at:
                raise ValueError("증적 관측 시각이 내보내기 시각보다 늦습니다.")
            if isinstance(dataset, CreationEvidence) and dataset.source_kind != "approval_workflow":
                raise ValueError("생성 승인 매칭은 별도 승인 워크플로 원천이 필요합니다.")
            if isinstance(dataset, CreationEvidence):
                for record in dataset.records:
                    if record.created_at > dataset.observed_at or (
                        record.approved_at is not None and record.approved_at > dataset.observed_at
                    ):
                        raise ValueError("관측 시각보다 미래의 생성·승인 기록입니다.")
                    if dataset.period_start and dataset.period_end and not (
                        dataset.period_start <= record.created_at < dataset.period_end
                    ):
                        raise ValueError("생성 기록이 수집 기간 밖에 있습니다.")
            if isinstance(dataset, PredeploymentEvidence):
                if dataset.source_kind not in ("official_admin_read", "deployment_records"):
                    raise ValueError("배포 전 평가는 실제 배포·평가 실행 원천이 필요합니다.")
                for record in dataset.records:
                    if record.deployed_at > dataset.observed_at or (
                        record.evaluation_completed_at is not None
                        and record.evaluation_completed_at > dataset.observed_at
                    ):
                        raise ValueError("관측 시각보다 미래의 배포·평가 기록입니다.")
            if isinstance(dataset, CostHistoryEvidence):
                if dataset.source_kind != "official_admin_read":
                    raise ValueError("비용 이력은 청구 원천의 관리자 읽기 증적이 필요합니다.")
                for record in dataset.records:
                    if not dataset.period_start or not dataset.period_end or not (
                        dataset.period_start <= record.occurred_at < dataset.period_end
                    ):
                        raise ValueError("비용 기록의 수집 기간을 확인할 수 없습니다.")
            if isinstance(dataset, UsageEvidence):
                if not dataset.period_start or not dataset.period_end:
                    raise ValueError("사용 이력에는 명시적 수집 기간이 필요합니다.")
                if any(record.coverage_end > dataset.observed_at for record in dataset.records):
                    raise ValueError("사용 관측 종료가 증적 관측 시각보다 늦습니다.")
                if any(
                    record.coverage_end != dataset.period_end or record.coverage_start < dataset.period_start
                    for record in dataset.records
                ):
                    raise ValueError("30·90일 호출 수의 기준 종료와 선언한 관측 구간이 일치해야 합니다.")
        return self


def read_report_evidence(
    path: Path, tenant: str, now: datetime, store: EvidenceStore,
) -> Collection:
    raw = path.read_bytes()
    export = ReportEvidenceExport.model_validate_json(raw)
    if export.tenant_id != str(uuid.UUID(tenant)) or export.data_mode != "live":
        raise ValueError("추가 증적의 실제 테넌트·데이터 구분이 수집 대상과 다릅니다.")
    if export.exported_at > now + timedelta(minutes=5) or any(
        now - dataset.observed_at > timedelta(hours=24) for dataset in export.datasets
    ):
        raise ValueError("추가 증적은 최근 24시간 관측과 현재 시각 확인이 필요합니다.")
    export = ReportEvidenceExport.model_validate_json(json.dumps(redact(export.model_dump(mode="json"))))
    digest = hashlib.sha256(raw).hexdigest()
    ref = store.save("report-evidence-export:" + digest, {
        "input_sha256": digest, "export": export.model_dump(mode="json"),
        "limit": "승인된 원천 내보내기이며 API 원천의 암호학적 서명은 아님. 기존 26개 등급에 합산하지 않음.",
    })
    result = Collection(collected_at=now, facts={
        "report_evidence_requested": True, "report_evidence_tenant_ids": [export.tenant_id],
    })
    for dataset in export.datasets:
        result.report_evidence.append(dataset.model_copy(update={"evidence_refs": [ref]}))
        if not dataset.complete:
            assert dataset.reason is not None
            result.issues.append(Issue(
                collector="report_evidence", target=dataset.code, reason=dataset.reason,
                detail="추가 보고서 증적 조회 미완료: " + dataset.source_ref, evidence_refs=[ref],
            ))
    return result


@dataclass(frozen=True)
class EvidenceMetric:
    code: str
    key: str
    label: str
    value: int | float | str | None
    unit: str
    reason: Reason | None
    limitation: str
    evidence_refs: list[str]


def _months(end: datetime, count: int) -> list[datetime]:
    last = (end - timedelta(microseconds=1)).astimezone(UTC)
    ordinal = last.year * 12 + last.month - 1
    return [
        datetime((ordinal - offset) // 12, (ordinal - offset) % 12 + 1, 1, tzinfo=UTC)
        for offset in range(count - 1, -1, -1)
    ]


def supplemental_metrics(data: Collection, criteria: dict) -> list[EvidenceMetric]:
    definitions = criteria.get("report_items", {})
    options = criteria.get("report_options", {})
    if definitions and (
        type(options.get("history_months")) is not int or not 1 <= options["history_months"] <= 12
        or options.get("inactivity_days") != 90
        or type(options.get("audit_required_months")) is not int or options["audit_required_months"] <= 0
    ):
        raise ValueError("추가 보고서 기준에는 1~12개월 이력·90일 사용·양수 감사 보존 개월 기준이 필요합니다.")
    by_code = {dataset.code: dataset for dataset in data.report_evidence}
    if len(by_code) != len(data.report_evidence):
        raise ValueError("추가 보고서 증적 코드가 중복되었습니다.")
    results: list[EvidenceMetric] = []
    for code, config in definitions.items():
        dataset = by_code.get(code)
        automatic = code in ("DP-SY-35", "DS-SY-36", "OE-SY-37", "DP-SY-38")
        ready = bool(dataset and dataset.complete and dataset.population_complete)
        base_reason: Reason = dataset.reason if dataset and dataset.reason else "not_found"
        limitation = (
            dataset.scope + ". 원천: " + dataset.source_ref + ". " + config["limit"]
            if dataset else config["limit"] + ". 해당 추가 증적 미수집."
        )
        refs = dataset.evidence_refs if dataset else []
        if automatic:
            collector = "agent365_registry" if code == "DP-SY-38" else "copilot_inventory"
            failures = [item for item in data.issues if item.collector == collector]
            base_reason = failures[0].reason if failures else "not_found"
            ready = (
                data.facts.get("agent365_registry_complete") is True
                if code == "DP-SY-38" else data.facts.get("copilot_inventory_complete") is True
            )
            limitation = config["limit"]
            refs = sorted({
                ref for item in (data.agent365_packages if code == "DP-SY-38" else data.copilot_agents)
                for ref in item.evidence_refs
            } | {ref for item in failures for ref in item.evidence_refs})

        def add(
            key: str, value: int | float | str | None, unit: str = "count", *,
            unavailable_reason: Reason | None = None,
            context: tuple[str, str, bool, Reason, str, list[str]] = (
                code, config["title"], ready, base_reason, limitation, refs,
            ),
        ) -> None:
            code, title, ready, base_reason, limitation, refs = context
            results.append(EvidenceMetric(
                code, key, title, value if ready else None, unit,
                None if ready and value is not None else unavailable_reason or base_reason, limitation, refs,
            ))

        def ratio(key: str, values: list[bool | None]) -> None:
            add(key, sum(value is True for value in values) / len(values)
                if values and all(value is not None for value in values) else None, "ratio")

        add("report." + code + ".present", 1 if ready else None)
        if automatic:
            values: list[bool | None]
            if code == "DP-SY-35":
                values = [agent.last_published_at is not None for agent in data.copilot_agents]
            elif code == "DS-SY-36":
                accepted = options.get("authenticated_modes", [])
                known = set(accepted) | {"None"}
                values = [
                    agent.authentication in accepted if agent.authentication in known else None
                    for agent in data.copilot_agents
                ]
            elif code == "OE-SY-37":
                values = [agent.owner_present for agent in data.copilot_agents]
            else:
                values = [] if any(package.request_type not in (
                    None, "publish", "activate", "access", "update",
                ) for package in data.agent365_packages) else [
                    package.request_status == "approved" if package.request_status in (
                        "pending", "approved", "rejected",
                    ) else None for package in data.agent365_packages if package.request_type == "publish"
                ]
            ratio(config["metric"], values)
            add(config["metric"] + ".total", len(values) if values else None)
            add(config["metric"] + ".count", sum(value is True for value in values)
                if values and all(value is not None for value in values) else None)
            continue
        if dataset is None or not ready:
            add(config["metric"], None, config.get("unit", "ratio"))
            continue
        if isinstance(dataset, CreationEvidence):
            ratio("approval.match", [
                None if record.approval_found is None else bool(
                    record.approval_found and record.approved_at is not None
                    and record.approved_at <= record.created_at
                )
                for record in dataset.records
            ])
            add("creation.total", len(dataset.records) if dataset.records else None)
            known = all(record.approval_found is not None for record in dataset.records)
            approved = sum(
                record.approval_found is True and record.approved_at is not None
                and record.approved_at <= record.created_at for record in dataset.records
            )
            add("creation.approved", approved if dataset.records and known else None)
            add("creation.unmatched", len(dataset.records) - approved if dataset.records and known else None)
            months = options.get("history_months")
            if type(months) is int and 1 <= months <= 12 and dataset.period_end and dataset.period_start:
                bins = _months(dataset.period_end, months)
                if dataset.period_start <= bins[0] and dataset.records and known:
                    add("creation.history", ",".join(value.strftime("%Y%m") for value in bins), "series")
                    for start in bins:
                        selected = [record for record in dataset.records if (
                            record.created_at.astimezone(UTC).year, record.created_at.astimezone(UTC).month
                        ) == (start.year, start.month)]
                        count = sum(
                            record.approval_found is True and record.approved_at is not None
                            and record.approved_at <= record.created_at for record in selected
                        )
                        add("creation.month." + start.strftime("%Y%m") + ".total", len(selected))
                        add("creation.month." + start.strftime("%Y%m") + ".approved", count)
        elif isinstance(dataset, RegistryEvidence):
            observed = set(dataset.observed_subjects)
            registered = {record.subject: record for record in dataset.records}
            add("registry.observed", len(observed) if observed else None)
            add("registry.registered", len(observed & registered.keys()) if observed else None)
            add("registry.missing", len(observed - registered.keys()) if observed else None)
            add("registry.match", len(observed & registered.keys()) / len(observed) if observed else None, "ratio")
            rows = [registered[key] for key in observed if key in registered]
            add("registry.metadata_missing", sum(
                record.owner_present is False or record.deployment_scope_present is False for record in rows
            ) if rows and all(
                record.owner_present is not None and record.deployment_scope_present is not None for record in rows
            ) else None)
        elif isinstance(dataset, PredeploymentEvidence):
            values = [
                None if record.evaluation_found is None else bool(
                    record.evaluation_found and record.evaluation_version == record.version
                    and record.evaluation_completed_at is not None
                    and record.evaluation_completed_at < record.deployed_at
                    and record.evaluation_status in ("completed", "succeeded")
                ) for record in dataset.records
            ]
            ratio("evaluation.predeploy", values)
            known = bool(values) and all(value is not None for value in values)
            add("evaluation.deployed", len(values) if values else None)
            matched = sum(value is True for value in values)
            add("evaluation.evaluated", matched if known else None)
            add("evaluation.missing", len(values) - matched if known else None)
        elif isinstance(dataset, BooleanControlEvidence):
            key = "identity.conditional_access" if code == "OE-SY-30" else "identity.departed"
            ratio(key, [record.value for record in dataset.records])
            add(key + ".count", sum(record.value is True for record in dataset.records)
                if dataset.records and all(record.value is not None for record in dataset.records) else None)
        elif isinstance(dataset, AuditRetentionEvidence):
            durations = {"ThreeMonths": 3, "SixMonths": 6, "NineMonths": 9, "TwelveMonths": 12, "TenYears": 120}
            values = [durations[record.retention_duration] if record.retention_duration is not None else None
                      for record in dataset.records]
            add("audit.retention", min(value for value in values if value is not None)
                if values and all(value is not None for value in values) else None, "months")
            required = options.get("audit_required_months")
            add("audit.required", required if type(required) is int and required > 0 else None, "months")
        elif isinstance(dataset, UsageEvidence):
            days = options.get("inactivity_days")
            end = dataset.period_end
            values: list[bool | None] = []
            buckets: list[str | None] = []
            if days != 90:
                raise ValueError("calls_90d 원천은 90일 기준에서만 사용할 수 있습니다.")
            if end is not None:
                cutoff = end - timedelta(days=days)
                for record in dataset.records:
                    coverage = record.coverage_start <= max(record.created_at, cutoff) and record.coverage_end >= end
                    if not coverage or record.calls_90d is None:
                        values.append(None)
                        buckets.append(None)
                        continue
                    inactive = record.created_at <= cutoff and record.calls_90d == 0
                    values.append(inactive)
                    buckets.append(
                        "inactive90" if inactive else "active30" if record.calls_30d is not None and record.calls_30d > 0
                        else "active31_90" if record.calls_30d == 0 and record.calls_90d > 0 else None
                    )
            ratio("usage.inactive90", values)
            for bucket in ("active30", "active31_90", "inactive90"):
                add("usage." + bucket + ".count", buckets.count(bucket)
                    if buckets and all(value is not None for value in buckets) else None)
            add("usage.total", len(values) if values and all(value is not None for value in values) else None)
        elif isinstance(dataset, ExposureEvidence):
            high = [record for record in dataset.records if record.severity == "high"]
            known = bool(dataset.records) and all(record.severity is not None for record in dataset.records)
            status_known = known and all(record.remediation is not None for record in high)
            add("security.exposure.total", len(high) if known else None)
            add("security.exposure.open", sum(record.remediation == "open" for record in high) if status_known else None)
            add("security.exposure.remediated", sum(record.remediation == "remediated" for record in high) if status_known else None)
            add("security.exposure", sum(record.remediation == "remediated" for record in high) / len(high)
                if high and status_known else None, "ratio")
            for category in ("national_id", "personal", "legal", "financial", "other"):
                rows = [record for record in high if record.category == category]
                add("security.exposure." + category + ".total", len(rows) if known else None)
                add("security.exposure." + category + ".open",
                    sum(record.remediation == "open" for record in rows) if status_known else None)
        elif isinstance(dataset, CostHistoryEvidence):
            currencies = {record.currency for record in dataset.records}
            if len(currencies) != 1:
                add("cost.history", None, "series", unavailable_reason="feature_unavailable")
                continue
            currency = next(iter(currencies))
            months = options.get("history_months")
            if type(months) is not int or not 1 <= months <= 12 or not dataset.period_end or not dataset.period_start:
                add("cost.history", None, "series")
                continue
            bins = _months(dataset.period_end, months)
            if dataset.period_start > bins[0]:
                add("cost.history", None, "series")
                continue
            add("cost.history", ",".join(value.strftime("%Y%m") for value in bins), "series")
            add("cost.currency", currency, "currency")
            grouped = defaultdict(list)
            for record in dataset.records:
                grouped[record.occurred_at.astimezone(UTC).strftime("%Y%m")].append(record)
            for start in bins:
                month = start.strftime("%Y%m")
                rows = grouped[month]
                add("cost.month." + month + ".total", sum(record.amount for record in rows) if rows else None, currency)
                add("cost.month." + month + ".attributed", sum(
                    record.attributed_amount for record in rows if record.attributed_amount is not None
                )
                    if rows and all(record.attributed_amount is not None for record in rows) else None, currency)
    return results
