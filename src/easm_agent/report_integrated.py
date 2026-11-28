"""Populate the integrated assessment without replacing its formatting or manual inputs."""

from __future__ import annotations

import json
import math
import re
from copy import copy
from datetime import UTC, timedelta, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, PatternFill, Side
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.datavalidation import DataValidation

from easm_agent.azure import redact
from easm_agent.models import Collection, Finding, load_criteria, timestamp
from easm_agent.report_evidence import _months, supplemental_metrics

GUIDE = "0_안내"
RAW = "2_SE 원천데이터"
GRADES = "3_SE 판정"
PROCESS = "4_프로세스 점수"
MATRIX = "2c_수집 매트릭스"
INTEGRATED_SHEETS = (
    GUIDE, "1_진단 개요", "1a_플랫폼 기준", RAW, "2a_월별 추이", "2b_세부 내역",
    MATRIX, GRADES, "3a_단계 신뢰도", PROCESS, "5_문서 실사", "6_인터뷰 기록",
    "7_보고서 산출", "7a_보고서 산출(범위·신뢰도)",
)
# Sheet tab colors group sheets by role and darken progressively like a gradient: green family
# for intro/SY sheets, blue family for interview/report sheets.
OVERVIEW_SHEET_COLOR = "A9D18E"
SY_SHEET_COLOR = "548235"
INTERVIEW_SHEET_COLOR = "9DC3E6"
REPORT_SHEET_COLOR = "1F4E78"
OVERVIEW_TAB_SHEETS = (GUIDE, "1_진단 개요", "1a_플랫폼 기준")
SY_TAB_SHEETS = (RAW, "2a_월별 추이", "2b_세부 내역", MATRIX, GRADES, "3a_단계 신뢰도")
INTERVIEW_TAB_SHEETS = (PROCESS, "5_문서 실사", "6_인터뷰 기록")
REPORT_TAB_SHEETS = ("7_보고서 산출", "7a_보고서 산출(범위·신뢰도)")
YELLOW = PatternFill("solid", fgColor="FFFFF2CC")
INPUT_FONT_COLOR = "FF0070C0"
KST = timezone(timedelta(hours=9))
EXTRACTED_FORMAT = 'yyyy-mm-dd hh:mm:ss "KST"'
RAW_GUIDE = (
    "'입력값' 열은 측정값·참조 수식 모두 노란 바탕·파란 글자로 통일합니다. 수식은 직접 수정하지 않습니다. "
    "수집 항목 · 도구는 System Evidence 수집 기준과 동일합니다."
)
THIN = Side(style="thin")
MEDIUM = Side(style="medium")
SHEET_GUIDES = {
    GUIDE: "사용 순서 · 색상 범례 · 판정 원칙 · 수집 범위 · 데이터 신뢰도 기준 안내. "
           "System Evidence 26개와 제공된 인터뷰 · 문서 입력을 구분합니다.",
    "1a_플랫폼 기준": "플랫폼별 Agent 수 · ID 귀속 수 · 수집 방식을 표시합니다. "
                    "노란 셀은 입력값, 흰 셀은 참조 수식이며 미확인 값은 공란으로 남깁니다.",
    RAW: RAW_GUIDE,
    "2a_월별 추이": "현재 관측 대상의 생성월·플랫폼별 생성·등록·배포 상태와 Azure 비용을 표시합니다. "
                  "과거 게시 이력·생성 승인 이력·이기종 비용을 추정하지 않습니다.",
    "2b_세부 내역": "MS·이기종 전체 관측 대상의 소유자·생성·등록·배포 구성과 ID·모델·버전·지역을 통합 표시합니다.",
    MATRIX: "항목별 수집 범위 · 측정 대상 · 확인 상태와 판정을 표시합니다. "
            "API 정보 확인율은 전사 Agent 커버리지와 구분합니다. "
            "수집 방식 - A API 자동 조회(승인된 위임 사용자 API 파일 포함) · E 관리 콘솔 화면·수동 내보내기 증적 · "
            "△ 운영자 확인(담당자 확인 참고치, 판정 제외) · X 측정 불가(범위 내이나 조회 실패) · "
            "해당 없음(플랫폼 측정 범위 밖 또는 API 필드 미지원, 사유는 비고·근거 참조).",
    GRADES: "System Evidence 26개 기준의 충족률과 L1~L5 판정을 표시합니다. "
            "흰 셀은 수식이며 조회 실패 · 필수 값 미확인 · 빈 분모는 N/A로 남깁니다.",
    "3a_단계 신뢰도": "단계별 API 정보 확인율 · 데이터 신뢰도 · 보정 적용 여부를 표시합니다. "
                     "프로세스 진단 ~ 최종 수준은 7_보고서 산출 값을 참조합니다.",
    "7_보고서 산출": "모든 값은 원천 시트의 참조 수식입니다. 보고서 표시값은 소수 첫째 자리로 반올림하며 "
                    "보정은 1_진단 개요 산정 기준값과 3a_단계 신뢰도를 따릅니다.",
    "7a_보고서 산출(범위·신뢰도)": "보고서에 옮겨 쓰는 수집 범위 · 데이터 신뢰도 요약입니다. "
                                 "점수 · 지표 수치는 7_보고서 산출 값을 참조합니다.",
}


def _unit_label(unit: str | None, currency: str | None) -> str:
    if currency:
        return {
            "USD": "미국 달러 (USD)", "KRW": "원 (KRW)", "EUR": "유로 (EUR)", "JPY": "엔 (JPY)",
        }.get(currency, currency)
    return {"count": "개", "amount": "금액"}.get(unit or "", "미확인")


def apply_template_layout(book: Workbook, template: bytes) -> None:
    """Restore template dimensions, retaining generated hidden evidence columns."""
    from io import BytesIO

    from easm_agent.report_layout import load_report_layout

    original = load_workbook(BytesIO(template))
    layout = load_report_layout()
    for sheet in book:
        for row in sheet:
            for cell in row:
                if not isinstance(cell, MergedCell) and (
                    (sheet.title in INTEGRATED_SHEETS and cell.row == 2) or (cell.font.i and not cell.font.b)
                ):
                    font = copy(cell.font)
                    font.name, font.sz = "Microsoft GothicNeo", 9
                    cell.font = font
        if sheet.title not in layout:
            raise ValueError(f"보고서 시트의 레이아웃 정의가 없습니다: {sheet.title}")
        reference_layout = layout[sheet.title]
        hidden_columns = {
            column for letter, dimension in sheet.column_dimensions.items() if dimension.hidden
            for column in range(
                dimension.min or column_index_from_string(letter),
                (dimension.max or column_index_from_string(letter)) + 1,
            )
        }
        sheet.sheet_format.defaultRowHeight = reference_layout["default_row_height"]
        sheet.column_dimensions.clear()
        for column in range(1, sheet.max_column + 1):
            letter = get_column_letter(column)
            reference = reference_layout["columns"].get(letter, {"width": 13, "hidden": False})
            dimension = sheet.column_dimensions[letter]
            dimension.width = reference["width"]
            dimension.hidden = column in hidden_columns or reference["hidden"]
            dimension.min = dimension.max = column
        last_row = max(sheet.max_row, max(map(int, reference_layout["row_heights"]), default=1))
        for row in range(1, last_row + 1):
            sheet.row_dimensions[row].height = reference_layout["row_heights"].get(
                str(row), reference_layout["default_row_height"],
            )
        if sheet.title not in original.sheetnames:
            continue
        source = original[sheet.title]
        for row in sheet.iter_rows(max_row=min(sheet.max_row, source.max_row), max_col=source.max_column):
            for cell in row:
                if not isinstance(cell, MergedCell):
                    alignment = copy(cell.alignment)
                    alignment.wrap_text = source[cell.coordinate].alignment.wrap_text
                    cell.alignment = alignment
    original.close()


def format_integrated_workbook(book: Workbook, definitions: dict[str, Any] | None = None) -> None:
    """Keep template structure and normalize colors within each input column."""
    from easm_agent.report_template import COLLECTION_METHODS, collection_method

    definitions = definitions or load_criteria()["items"]
    last_matrix_row = 7 + len(definitions)
    for name in INTEGRATED_SHEETS:
        sheet = book[name]
        for row in sheet:
            for cell in row:
                if isinstance(cell, MergedCell):
                    continue
                if cell.fill.fgColor.type == "rgb" and cell.fill.fgColor.rgb == "FFFFC000":
                    cell.fill = copy(YELLOW)
                cell.comment = None
        if name in SHEET_GUIDES:
            sheet["A2"] = SHEET_GUIDES[name]
        if name in OVERVIEW_TAB_SHEETS:
            sheet.sheet_properties.tabColor = OVERVIEW_SHEET_COLOR
        elif name in SY_TAB_SHEETS:
            sheet.sheet_properties.tabColor = SY_SHEET_COLOR
        elif name in INTERVIEW_TAB_SHEETS:
            sheet.sheet_properties.tabColor = INTERVIEW_SHEET_COLOR
        elif name in REPORT_TAB_SHEETS:
            sheet.sheet_properties.tabColor = REPORT_SHEET_COLOR
        # Opening the file should land on 0_안내 with no other sheet highlighted/grouped.
        sheet.sheet_view.tabSelected = name == GUIDE
    book.active = book.index(book[GUIDE])
    for name, region in (
        ("1_진단 개요", "B5:B19"),
        ("1_진단 개요", "B23:D30"),
        ("1a_플랫폼 기준", "F5:G11"),
    ):
        for row in book[name][region]:
            for cell in row:
                font = copy(cell.font)
                font.color = INPUT_FONT_COLOR
                cell.font, cell.fill = font, copy(YELLOW)
    book[GUIDE]["C16"] = (
        "입력·참조 값 열 - 노란 채우기(FFF2CC) · 파란 글자(0070C0). "
        "같은 표의 같은 열은 빈 셀·참조 수식을 포함해 색상을 통일합니다."
    )
    book[GUIDE]["C17"] = (
        "계산 열 - 흰 바탕 · 검정 글자. 입력·참조 값 열에도 수식이 포함될 수 있으므로 "
        "수식 입력줄에서 확인하고 수식은 직접 수정하지 않습니다."
    )
    matrix = book[MATRIX]
    for row in matrix.iter_rows():
        for cell in row:
            if isinstance(cell, MergedCell) or cell.row == 1 or cell.font.name == "Microsoft GothicNeo" and cell.font.sz == 10.0:
                continue
            font = copy(cell.font)
            font.name, font.sz = "Microsoft GothicNeo", 10.0
            cell.font = font
    matrix.data_validations.dataValidation.clear()
    scope_validation = DataValidation(
        type="list", formula1='"A,E,△,X,해당 없음"', allow_blank=True, showDropDown=False,
        showInputMessage=True, promptTitle="수집 방식",
        prompt="A 자동 수집 · E Export\nX 조회 실패\n해당 없음 플랫폼 범위 밖·API 필드 미지원",
    )
    matrix.add_data_validation(scope_validation)
    scope_validation.add(f"E8:K{last_matrix_row}")
    matrix.column_dimensions["B"].width = 35
    matrix.column_dimensions["D"].width = 35
    matrix.column_dimensions["AA"].hidden = True
    for matrix_row in range(8, last_matrix_row + 1):
        cell = matrix[f"D{matrix_row}"]
        alignment = copy(cell.alignment)
        alignment.horizontal = "left"
        cell.alignment = alignment
    raw = book[RAW]
    raw["I4"], raw["J4"] = "추출 일시 (KST)", "추출자"
    raw["L1"], raw["M4"], raw["N4"] = "easm_collected_at_utc", "easm_measurement_unit", "easm_currency"
    for address in ("L1", "L2", "M4", "N4"):
        raw[address].font = copy(raw["F5"].font)
    raw.column_dimensions.group("L", "N", hidden=True)
    for column, width in {
        "A": 11, "B": 6, "C": 9, "D": 32, "E": 46, "F": 13,
        "G": 15, "H": 48, "I": 21, "J": 15, "K": 24,
    }.items():
        dimension = raw.column_dimensions[column]
        dimension.width = width
        dimension.min = dimension.max = column_index_from_string(column)
    raw.row_dimensions[2].height = 30
    raw.row_dimensions[4].height = 18
    for column in "ABCDEFGHIJK":
        cell = raw[f"{column}4"]
        cell.border = Border(left=THIN, right=THIN if column == "K" else None, top=THIN, bottom=MEDIUM)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in range(5, 57):
        raw.row_dimensions[row].height = 18
        value = raw[f"F{row}"]
        value.fill = copy(YELLOW)
        font = copy(value.font)
        font.color = INPUT_FONT_COLOR
        value.font = font
        code = raw[f"A{row}"].value
        config = definitions.get(code)
        offset = (row - 5) % 2
        if config:
            label = config.get("numerator") if offset == 0 else config.get("denominator")
            if label:
                raw[f"E{row}"] = label
        unit = raw[f"M{row}"].value or raw[f"G{row}"].value
        if unit in ("count", "amount"):
            raw[f"M{row}"] = unit
            raw[f"G{row}"] = _unit_label(unit, raw[f"N{row}"].value)
            value.number_format = "General" if unit == "amount" else "#,##0"
        for column in ("M", "N"):
            raw[f"{column}{row}"].font = copy(value.font)
        if offset == 0 and code in COLLECTION_METHODS:
            raw[f"H{row}"] = collection_method(code, config)
        if raw[f"K{row}"].value == "not_found - 아직 수집하지 않음":
            raw[f"K{row}"] = "수집 전"
        raw[f"I{row}"].number_format = EXTRACTED_FORMAT
        bottom = MEDIUM if offset == 1 else THIN
        for column in "ABCDEFGHIJK":
            cell = raw[f"{column}{row}"]
            cell.border = Border(
                left=THIN, right=THIN if column == "K" else None, top=THIN, bottom=bottom,
            )
        for column, horizontal in (
            ("A", "center"), ("B", "center"), ("C", "center"), ("D", "left"), ("E", "left"),
            ("F", "center"), ("G", "center"), ("H", "left"), ("I", "left"), ("J", "left"), ("K", "left"),
        ):
            cell = raw[f"{column}{row}"]
            cell.alignment = Alignment(horizontal=horizontal, vertical="center", wrap_text=True)
    # Rows beyond the 52 data rows are leftover template structure - clear stray fills/borders/values.
    for row in range(57, raw.max_row + 1):
        for column in "ABCDEFGHIJKLMN":
            cell = raw[f"{column}{row}"]
            if isinstance(cell, MergedCell):
                continue
            cell.value = None
            cell.fill = PatternFill()
            cell.border = Border()
    if raw.max_row > 56:
        raw.delete_rows(57, raw.max_row - 56)
    raw.data_validations.dataValidation.clear()
    raw.freeze_panes = "F5"
    raw.print_area = "A1:K56"
    raw.print_title_rows = "1:4"
    book[GRADES]["L4"] = "수집결과 근거"
    platform = book["1a_플랫폼 기준"]
    platform["N4"] = "해당 없음"
    for row in range(5, 12):
        for column, letter in (("J", "A"), ("K", "E"), ("L", "△"), ("M", "X"), ("N", "해당 없음")):
            platform[f"{column}{row}"] = (
                f"=COUNTIF(INDEX('{MATRIX}'!$E$8:$K${last_matrix_row},0,"
                f"MATCH($A{row},'{MATRIX}'!$E$6:$K$6,0)),\"{letter}\")"
            )
        platform[f"I{row}"] = f"=J{row}+K{row}"
    for row in (12, 13):
        for column in "IJKLMN":
            platform[f"{column}{row}"] = f'=SUMIF($C$5:$C$11,$C{row},{column}$5:{column}$11)'
    for column in "IJKLMN":
        platform[f"{column}14"] = f"=SUM({column}5:{column}11)"
    platform["H13"] = '=IF(AND(F14>0,ISNUMBER(F13)),F13/F14,"미확인")'
    # p.9 III "항목별 측정 범위 · 신뢰도" formulas were sized for the former 20-item range (rows 8:27);
    # extend to the full 26-item range (rows 8 through last_matrix_row) so the table can resolve.
    scope_sheet = book["7a_보고서 산출(범위·신뢰도)"]
    for row in scope_sheet.iter_rows():
        for cell in row:
            if isinstance(cell.value, str):
                cell.value = re.sub(
                    r"(\$[A-Z]+\$8:\$[A-Z]+\$)27\b", rf"\g<1>{last_matrix_row}", cell.value,
                )
    for row in range(57, 57 + len(definitions)):
        code = list(definitions)[row - 57]
        bottom = MEDIUM if row == 56 + len(definitions) or (
            code.split("-")[0] != list(definitions)[row - 56].split("-")[0]
        ) else THIN
        for column in range(1, 6):
            scope_sheet.cell(row, column).border = Border(left=THIN, right=THIN, top=THIN, bottom=bottom)
        scope_sheet.row_dimensions[row].height = 28
    for column in range(1, 6):
        scope_sheet.cell(56, column).border = Border(left=THIN, right=THIN, top=MEDIUM, bottom=MEDIUM)
    report = book["7_보고서 산출"]
    report.freeze_panes = "A3"
    report.print_title_rows = "1:2"
    report.sheet_format.defaultRowHeight = 24
    for row in report:
        report.row_dimensions[row[0].row].height = 24
        for cell in row:
            if isinstance(cell, MergedCell):
                continue
            alignment = copy(cell.alignment)
            alignment.vertical, alignment.wrap_text = "center", False
            alignment.shrink_to_fit = cell.row == 4 or cell.row >= 15 and 3 <= cell.column <= 7
            cell.alignment = alignment
            if cell.row >= 15:
                cell.number_format = "General"
    for row in range(5, 12):
        for column in "CDEFHIJKLM":
            report[f"{column}{row}"].number_format = "0.0"
        report[f"G{row}"].number_format = "General"
    report["F11"], report["L11"] = "-", "-"
    report["G11"] = '=COUNTIF(G5:G10,"보정")&"개 단계 보정 · "&COUNTIF(G5:G10,"보류")&"개 단계 보류"'
    report["A12"] = (
        '="보정: 괴리 ≥ "&TEXT(\'1_진단 개요\'!$B$34,"0.0")&" 및 신뢰도 "&\'1_진단 개요\'!$B$43&'
        '" 이상이면 실측 + "&TEXT(\'1_진단 개요\'!$B$35,"0.0")&'
        '", 그 외 프로세스 점수. 인터뷰 미입력 시 실측 기준 잠정. 전체 실측은 26개 항목 평균."'
    )
    report["E15"] = "단위·표시 기준"
    for row in range(16, 182):
        if report[f"A{row}"].value is not None:
            report[f"E{row}"] = "원천 기준"
    report.column_dimensions["F"].width = 45
    report.column_dimensions["G"].width = 90
    scope_sheet["C56"] = "항목"
    scope_sheet["E56"] = "확인 상태"
    scope_last = 56 + len(definitions)
    scope_sheet["A84"] = "상세 장표 공통 - 전체 26개 API 측정 범위 요약"
    for column, value in {
        "A": "p.12~p.15", "B": f"=COUNTA(B57:B{scope_last})",
        "C": f'=IF(COUNT(D57:D{scope_last})>0,MIN(D57:D{scope_last}),"필수 값 미확인")',
        "D": f'=IF(COUNT(D57:D{scope_last})>0,MAX(D57:D{scope_last}),"필수 값 미확인")',
        "E": f'=COUNTIF(E57:E{scope_last},"<>API 정보 확인")',
        "F": '=IF(E86=0,"26개 API 정보 확인 - 플랫폼별 적용 범위·단위는 원천 참조",E86&"개 항목 판정 보류 - 원천 사유 참조")',
    }.items():
        scope_sheet[f"{column}86"] = value
    for row in range(87, 90):
        for column in range(1, 7):
            cell = scope_sheet.cell(row, column)
            cell.value, cell.border, cell.fill = None, Border(), PatternFill()
    for row in (85, 86):
        for column in range(1, 7):
            scope_sheet.cell(row, column).border = Border(left=THIN, right=THIN, top=THIN, bottom=MEDIUM)
    # G8:G11 (Agent ID 보유 for non-MS platforms P4-P7) are intentionally always blank - there is
    # no collector for those platforms at all, mirroring F14's "MS Agent·후보 합계" scope (=F12).
    # G14 previously required all 7 platforms' G column non-blank, which it can never satisfy.
    platform["G14"] = "=G12"
    # B20 ("Agent ID 보유 연계") was converted to an informational readout (never literally "OK"),
    # but the template's conditional formatting still flags any non-"OK" text in B19:B20 as an
    # error - that made B20 permanently red regardless of the real data. Only B19 is a true check.
    cf = platform.conditional_formatting
    if "B19:B20" in (str(range_.sqref) for range_ in cf):
        rules = cf["B19:B20"]
        del cf["B19:B20"]
        for rule in rules:
            cf.add("B19", rule)

    # B20 ("Agent ID 보유 연계") was converted to an informational readout (never literally "OK"),
    # but the template's conditional formatting still flags any non-"OK" text in B19:B20 as an
    # error - that made B20 permanently red regardless of the real data. Only B19 is a true check.
    for rule_range in list(platform.conditional_formatting._cf_rules):
        if str(rule_range.sqref) == "B19:B20":
            rules = platform.conditional_formatting._cf_rules.pop(rule_range)
            platform.conditional_formatting._cf_rules[type(rule_range)("B19")] = rules

    # GRADES had only left/top thin borders (no right/bottom) - close the grid and add a
    # medium separator at the header and at each Demand/Design/Build/Deploy/Operate/Optimize
    # stage boundary, matching the RAW sheet's code-group border convention.
    grades = book[GRADES]
    code_rows = system_rows(book)
    stage_of = {row: code.split("-", 1)[0] for code, row in code_rows.items()}
    last_row = 4 + len(code_rows)
    for row in range(4, last_row + 1):
        bottom = MEDIUM if row == 4 or stage_of.get(row) != stage_of.get(row + 1) else THIN
        for column in range(1, grades.max_column + 1):
            cell = grades.cell(row, column)
            if isinstance(cell, MergedCell):
                continue
            cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=bottom)
    # A genuinely-collected zero total (denominator = 0, not "unknown") was showing "미확인" for
    # every share/rate in that table instead of 0 - fix the known zero-total share formulas.
    details = book["2b_세부 내역"]
    for numerator_col, denominator_cell, rows_ in (
        ("B", "$B$8", range(5, 8)), ("B", "$B$16", range(12, 16)), ("B", "$B$23", range(20, 23)),
    ):
        for row in rows_:
            details[f"C{row}"] = (
                f'=IF(AND(ISNUMBER({numerator_col}{row}),ISNUMBER({denominator_cell})),'
                f'IF({denominator_cell}>0,{numerator_col}{row}/{denominator_cell},0),"미확인")'
            )
    for row in range(28, 32):
        details[f"E{row}"] = (
            f'=IF(AND(ISNUMBER(D{row}),ISNUMBER($B${row})),IF($B${row}>0,D{row}/$B${row},0),"미확인")'
        )
    details["A1"] = "2b_세부 내역 - 전체 Agent 소유자·권한·플랫폼 상태·구성 점검"
    details["A18"] = "표3. Copilot 인벤토리 게시·채널 구성 - 사용 이력 아님"
    details["A20"], details["A21"], details["A22"] = (
        "게시 기록·채널 모두 확인", "게시 기록 있음·채널 없음", "미게시 초안",
    )
    details["A24"] = "수집 Copilot Agent 수"
    details["C24"] = None
    details["D24"] = "분류 합계 차이"
    details["E24"] = '=IF(COUNT(B23:B24)=2,B23-B24,"필수 값 미확인")'
    details["F24"] = "0이면 전체 인벤토리와 일치"
    details["A26"] = "표4. Copilot 구성 점검 - 실제 노출·조치 기록 아님"
    for column, label in zip("ABCDEF", (
        "점검 항목", "점검 대상 (건)", "조건 충족 (건)", "조건 미충족 (건)", "충족 비율", "측정 근거·한계",
    ), strict=True):
        details[f"{column}27"] = label
    for row in range(28, 33):
        details[f"D{row}"] = f'=IF(COUNT(B{row}:C{row})=2,B{row}-C{row},"필수 값 미확인")'
        details[f"E{row}"] = (
            f'=IF(COUNT(B{row}:C{row})=2,IF(B{row}>0,C{row}/B{row},0),"필수 값 미확인")'
        )
    details["A32"] = "점검 합계 (Agent 중복)"
    details["F32"] = "같은 Agent가 여러 구성 점검에 포함됩니다."
    for column, width in {"A": 40, "B": 16, "C": 16, "D": 18, "E": 17, "F": 62}.items():
        details.column_dimensions[column].width = width
    for row in range(28, 33):
        details.row_dimensions[row].height = 32
        details[f"F{row}"].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    # "승인 요청 매칭"/"Agent별 식별 비용" require a separate approval-workflow or cost-attribution
    # dataset this system never collects (criteria.yaml explicitly forbids substituting Agent 365
    # publish-approval or current inventory for them) - replace the generic "미확인" fallback with
    # the real reason so it reads as "not collected", not an unexplained gap.
    trend = book["2a_월별 추이"]
    for row in range(5, 12):
        trend[f"D{row}"] = trend[f"D{row}"].value.replace('"미확인"', '"승인 워크플로 미수집"')
        trend[f"E{row}"] = trend[f"E{row}"].value.replace('"미확인"', '"승인 워크플로 미수집"')
        trend[f"J{row}"] = trend[f"J{row}"].value.replace('"미확인"', '"비용 귀속 자료 미수집"')
        trend[f"K{row}"] = trend[f"K{row}"].value.replace('"미확인"', '"비용 귀속 자료 미수집"')
    trend["K13"] = trend["K13"].value.replace('"미확인"', '"비용 귀속 자료 미수집"')


def is_integrated(book: Workbook) -> bool:
    return all(name in book.sheetnames for name in INTEGRATED_SHEETS)


PLATFORM_CODES = ("P1", "P2", "P3", "P4", "P5", "P6", "P7")
# Power Platform environment-level items: measured per environment, shared by Copilot Studio (P1) and Agent Builder (P2).
POWER_PLATFORM_CODES = ("DM-SY-01", "DS-SY-02", "BI-SY-08")
# Entra Agent ID-level items: decomposable by real identity-to-agent correlation (Copilot entra_agent_id, Foundry blueprint tags).
IDENTITY_CODES = ("DS-SY-03", "OE-SY-16", "OE-SY-17")


def identity_platform_map(data: Collection) -> dict[str, str]:
    """Map each known Entra Agent Identity to its owning platform via real, already-collected linkage.

    Copilot Studio/Agent Builder agents carry entra_agent_id directly. Foundry agents are
    correlated through the same Blueprint-tag matching used to grade DP-SY-15 - no new heuristic.
    """
    from easm_agent.api_grading import agent_blueprint_ids

    mapping: dict[str, str] = {}
    for agent in data.copilot_agents:
        if agent.entra_agent_id and agent.platform in ("copilot_studio", "agent_builder"):
            mapping[agent.entra_agent_id.lower()] = "P1" if agent.platform == "copilot_studio" else "P2"
    foundry_agents = [agent for agent in data.agents if agent.platform == "foundry"]
    for identity in data.entra_agent_identities:
        key = identity.identity_id.lower()
        if key in mapping or not identity.blueprint_id:
            continue
        if any(identity.blueprint_id.lower() in agent_blueprint_ids(agent, data.entra_blueprints)
               for agent in foundry_agents):
            mapping[key] = "P3"
    return mapping


def platform_scope(
    code: str, ready: bool, config: dict[str, Any] | None = None,
    finding: Finding | None = None, data: Collection | None = None,
) -> dict[str, str]:
    """Classify each platform's collection status for one item.

    "A" = this item's real measurement succeeded for a platform within its scope; "X" = the item
    is within scope but the measurement genuinely failed/was incomplete (a real error, counted in
    the "측정 불가" population); platforms outside this item's measurement scope are excluded from
    the population entirely ("해당 없음") rather than counted as a failure.
    """
    if config and config.get("registry_check"):
        result = dict.fromkeys(PLATFORM_CODES, "해당 없음")
        platforms = {"P1": "copilot_studio", "P2": "agent_builder", "P3": "foundry",
                     "P5": "AmazonBedrock", "P6": "SnowflakeAI"}
        complete = bool(data and data.facts.get("agent365_registry_complete") is True)
        for platform, origin in platforms.items():
            targets = [target for target in finding.measurement.targets
                       if target.observed.get("platform") == origin] if finding and finding.measurement else []
            included = [target for target in targets if target.status != "excluded"]
            if included:
                result[platform] = "A" if complete and all(
                    target.status in ("compliant", "non_compliant") for target in included
                ) else "X"
            elif not complete:
                result[platform] = "X"
        return result
    if code in POWER_PLATFORM_CODES:
        covered = {"P1", "P2"}
    elif code in IDENTITY_CODES or (config and config.get("copilot_inventory_check")):
        covered = {"P1", "P2", "P3"}
    else:
        covered = {"P3"}
    result = {platform: ("A" if ready else "X") if platform in covered else "해당 없음"
              for platform in PLATFORM_CODES}
    if code in POWER_PLATFORM_CODES and ready and data:
        sources = {"powerplatform.environments"}
        sources.update({
            "DM-SY-01": ("powerplatform.environment_roles", "powerplatform.dataverse_roles"),
            "DS-SY-02": ("powerplatform.dlp_policies",),
            "BI-SY-08": (),
        }[code])
        if any(read.source in sources and read.portal_pages for read in data.admin_evidence):
            result["P1"] = result["P2"] = "E"
    if code in IDENTITY_CODES and data:
        builders = [agent for agent in data.copilot_agents if agent.platform == "agent_builder"]
        if builders and all(
            agent.field_status.get("entra_agent_id")
            and agent.field_status["entra_agent_id"].reason == "feature_unavailable"
            for agent in builders
        ):
            result["P2"] = "해당 없음"
    if config and config.get("copilot_inventory_check") and finding and finding.measurement:
        for platform, origin in (("P1", "copilot_studio"), ("P2", "agent_builder")):
            targets = [
                target for target in finding.measurement.targets
                if target.observed.get("platform") == origin
            ]
            if targets and all(target.status == "excluded" for target in targets):
                result[platform] = "해당 없음"
                continue
            complete = data.facts.get("copilot_inventory_complete") if data else None
            if config["copilot_inventory_check"] == "blueprint" and data:
                complete = (
                    complete is True and data.facts.get("entra_agents_complete") is True
                    and data.facts.get("entra_blueprints_complete") is True
                )
            if config["copilot_inventory_check"] == "region" and data:
                complete = complete is True and any(
                    read.source == "powerplatform.environments" and read.completed for read in data.admin_evidence
                )
            if targets:
                source_kind = "E" if any(
                    target.observed.get("review_source") == "official_admin_portal_read" for target in targets
                ) else "A"
                result[platform] = source_kind if (
                    (complete is True or complete is None and ready)
                    and all(target.status != "unknown" for target in targets)
                ) else "X"
            elif complete is True and data and not any(
                agent.platform == origin for agent in data.copilot_agents
            ):
                result[platform] = "해당 없음"
    if data and finding and finding.measurement:
        from easm_agent.agent365_grading import CONNECTED_PLATFORMS

        for provider, platform in CONNECTED_PLATFORMS.items():
            records = [row for row in data.agent365_packages if row.platform == provider]
            if not records:
                continue
            targets_ = [row for row in finding.measurement.targets
                        if row.observed.get("platform") == provider]
            result[platform] = (
                "해당 없음" if targets_ and all(row.status == "excluded" for row in targets_) else
                "A" if data.facts.get("agent365_registry_complete") is True and targets_
                and all(row.status in ("compliant", "non_compliant") for row in targets_) else "X"
            )
    return result


def platform_breakdown(
    code: str, finding: Finding | None, identity_map: dict[str, str],
    config: dict[str, Any] | None = None,
) -> dict[str, tuple[int, int] | None]:
    """Decompose one item's real measurement by platform using only already-collected linkage.

    Returns None per platform that is structurally out of this item's measurement scope
    (never a guess); counts are always a real subset of the saved numerator/denominator.
    """
    result: dict[str, tuple[int, int] | None] = dict.fromkeys(PLATFORM_CODES)
    measured = finding.measurement if finding else None
    if not measured or measured.unit != "count":
        return result
    if config and config.get("registry_check"):
        for platform, origin in (("P1", "copilot_studio"), ("P2", "agent_builder"), ("P3", "foundry"),
                                 ("P5", "AmazonBedrock"), ("P6", "SnowflakeAI")):
            targets = [target for target in measured.targets
                       if target.status != "excluded" and target.observed.get("platform") == origin]
            if targets and all(target.status in ("compliant", "non_compliant") for target in targets):
                result[platform] = (sum(target.status == "compliant" for target in targets), len(targets))
        return result
    if not measured.complete:
        return result
    if code in POWER_PLATFORM_CODES:
        if measured.numerator is not None and measured.denominator:
            result["P1"] = result["P2"] = (int(measured.numerator), int(measured.denominator))
        return result
    if config and (config.get("copilot_inventory_check") or config.get("connected_inventory_check")):
        tallies = {platform: [0, 0] for platform in ("P1", "P2", "P3", "P5", "P6")}
        for target in measured.targets:
            if target.status == "excluded":
                continue
            platform = {
                "copilot_studio": "P1", "agent_builder": "P2",
                "unclassified_copilot": None,
                "AmazonBedrock": "P5", "SnowflakeAI": "P6",
            }.get(target.observed.get("platform"), "P3")
            if platform is None:
                continue
            tallies[platform][1] += 1
            tallies[platform][0] += target.status == "compliant"
        for platform, (numerator, denominator) in tallies.items():
            result[platform] = (numerator, denominator)
        return result
    if code in IDENTITY_CODES:
        tallies = {platform: [0, 0] for platform in ("P1", "P2", "P3")}
        for target in measured.targets:
            platform = identity_map.get(target.subject.lower())
            if target.status == "excluded" or platform is None:
                continue
            tallies[platform][1] += 1
            if target.status == "compliant":
                tallies[platform][0] += 1
        for platform, (numerator, denominator) in tallies.items():
            result[platform] = (numerator, denominator)
        return result
    # Remaining items measure Azure AI resources/Foundry Agents - inherently P3-only in this system.
    if measured.numerator is not None and measured.denominator:
        result["P3"] = (int(measured.numerator), int(measured.denominator))
    return result


# 1_진단 개요 "라이선스 보유 현황" rows (B23:B30), one per product.
LICENSE_ROWS = {
    23: "m365", 24: "power_platform", 25: "entra", 26: "foundry",
    27: "defender", 28: "purview", 29: "agent365", 30: "cost_management",
}


def license_checks(data: Collection, findings: list[Finding]) -> dict[int, str | None]:
    """Cross-check the manually entered license Y/N rows against real collection evidence.

    Returns "Y"/"N" only where the evidence is unambiguous (a completed read, or a finding whose
    reason is explicitly license_missing); returns None when there is no reliable signal, so the
    manually entered value is left untouched rather than guessed.
    """
    by_code = {finding.se_code: finding for finding in findings}

    def by_facts(*keys: str) -> str | None:
        if not keys or any(data.facts.get(key) is not True for key in keys):
            return None
        return "Y"

    def by_codes(codes: tuple[str, ...]) -> str | None:
        relevant = [by_code[code] for code in codes if code in by_code
                    and not criteria_for(data)["items"].get(code, {}).get("registry_check")]
        if any(finding.reason == "license_missing" for finding in relevant):
            return "N"
        if any(finding.measurement and finding.measurement.complete for finding in relevant):
            return "Y"
        return None

    signals = {
        "m365": by_facts("copilot_inventory_complete"),
        "power_platform": by_codes(("DM-SY-01", "DS-SY-02", "BI-SY-08")),
        "entra": by_facts("entra_agents_complete", "entra_blueprints_complete"),
        "foundry": by_facts("agent_inventory_complete"),
        "defender": by_codes(("BI-SY-10", "OT-SY-25")),
        "purview": None,
        "agent365": by_facts("agent365_registry_complete"),
        "cost_management": by_codes(("OT-SY-24", "OT-SY-26")),
    }
    return {row: signals[product] for row, product in LICENSE_ROWS.items()}


def criteria_for(data: Collection) -> dict[str, Any]:
    snapshot = data.assessment_provenance.criteria_snapshot if data.assessment_provenance else {}
    return snapshot if isinstance(snapshot.get("items"), dict) and snapshot["items"] else load_criteria()


def system_rows(book: Workbook) -> dict[str, int]:
    return {
        str(book[GRADES].cell(row, 1).value): row for row in range(5, 31)
        if book[GRADES].cell(row, 1).value
    }


def copy_manual_inputs(book: Workbook, source: Path) -> None:
    manual = load_workbook(source, rich_text=True)
    if not is_integrated(manual):
        manual.close()
        raise ValueError("수동 입력 원본에는 통합 14개 시트가 필요합니다.")
    expected = {book[PROCESS].cell(row, 3).value: row for row in range(5, 59)}
    incoming = {manual[PROCESS].cell(row, 3).value: row for row in range(5, 59)}
    if len(incoming) != 54 or incoming.keys() != expected.keys():
        manual.close()
        raise ValueError("수동 입력 원본의 인터뷰 54개 코드가 템플릿과 다릅니다.")
    for code, row in expected.items():
        for column in (4, 5, 6, 7, 8, 9, 13):
            book[PROCESS].cell(row, column).value = manual[PROCESS].cell(incoming[code], column).value
    for name, first, last, columns in (
        ("5_문서 실사", 5, 66, (1, 2, 3, 4, 5, 6, 7, 10)),
        ("6_인터뷰 기록", 5, 16, (1, 2, 3, 4, 5, 6)),
    ):
        for row in range(first, last + 1):
            for column in columns:
                book[name].cell(row, column).value = manual[name].cell(row, column).value
    for address in ("B5", "B6", "B7", "B8", "B10", "B15", "B16", "B17", "B18", "B19",
                    "B34", "B35", "B36", "B37", "B38", "B39", "B40", "B41", "B43"):
        book["1_진단 개요"][address] = manual["1_진단 개요"][address].value
    # E:K "Export"/"운영자 확인" markings are never computed by this system - only a manual reviewer
    # can set them (e.g. after checking a management console export) - so they must be carried
    # forward, or populate_integrated's automated A/X/해당없음 would silently erase the override.
    for row in range(8, manual[MATRIX].max_row + 1):
        marker = manual[MATRIX][f"AA{row}"].value
        legacy = str(manual[MATRIX][f"Z{row}"].value or "")
        if marker is None and re.fullmatch(r"[E-K](?:,[E-K])*", legacy):
            marker = legacy
        automatic = set(str(marker or "").split(","))
        for column in "EFGHIJK":
            value = manual[MATRIX][f"{column}{row}"].value
            if value in ("E", "△") and column not in automatic:
                book[MATRIX][f"{column}{row}"] = value
    from easm_agent.report_layout import PLATFORM_ORDER, PLATFORM_SHEET

    reordered = manual[PLATFORM_SHEET]["G4"].value == "생성·등록·배포 확인"
    for name in INTEGRATED_SHEETS:
        for row in manual[name]:
            for source_cell in row:
                if source_cell.has_style:
                    column = source_cell.column
                    if name == PLATFORM_SHEET and reordered and column <= len(PLATFORM_ORDER):
                        column = PLATFORM_ORDER[column - 1]
                    target = book[name].cell(source_cell.row, column)
                    font = copy(target.font)
                    font.name, font.sz = source_cell.font.name, source_cell.font.sz
                    target.font = font
    manual.close()


def _unified_agent_details(book: Workbook, data: Collection) -> None:
    from easm_agent.report_agent_inventory import agent_report_records

    sheet = book["2b_세부 내역"]
    records = agent_report_records(data)
    if not records:
        sheet.print_area = "A1:F32"
        return
    sheet["A35"] = "표5. 전체 관측 Agent 상세 - MS·이기종 통합, 미확인은 사유 유지"
    sheet["A35"]._style = copy(sheet["A26"]._style)
    sheet.merge_cells("A35:M35")
    headers = (
        "플랫폼", "Agent", "ID 종류", "Agent ID (SHA256)", "모델",
        "버전", "버전 종류", "생성·등록·배포 상태", "생성 시각 (KST)", "최근 사용 (KST)",
        "지역", "소유자 기록", "비고",
    )
    for column, title in enumerate(headers, 1):
        sheet.cell(36, column, title)._style = copy(sheet["A27"]._style)
    for row, record in enumerate(records, 37):
        values = (
            record.platform, record.name, record.identifier_kind, record.identifier_sha256 or "미확인",
            record.model or "미확인", record.version or "미확인", record.version_kind,
            record.lifecycle_status,
            record.created_at.astimezone(KST).replace(tzinfo=None) if record.created_at else "미확인",
            record.last_used_at.astimezone(KST).replace(tzinfo=None) if record.last_used_at else "미확인",
            record.region or "미확인",
            "있음" if record.owner_present is True else "없음" if record.owner_present is False else "미확인",
            record.lifecycle_basis,
        )
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row, column)
            cell._style = copy(sheet["B28"]._style)
            cell.value = redact(value)
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
            if column in (9, 10) and not isinstance(value, str):
                cell.number_format = EXTRACTED_FORMAT
        sheet.cell(row, 2).comment = Comment("증적: " + "; ".join(record.evidence_refs), "EASM")
        sheet.cell(row, 8).comment = Comment(record.lifecycle_basis, "EASM")
        sheet.cell(row, 14, int(record.lifecycle_confirmed) if record.lifecycle_confirmed is not None else None)
    sheet["N36"] = "easm_lifecycle_confirmed"
    sheet.column_dimensions["N"].hidden = True
    sheet.print_area = f"A1:M{max(36, 36 + len(records))}"


def populate_integrated(book: Workbook, data: Collection, findings: list[Finding]) -> dict[str, int]:
    """Write observed values only; nulls stay blank with explicit reasons."""
    definitions = criteria_for(data)["items"]
    rows = system_rows(book)
    if set(rows) != set(load_criteria()["items"]):
        raise ValueError("통합 템플릿의 SY 26개 코드가 기준과 다릅니다.")
    if len({finding.se_code for finding in findings}) != len(findings):
        raise ValueError("수집 결과의 SY 코드가 중복되었습니다.")
    if any(finding.se_code not in rows for finding in findings):
        raise ValueError("평가 결과 템플릿에 없는 SY 코드가 수집 결과에 포함되었습니다.")
    from easm_agent.report_agent_inventory import agent_report_records, monthly_inventory_cost
    from easm_agent.report_excel import readable
    from easm_agent.report_template import collection_method

    format_integrated_workbook(book, definitions)
    by_code = {finding.se_code: finding for finding in findings}
    observed_records = agent_report_records(data)
    if definitions["DM-SY-01"].get("registry_check"):
        book[GUIDE]["A2"] = (
            SHEET_GUIDES[GUIDE] + " MS·이기종 공통 항목은 Agent 365 등록부 기준이며 "
            "등록부와 관측 인벤토리의 대상 범위를 구분합니다."
        )
        book[MATRIX]["A2"] = (
            SHEET_GUIDES[MATRIX] + " 공통 항목은 MS·이기종 모두 Agent 365 등록부 기준. "
            "상단 관측 Agent 수와 항목별 등록 패키지 분모를 구분합니다."
        )
    instant = data.collected_at.astimezone(UTC).isoformat()
    extracted = data.collected_at.astimezone(KST).replace(tzinfo=None)
    book[RAW]["L2"] = instant

    def put(name: str, address: str, value: Any) -> None:
        cell = book[name][address]
        cell.value = redact(value)
        if cell.fill.fgColor.type == "rgb" and cell.fill.fgColor.rgb[-6:] in ("FFF2CC", "FFC000"):
            cell.fill = copy(YELLOW)

    put("1_진단 개요", "B9", extracted)
    if definitions["DM-SY-01"].get("registry_check"):
        book["1_진단 개요"]["B9"].comment = Comment(
            "기본 수집 시각입니다. Agent 365 새 조회 시각은 각 공통 항목의 RAW 추출 일시와 증적을 참조합니다. "
            "이전 Azure·Copilot 증적을 새로 수집한 것으로 표시하지 않습니다.", "EASM")
    book["1_진단 개요"]["B9"].number_format = EXTRACTED_FORMAT
    put("1_진단 개요", "B11", "EASM 자동수집 · 인터뷰")
    put("1_진단 개요", "B12", len(data.evidence_sources))
    put("1_진단 개요", "A14", "생성·등록·배포 확인 Agent 수")
    put("1_진단 개요", "B14", '=IF(COUNT(\'1a_플랫폼 기준\'!P5:P11)=0,"미확인",'
        'SUM(\'1a_플랫폼 기준\'!P5:P11))')
    put("1_진단 개요", "C14", "실행·채널 게시 별도")
    # Cross-check manually entered license possession (Y/N) against real collection evidence:
    # override only when clear evidence exists (a completed read vs a license_missing reason);
    # otherwise leave the existing manual entry untouched.
    license_overrides = license_checks(data, findings)
    for row, verdict in license_overrides.items():
        if verdict is not None:
            put("1_진단 개요", f"B{row}", verdict)
    # The "연계 · 검증" cross-check compared two genuinely different populations (G14 = all MS
    # platforms' Agent ID holders vs DP-SY-15 = Azure Blueprint-linked Foundry agents only), so it
    # could never resolve to "OK" by design - replaced with an informational, non-judgmental readout.
    dp_sy_15_row = rows.get("DP-SY-15")
    if dp_sy_15_row is not None:
        dp_sy_15_raw_row = 5 + (dp_sy_15_row - 5) * 2
        platform_sheet = book["1a_플랫폼 기준"]
        platform_sheet["B20"] = (
            f'="G14 "&$G$14&"건 · DP-SY-15 "&\'{RAW}\'!$F${dp_sy_15_raw_row}&"건 (참고용, 범위 다름)"'
        )
        platform_sheet["D20"] = (
            f"G14(플랫폼별 원본 Agent 식별자 확인 수 합계)와 {RAW} DP-SY-15 "
            f"'{definitions['DP-SY-15']['title']}'(F{dp_sy_15_raw_row})는 보유·연결 확인의 조건과 모집단이 "
            "다른 별도 지표입니다. Agent Builder의 신원 필드 미적용은 실패로 보지 않습니다."
        )
    identity_map = identity_platform_map(data)
    low_confidence_rows: list[int] = []
    for code, row in rows.items():
        finding = by_code.get(code)
        config = definitions.get(code)
        measured = finding.measurement if finding else None
        first = 5 + (row - 5) * 2
        ready = bool(
            finding and measured and measured.complete and finding.reason is None
            and finding.metric_value is not None and measured.numerator is not None
            and measured.denominator is not None and measured.denominator > 0
        )
        if ready and not math.isclose(measured.numerator / measured.denominator, finding.metric_value):
            raise ValueError(f"{code}: 충족률과 분자·분모가 일치하지 않습니다.")
        note = (
            "승인 관리자 읽기 증적 기준" if code in ("DM-SY-01", "DS-SY-02", "BI-SY-08") else
            "동일 통화 비용 기준" if measured and measured.unit == "amount" else "API 조회 범위 기준"
        ) if ready else readable(finding.reason if finding and finding.reason else "not_found")
        unit = measured.unit if measured else None
        currency = measured.currency if measured else None
        display_unit = _unit_label(unit, currency)
        observations = [data.collected_at]
        if config and (config.get("connected_inventory_check") or config.get("registry_check")):
            observed = timestamp(data.facts.get("agent365_collected_at"))
            if observed is not None:
                observations.append(observed)
        if (code in POWER_PLATFORM_CODES and not (config and config.get("registry_check"))) \
                or config and config.get("copilot_inventory_check") == "region":
            sources = {"powerplatform.environments"}
            if code == "DM-SY-01":
                sources.update(("powerplatform.environment_roles", "powerplatform.dataverse_roles"))
            elif code == "DS-SY-02":
                sources.add("powerplatform.dlp_policies")
            observations.extend(read.observed_at for read in data.admin_evidence if read.source in sources)
        if config and config.get("copilot_inventory_check"):
            observations.extend(
                observed_instant for status in data.facts.get("copilot_inventory_status", [])
                if (observed_instant := timestamp(status.get("observed_at"))) is not None
            )
            if config["copilot_inventory_check"] == "evaluation":
                observations.extend(
                    review.observed_at for review in data.copilot_reviews
                    if finding and set(review.evidence_refs) & set(finding.evidence_refs)
                )
        row_extracted = max(observations).astimezone(KST).replace(tzinfo=None)
        for offset, value in enumerate((
            measured.numerator if ready else None, measured.denominator if ready else None,
        )):
            number = first + offset
            put(RAW, f"F{number}", value)
            put(RAW, f"I{number}", row_extracted)
            put(RAW, f"J{number}", "EASM 자동화 모듈")
            put(RAW, f"K{number}", note)
            put(RAW, f"M{number}", unit)
            put(RAW, f"N{number}", currency)
            amount = unit == "amount"
            book[RAW][f"F{number}"].number_format = (
                "General" if amount or value is not None and not float(value).is_integer() else "#,##0"
            )
            if config:
                put(RAW, f"D{number}", config["title"] if offset == 0 else None)
                method = collection_method(code, config)
                if not config.get("registry_check") and any(
                    package.platform in ("AmazonBedrock", "SnowflakeAI") for package in data.agent365_packages
                ):
                    method += "\n이기종: Agent 365 → Registry → Agent 상세에서 항목 필드 확인"
                put(RAW, f"H{number}", method if offset == 0 else None)
                if offset == 0:
                    book[RAW].row_dimensions[number].height = 34
                    summaries = [
                        {"platform": target.observed.get("platform", "Azure"),
                         "status": target.status, "values": target.observed, "reason": target.reason}
                        for target in measured.targets
                    ] if measured else []
                    comment = config["limit"] + "\n통합 대상별 관측:\n" + json.dumps(
                        redact(summaries), ensure_ascii=False, default=str,
                    )
                    book[RAW][f"D{number}"].comment = Comment(
                        comment if len(comment) <= 30000 else config["limit"] + "\n전체 대상별 값은 2b·수집결과 근거·원본 JSON 참조",
                        "EASM",
                    )
            put(RAW, f"G{number}", display_unit)
        # A saved grade is authoritative, even when its historical measurement is absent.
        score = int(finding.level[1:]) if finding and finding.level != "N/A" else None
        put(GRADES, f"U{row}", score)
        put(GRADES, f"V{row}", finding.metric_value if ready else None)
        put(GRADES, f"W{row}", "Y" if finding and finding.level != "N/A" else "N")
        put(GRADES, f"X{row}", finding.reason if finding else "not_found")
        put(GRADES, f"M{row}", (
            config["levels"][finding.level] if ready and config else
            f"저장된 {finding.level} 판정 - 측정값 확인 필요" if finding and finding.level != "N/A" else note
        ))
        put(GRADES, f"Y{row}", finding.next_step if finding else "수집 대상·권한 확인 후 재수집")
        put(GRADES, f"J{row}", None)
        if config:
            put(GRADES, f"D{row}", config["title"])
            put(GRADES, f"F{row}", config["levels"]["L3"])
            for column, text in zip(range(16, 21), config["levels"].values(), strict=True):
                book[GRADES].cell(row, column, text)
            rules = {rule["level"]: rule["when"]["coverage"] for rule in config["rules"]}
            put(GRADES, f"N{row}", rules["L3"]["gte"])
            put(GRADES, f"O{row}", rules["L4"]["gte"])
        matrix_row = row + 3
        put(MATRIX, f"M{matrix_row}", measured.denominator if ready else None)
        put(MATRIX, f"N{matrix_row}", measured.numerator if ready else None)
        put(MATRIX, f"O{matrix_row}", 1 if ready else None)
        put(MATRIX, f"S{matrix_row}", "높음" if ready else "미확인")
        put(MATRIX, f"T{matrix_row}", "API 정보 확인" if ready else "판정 보류")
        put(MATRIX, f"W{matrix_row}", "API 판정" if score is not None else "판정 보류")
        put(MATRIX, f"P{matrix_row}", (
            sum(target.status == "unknown" for target in measured.targets) if measured else None
        ))
        if config:
            put(MATRIX, f"B{matrix_row}", config["title"])
            put(MATRIX, f"D{matrix_row}", config["denominator"])
            breakdown = platform_breakdown(code, finding, identity_map, config)
            unattributed = unattributed_total = 0
            if code in IDENTITY_CODES and measured:
                tracked = [target for target in measured.targets if target.status != "excluded"]
                unattributed_total = sum(identity_map.get(target.subject.lower()) is None for target in tracked)
                unattributed = sum(
                    target.status == "compliant" and identity_map.get(target.subject.lower()) is None
                    for target in tracked
                )
            if config.get("copilot_inventory_check") and measured:
                tracked = [target for target in measured.targets if target.status != "excluded"
                           and target.observed.get("platform") == "unclassified_copilot"]
                unattributed_total = len(tracked)
                unattributed = sum(target.status == "compliant" for target in tracked)
            copilot_breakdown = " · ".join(
                f"{platform} {breakdown[platform][0]}/{breakdown[platform][1]}"
                for platform in PLATFORM_CODES if breakdown[platform]
            )
            copilot_breakdown += (
                f" · 도구 미분류 {unattributed}/{unattributed_total}" if unattributed_total else ""
            )
            copilot_notes = {
                "owner": "Copilot 소유자 존재 / Azure 4개 메타데이터",
                "authentication": "Copilot 인증 방식 / Azure 관리 ID·역할·키",
                "model": "Copilot 모델·오케스트레이션 / Azure 배포 모델 구성",
                "access": "Copilot 인증·공유 제한 / Azure 인바운드 경계",
                "connector_consent": "Copilot 사용자 동의 / MCP 실행 승인 (다른 통제)",
                "security": "Copilot 위험 구성 3종 / Azure 보안 권고",
                "publishing": "Copilot 게시 시각 / Foundry 버전 (승인 아님)",
                "evaluation": "Copilot 기존 평가 GET(응답 검증 범위) 또는 실제 검토 화면의 평가 없음 / Foundry 프로젝트",
                "blueprint": "Copilot Studio 실제 Agent ID 연결 / Azure 청사진 대조",
                "region": "Copilot 관리 환경 지역만 / Azure 지역·workspace 보존",
            }
            excluded_reasons = sorted({
                target.reason for target in measured.targets
                if target.status == "excluded" and target.reason
            }) if measured else []
            copilot_note = copilot_notes.get(config.get("copilot_inventory_check"), "")
            if excluded_reasons:
                copilot_note += " - " + " · ".join(excluded_reasons)
            connected_check = config.get("connected_inventory_check")
            put(MATRIX, f"Q{matrix_row}", (
                "Agent 365 공통 등록부 - " + copilot_breakdown + " - " + config["limit"]
                if config.get("registry_check") else
                "P1·P2 Power Platform 환경 공통 측정 (Agent 단위 분해 아님, P3~P7 해당 없음)"
                if code in POWER_PLATFORM_CODES else
                copilot_note + " - " + copilot_breakdown
                if config.get("copilot_inventory_check") else
                "플랫폼별 원본 필드 충족률 - " + copilot_breakdown
                if connected_check else
                "Azure AI·Foundry 전용 측정 범위 (P3만 해당, 나머지 플랫폼 해당 없음)"
                if code not in IDENTITY_CODES else
                "Entra Agent ID 귀속 기준 플랫폼별 분해 (Agent Builder 신원 필드 미적용, P4~P7은 현재 진단 범위 밖)"
                + (f" - {breakdown_text}" if (breakdown_text := " · ".join(
                    f"{platform} {breakdown[platform][0]}/{breakdown[platform][1]}"
                    for platform in ("P1", "P2", "P3") if breakdown[platform]
                )) else "")
                + (f" - 플랫폼 미귀속 {unattributed_total}건 중 충족 {unattributed}건은 합계에서 제외"
                   if unattributed_total else "")
            ))
        scope_map = platform_scope(code, ready, config, finding, data)
        automatic_exports = []
        for column, platform in zip("EFGHIJK", PLATFORM_CODES, strict=True):
            existing = book[MATRIX][f"{column}{matrix_row}"].value
            value = existing if existing in ("E", "△") else scope_map[platform]
            put(MATRIX, f"{column}{matrix_row}", value)
            if existing not in ("E", "△") and value == "E":
                automatic_exports.append(column)
        put(MATRIX, f"AA{matrix_row}", ",".join(automatic_exports) or None)
        put(MATRIX, f"Z{matrix_row}", f'=A{matrix_row}&" "&B{matrix_row}')
        external = [
            target for target in measured.targets
            if target.observed.get("source") == "agent365_catalog"
        ] if measured else []
        if external:
            external_note = (
                "Agent 365 등록 패키지 분기: " + config.get("connected_inventory_check", "필수 필드 미제공")
                + " - 원본 플랫폼 통제 실효성·실행 이력으로 추론하지 않음"
            )
            reasons = sorted({target.reason for target in external if target.reason})
            if reasons:
                external_note += " - " + " · ".join(reasons)
            put(MATRIX, f"Q{matrix_row}", str(book[MATRIX][f"Q{matrix_row}"].value or "")
                + " · P5·P6 " + external_note)
        put(MATRIX, f"L{matrix_row}", f'=COUNTIF(E{matrix_row}:K{matrix_row},"A")')
        scope = finding.scope if finding else None
        put(MATRIX, f"R{matrix_row}", {
            "partial": "일부 범위", "in_scope": "진단 범위", "out_of_scope": "범위 밖",
        }.get(scope or "", "미확인"))
        if not ready:
            low_confidence_rows.append(matrix_row)
    # p.9 III "항목별 측정 범위 · 신뢰도" table surfaces up to the first 10 non-"높음" rows, in order.
    for rank, matrix_row in enumerate(low_confidence_rows[:10], 1):
        put(MATRIX, f"X{matrix_row}", rank)

    copilot_complete = data.facts.get("copilot_inventory_complete") is True
    inventory_complete = data.facts.get("agent_inventory_complete") is True
    for row, records, complete in (
        (5, [agent for agent in data.copilot_agents if agent.platform == "copilot_studio"], copilot_complete),
        (6, [agent for agent in data.copilot_agents if agent.platform == "agent_builder"], copilot_complete),
        (7, [agent for agent in data.agents if agent.platform == "foundry"], inventory_complete),
    ):
        put("1a_플랫폼 기준", f"F{row}", len(records) if complete else None)
        linked: int | float | None = None
        if row < 7 and complete:
            linked = sum(bool(agent.entra_agent_id) for agent in records)
        elif row == 7:
            finding = by_code.get("DP-SY-15")
            if finding and finding.measurement and finding.measurement.complete:
                from easm_agent.api_grading import agent_has_entra_identity

                linked = sum(agent_has_entra_identity(agent, data.entra_blueprints) for agent in records)
        put("1a_플랫폼 기준", f"G{row}", linked)

    from easm_agent.agent365_grading import CONNECTED_PLATFORMS

    external_packages = [p for p in data.agent365_packages if p.platform in CONNECTED_PLATFORMS]
    if external_packages:
        for provider, row, label in (
            ("AmazonBedrock", 9, "Amazon Bedrock Classic·AgentCore"),
            ("SnowflakeAI", 10, "Snowflake Cortex Agents"),
        ):
            packages = [p for p in external_packages if p.platform == provider]
            put("1a_플랫폼 기준", f"B{row}", label)
            put("1a_플랫폼 기준", f"D{row}", "Agent 365 API")
            put("1a_플랫폼 기준", f"E{row}", "동기화된 등록 패키지 목록·상세 (고유 Agent 대사와 구분)")
            put("1a_플랫폼 기준", f"F{row}", len(packages)
                if data.facts.get("agent365_registry_complete") is True else None)
            put("1a_플랫폼 기준", f"G{row}", len(packages)
                if packages and data.facts.get("agent365_registry_complete") is True
                and all(p.connected_metadata.source_agent_id_sha256 for p in packages) else None)
        for column in "FG":
            put("1a_플랫폼 기준", f"{column}13",
                f'=IF(COUNT({column}9:{column}10)=2,SUM({column}9:{column}10),"필수 값 미확인")')
        put("1a_플랫폼 기준", "F14", "=SUM(F12,F13)")
        put("1a_플랫폼 기준", "G14",
            '=IF(COUNT(G12:G13)=2,SUM(G12:G13),"미확인")')
        put("1a_플랫폼 기준", "A14", "관측 Agent·등록 기록 합계")
        put("1a_플랫폼 기준", "F4", "Agent·등록 패키지 수")
        put("1_진단 개요", "A13", "관측 Agent·등록 패키지·후보 수")
        put("1_진단 개요", "C13", "등록 패키지는 고유 Agent·활성 Agent 수가 아님")

    platform_sheet = book["1a_플랫폼 기준"]
    entra_counts = {row: platform_sheet[f"G{row}"].value for row in (5, 6, 7)}
    platform_sheet["G4"] = "Agent ID 보유"
    platform_sheet.column_dimensions["G"].width = 23
    put(MATRIX, "D5", "Agent ID 보유")
    for column, title in (("O", "Entra Agent ID 보유"), ("P", "생성·등록·배포 확인"), ("Q", "미게시·미확인")):
        platform_sheet[f"{column}4"] = title
        platform_sheet[f"{column}4"]._style = copy(platform_sheet["F4"]._style)
        platform_sheet.column_dimensions[column].width = 22
        for row in range(5, 15):
            platform_sheet[f"{column}{row}"]._style = copy(platform_sheet[f"F{row}"]._style)
            platform_sheet[f"{column}{row}"] = None
    for row, origin in ((5, "copilot_studio"), (6, "agent_builder")):
        records = [agent for agent in data.copilot_agents if agent.platform == origin]
        statuses = [record for record in observed_records if record.platform == origin]
        if copilot_complete:
            put("1a_플랫폼 기준", f"G{row}", sum(bool(agent.agent_id) for agent in records))
            put("1a_플랫폼 기준", f"O{row}", entra_counts[row])
            put("1a_플랫폼 기준", f"P{row}", sum(record.lifecycle_confirmed is True for record in statuses))
            put("1a_플랫폼 기준", f"Q{row}", sum(record.lifecycle_confirmed is not True for record in statuses))
    put("1a_플랫폼 기준", "E7", "Foundry Agent·Entra 읽기")
    if inventory_complete:
        put("1a_플랫폼 기준", "G7", sum(bool(agent.agent_id) for agent in data.agents))
        put("1a_플랫폼 기준", "O7", entra_counts[7])
        statuses = [record for record in observed_records if record.platform in {agent.platform for agent in data.agents}]
        put("1a_플랫폼 기준", "P7", sum(record.lifecycle_confirmed is True for record in statuses))
        put("1a_플랫폼 기준", "Q7", sum(record.lifecycle_confirmed is not True for record in statuses))
    for provider, row in (("AmazonBedrock", 9), ("SnowflakeAI", 10)):
        packages = [package for package in external_packages if package.platform == provider]
        statuses = [record for record in observed_records if record.platform == provider]
        if packages and data.facts.get("agent365_registry_complete") is True:
            put("1a_플랫폼 기준", f"O{row}", sum(bool(package.agent_identity_id) for package in packages)
                if all(package.agent_identity_id for package in packages) else "미제공")
            put("1a_플랫폼 기준", f"P{row}", sum(record.lifecycle_confirmed is True for record in statuses))
            put("1a_플랫폼 기준", f"Q{row}", sum(record.lifecycle_confirmed is not True for record in statuses))
    for column in "PQ":
        for row, start, end in ((12, 5, 7), (13, 9, 10), (14, 5, 11)):
            put("1a_플랫폼 기준", f"{column}{row}", f"=SUM({column}{start}:{column}{end})")
    for row, start, end in ((12, 5, 7), (13, 9, 10), (14, 5, 11)):
        cells = f"O{start}:O{end}"
        if row == 14:
            put("1a_플랫폼 기준", "O14", '=IF(COUNT(O12:O13)=2,SUM(O12:O13),"미확인")')
        else:
            put("1a_플랫폼 기준", f"O{row}", f'=IF(COUNT({cells})=ROWS({cells}),SUM({cells}),"미제공·미확인")')
    platform_sheet["G4"].comment = Comment(
        "플랫폼 원본 ID 기준: Copilot Bot ID, Foundry Agent ID, "
        "AWS·Snowflake SourceAgentId. 서로 다른 ID 체계의 확인 기록 합계이며 전사 고유 ID 수가 아닙니다. "
        "외부 ID는 Agent 365에서 확인하고 SHA256으로 보존합니다.", "EASM")
    platform_sheet["O4"].comment = Comment("Entra Agent ID만 별도 집계. 플랫폼 원본 ID로 대체하지 않습니다.", "EASM")
    platform_sheet["P4"].comment = Comment(
        "Foundry는 생성·등록, Copilot은 게시 시각, 이기종은 Agent 365 원본 ID 연결 기준입니다. "
        "서로 다른 플랫폼 구성 관측이며 공통 실행 성공·운영 실효성을 뜻하지 않습니다.", "EASM")
    platform_sheet["Q4"].comment = Comment("현재 관측 대상 중 미게시 또는 플랫폼 상태 미확인 수. 미수집 플랫폼은 모집단에서 제외합니다.", "EASM")
    platform_sheet.print_area = "A1:Q21"
    _unified_agent_details(book, data)
    put("7_보고서 산출", "C108", "BI-SY-12 Agent 버전 식별")


    records = observed_records
    current_cost = monthly_inventory_cost(data)
    metrics = {metric.key: metric for metric in supplemental_metrics(data, criteria_for(data))}
    history = next((entry for entry in data.report_evidence if entry.code == "OT-SY-34"), None)
    months = _months(history.period_end if history and history.period_end else data.collected_at, 6)
    registry_ready = data.facts.get("agent365_registry_complete") is True
    for row, month in enumerate(months, 5):
        put("2a_월별 추이", f"A{row}", month.replace(tzinfo=None))
        put("2a_월별 추이", f"G{row}", month.replace(tzinfo=None))
        detail_end = 36 + len(records)
        dates = f"'2b_세부 내역'!$I$37:$I${detail_end}"
        states = f"'2b_세부 내역'!$N$37:$N${detail_end}"
        if records:
            put("2a_월별 추이", f"B{row}",
                f'=COUNTIFS({dates},">="&A{row},{dates},"<"&EDATE(A{row},1))')
            put("2a_월별 추이", f"C{row}",
                f'=COUNTIFS({dates},">="&A{row},{dates},"<"&EDATE(A{row},1),{states},1)')
        else:
            put("2a_월별 추이", f"B{row}", None)
            put("2a_월별 추이", f"C{row}", None)
        cost = metrics.get("cost.month." + month.strftime("%Y%m") + ".total")
        put("2a_월별 추이", f"H{row}", cost.value if cost else None)
        matched = 0 if cost and cost.value == 0 else current_cost.get(month.strftime("%Y%m"))
        put("2a_월별 추이", f"I{row}", matched)
    currency = metrics.get("cost.currency")
    put("2a_월별 추이", "A3", "표1. 통합 관측 대상 생성월·플랫폼별 구성 상태")
    for cell, label in (
        ("B4", "생성 시각 확인 대상"), ("C4", "생성·등록·배포 확인"), ("D4", "미게시·상태 미확인"),
        ("E4", "상태 확인 비율"), ("I4", "현재 Agent 매칭 금액"), ("J4", "단일 매칭 불가·미확인"), ("K4", "현재 매칭 비율"),
    ):
        put("2a_월별 추이", cell, label)
    put("2a_월별 추이", "A13", "생성 시각 미확인 대상")
    put("2a_월별 추이", "B13",
        f'=COUNTIF(\'2b_세부 내역\'!I37:I{36 + len(records)},"미확인")' if records else None)
    put("2a_월별 추이", "G3", "표2. Azure AI 리소스 비용 (" + (
        str(currency.value) if currency and currency.value is not None else "통화 미확인"
    ) + ") - 현재 인벤토리 매칭, 과거 귀속·이기종 비용 아님")
    trend = book["2a_월별 추이"]
    trend["A3"].comment = Comment(
        "현재 생성월 분포와 플랫폼별 구성 상태를 대조합니다. Foundry 생성·등록, Copilot 게시, Agent 365 원본 ID 연결 기준입니다. "
        "과거 게시·생성 승인·실행 성공 이력이 아닙니다. 생성일 미확인 대상은 별도 집계합니다.", "EASM")
    trend["I4"].comment = Comment(
        "동일 일자·리소스·통화·금액의 실제 비용 행과 OT-SY-24의 현재 인벤토리 단일 Agent 매칭을 대조한 금액입니다. 과거 소유·배포 시점의 비용 귀속 증명은 아닙니다. AWS·Snowflake 비용은 Agent 365에서 미제공입니다.", "EASM")
    for row in range(5, 12):
        trend[f"D{row}"] = f'=IF(COUNT(B{row}:C{row})=2,B{row}-C{row},"필수 값 미확인")'
        trend[f"E{row}"] = f'=IF(COUNT(B{row}:C{row})=2,IF(B{row}>0,C{row}/B{row},0),"필수 값 미확인")'
        trend[f"J{row}"] = f'=IF(COUNT(H{row}:I{row})=2,H{row}-I{row},"비용 매칭 근거 미확인")'
        trend[f"K{row}"] = f'=IF(COUNT(H{row}:I{row})=2,IF(H{row}>0,I{row}/H{row},0),"비용 매칭 근거 미확인")'
    trend["C11"] = '=IF(COUNT(C5:C10)=6,SUM(C5:C10),"필수 값 미확인")'
    trend["I11"] = '=IF(COUNT(I5:I10)=6,SUM(I5:I10),"비용 매칭 근거 미확인")'
    trend["K13"] = '=IF(COUNT(H10:I10)=2,IF(H10>0,(H10-I10)/H10,0),"비용 매칭 근거 미확인")'
    buckets = [sum(record.lifecycle_confirmed is value for record in records) for value in (True, False, None)]
    publication_known = (not data.agents or inventory_complete) and (not data.copilot_agents or copilot_complete) and (
        not external_packages or registry_ready)
    details = book["2b_세부 내역"]
    details["A3"] = "표1. 전체 관측 대상 소유자 기록"
    for row, value, label in (
        (5, True, "소유자 기록 있음"), (6, False, "소유자 기록 없음"), (7, None, "소유자 기록 미확인"),
    ):
        put("2b_세부 내역", f"A{row}", label)
        put("2b_세부 내역", f"B{row}", sum(record.owner_present is value for record in records) if publication_known else None)
    details["A17"] = f"표2는 Entra 앱 역할 조회 범위 {len(data.entra_agent_identities)}개 - 이기종 권한으로 추정하지 않음"
    details.merge_cells("A17:F17")
    details["A18"] = "표3. 생성·등록·배포 상태 - 실행·사용 이력 아님"
    for row, label in enumerate(("생성·등록·배포 확인", "미게시 확인", "플랫폼 상태 미확인"), 20):
        put("2b_세부 내역", f"A{row}", label)
    for row, value in enumerate(buckets, 20):
        put("2b_세부 내역", f"B{row}", value if publication_known else None)
    put("2b_세부 내역", "A24", "전체 관측 대상 수")
    put("2b_세부 내역", "B24", len(records) if publication_known else None)
    put("2b_세부 내역", "F24", (
        "0이면 통합 관측 대상과 일치" if publication_known else "전체 플랫폼 인벤토리 조회 미완료"
    ))
    common_registry = bool(definitions["OE-SY-16"].get("registry_check"))
    if common_registry:
        details["A3"] = "표1. 관측 Agent 인벤토리 소유자 - 공통 등록부 평가와 범위 구분"
    for row, code, label, limitation in (
        (28, "OE-SY-16" if common_registry else "BI-SY-13", "소유자 존재",
         "소유자 존재만 확인. 재직·스폰서·책임 승인 아님"),
        (29, "OE-SY-19", "인증 방식 구성", "명시된 인증 방식. 실제 로그인 성공 아님"),
        (30, "DS-SY-05", "인증·전체 테넌트 공유 제한", "공유 제한은 네트워크 격리·공유 승인 아님"),
        (31, "BI-SY-10", "인증·공유·커넥터 위험 구성", "위험 구성 3종 점검. 실제 노출·조치 기록 아님"),
    ):
        finding = by_code.get(code)
        measured = finding.measurement if finding else None
        targets = [
            target for target in measured.targets if target.status != "excluded"
        ] if measured else []
        complete = measured is not None and measured.complete and all(
            target.status in ("compliant", "non_compliant") for target in targets
        )
        put("2b_세부 내역", f"A{row}", label)
        put("2b_세부 내역", f"B{row}", len(targets) if measured else None)
        put("2b_세부 내역", f"C{row}", sum(target.status == "compliant" for target in targets) if complete else None)
        put("2b_세부 내역", f"F{row}", code + " 통합 API 대상 (단위·조건은 항목별) - " + (
            limitation if complete else "필수 대상별 판정 증적 미확인. " + limitation
        ))
    details["A26"] = "표4. 전체 플랫폼 구성 점검 - 실제 노출·조치 기록 아님"

    report = book["7_보고서 산출"]
    for index, (code, config) in enumerate(definitions.items()):
        grade_row, report_row, raw_row = rows[code], 97 + index, 5 + index * 2
        for column, value in (
            ("A", "p.11"), ("B", "26개 항목 판정"), ("C", code + " " + config["title"]),
            ("D", f"='{GRADES}'!K{grade_row}"), ("E", "등급·충족률"),
            ("F", f"{GRADES}!K{grade_row} · H{grade_row}"),
            ("G", f'=IF(ISNUMBER(D{report_row}),"L"&TEXT(D{report_row},"0")&" · "&'
                  f'\'{GRADES}\'!H{grade_row},"N/A - 원천 판정 사유 참조")'),
        ):
            put("7_보고서 산출", f"{column}{report_row}", value)
        for column in ("A", "B"):
            report[f"{column}{report_row}"].border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        detail_row = 134 + index
        for column, value in (
            ("A", "p.11~p.15"), ("B", "항목별 원천 측정"), ("C", code + " " + config["title"]),
            ("D", f'=IF(ISNUMBER(\'{RAW}\'!F{raw_row}),\'{RAW}\'!F{raw_row},"필수 값 미확인")'),
            ("E", f"='{RAW}'!G{raw_row}"), ("F", f"{RAW}!F{raw_row}:F{raw_row+1}"),
            ("G", f'=IF(COUNT(\'{RAW}\'!F{raw_row}:F{raw_row+1})=2,'
                  f'TEXT(\'{RAW}\'!F{raw_row},"0.########")&" / "&'
                  f'TEXT(\'{RAW}\'!F{raw_row+1},"0.########")&" "&E{detail_row},"필수 값 미확인")'),
        ):
            put("7_보고서 산출", f"{column}{detail_row}", value)
        report[f"D{detail_row}"].number_format = book[RAW][f"F{raw_row}"].number_format
    for report_row, detail_row, label in (
        (166, 8, "소유자·스폰서 연결 누락"), (167, 16, "쓰기 권한 패턴 검토 후보"),
        (168, 23, "전체 관측 대상 생성·등록·배포 상태"), (169, 32, "전체 플랫폼 구성 점검 (중복 대상 포함)"),
    ):
        for column, value in (
            ("C", label), ("D", f"='2b_세부 내역'!B{detail_row}"),
            ("E", "건"), ("F", f"2b_세부 내역!B{detail_row}"),
            ("G", f'=IF(ISNUMBER(D{report_row}),TEXT(D{report_row},"0")&"건","필수 값 미확인")'),
        ):
            put("7_보고서 산출", f"{column}{report_row}", value)
    put(RAW, "O1", "easm_issue_count")
    put(RAW, "O2", len(data.issues))
    put(RAW, "P1", "easm_grading_profile")
    put(RAW, "P2", criteria_for(data)["grading_profile"])
    put(RAW, "Q1", "easm_api_evidence_reference_count")
    put(RAW, "Q2", len({ref for source in data.evidence_sources for ref in source.evidence_refs}))
    book[RAW].column_dimensions.group("L", "Q", hidden=True)
    for report_row, source in ((171, "O2"), (172, "P2")):
        put("7_보고서 산출", f"D{report_row}", f"='{RAW}'!{source}")
        put("7_보고서 산출", f"E{report_row}", "원천 값")
        put("7_보고서 산출", f"F{report_row}", f"{RAW}!{source}")
        put("7_보고서 산출", f"G{report_row}", f"=D{report_row}")
    for report_row, label, source, unit in (
        (79, "수집 항목 수", f"COUNTA('{GRADES}'!A5:A30)", "개"),
        (80, "수집 유형 수", f"COUNTA('{GRADES}'!A45:A49)", "개"),
        (81, "API 조회 원천 수", "'1_진단 개요'!B12", "개"),
        (82, "API 증적 참조 수", f"'{RAW}'!Q2", "개"),
        (83, "라이선스 Y 표기 제품 수", "COUNTIF('1_진단 개요'!B23:B30,\"Y\")", "개"),
        (84, "기본 수집 시각 (KST)", "'1_진단 개요'!B9", "KST"),
        (170, "관측 Agent·후보", "'1a_플랫폼 기준'!F14", "개"),
        (173, "SY 항목 수", f"COUNTA('{GRADES}'!A5:A30)", "개"),
        (174, "기본 수집 시각 (UTC)", f"'{RAW}'!L2", "UTC ISO 8601"),
    ):
        put("7_보고서 산출", f"C{report_row}", label)
        put("7_보고서 산출", f"D{report_row}", "=" + source)
        put("7_보고서 산출", f"E{report_row}", unit)
        put("7_보고서 산출", f"F{report_row}", source)
        put("7_보고서 산출", f"G{report_row}", f"=D{report_row}")
    report["D84"].number_format = EXTRACTED_FORMAT
    report["G84"] = '=IF(ISNUMBER(D84),TEXT(D84,"yyyy-mm-dd hh:mm:ss")&" KST","수집 시각 미확인")'
    put("7_보고서 산출", "F18", f"{GRADES}!D41")
    put("7_보고서 산출", "F19", "7_보고서 산출!I11")
    for report_row, grade_row in (*zip(range(85, 91), range(35, 41), strict=True),
                                  *zip(range(91, 96), range(45, 50), strict=True), (96, 41)):
        put("7_보고서 산출", f"F{report_row}", f"{GRADES}!D{grade_row}")
    for report_row, grade_row in zip(range(123, 128), range(54, 59), strict=True):
        put("7_보고서 산출", f"F{report_row}", f"{GRADES}!C{grade_row}")
    for report_row, trend_row in zip(range(128, 134), range(5, 11), strict=True):
        put("7_보고서 산출", f"C{report_row}",
            f'=TEXT(\'2a_월별 추이\'!A{trend_row},"yyyy-mm")&" 생성·등록·배포 확인"')
        put("7_보고서 산출", f"D{report_row}", (
            f'=IF(ISNUMBER(\'2a_월별 추이\'!C{trend_row}),\'2a_월별 추이\'!C{trend_row},"플랫폼 상태 미확인")'
        ))
        put("7_보고서 산출", f"E{report_row}", "플랫폼별 구성 확인 수")
        put("7_보고서 산출", f"F{report_row}", f"2a_월별 추이!C{trend_row}")
        put("7_보고서 산출", f"G{report_row}", f"=D{report_row}")
    for report_row, trend_row in zip(range(160, 166), range(5, 11), strict=True):
        put("7_보고서 산출", f"C{report_row}", f'=TEXT(\'2a_월별 추이\'!G{trend_row},"yyyy-mm")&" Azure AI 리소스 비용"')
        put("7_보고서 산출", f"D{report_row}", (
            f'=IF(ISNUMBER(\'2a_월별 추이\'!H{trend_row}),\'2a_월별 추이\'!H{trend_row},"비용 이력 미수집")'
        ))
        put("7_보고서 산출", f"E{report_row}", str(currency.value) if currency and currency.value else "통화 미확인")
        put("7_보고서 산출", f"F{report_row}", f"2a_월별 추이!H{trend_row}")
        put("7_보고서 산출", f"G{report_row}", f"=D{report_row}")
    for report_row, score_row in zip(range(175, 181), range(5, 11), strict=True):
        put("7_보고서 산출", f"E{report_row}", "점수 차이")
        put("7_보고서 산출", f"F{report_row}", f"7_보고서 산출!L{score_row} · G{score_row}")
        report[f"D{report_row}"].number_format = "0.0"
    put("7_보고서 산출", "E181", "수준 (1~5)")

    identities = data.entra_agent_identities
    ownership_ready = bool(identities) and data.facts.get("entra_agents_complete") is True and all(
        entry.owner_count is not None and entry.sponsor_count is not None for entry in identities
    )
    if ownership_ready:
        for row, value in (
            (5, sum(entry.owner_count == 0 and entry.sponsor_count > 0 for entry in identities)),
            (6, sum(entry.owner_count == 0 and entry.sponsor_count == 0 for entry in identities)),
            (7, sum(entry.owner_count > 0 and entry.sponsor_count == 0 for entry in identities)),
        ):
            put("2b_세부 내역", f"B{row}", value)
    permission_finding = by_code.get("OE-SY-17")
    if permission_finding and permission_finding.measurement and permission_finding.measurement.complete:
        names = [str(book["2b_세부 내역"][f"A{row}"].value) for row in range(12, 15)]
        counts = dict.fromkeys([*names, "기타"], 0)
        for identity in identities:
            if identity.overprivileged_roles:
                bucket = next((name for name in names if name in identity.overprivileged_roles), "기타")
                counts[bucket] += 1
        for row, value in enumerate(counts.values(), 12):
            put("2b_세부 내역", f"B{row}", value)

    book[GRADES].column_dimensions.group("U", "Y", hidden=True)
    book.active = book.index(book[GUIDE])
    return rows


def refresh_integrated_summary(path: Path, data: Collection) -> None:
    from easm_agent.report_interviews import result_cell_updates

    path.write_bytes(result_cell_updates(path, {"A2": SHEET_GUIDES[GUIDE]}, sheet_name=GUIDE))


def save_integrated_package(path: Path, template: bytes) -> None:
    """Preserve template-only Office parts and cache saved API grades for headless readers."""
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile

    from lxml import etree

    main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with ZipFile(BytesIO(template)) as original, ZipFile(path) as generated:
        parts = {entry.filename: generated.read(entry.filename) for entry in generated.infolist()}
        for name in original.namelist():
            if name.startswith("docMetadata/"):
                parts[name] = original.read(name)
        # Preserve sensitivity labels, if a private local template has them.
        for name, attribute in (("_rels/.rels", "Target"), ("[Content_Types].xml", "PartName")):
            root = etree.fromstring(parts[name])
            for node in etree.fromstring(original.read(name)):
                if node.get(attribute, "").lstrip("/").startswith("docMetadata/"):
                    cloned = copy(node)
                    if name.endswith(".rels"):
                        cloned.set("Id", "easmMetadata" + str(len(root)))
                    root.append(cloned)
            parts[name] = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    workbook = load_workbook(path)
    index = workbook.sheetnames.index(GRADES) + 1
    part = f"xl/worksheets/sheet{index}.xml"
    root = etree.fromstring(parts[part])
    from easm_agent.report_values import PENDING, build_report_values

    values = build_report_values(workbook)
    roots = {part: root}
    for (sheet, address), value in values.cells.items():
        sheet_part = f"xl/worksheets/sheet{workbook.sheetnames.index(sheet) + 1}.xml"
        if sheet_part not in roots:
            roots[sheet_part] = etree.fromstring(parts[sheet_part])
        sheet_root = roots[sheet_part]
        cell = sheet_root.find(f".//{main}c[@r='{address}']")
        if cell is None or cell.find(main + "f") is None:
            continue
        cached = cell.find(main + "v")
        if cached is None:
            cached = etree.SubElement(cell, main + "v")
        if isinstance(value, (int, float)):
            cell.attrib.pop("t", None)
            cached.text = str(value)
        else:
            cell.set("t", "str")
            cached.text = str(value) if value is not None else (
                "" if sheet == PROCESS and address.startswith("L") else PENDING
            )
    for name, sheet_root in roots.items():
        parts[name] = etree.tostring(sheet_root, encoding="UTF-8", xml_declaration=True)
    for name in parts:
        if name.startswith("xl/comments/") and name.endswith(".xml"):
            comments = etree.fromstring(parts[name])
            for text in comments.iter(main + "text"):
                for child in list(text):
                    if child.tag == main + "t":
                        run = etree.Element(main + "r")
                        text.replace(child, run)
                        run.append(child)
                for run in text.findall(main + "r"):
                    properties = run.find(main + "rPr")
                    if properties is None:
                        properties = etree.Element(main + "rPr")
                        run.insert(0, properties)
                    for tag, value in (("rFont", "Microsoft GothicNeo"), ("sz", "9")):
                        setting = properties.find(main + tag)
                        if setting is None:
                            setting = etree.SubElement(properties, main + tag)
                        setting.set("val", value)
            parts[name] = etree.tostring(comments, encoding="UTF-8", xml_declaration=True)
    styles = etree.fromstring(parts["xl/styles.xml"])
    font_name = workbook[RAW]["F5"].font.name
    for font in styles.findall(f"{main}fonts/{main}font"):
        name = font.find(main + "name")
        if name is not None and name.get("val") == "Arial":
            name.set("val", font_name)
    parts["xl/styles.xml"] = etree.tostring(styles, encoding="UTF-8", xml_declaration=True)
    workbook.close()
    from easm_agent.report_layout import reorder_platform_parts

    reorder_platform_parts(parts)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
