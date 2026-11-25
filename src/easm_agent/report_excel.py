from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from copy import copy, deepcopy
from pathlib import Path
from typing import Any, TypedDict

from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import BaseModel

from easm_agent.azure import redact
from easm_agent.collect_agent365 import STATUS_LABELS
from easm_agent.deck_model import _score
from easm_agent.models import (
    AdminReadResult,
    Agent365Crosscheck,
    Agent365Package,
    AgentEvidence,
    Budget,
    Collection,
    CopilotAgentEvidence,
    CostRecord,
    DefenderPlan,
    EntraAgentIdentity,
    EntraBlueprint,
    EvaluationRun,
    Finding,
    Issue,
    LogSetting,
    ModelDeployment,
    PolicyAssignment,
    ProposalObservation,
    ReportEvidenceRawRecord,
    SecureScore,
    SecurityRecommendation,
)
from easm_agent.proposals import DOMAINS, TITLES, azure_agents
from easm_agent.report_backdata import with_evidence_only_findings
from easm_agent.report_evidence import supplemental_metrics
from easm_agent.report_interviews import result_cell_updates
from easm_agent.report_resources import ResourceName, resource_names, resource_summary
from easm_agent.report_template import (
    COLLECTION_METHODS,
    CRITERIA_SHEET,
    RESULT_ROW_HEIGHT,
    RESULT_SHEET,
    format_assessment_workbook,
    load_report_template,
    preserve_template_parts,
)

LABELS = {
    "permission_denied": "조회 권한 부족",
    "feature_unavailable": "현재 환경에서 조회 기능 제공 안 됨",
    "license_missing": "필요 라이선스 확인 또는 추가 필요",
    "not_found": "확인 자료 없음",
    "error": "조회 중 오류 발생",
    "in_scope": "진단 범위에 포함",
    "partial": "진단 범위 일부 - 조직 전체 판정 아님",
    "out_of_scope": "진단 범위 밖",
    "N/A": "판정 보류",
    "null": "확인 자료 없음",
    "foundry": "Microsoft Foundry",
    "langchain": "LangChain 탐지 후보",
    "custom": "자체 Agent 탐지 후보",
    "manual": "수동 등록",
    "other": "기타 플랫폼",
    "tag": "태그를 근거로 탐지",
    "name_heuristic": "이름을 근거로 추정 - Agent 여부 추가 확인 필요",
}
SE_AREAS = {
    "DM": "1. Demand", "DS": "2. Design", "BI": "3. Build",
    "DP": "4. Deploy", "OE": "5. Operate", "OT": "6. Optimize",
}
SE_NAMES = {
    "DS-SY-04": "모델 배포 버전·업데이트 구성",
    "BI-SY-09": "Foundry 프로젝트 평가 실행 이력",
    "BI-SY-10": "AI 리소스 보안 권고 상태",
    "OE-SY-18": "Agent 리소스 실행 로그 연결",
    "OT-SY-23": "AI 리소스 사용량 관측 범위",
    "OT-SY-24": "AI 비용의 단일 Agent 귀속",
    "DS-SY-03": "Agent ID의 Blueprint 연결",
    "DP-SY-15": "Agent ID 부여율(Azure Agent 기준)",
    "OE-SY-16": "소유자·스폰서 미지정 Agent",
    "OE-SY-17": "Agent 부여 권한·과다 권한",
    **TITLES,
}
FIELD_NAMES = {
    "tenant_id": "테넌트", "subscription_id": "구독", "resource_group": "리소스 그룹",
    "agent_version": "Agent 버전", "resource_id": "리소스",
    "hosting_type": "호스팅 유형", "owner": "담당자", "sponsor": "업무 책임자",
    "model": "사용 모델", "model_version": "모델 버전", "model_resource_id": "모델 리소스",
    "tools": "연결 도구", "created_at": "생성 시각", "deployed_at": "배포 시각",
    "last_used_at": "마지막 사용 시각", "cost_30d": "최근 30일 비용", "currency": "통화",
    "usage_30d": "최근 30일 사용량", "usage_30d.calls": "최근 30일 호출 수",
    "usage_30d.tokens": "최근 30일 토큰 수", "calls_90d": "최근 90일 호출 수",
    "usage_coverage_start": "사용 관측 시작 시각",
    "evaluated_before_deploy": "배포 전 평가 여부", "guardrail_applied": "안전장치 적용 여부",
}
RATIOS = set(SE_NAMES)
EMPTY = "수집된 데이터 없음 - 미수행 또는 0건으로 확정하지 않음"
ORIGINAL = "원본 JSON"
FONT_SIZE = 10
HEADER_FILL = "D9D9D9"
_SIDE = Side(style="thin", color="000000")
_OUTER = Side(style="medium", color="000000")
BORDER = Border(left=_SIDE, right=_SIDE, top=_SIDE, bottom=_SIDE)
COLUMN_WIDTHS = {
    "SY코드": 10, "코드": 10, "진단 영역": 9, "항목": 19, "제안": 19,
    "확인상태": 10, "수집 상태": 10, "지표": 12, "판정": 7, "원인": 11,
    "근거": 27, "다음조치": 19, "수동검토상태": 10, "검토메모": 15,
    "수집 요약": 42, "한계": 38, "설명": 60, "detail": 40,
    "evidence_refs": 32, ORIGINAL: 48,
    "리소스 유형": 22, "리소스 이름": 42, "구독 ID": 40, "리소스 그룹": 34, "식별자": 75,
}
CENTERED = {"SY코드", "코드", "진단 영역", "확인상태", "수집 상태", "지표", "판정", "수동검토상태"}
DETAILS_TITLE = "수집결과 근거"
RAW_TITLE = "수집 Raw 데이터"
# Integrated-template appendix sheets keep the "8, 8a, 8b, 8c" family numbering used by
# sibling sheets (e.g. "2, 2a, 2b, 2c") instead of a sequential "15./16./17./18." position count.
FIXED_SHEET_NAMES = {
    DETAILS_TITLE: "8_수집결과 근거",
    RAW_TITLE: "8a_수집 Raw 데이터",
    "수집이슈 Raw 데이터": "8b_수집이슈 Raw 데이터",
    "필드누락사유": "8c_필드누락사유",
}


class ReviewLayout(TypedDict):
    widths: tuple[float, ...]
    height: float
    default_height: float
    default_width: float


REVIEW_LAYOUTS: dict[str, ReviewLayout] = {
    DETAILS_TITLE: {
        "widths": (10.625, 14.875, 25.5, 14.875, 10.625, 90.375, 53.125, 90.375, 65.125, 18, 90, 65),
        "height": 60, "default_height": 60, "default_width": 109.625,
    },
}

PRESENTATION_EVIDENCE = (
    ("DM-SY-01", "제작 허용 범위", "DM-SY-01", False, "환경 역할 할당은 제작 허용 대상과 다릅니다."),
    ("DM-SY-02", "제작 권한자 수", "DM-SY-01", False, "환경 역할 할당 건수는 고유 사용자 수가 아닙니다."),
    ("DM-SY-03", "생성-요청 매칭", "", False, "승인 요청과 생성 이력을 연결하는 증적이 없습니다."),
    ("DS-SY-04", "데이터 정책 적용 환경", "DS-SY-02", True, "관리자에게 보이는 환경의 정책 적용 범위입니다."),
    ("DS-SY-05", "ID 템플릿 정의", "DS-SY-03", False, "Blueprint 연결은 조직 표준 템플릿 정의가 아닙니다."),
    ("DS-SY-06", "허용 모델 일치", "DS-SY-04", False, "모델 배포 구성은 승인된 모델 목록과의 대조가 아닙니다."),
    ("BI-SY-07", "관리형 환경", "BI-SY-08", True, "관리자에게 보이는 환경의 보호 수준 구성입니다."),
    ("BI-SY-08", "배포 전 평가", "BI-SY-09", False, "프로젝트 평가 이력은 Agent별 배포 전 평가가 아닙니다."),
    ("BI-SY-09", "고위험 보안 권고 조치", "BI-SY-10", False, "AI 리소스 판정과 고위험 권고 건수는 다릅니다."),
    ("DP-SY-10", "공식 등록부 대사", "", False, "공식 등록부와 Agent 인벤토리의 대사 증적이 없습니다."),
    ("DP-SY-11", "공유·설치 통제", "", False, "공유·설치 승인 설정을 확인하는 증적이 없습니다."),
    ("DP-SY-12", "Agent ID 부여", "DP-SY-15", False, "현재 지표는 Azure Agent 범위이며 원본의 전체 Agent 범위와 다릅니다."),
    ("OE-SY-13", "고아 Agent", "OE-SY-16", False, "Agent ID 소유자·스폰서 연결은 전체 Agent의 고아 여부가 아닙니다."),
    ("OE-SY-14", "과다 권한 Agent", "OE-SY-17", False, "권한 이름 패턴 확인은 업무별 권한 적정성 판정이 아닙니다."),
    ("OE-SY-15", "조건부 접근", "", False, "조건부 접근 적용 여부를 확인하는 증적이 없습니다."),
    ("OE-SY-16", "감사 로그 보관", "OE-SY-18", False, "Agent 실행 진단 로그 연결은 감사 로그 보관기간이 아닙니다."),
    ("OT-SY-17", "Shadow AI 탐지", "", False, "전체 조직의 Shadow AI 탐지 증적이 없습니다."),
    ("OT-SY-18", "90일 미사용 Agent", "OT-SY-23", False, "최근 사용 관측 범위는 90일 미사용 비율이 아닙니다."),
    ("OT-SY-19", "Agent별 비용 식별", "OT-SY-24", False, "현재 비용 귀속은 수집 범위와 통화별 금액으로 한정됩니다."),
    ("OT-SY-20", "고위험 민감 데이터 노출 조치", "OT-SY-25", False, "Defender 플랜 구성은 민감 데이터 노출 조치 결과가 아닙니다."),
)


def readable(value: Any) -> str:
    if value is None or value == "":
        return "확인 자료 없음"
    if isinstance(value, bool):
        return "확인됨" if value else "해당하지 않음"
    text = str(redact(value)).replace("\u2014", "-").replace("\u2013", "-")
    text = text.replace("후원자", "스폰서").replace("민감도 라벨", "민감도 레이블")
    for key, label in LABELS.items():
        text = re.sub(r"(?<![\w/-])" + re.escape(key) + r"(?![\w/-])", label, text)
    return text


def metric(finding: Finding) -> str:
    if finding.assessment_basis == "configuration":
        if finding.configuration_value is None:
            raise ValueError(f"{finding.se_code}: 구성 기반 등급의 관측 건수가 없습니다.")
        return f"기본 구성 {finding.configuration_value:g}건"
    if finding.metric_value is None:
        return "확인 자료 없음" + (" - 분모 확인 안됨" if finding.se_code in RATIOS else "")
    value = finding.metric_value
    if finding.se_code in RATIOS:
        return f"{value * 100:.2f}%"
    return f"{value:g}" + ("일" if finding.se_code == "OE-SY-18" else "건")


def _value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def _emphasize_evidence(text: str) -> CellRichText:
    number = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    pattern = (
        r"^(?:수집[ \t]*결과|관련[ \t]*리소스|판정[ \t]*근거):"
        rf"|(?<![A-Za-z0-9_./:-]){number}(?:\s*/\s*{number})?%?(?![A-Za-z0-9_./:%-])"
    )
    content = CellRichText()
    position = 0
    for match in re.finditer(pattern, text, re.MULTILINE):
        prefix = text[position:match.start()]
        if prefix:
            if prefix.isspace() and content:
                previous = content[-1]
                if isinstance(previous, TextBlock):
                    previous.text += prefix
                else:
                    content[-1] = previous + prefix
            elif not prefix.isspace():
                content.append(prefix)
        leading = prefix if prefix.isspace() and not content else ""
        content.append(TextBlock(InlineFont(b=True), leading + match.group()))
        position = match.end()
    suffix = text[position:]
    if suffix:
        if suffix.isspace() and content and isinstance(content[-1], TextBlock):
            content[-1].text += suffix
        else:
            content.append(suffix)
    return content


def _wrapped_height(text: str, width: float, font_size: float) -> float:
    lines = sum(
        max(1, math.ceil(sum(
            2 if unicodedata.east_asian_width(character) in ("W", "F") else 1
            for character in line.expandtabs(4)
        ) / width))
        for line in text.splitlines()
    )
    return lines * font_size * 1.35


def _fit_audit_rows(sheet: Worksheet, first: int, last: int, columns: int) -> None:
    for row in range(first, last + 1):
        height = max(
            _wrapped_height(str(sheet.cell(row, column).value or ""),
                            sheet.column_dimensions[get_column_letter(column)].width, FONT_SIZE)
            for column in range(1, columns + 1)
        )
        sheet.row_dimensions[row].height = min(409, max(60, height + 6))


def _cell(sheet: Worksheet, row: int, column: int, value: Any) -> None:
    value = _value(value)
    if isinstance(value, str) and len(value) > 32767:
        raise ValueError(
            f"Excel 셀 길이 오류: {sheet.title}!{get_column_letter(column)}{row} "
            f"- {len(value)}자, 최대 32767자"
        )
    cell = sheet.cell(row, column, value)
    if isinstance(value, str):
        # Assigning a leading '=' normally makes openpyxl create a formula.
        cell.data_type = "s"
        cell.number_format = "@"
    cell.font = Font(name="Arial", size=FONT_SIZE, color="000000")
    cell.alignment = Alignment(vertical="center", wrap_text=True)
    cell.border = BORDER
    cell.hyperlink = None


def _table(
    book: Workbook, title: str, headers: list[str], rows: Iterable[dict[str, Any]],
    *, sheet: Worksheet | None = None, start_row: int = 1, integrated: bool = False,
) -> Worksheet:
    if sheet is None:
        name = FIXED_SHEET_NAMES[title] if integrated and title in FIXED_SHEET_NAMES else (
            f"{len(book.worksheets) + 1}. {title}"
        )
        sheet = book.create_sheet(name)
    layout = REVIEW_LAYOUTS.get(title)
    if sheet.freeze_panes is None:
        sheet.freeze_panes = f"A{start_row + 1}"
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 80
    sheet.sheet_format.defaultRowHeight = layout["default_height"] if layout else 15
    if layout:
        sheet.sheet_format.defaultColWidth = layout["default_width"]
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    for column, header in enumerate(headers, 1):
        _cell(sheet, start_row, column, header)
        cell = sheet.cell(start_row, column)
        cell.font = Font(name="Arial", size=FONT_SIZE, bold=True, color="000000")
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        width = (
            layout["widths"][column - 1] if layout else COLUMN_WIDTHS.get(header, 18)
        )
        key = get_column_letter(column)
        previous = sheet.column_dimensions[key].width if key in sheet.column_dimensions else 0
        sheet.column_dimensions[key].width = max(previous, width)
    row_number = start_row
    for row_number, row in enumerate(rows, start_row + 1):
        safe = redact(row)
        for column, header in enumerate(headers, 1):
            _cell(sheet, row_number, column, safe.get(header))
            cell = sheet.cell(row_number, column)
            cell.fill = PatternFill() if layout else PatternFill("solid", fgColor="FFFFFF")
            if layout:
                cell.alignment = Alignment(
                    horizontal="center" if column <= 2 else "left", vertical="center", wrap_text=True,
                )
            elif header in CENTERED:
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.row_dimensions[row_number].height = layout["height"] if layout else 33.75
    if row_number == start_row:
        for column in range(1, len(headers) + 1):
            _cell(sheet, start_row + 1, column, EMPTY if column == 1 else None)
        row_number = start_row + 1
        sheet.row_dimensions[row_number].height = layout["height"] if layout else 33.75
    for row in sheet.iter_rows(min_row=start_row, max_row=row_number, max_col=len(headers)):
        for cell in row:
            if title == DETAILS_TITLE and cell.row > start_row:
                cell.border = BORDER
                continue
            cell.border = Border(
                left=_OUTER if cell.column == 1 else _SIDE,
                right=_OUTER if cell.column == len(headers) and title != DETAILS_TITLE else _SIDE,
                top=_OUTER if cell.row == start_row else _SIDE,
                bottom=_OUTER if cell.row == row_number else _SIDE,
            )
    table = Table(
        displayName=f"EvidenceTable{book.worksheets.index(sheet) + 1}_{len(sheet.tables) + 1}",
        ref=f"A{start_row}:{get_column_letter(len(headers))}{row_number}",
    )
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleLight1", showRowStripes=False, showColumnStripes=False,
    )
    sheet.add_table(table)
    sheet.row_dimensions[start_row].height = 16.5 if layout else 33
    if sheet.print_title_rows is None:
        sheet.print_title_rows = f"{start_row}:{start_row}"
    sheet.print_options.horizontalCentered = True
    return sheet


def collection_summary(data: Collection, finding: Finding) -> tuple[str, str | None]:
    from easm_agent.report_integrated import criteria_for

    if data.copilot_agents and criteria_for(data)["items"].get(finding.se_code, {}).get("copilot_inventory_check"):
        return ("증적 확인" if finding.metric_value is not None else "일부 수집"), finding.rationale
    agents = azure_agents(data)
    proposal = next((item for item in data.proposals if item.code == finding.se_code), None)
    if proposal is not None:
        return proposal.status, proposal.observation
    code = finding.se_code
    summary = None
    if code == "DS-SY-04" and (data.deployments or data.facts.get("deployment_inventory_complete")):
        summary = f"모델 배포 {len(data.deployments)}개"
    elif code == "BI-SY-09" and (data.evaluations or data.facts.get("evaluation_complete_projects")):
        summary = f"평가 실행 {len(data.evaluations)}건, Azure Agent {len(agents)}개"
    elif code == "BI-SY-10" and (data.security or data.secure_scores):
        summary = f"보안 권고 {len(data.security)}건, 구독 보안 점수 {len(data.secure_scores)}건"
    elif code == "OE-SY-18" and data.logs:
        retention = [item.retention_days for item in data.logs if item.retention_days is not None]
        scope = "Agent 실행 로그" if data.facts.get("audit_log_scope") == "agent_resource_execution" else "진단 로그"
        summary = (
            f"{scope} 대상 {len(data.logs)}개, 활성 {sum(item.enabled for item in data.logs)}개"
            + (f", 확인한 최소 보존 {min(retention)}일" if retention else ", 보존기간 미확보")
        )
    elif code == "OT-SY-23" and agents:
        summary = f"Azure Agent {len(agents)}개 중 최근 사용일 확인 {sum(item.last_used_at is not None for item in agents)}개"
    elif code == "OT-SY-24" and (data.costs or data.budgets):
        summary = f"비용 행 {len(data.costs)}건, 예산 {len(data.budgets)}개"
    elif code in ("DM-SY-01", "DS-SY-02", "BI-SY-08"):
        reads = [row for row in data.admin_evidence if row.source == "powerplatform.environments" and row.completed]
        if reads:
            summary = f"Power Platform 환경 {len(reads[0].environments)}개"
    elif code == "OT-SY-25" and data.defender_plans:
        summary = (
            f"Defender 플랜 {len(data.defender_plans)}건, AI 위협 방지 Standard "
            f"{sum(row.plan == 'AI' and row.tier == 'Standard' for row in data.defender_plans)}개 구독, "
            f"민감 데이터 검색 활성 "
            f"{sum(row.plan == 'CloudPosture' and row.extensions.get('SensitiveDataDiscovery') is True for row in data.defender_plans)}개 구독"
        )
    elif code == "DS-SY-03" and data.facts.get("entra_blueprints_complete"):
        summary = f"Blueprint {len(data.entra_blueprints)}개"
    elif code == "OE-SY-17" and (
        data.entra_agent_identities or data.facts.get("entra_agents_complete")
    ):
        identities = data.entra_agent_identities
        summary = (
            f"Entra Agent ID {len(identities)}개, 수집 앱 역할 이름 {sum(len(row.app_roles) for row in identities)}건, "
            f"쓰기·전체제어 패턴 해당 {sum(len(row.overprivileged_roles) for row in identities)}건"
        )
    elif code == "OE-SY-16" and (
        data.entra_agent_identities or data.facts.get("entra_agents_complete")
    ):
        identities = data.entra_agent_identities
        summary = (
            f"Entra Agent ID {len(identities)}개, 소유자 연결 {sum(bool(row.owner_count) for row in identities)}개, "
            f"스폰서 연결 {sum(bool(row.sponsor_count) for row in identities)}개"
        )
        if any(row.owner_count is None or row.sponsor_count is None for row in identities):
            summary += (
                f" (소유자 수 미확인 {sum(row.owner_count is None for row in identities)}개, "
                f"스폰서 수 미확인 {sum(row.sponsor_count is None for row in identities)}개)"
            )
    elif code == "DP-SY-15" and (
        data.entra_agent_identities or data.facts.get("entra_agents_complete")
    ):
        summary = f"Graph Agent ID {len(data.entra_agent_identities)}개, Azure Agent {len(agents)}개"
    if finding.reason in ("permission_denied", "error", "license_missing", "feature_unavailable"):
        return ("일부 수집" if summary else "수집 불가"), summary
    return ("수집됨" if summary else "증적 확인" if finding.metric_value is not None else "자료 미확보"), summary


def presentation_evidence_rows(data: Collection, findings: list[Finding]) -> Iterable[dict[str, Any]]:
    by_code = {finding.se_code: finding for finding in findings}
    snapshot = data.assessment_provenance.criteria_snapshot if data.assessment_provenance else {}
    items = snapshot.get("items", {})
    expected_metrics = {"DS-SY-02": "data_policy_environment_ratio", "BI-SY-08": "managed_environment_ratio"}
    for source_code, name, current_code, comparable, limitation in PRESENTATION_EVIDENCE:
        finding = by_code.get(current_code)
        measurement = finding.measurement if finding else None
        metric_confirmed = (
            comparable and snapshot.get("grading_profile") == "api_configuration_v1"
            and isinstance(items, dict) and isinstance(items.get(current_code), dict)
            and items[current_code].get("metric") == expected_metrics[current_code]
        )
        measured = (
            metric_confirmed and finding is not None and finding.level != "N/A"
            and finding.metric_value is not None and finding.reason is None
            and measurement is not None and measurement.complete and measurement.reason is None
            and measurement.numerator is not None and measurement.denominator is not None
            and measurement.unit == "count"
            and measurement.denominator > 0
            and 0 <= measurement.numerator <= measurement.denominator
            and math.isclose(finding.metric_value, measurement.numerator / measurement.denominator)
        )
        reason = (
            "수집 당시 지표 기준 미확인" if comparable and not metric_confirmed
            else readable(finding.reason) if comparable and finding and finding.reason
            else "수집 결과 또는 완전한 측정값 없음" if comparable and not measured
            else limitation if not comparable else "해당 없음"
        )
        yield {
            "원본 PPT 항목": source_code,
            "요구 지표": name,
            "관련 현재 SY 코드": current_code or None,
            "지표 값": f"{finding.metric_value * 100:.2f}%" if measured and finding else None,
            "확인 상태": "수집됨" if measured else "판정 보류",
            "사유 코드": None if measured else (
                finding.reason if comparable and metric_confirmed and finding and finding.reason
                else "not_found" if comparable else "feature_unavailable"
            ),
            "보류 사유·범위 차이": reason,
            "해석 한계": limitation,
        }


def _raw_rows(models: Iterable[BaseModel]) -> Iterable[dict[str, Any]]:
    for model in models:
        row = redact(model.model_dump(mode="json"))
        yield {**row, ORIGINAL: row}


def _raw_sheet(
    book: Workbook, sections: Iterable[tuple[str, type[BaseModel], Sequence[BaseModel]]],
    *, integrated: bool = False,
) -> None:
    name = FIXED_SHEET_NAMES[RAW_TITLE] if integrated else f"{len(book.worksheets) + 1}. {RAW_TITLE}"
    sheet = book.create_sheet(name)
    sheet.freeze_panes = "A3"
    row = 1
    for title, model, records in sections:
        label = "구성 관측" if title == "제안 Raw 데이터" else title.removesuffix(" Raw 데이터")
        count = f"{len(records)}개 레코드" if records else "확보된 레코드 없음"
        _cell(sheet, row, 1, f"{label} - {count}")
        sheet.cell(row, 1).font = Font(name="Arial", size=FONT_SIZE, bold=True, color="000000")
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(model.model_fields) + 1)
        sheet.row_dimensions[row].height = 24
        _table(book, RAW_TITLE, [*model.model_fields, ORIGINAL], _raw_rows(records),
               sheet=sheet, start_row=row + 1)
        row += max(1, len(records)) + 4


def _missing_rows(data: Collection) -> Iterable[dict[str, Any]]:
    for agent in data.agents:
        fields = agent.model_dump(mode="json")
        missing = dict(agent.field_status)
        for field, value in fields.items():
            if value is None:
                missing.setdefault(field, None)
        if agent.usage_30d is not None:
            for field, value in agent.usage_30d.model_dump().items():
                if value is None:
                    missing.setdefault(f"usage_30d.{field}", None)
        for field, status in missing.items():
            yield {
                "agent_id": agent.agent_id,
                "subscription_id": agent.subscription_id,
                "필드명": FIELD_NAMES.get(field, field),
                "field": field,
                "reason": status.reason if status else "not_found",
                "설명": readable(status.detail) if status else
                "확인 자료 없음 - 원본 값이 null이며 별도 조회 상태 기록 없음",
                ORIGINAL: status.model_dump(mode="json") if status else None,
            }


def _with_collection_method(value: str | CellRichText, method: str) -> str | CellRichText:
    bullet = f"- [{method}]"
    if isinstance(value, str):
        title, separator, body = value.partition("\n")
        return title + "\n" + bullet + (separator + body if separator else "")
    result = CellRichText()
    inserted = False
    for block in value:
        text = block.text if isinstance(block, TextBlock) else block
        if not inserted and "\n" in text:
            title, _, body = text.partition("\n")
            if title:
                result.append(TextBlock(deepcopy(block.font), title) if isinstance(block, TextBlock) else title)
            result.append(TextBlock(InlineFont(b=False), "\n" + bullet + ("" if body else "\n")))
            if body:
                result.append(
                    TextBlock(deepcopy(block.font), "\n" + body) if isinstance(block, TextBlock) else "\n" + body,
                )
            inserted = True
        else:
            result.append(deepcopy(block))
    if not inserted:
        result.append(TextBlock(InlineFont(b=False), "\n" + bullet))
    return result


def _scope_summary(
    sheet: Worksheet, data: Collection, findings: list[Finding], evidence_only_codes: set[str],
) -> None:
    system_codes = {
        sheet.cell(row, 2).value for row in range(5, sheet.max_row + 1)
        if "-SY-" in str(sheet.cell(row, 2).value)
    }
    graded = {item.se_code for item in findings if item.level != "N/A" and item.se_code not in evidence_only_codes}
    pending = {item.se_code for item in findings if item.se_code not in graded}
    missing = system_codes - graded - pending
    admin_failed = sum(not item.completed for item in data.admin_evidence)
    interviews = [
        row for row in range(5, sheet.max_row + 1)
        if re.fullmatch(r"[A-Z]{2}-(?:PR|PE|DA|TE)-\d+", str(sheet.cell(row, 2).value))
    ]
    completed = sum(_score(sheet.cell(row, 13).value) is not None for row in interviews)

    sheet["B2"] = (
        f"점검 요약 - 인터뷰 {len(interviews)}개 항목(답변 완료 {completed}개), "
        f"System Evidence {len(system_codes)}개 중 등급 산정 {len(graded)}개, "
        f"판정 보류 {len(pending)}개(보조 증거 포함), 자동 수집 결과 없음 {len(missing)}개. "
        f"API 조회 이슈 {len(data.issues)}건, 관리자 조회 미완료 {admin_failed}건.\n"
        f"수집 대상 : 구독 {len(data.subscriptions)}개, Azure Agent {len(azure_agents(data))}개."
    )

    provenance = data.assessment_provenance
    basis = (
        f"기준 SHA256 {provenance.criteria_sha256[:12]} / 평가 실행기 {provenance.collector_version}. "
        + ("저장된 실측 데이터 재평가이며 새 API 수집 아님. "
           if provenance.origin == "saved_snapshot_reassessment" else "")
    ) if provenance else "수집 당시 평가 기준 사본·수집기 버전 미기록 - 과거 결과에 현재 기준을 소급 기재하지 않음. "
    sheet["B3"] = (
        "참고 - L5는 해당 API 구성·기록의 충족률 100%이며 조직 전체 거버넌스 성숙도·정책 실효성의 증명이 아닙니다. "
        "실패·미확인·빈 분모는 0점이 아닌 판정 보류입니다. " + basis
        + "7번 시트에서 계산값·대상별 판정·증적·기준 출처를 확인하세요."

    )
    for row in (2, 3):
        sheet.row_dimensions[row].height = 45
        sheet.cell(row, 2).alignment = Alignment(vertical="center", wrap_text=True)


def refresh_interview_summary(path: Path, data: Collection, findings: list[Finding]) -> None:
    """Refresh completion labels without rewriting workbook scores, styles or formula caches."""
    book = load_workbook(path, rich_text=True)
    from easm_agent.report_integrated import is_integrated, refresh_integrated_summary

    if is_integrated(book):
        book.close()
        refresh_integrated_summary(path, data)
        return
    sheet = book[RESULT_SHEET]
    updates = {}
    for row in range(5, sheet.max_row + 1):
        if re.fullmatch(r"[A-Z]{2}-(?:PR|PE|DA|TE)-\d+", str(sheet.cell(row, 2).value)):
            updates[f"G{row}"] = (
                "인터뷰 완료" if str(sheet.cell(row, 7).value or "") == "인터뷰 완료"
                else "답변 완료" if _score(sheet.cell(row, 13).value) is not None else "인터뷰 필요"
            )
    evidence_only = {proposal.code for proposal in data.proposals if proposal.evidence_only}
    _scope_summary(sheet, data, findings, evidence_only)
    updates.update({coordinate: sheet[coordinate].value for coordinate in ("B2", "B3")})
    book.close()
    path.write_bytes(result_cell_updates(path, updates))

def _result_sheet(
    book: Workbook, data: Collection, findings: list[Finding], resources: dict[str, list[ResourceName]],
) -> dict[str, int]:
    source = book[CRITERIA_SHEET]
    evidence_only_codes = {proposal.code for proposal in data.proposals if proposal.evidence_only}
    sheet = book.copy_worksheet(source)
    sheet.title = RESULT_SHEET
    sheet.delete_cols(10)
    sheet.insert_cols(11)
    sheet.views = deepcopy(source.views)
    sheet.sheet_view.tabSelected = True
    sheet.freeze_panes = "G5"
    sheet.auto_filter.ref = f"B4:N{source.max_row}"
    sheet.print_title_rows = "1:4"
    headers = ("확인상태", "지표", "판정", "근거", "수집결과", "다음조치", source.cell(4, 13).value, "검토메모")
    for column, header in enumerate(headers, 7):
        sheet.cell(4, column, header)
    sheet.cell(4, 11)._style = copy(sheet.cell(4, 10)._style)
    sheet.cell(4, 13)._style = copy(source.cell(4, 13)._style)
    header_font = copy(sheet.cell(4, 9).font)
    header_font.bold = True
    sheet.cell(4, 9).font = header_font
    for column, width in enumerate((16, 25, 55, 90, 14, 60, 18, 30), 7):
        sheet.column_dimensions[get_column_letter(column)].width = width
    by_code = {finding.se_code: finding for finding in findings}
    if len(by_code) != len(findings):
        raise ValueError("수집 결과의 SY 코드가 중복되었습니다.")
    rows = {}
    for number in range(5, source.max_row + 1):
        code = source.cell(number, 2).value
        for column in range(7, 15):
            sheet.cell(number, column).value = None
        if not code:
            continue
        if code in COLLECTION_METHODS:
            description = source.cell(number, 6).value
            if not isinstance(description, (str, CellRichText)):
                raise ValueError(f"수집 방법을 표시할 점검 내용이 없습니다: {code}")
            sheet.cell(number, 6).value = _with_collection_method(description, COLLECTION_METHODS[code])
        finding = by_code.get(str(code))
        if finding is None:
            values = (
                "수집하지 않음" if "-SY-" in str(code) else "인터뷰 필요",
                None, None,
                "자동 수집 결과 없음 또는 자동 수집 범위 밖 - 수동 확인 필요"
                if "-SY-" in str(code) else "인터뷰를 통해 확인하는 수동 심사 항목",
                None, None, None, None,
            )
        else:
            rows[finding.se_code] = number
            status, summary = collection_summary(data, finding)
            level_text = readable(finding.level)
            if finding.level != "N/A":
                legacy_grade = data.facts.get("assessment_revision") is not None and not data.facts.get("grading_profile")
                criterion = finding.level_criterion or (
                    "수집 당시 기준의 등급 - 원본 JSON 판정 근거 참조" if legacy_grade else
                    source.cell(number, 6 + int(finding.level[1:])).value
                )
                if not isinstance(criterion, str) or not criterion.strip():
                    raise ValueError(f"{finding.se_code}: {finding.level} 평가기준 문장이 없습니다.")
                level_text = f"Level {finding.level[1:]} ({readable(criterion)})"
            values = (
                "일부 수집" if finding.se_code in evidence_only_codes and status == "일부 수집" else
                "수집됨" if status in ("수집됨", "일부 수집", "증적 확인")
                else "수집하지 않음",
                metric(finding) if finding.assessment_basis == "configuration" or finding.metric_value is not None
                or not summary or status == "수집 불가" else "실측 구성 - 근거 참조",
                level_text,
                ("수집 결과: " + readable(summary) + "\n" if summary else "")
                + "관련 리소스: " + str(redact(resource_summary(resources[finding.se_code]))) + "\n"
                + ("조회 제한: " + readable(finding.reason) + " (" + status + ")\n" if finding.reason else "")
                + "판정 근거: " + readable(finding.rationale),
                None,
                None if finding.level == "L5" else readable(finding.next_step),
                int(finding.level[1:]) if finding.level != "N/A"
                and status in ("수집됨", "일부 수집", "증적 확인") else None,
                None,
            )
        for column, value in enumerate(values, 7):
            style = copy(source.cell(number, column + (column == 10))._style)
            _cell(sheet, number, column, value)
            sheet.cell(number, column)._style = style
        if finding is not None and finding.level != "N/A":
            label = f"Level {finding.level[1:]}"
            sheet.cell(number, 9).value = CellRichText(
                TextBlock(InlineFont(b=True), label), level_text[len(label):],
            )
            if finding.level != "L5" and not (
                data.facts.get("assessment_revision") is not None and not data.facts.get("grading_profile")
            ):
                next_level = int(finding.level[1:]) + 1
                condition = source.cell(number, 6 + next_level).value
                if not isinstance(condition, str) or not condition.strip():
                    raise ValueError(f"{finding.se_code}: L{next_level} 평가기준 문장이 없습니다.")
                sheet.cell(number, 12).value = CellRichText(
                    TextBlock(InlineFont(b=True), f"Level {next_level}"), ": " + condition,
                )
        evidence = sheet.cell(number, 10)
        if finding is not None and isinstance(evidence.value, str):
            evidence.value = _emphasize_evidence(evidence.value)
            font = copy(evidence.font)
            font.bold = False
            evidence.font = font
        sheet.cell(number, 11).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.cell(number, 13).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.row_dimensions[number].height = RESULT_ROW_HEIGHT
    sheet.cell(4, 11).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.cell(4, 13).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if rows.keys() != by_code.keys():
        raise ValueError("평가 결과 템플릿에 없는 SY 코드가 수집 결과에 포함되었습니다.")
    validation = DataValidation(
        type="whole", operator="between", formula1="1", formula2="5", allow_blank=True,
    )
    validation.errorTitle = "평가 점수 확인"
    validation.error = "1~5 정수만 입력하세요. 판정이 없는 항목은 빈칸으로 유지하세요."
    validation.showErrorMessage = True
    validation.errorStyle = "stop"
    sheet.add_data_validation(validation)
    validation.add(f"M5:M{source.max_row}")
    book.active = sheet
    _scope_summary(sheet, data, findings, set(evidence_only_codes))
    return rows


def write_workbook(
    data: Collection, findings: list[Finding], path: Path, *, interview_workbook: Path | None = None,
) -> None:
    """Extend the assessment template with a masked collected-evidence snapshot."""
    data, findings = with_evidence_only_findings(data, findings)
    book, template = load_report_template()
    from easm_agent.report_integrated import (
        GRADES,
        copy_manual_inputs,
        is_integrated,
        populate_integrated,
        save_integrated_package,
    )

    integrated = is_integrated(book)
    if interview_workbook is not None:
        if not integrated:
            raise ValueError("수동 입력 원본 지정은 통합 14개 시트 템플릿에서 지원합니다.")
        copy_manual_inputs(book, interview_workbook)
    resources = {
        code: resource_names(data, code)
        for code in {finding.se_code for finding in findings} | {proposal.code for proposal in data.proposals}
    }
    from easm_agent.report_integrated import criteria_for

    copilot_codes = {
        code for code, definition in criteria_for(data)["items"].items()
        if definition.get("copilot_inventory_check")
    }
    result_rows = populate_integrated(book, data, findings) if integrated else _result_sheet(
        book, data, findings, resources,
    )
    details = [
        {
            "SY 코드": item.code, "진단 영역": item.area or DOMAINS.get(item.code, ("",))[0],
            "점검 항목": item.title + (
                " (Azure 세부 점검)" if item.code in copilot_codes else ""
            ), "조회 상태": item.status,
            "조회 제한 사유": readable(item.reason) if item.reason else "해당 없음",
            "수집 구성 요약": readable(item.observation), "구성 값·건수": item.metrics, "검증 한계": item.limit,
            "증적 ID": item.evidence_refs,
        } for item in data.proposals
    ]
    codes = {item["SY 코드"] for item in details}
    if len(codes) != len(details):
        raise ValueError("수집결과 근거의 SY 코드가 중복되었습니다.")
    for finding in findings:
        if finding.se_code in codes:
            continue
        status, summary = collection_summary(data, finding)
        details.append({
            "SY 코드": finding.se_code, "진단 영역": SE_AREAS.get(finding.se_code[:2], ""),
            "점검 항목": SE_NAMES.get(finding.se_code, finding.se_code), "조회 상태": status,
            "조회 제한 사유": readable(finding.reason) if finding.reason else "해당 없음",
            "수집 구성 요약": readable(summary),
            "구성 값·건수": {
                "metric_value": finding.metric_value, "assessment_basis": finding.assessment_basis,
                "configuration_value": finding.configuration_value,
            },
            "검증 한계": readable(finding.scope) + ". 등급별 승인·기간·집행 검증은 판정 시트 근거 확인",
            "증적 ID": finding.evidence_refs,
        })
    details.sort(key=lambda item: result_rows.get(item["SY 코드"], float("inf")))
    by_code = {item.se_code: item for item in findings}
    for detail in details:
        finding = by_code.get(detail["SY 코드"])
        if finding is None or finding.measurement is None:
            continue
        measured = finding.measurement
        detail["구성 값·건수"] = {
            "numerator": measured.numerator, "denominator": measured.denominator,
            "unit": measured.unit, "currency": measured.currency, "coverage": finding.metric_value,
            "complete": measured.complete, "reason": measured.reason,
            "target_count": len(measured.targets),
        }
        detail["수집 구성 요약"] = str(detail["수집 구성 요약"] or "") + (
            f"\n계산: {measured.numerator:g} / {measured.denominator:g}"
            + (f" {measured.currency}" if measured.currency else "개")
            + f" = {finding.metric_value:.2%}"
            if measured.complete and measured.numerator is not None and measured.denominator is not None
            and finding.metric_value is not None else "\n계산 보류: " + (measured.reason or "값 미확인")
        )
        detail["증적 ID"] = finding.evidence_refs
    crosschecks = {item.se_code: item for item in data.agent365_crosschecks}
    for detail in details:
        detail["수집 구성 요약"] = (
            str(detail["수집 구성 요약"] or "") + "\n관련 리소스: " + resource_summary(resources[detail["SY 코드"]])
        )
        check = crosschecks.get(detail["SY 코드"])
        detail["Agent 365 교차검증"] = STATUS_LABELS[check.status] if check else "미수행"
        detail["교차검증 범위·결과"] = (
            f"{check.scope}\n{check.detail}"
            + (f"\n비교 {check.compared}, 일치 {check.matched}, 불일치 {check.mismatched}, 미확인 {check.unverified}"
               if check.compared is not None else "")
            + (f"\n조회 사유: {readable(check.reason)}" if check.reason else "")
        ) if check else "기존 수집 결과에 Agent 365 교차검증 기록 없음. 기존 등급 유지"
        if check and check.status == "not_comparable":
            detail["교차검증 범위·결과"] = (
                "기존 Azure/Graph API로 평가하는 항목 - 평가 제외 아님\n"
                "Agent 365 등록부에 같은 판정 정보 미제공\n" + check.detail
            )
        detail["교차검증 증적"] = check.evidence_refs if check else []
    proposals_sheet = _table(book, DETAILS_TITLE, [
        "SY 코드", "진단 영역", "점검 항목", "조회 상태", "조회 제한 사유",
        "수집 구성 요약", "구성 값·건수", "검증 한계", "증적 ID",
        "Agent 365 교차검증", "교차검증 범위·결과", "교차검증 증적",
    ], details, start_row=3, integrated=integrated)
    for row, item in enumerate(details, 4):
        code = item["SY 코드"]
        if code not in result_rows:
            continue
        cell = book[GRADES if integrated else RESULT_SHEET].cell(result_rows[code], 12 if integrated else 11)
        cell.value = "수집결과"
        font = copy(cell.font)
        font.color = "FF0563C1"
        font.underline = "single"
        cell.font = font
        cell.hyperlink = Hyperlink(
            ref=cell.coordinate, location=f"'{proposals_sheet.title}'!A{row}",
            display="수집결과", tooltip=f"{code} 수집결과 근거로 이동",
        )
    _cell(proposals_sheet, 1, 1, (
        "수집된 설정·값·건수와 검증 한계. 하단에 리소스 목록·대상별 판정·기준 출처 포함. "
        + ("다음조치는 3_SE 판정 M열 확인" if integrated else "다음조치는 6. 수집 결과의 L열 확인")
    ))
    proposals_sheet.merge_cells("A1:L1")
    proposals_sheet.row_dimensions[1].height = 30
    proposals_sheet.print_title_rows = "1:3"
    explanations = (
        "판정 시트와 연결되는 System Evidence 항목 코드",
        "항목이 속한 진단 영역", "조회한 Azure 구성 점검 항목의 이름",
        "실제 조회 상태. 등급이나 개선 필요 여부를 뜻하지 않음",
        "권한·기능·대상 없음 등 조회를 제한한 사유",
        "실제 조회된 설정과 건수를 읽기 쉽게 요약한 값",
        "원본 키를 유지한 구성 값·건수. 승인 충족률이나 효과 검증 결과가 아님",
        "구성 조회만으로 입증할 수 없는 승인·집행 효과·운영 절차",
        "원본 JSON evidence에 첨부된 마스킹 증적 ID 또는 확인이 필요한 참조",
        "독립 등록부의 일부 필드 대조 결과. 기존 등급과 별개",
        "실제 비교 범위·불일치·미확인 사유. 패키지 버전을 런타임 버전과 비교하지 않음",
        "교차검증에 사용한 최소 필드 등록부 및 기존 API 증적 ID",
    )
    for column, explanation in enumerate(explanations, 1):
        proposals_sheet.cell(3, column).comment = Comment(explanation, "EASM Agent")
    sections: list[tuple[str, type[BaseModel], Sequence[BaseModel]]] = [
        ("Agent Raw 데이터", AgentEvidence, data.agents),
        ("제안 Raw 데이터", ProposalObservation, data.proposal_observations),
        ("평가 Raw 데이터", EvaluationRun, data.evaluations),
        ("모델배포 Raw 데이터", ModelDeployment, data.deployments),
        ("비용 Raw 데이터", CostRecord, data.costs),
        ("로그 Raw 데이터", LogSetting, data.logs),
        ("보안 Raw 데이터", SecurityRecommendation, data.security),
        ("보안점수 Raw 데이터", SecureScore, data.secure_scores),
        ("Defender 플랜 Raw 데이터", DefenderPlan, data.defender_plans),
        ("정책할당 Raw 데이터", PolicyAssignment, data.policy_assignments),
        ("예산 Raw 데이터", Budget, data.budgets),
        ("Blueprint Raw 데이터", EntraBlueprint, data.entra_blueprints),
        ("AgentID Raw 데이터", EntraAgentIdentity, data.entra_agent_identities),
        ("Agent365 등록 Raw 데이터", Agent365Package, data.agent365_packages),
        ("Agent365 대조 Raw 데이터", Agent365Crosscheck, data.agent365_crosschecks),
        ("관리자 읽기 Raw 데이터", AdminReadResult, data.admin_evidence),
        ("Copilot Agent Raw 데이터", CopilotAgentEvidence, data.copilot_agents),
        ("추가 보고서 SY Raw 데이터", ReportEvidenceRawRecord, [
            ReportEvidenceRawRecord(
                **dataset.model_dump(exclude={"kind", "records", "observed_subjects"}),
                values=values,
            )
            for dataset in data.report_evidence
            for values in (
                [record.model_dump(mode="json") for record in dataset.records]
                + ([{"observed_subject": subject} for subject in dataset.observed_subjects]
                   if dataset.kind == "registry" else [])
                or [{}]
            )
        ]),
    ]
    _raw_sheet(book, sections, integrated=integrated)
    issue_title = "수집이슈 Raw 데이터"
    _table(
        book, issue_title, [*Issue.model_fields, ORIGINAL], _raw_rows(data.issues), integrated=integrated,
    )
    _table(book, "필드누락사유", [
        "agent_id", "subscription_id", "필드명", "field", "reason", "설명", ORIGINAL,
    ], _missing_rows(data), integrated=integrated)
    resource_rows = []
    for code in sorted(resources, key=lambda value: (result_rows.get(value, float("inf")), value)):
        names = resources[code]
        for resource in names:
            resource_rows.append({
                "SY 코드": code, "리소스 유형": resource.category, "리소스 이름": resource.name,
                "구독 ID": resource.subscription_id, "리소스 그룹": resource.resource_group,
                "식별자": resource.identifier,
            })
        if not names:
            resource_rows.append({"SY 코드": code})
    resource_header = proposals_sheet.max_row + 4
    _cell(proposals_sheet, resource_header - 1, 1, "항목별 관련 리소스 전체 목록")
    proposals_sheet.merge_cells(
        start_row=resource_header - 1, end_row=resource_header - 1, start_column=1, end_column=12,
    )
    _table(book, DETAILS_TITLE, [
        "SY 코드", "리소스 유형", "리소스 이름", "구독 ID", "리소스 그룹", "식별자",
    ], resource_rows, sheet=proposals_sheet, start_row=resource_header)
    target_rows = []
    status_labels = {"compliant": "충족", "non_compliant": "미충족", "unknown": "미확인", "excluded": "계산 제외"}
    for finding in findings:
        if finding.measurement is None:
            continue
        for target in finding.measurement.targets:
            target_rows.append({
                "SY 코드": finding.se_code, "확인 상태": status_labels[target.status],
                "대상 식별자": target.subject, "확인한 설정·값": target.observed,
                "단위": "금액" if finding.measurement.unit == "amount" else "개수",
                "계산 기여값": target.contribution, "통화": finding.measurement.currency,
                "사유": target.reason, "증적 ID": target.evidence_refs,
            })
    header = proposals_sheet.max_row + 4
    _cell(proposals_sheet, header - 1, 1, "대상별 판정 - 미확인·제외 대상과 금액 귀속 내역 포함. 종합 판정 보류 시 개별 관측값은 점수가 아닙니다.")
    proposals_sheet.merge_cells(start_row=header - 1, end_row=header - 1, start_column=1, end_column=12)
    _table(book, DETAILS_TITLE, [
        "SY 코드", "확인 상태", "단위", "계산 기여값", "통화", "확인한 설정·값", "대상 식별자", "사유", "증적 ID",
    ], target_rows, sheet=proposals_sheet, start_row=header)
    _fit_audit_rows(proposals_sheet, header + 1, proposals_sheet.max_row, 9)
    provenance = data.assessment_provenance
    provenance_rows = [
        {"항목": "원본 API 수집 시각", "값": data.collected_at.isoformat()},
        {"항목": "평가 범위", "값": "API 구성·기록 충족률. 조직 승인·정책 실효성·전체 성숙도 판정 아님"},
    ]
    if provenance:
        provenance_rows.extend([
            {"항목": "평가 시각", "값": provenance.evaluated_at.isoformat()},
            {"항목": "평가 구분", "값": "저장 실측 재평가 - 새 수집 아님"
             if provenance.origin == "saved_snapshot_reassessment" else "수집 데이터 평가"},
            {"항목": "평가 기준 SHA256", "값": provenance.criteria_sha256},
            {"항목": "태그 규약 SHA256", "값": provenance.conventions_sha256},
            {"항목": "재평가 실행기 버전" if provenance.origin == "saved_snapshot_reassessment" else "수집기 버전",
             "값": provenance.collector_version},
            {"항목": "평가 실행기 Python 소스 SHA256", "값": provenance.collector_source_sha256},
            {"항목": "해시 범위", "값": provenance.hash_scope},
            {"항목": "기준 사본", "값": "결과 JSON의 collection.assessment_provenance.criteria_snapshot"},
        ])
        if provenance.source_result_data_sha256:
            provenance_rows.append({"항목": "재평가 전 원본 결과 데이터 SHA256", "값": provenance.source_result_data_sha256})
    else:
        provenance_rows.append({"항목": "기준·버전 출처", "값": "과거 수집 당시 사본 미기록. 현재 기준으로 채워 넣지 않음"})
    header = proposals_sheet.max_row + 4
    _cell(proposals_sheet, header - 1, 1, "평가 기준·수집기 출처")
    proposals_sheet.merge_cells(start_row=header - 1, end_row=header - 1, start_column=1, end_column=12)
    _table(book, DETAILS_TITLE, ["항목", "값"], provenance_rows, sheet=proposals_sheet, start_row=header)
    _fit_audit_rows(proposals_sheet, header + 1, proposals_sheet.max_row, 2)
    header = proposals_sheet.max_row + 4
    _cell(
        proposals_sheet, header - 1, 1,
        "PPT 원본 요구 지표와 현재 SY의 대응 - 원본 코드는 참고용이며 현재 26개 평가 코드가 아닙니다.",
    )
    proposals_sheet.merge_cells(start_row=header - 1, end_row=header - 1, start_column=1, end_column=12)
    _table(book, DETAILS_TITLE, [
        "원본 PPT 항목", "요구 지표", "관련 현재 SY 코드", "지표 값",
        "확인 상태", "사유 코드", "보류 사유·범위 차이", "해석 한계",
    ], presentation_evidence_rows(data, findings), sheet=proposals_sheet, start_row=header)
    _fit_audit_rows(proposals_sheet, header + 1, proposals_sheet.max_row, 8)
    header = proposals_sheet.max_row + 4
    _cell(proposals_sheet, header - 1, 1, "추가 보고서 System Evidence - 기존 26개 API 등급과 별도. 원천·범위·기간은 Raw 확인")
    proposals_sheet.merge_cells(start_row=header - 1, end_row=header - 1, start_column=1, end_column=12)
    _table(book, DETAILS_TITLE, [
        "SY 코드", "지표 키", "확인 항목", "값", "단위", "상태", "사유", "원천·범위·한계", "증적 ID",
    ], (
        {
            "SY 코드": metric.code, "지표 키": metric.key, "확인 항목": metric.label,
            "값": metric.value, "단위": metric.unit,
            "상태": "관측" if metric.value is not None else "판정 보류",
            "사유": metric.reason, "원천·범위·한계": metric.limitation, "증적 ID": metric.evidence_refs,
        }
        for metric in supplemental_metrics(
            data, data.assessment_provenance.criteria_snapshot if data.assessment_provenance else {},
        ) if not metric.key.startswith("report.") and ".month." not in metric.key
    ), sheet=proposals_sheet, start_row=header)
    _fit_audit_rows(proposals_sheet, header + 1, proposals_sheet.max_row, 9)
    if integrated:
        from easm_agent.report_values import build_report_values, configure_calculation_formulas

        configure_calculation_formulas(book)
        contract = build_report_values(book)
        header = proposals_sheet.max_row + 4
        _cell(proposals_sheet, header - 1, 1, "Working Backwards - PPT 표시값 → Excel 셀 → 제공 수동 입력 / 저장 API 측정값")
        proposals_sheet.merge_cells(start_row=header - 1, end_row=header - 1, start_column=1, end_column=12)
        _table(book, DETAILS_TITLE, ["슬라이드", "도형 ID", "PPT 표시값", "Excel 시트", "Excel 셀", "계산식"], (
            {"슬라이드": binding.page + 1, "도형 ID": binding.shape,
             "PPT 표시값": contract.display(binding), "Excel 시트": binding.sheet,
             "Excel 셀": binding.cell, "계산식": str(book[binding.sheet][binding.cell].value)}
            for binding in contract.bindings
        ), sheet=proposals_sheet, start_row=header)
    if integrated:
        from easm_agent.report_integrated import GUIDE

        guide_index = book.index(book[GUIDE])
        book.active = guide_index
        for view in book.views:
            view.activeTab, view.firstSheet = guide_index, 0
        for sheet in book:
            for view in sheet.views.sheetView:
                view.tabSelected = sheet.title == GUIDE
    book.save(path)
    if integrated:
        save_integrated_package(path, template)
    else:
        preserve_template_parts(path, template)
        format_assessment_workbook(path)
