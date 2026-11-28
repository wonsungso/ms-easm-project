"""Presentation values and their collection limits computed from a collection."""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from easm_agent.agent365_grading import REGISTRY_PROFILES
from easm_agent.azure import redact
from easm_agent.models import Collection, Finding, Reason
from easm_agent.proposals import azure_agents
from easm_agent.report_evidence import supplemental_metrics


def coverage_label(condition: object) -> str | None:
    if not isinstance(condition, dict) or not condition:
        return None
    operators = {"eq": "=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    if condition.keys() - operators.keys():
        return None
    if any(type(value) not in (int, float) or not 0 <= value <= 1 for value in condition.values()):
        return None
    lower = next((key for key in ("gt", "gte") if key in condition), None)
    upper = next((key for key in ("lt", "lte") if key in condition), None)
    if lower and upper and len(condition) == 2:
        sign = "<" if lower == "gt" else "<="
        return f"{condition[lower] * 100:g}%{sign}p{operators[upper]}{condition[upper] * 100:g}%"
    return "·".join(
        f"p{symbol}{condition[operator] * 100:g}%"
        for operator, symbol in operators.items() if operator in condition
    )


class ReportMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    value: StrictInt | StrictFloat | StrictStr | None = None
    unit: str = ""
    status: Literal["observed", "unavailable"] = "unavailable"
    reason: Reason | None = "not_found"
    limitation: str
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_status(self) -> ReportMetric:
        if self.status == "observed" and (self.value is None or self.reason is not None):
            raise ValueError("확인된 보고서 값에는 값과 오류 없음이 필요합니다.")
        if self.status == "unavailable" and (self.value is not None or self.reason is None):
            raise ValueError("판정 보류 보고서 값은 null과 사유를 유지해야 합니다.")
        if self.status == "observed" and self.unit == "ratio" and not (
            isinstance(self.value, (int, float)) and 0 <= self.value <= 1
        ):
            raise ValueError("보고서 충족률은 0~1 사이 숫자여야 합니다.")
        if self.key == "run.mode" and self.status == "observed" and self.value not in ("live", "fixture"):
            raise ValueError("보고서 데이터 구분이 올바르지 않습니다.")
        return self

def report_metrics(data: Collection, findings: list[Finding], mode: str) -> list[ReportMetric]:
    records: list[ReportMetric] = []

    def add(
        key: str, label: str, value: int | float | str | None, unit: str, limitation: str,
        *, reason: Reason = "not_found", refs: list[str] | None = None,
    ) -> None:
        records.append(ReportMetric(
            key=key, label=label, value=value, unit=unit,
            status="observed" if value is not None else "unavailable",
            reason=None if value is not None else reason,
            limitation=limitation, evidence_refs=sorted(set(refs or [])),
        ))

    def failure(collector: str) -> tuple[Reason, list[str]]:
        issues = [issue for issue in data.issues if issue.collector == collector]
        order = ["permission_denied", "error", "license_missing", "feature_unavailable", "not_found"]
        reason = min((issue.reason for issue in issues), key=order.index) if issues else "not_found"
        return reason, [ref for issue in issues for ref in issue.evidence_refs]

    add("run.mode", "데이터 구분", mode, "", "fixture는 실제 진단 결과가 아닙니다.")
    add("run.collected_at", "원본 수집 시각", data.collected_at.isoformat(), "", "재패키징 시각이 아닙니다.")
    add("scope.subscriptions", "수집 구독", len(data.subscriptions), "개", "승인된 Azure 범위입니다.")
    source_refs = sorted({ref for source in data.evidence_sources for ref in source.evidence_refs})
    add(
        "run.evidence_sources", "수집 원천 증적 참조", len(source_refs) if source_refs else None, "개",
        "수집기에 기록된 참조 목록이며 조회 성공이나 수집 범위의 완전성을 의미하지 않습니다. "
        "첨부 상태와 원문은 결과 JSON에서 확인하세요.",
        refs=source_refs,
    )
    add(
        "inventory.azure", "Foundry Agent", len(azure_agents(data))
        if data.facts.get("agent_inventory_complete") else None, "개",
        "Foundry API로 확인한 Agent 레코드이며 Microsoft 365 전체 고유 Agent 수가 아닙니다.",
        refs=[ref for agent in azure_agents(data) for ref in agent.evidence_refs],
    )
    copilot_complete = data.facts.get("copilot_inventory_complete") is True
    copilot_reason, copilot_refs = failure("copilot_inventory")
    copilot_refs.extend(ref for agent in data.copilot_agents for ref in agent.evidence_refs)
    unclassified = any(agent.platform == "unclassified_copilot" for agent in data.copilot_agents)
    for platform, label in (
        ("agent_builder", "Copilot Agent Builder"),
        ("copilot_studio", "Copilot Studio"),
        ("unclassified_copilot", "작성 도구 미확인 Copilot Agent"),
    ):
        add(
            "inventory." + platform, label,
            sum(agent.platform == platform for agent in data.copilot_agents)
            if copilot_complete and (platform == "unclassified_copilot" or not unclassified) else None,
            "개", "Power Platform 인벤토리 반환 범위. 반영 지연이 있을 수 있으며 V1 봇은 제외. "
            "0건은 테넌트 전체 Agent 부재 판정이 아닙니다. 별도 Dataverse 초안·미게시 조회와 범위가 다를 수 있습니다.",
            reason=copilot_reason, refs=copilot_refs,
        )
    ownership_known = copilot_complete and bool(data.copilot_agents) and all(
        agent.owner_present is not None for agent in data.copilot_agents
    )
    add(
        "copilot.owner_missing", "소유자 미지정 Copilot Agent",
        sum(agent.owner_present is False for agent in data.copilot_agents) if ownership_known else None,
        "개", "명시적 ownerId 부재만 집계. 소유자 재직 여부·스폰서 부재·Azure 고아 Agent는 판정하지 않습니다.",
        reason=copilot_reason, refs=copilot_refs,
    )
    catalog_reason, catalog_refs = failure("agent365_registry")
    catalog_refs.extend(ref for package in data.agent365_packages for ref in package.evidence_refs)
    add(
        "inventory.catalog_packages", "Agent 365 카탈로그 패키지",
        len(data.agent365_packages) if data.facts.get("agent365_registry_complete") else None,
        "개", "선택한 카탈로그 범위의 패키지 수이며 고유 Agent 수·공식 등록부 대사율이 아닙니다.",
        reason=catalog_reason, refs=catalog_refs,
    )
    usage_fields = (
        ("active_users_30d", "30일 활성 사용자", "명"),
        ("total_sessions_30d", "30일 세션", "건"),
        ("total_run_time_hours_30d", "30일 실행 시간", "시간"),
        ("exception_count_30d", "30일 예외 건수", "건"),
        ("last_used_at", "마지막 사용 시각", ""),
    )
    usage_limit = (
        "선택한 카탈로그의 패키지별 상세 API 값입니다. 동일 Agent·사용자의 패키지 간 중복과 "
        "테넌트 전체 관측 범위를 확인하지 않아 합산하지 않습니다. "
        "30일 지표·마지막 사용 시각은 90일 전체 관측·미사용 판정·ROI의 근거가 아닙니다. "
        "미조회 패키지·필드는 null과 사유를 유지하며 원천 기간 경계를 수집 시각으로 복원하지 않습니다. "
        "exceptionRate는 문서상 30일 예외 건수이며 예외율로 해석하지 않습니다."
    )
    metadata_fields = (
        ("package_type", "패키지 유형", ""),
        ("manifest_version", "매니페스트 버전", ""),
        ("app_id", "앱 ID", ""),
        ("supported_hosts", "지원 호스트", ""),
        ("element_types", "요소 유형", ""),
        ("categories", "분류", ""),
        ("category_count", "분류 항목 수", "개"),
        ("sensitivity", "민감도 문자열", ""),
        ("sensitivity_present", "민감도 문자열 존재", ""),
    )
    metadata_limit = (
        "선택한 카탈로그의 패키지 레코드별 관측이며 고유 Agent 수·테넌트 전체 분포가 아닙니다. "
        "원천과 필드별 증적이 확인된 값만 표시합니다. 분류 항목 수는 유효 배열 항목 수입니다. "
        "민감도 문자열 존재는 민감도 레이블 적용·정책 실효성을 증명하지 않습니다."
    )
    package_counts = Counter(package.package_id for package in data.agent365_packages)
    any_usage = False
    usage_refs: list[str] = []
    for index, package in enumerate(data.agent365_packages, 1):
        duplicated = package_counts[package.package_id] > 1
        usage_refs.extend(package.detail_evidence_refs)
        for field, label, unit in usage_fields:
            status = package.field_status.get(field)
            value = None if duplicated or status else getattr(package, field)
            any_usage |= value is not None
            add(
                f"catalog.package.{index}.{field}", f"패키지 {package.package_id} - {label}",
                value.isoformat() if isinstance(value, datetime) else value, unit,
                usage_limit + (" 동일 package_id 중복 레코드의 값을 보류합니다." if duplicated else "")
                + (f" 필드 사유: {status.detail}" if status else ""),
                reason="error" if duplicated else status.reason if status else "not_found",
                refs=package.detail_evidence_refs,
            )
        for field, label, unit in metadata_fields:
            status = package.field_status.get(field)
            source = package.metadata_field_sources.get(field)
            refs = package.metadata_evidence_refs.get(field, [])
            value = (
                getattr(package, field)
                if not duplicated and status is None and source in ("catalog", "detail") and refs
                else None
            )
            limitation = metadata_limit + f" metadata_field_sources.{field}={source or '미기록'}."
            if duplicated:
                limitation += " 동일 package_id 중복 레코드의 값을 보류합니다."
            if status:
                limitation += " 필드 사유: " + status.detail
            if isinstance(value, (list, bool)):
                value = json.dumps(value, ensure_ascii=False)
            key = f"catalog.package.{index}.metadata.{field}"
            add(
                key, f"패키지 {package.package_id} - {label}", value, unit, limitation,
                reason="error" if duplicated else status.reason if status else "not_found",
                refs=refs,
            )
            if source is not None:
                add(
                    key + ".source", f"패키지 {package.package_id} - {label} 원천", source, "",
                    "수집 원천 표시는 값의 확인·정책 적용을 증명하지 않습니다. " + metadata_limit,
                    refs=refs,
                )
    add(
        "catalog.usage.scope", "Agent 365 사용 지표 범위", "패키지별 확인" if any_usage else None, "",
        usage_limit, reason=failure("agent365_package_details")[0], refs=usage_refs,
    )
    for field, label, unit in usage_fields:
        add(
            "catalog.usage." + field, "테넌트 전체 " + label, None, unit, usage_limit,
            reason="feature_unavailable", refs=usage_refs,
        )
    snapshot = data.assessment_provenance.criteria_snapshot if data.assessment_provenance else {}
    add("criteria.profile", "평가 프로필", snapshot.get("grading_profile"), "",
        "서로 다른 평가 프로필의 등급·충족률은 직접 비교하지 않습니다.")
    configs = list(snapshot.get("items", {}).values())
    for level in ("L1", "L2", "L3", "L4", "L5"):
        conditions = [
            next((rule.get("when", {}) for rule in config.get("rules", []) if rule.get("level") == level), {})
            for config in configs
        ]
        condition = conditions[0] if conditions and all(item == conditions[0] for item in conditions) else {}
        label = coverage_label(condition.get("coverage")) if condition.keys() == {"coverage"} else None
        add(
            f"criteria.{level}.text", level + " 공통 충족률 조건", label, "",
            "수집 당시 모든 항목에 공통인 규칙만 표시. 항목별 기준이 다르면 공통 척도 보류.",
        )
    for group, config in snapshot.get("report_groups", {}).items():
        add(
            f"group.{group}.codes", config["label"], ",".join(config["codes"]), "",
            "보고서 표시용 분류이며 API 등급을 변경하지 않습니다.",
        )
    for finding in findings:
        config = snapshot.get("items", {}).get(finding.se_code, {})
        if config.get("registry_check"):
            add(f"se.{finding.se_code}.title", finding.se_code + " 항목", config.get("short_title", config["title"]), "",
                "저장된 평가 기준의 보고서용 짧은 항목명.")
        measurement = finding.measurement
        current_ratio = (
            snapshot.get("grading_profile") in ("api_configuration_v1", *REGISTRY_PROFILES)
            and finding.level != "N/A" and finding.reason is None
            and finding.metric_value is not None
            and measurement is not None and measurement.complete and measurement.reason is None
            and measurement.numerator is not None and measurement.denominator is not None
            and measurement.denominator > 0
            and 0 <= measurement.numerator <= measurement.denominator
            and math.isclose(finding.metric_value, measurement.numerator / measurement.denominator)
        )
        add(
            "se." + finding.se_code, finding.se_code,
            finding.metric_value if current_ratio else None, "ratio",
            finding.rationale + (
                "" if current_ratio else " 현재 API 충족률로 표시할 완전한 측정·기준 증적 없음."
            ),
            reason=finding.reason or "not_found", refs=finding.evidence_refs,
        )
        amount_unit = (
            measurement.currency if measurement is not None and measurement.unit == "amount"
            and measurement.currency else "건"
        )
        for field in ("numerator", "denominator"):
            add(
                f"se.{finding.se_code}.{field}", finding.se_code + " " + field,
                getattr(measurement, field) if current_ratio else None, amount_unit,
                "해당 항목의 API 구성·기록 측정 분자·분모입니다. 고유 Agent 수나 업무 영향이 아닙니다. "
                + finding.rationale,
                reason=finding.reason or "not_found", refs=finding.evidence_refs,
            )
        item_config = snapshot.get("items", {}).get(finding.se_code, {})
        minimum = next((
            rule.get("when", {}).get("coverage", {}).get("gte")
            for rule in item_config.get("rules", []) if rule.get("level") == "L3"
        ), None)
        add(
            "se." + finding.se_code + ".l3_min", finding.se_code + " L3 하한",
            minimum if type(minimum) in (int, float) and 0 <= minimum <= 1 else None,
            "ratio", "수집 당시 평가 기준의 L3 충족률 하한입니다.",
        )
    supplemental = supplemental_metrics(data, snapshot)
    supplemental_keys = {metric.key for metric in supplemental}
    for metric in supplemental:
        add(
            metric.key, metric.code + " " + metric.label, metric.value, metric.unit,
            metric.limitation, reason=metric.reason or "not_found", refs=metric.evidence_refs,
        )
    for key, value in snapshot.get("report_options", {}).get("targets", {}).items():
        add("report.target." + key, "보고서 검토 목표", value, "ratio", "보고서용 검토 목표이며 기존 26개 등급에 합산하지 않음")
    for key, label, limitation in (
        ("approval.match", "생성-승인 요청 매칭", "승인 요청과 생성 레코드를 연결한 증적 미수집"),
        ("registry.match", "공식 등록부 대사", "독립된 공식 등록부와 인벤토리를 대사한 증적 미수집"),
        ("identity.departed", "퇴사자 소유 Agent", "인사·사용자 재직 상태 증적 미수집"),
        ("security.exposure", "고위험 민감 데이터 노출", "Purview 노출·조치 결과 미수집. Defender 플랜 구성과 다름"),
        ("audit.retention", "Microsoft 365 감사 보존기간", "Purview 감사 보관 정책 미수집. Azure 실행 로그와 다름"),
        ("usage.inactive90", "90일 미사용 Agent", "Agent별 90일 전체 관측 이력 미수집"),
        ("cost.history", "6개월 월별 Agent 비용", "현재 수집은 최근 비용 창이며 과거 6개월 청구 이력이 아님"),
        ("creation.history", "6개월 월별 신규 Agent 생성", "현재 생존 인벤토리로 삭제된 Agent를 포함한 과거 생성 이력을 복원하지 않음"),
        ("security.shadow", "조직 전체 Shadow AI", "전체 조직의 독립 탐지 결과·탐지 범위 미수집"),
        ("business.loss_amount", "금전 손실", "실제 사고·업무 중단·손실 금액 증적 미수집. 구성 미충족으로 손실을 추정하지 않음"),
        ("business.roi", "투자 수익률", "업무 성과·투자비·절감 실현 증적 미수집. 구성 점수로 ROI를 추정하지 않음"),
    ):
        if key not in supplemental_keys:
            add(key, label, None, "", limitation, reason="feature_unavailable")
    return records


def with_evidence_only_findings(
    data: Collection, findings: list[Finding],
) -> tuple[Collection, list[Finding]]:
    """Add pending findings for evidence-only proposals that have no original grade."""
    proposals = {proposal.code: proposal for proposal in data.proposals}
    data = data.model_copy(update={"proposals": list(proposals.values())})
    original_codes = {finding.se_code for finding in findings}
    return data, [*findings, *[
        Finding(
            se_code=code, scope="partial", level="N/A", reason=proposal.reason or "not_found",
            rationale=proposal.limit, evidence_refs=proposal.evidence_refs,
            next_step="원래 평가 기준을 충족할 증거가 부족해 점수 보류",
        )
        for code, proposal in proposals.items()
        if proposal.evidence_only and code not in original_codes
    ]]


def metrics_by_key(data: Collection, findings: list[Finding], mode: str) -> dict[str, ReportMetric]:
    """Compute presentation metrics in memory, keyed by metric key."""
    data, findings = with_evidence_only_findings(data, findings)
    return {
        metric.key: metric.model_copy(update={
            "label": redact(metric.label), "value": redact(metric.value),
            "limitation": redact(metric.limitation), "evidence_refs": redact(metric.evidence_refs),
        })
        for metric in report_metrics(data, findings, mode)
    }
