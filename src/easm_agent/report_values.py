"""PPT-first display contract: every computed display value has an Excel source cell."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from statistics import mean
from typing import Literal

from openpyxl.workbook.workbook import Workbook

from easm_agent.deck_model import AREAS, AreaScore, _score, round1

REPORT = "7_보고서 산출"
PROCESS = "4_프로세스 점수"
GRADES = "3_SE 판정"
PENDING = "확인 중"
Scalar = str | int | float | None
Cell = tuple[str, str]


@dataclass(frozen=True)
class DisplayBinding:
    page: int
    shape: int
    sheet: str
    cell: str
    format: Literal["number", "level", "count", "text"] = "number"

    @property
    def reference(self) -> Cell:
        return self.sheet, self.cell


@dataclass
class ReportValues:
    cells: dict[Cell, Scalar] = field(default_factory=dict)
    bindings: list[DisplayBinding] = field(default_factory=list)
    areas: dict[str, AreaScore] = field(default_factory=dict)
    overall: float | None = None
    overall_status: str = "판정 보류"

    def display(self, binding: DisplayBinding) -> str:
        value = self.cells.get(binding.reference)
        if value is None:
            return PENDING
        if binding.format == "text":
            return str(value)
        if not isinstance(value, (int, float)):
            return str(value)
        if binding.format == "count":
            return f"{value:g}개 단계"
        return ("L" if binding.format == "level" else "") + f"{round1(value):.1f}"

    def export(self) -> dict:
        return {
            "schema_version": 1,
            "method": "PPT display -> Excel cell -> manual inputs or saved API observations",
            "limits": "API 판정 보류를 0점으로 환산하거나 원하는 PPT 값에 맞춰 측정값을 역조작하지 않음",
            "cells": [
                {"sheet": sheet, "cell": address, "value": value}
                for (sheet, address), value in self.cells.items()
            ],
            "bindings": [
                {"slide": entry.page + 1, "shape_id": entry.shape,
                 "sheet": entry.sheet, "cell": entry.cell,
                 "format": entry.format, "display": self.display(entry)}
                for entry in self.bindings
            ],
            "system_table": [
                {"slide": 17, "shape_id": 3, "row": 1 + index % 13,
                 "column": 3 * (index // 13),
                 "code": self.cells.get((GRADES, f"A{index+5}")),
                 "excel_refs": [f"{GRADES}!A{index+5}", f"{GRADES}!D{index+5}",
                                f"{GRADES}!H{index+5}", f"{GRADES}!K{index+5}"],
                 "measurement_refs": [f"2_SE 원천데이터!F{index*2+5}",
                                      f"2_SE 원천데이터!F{index*2+6}"]}
                for index in range(26)
            ],
        }


def _average(values: list[float | int]) -> float | None:
    return mean(values) if values else None


def _numeric(book: Workbook, address: str, *, integer: bool = False) -> float:
    value = book["1_진단 개요"][address].value
    if type(value) not in (int, float) or (integer and not float(value).is_integer()):
        raise ValueError(f"1_진단 개요!{address}: 유효한 산정 기준값이 필요합니다.")
    return float(value)


def configure_calculation_formulas(book: Workbook) -> None:
    gate = f'=IF(COUNT(\'{GRADES}\'!$U$5:$U$30)=0,"판정 보류",'
    for name in (REPORT, "3a_단계 신뢰도"):
        for row in book[name]:
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith(gate):
                    cell.value = "=" + cell.value[len(gate):-1]
    for row in range(5, 31):
        book[GRADES][f"G{row}"] = f'=IF(ISNUMBER(V{row}),V{row},"{PENDING}")'
        book[GRADES][f"H{row}"] = f'=IF(ISNUMBER(G{row}),TEXT(G{row},"0.00%"),"{PENDING}")'
    for row in range(5, 11):
        score_row = row + 30
        book[GRADES][f"D{score_row}"] = (
            f'=IFERROR(AVERAGEIF($B$5:$B$30,A{score_row},$K$5:$K$30),"{PENDING}")'
        )
        for column, source in (("C", f"'{PROCESS}'!J{row+68}"), ("D", f"'{PROCESS}'!J{row+58}"),
                               ("E", f"'{GRADES}'!D{score_row}")):
            book[REPORT][f"{column}{row}"] = f"={source}"
        book[REPORT][f"F{row}"] = f'=IF(AND(ISNUMBER(D{row}),ISNUMBER(E{row})),D{row}-E{row},"{PENDING}")'
        book[REPORT][f"G{row}"] = (
            f'=IF(ISNUMBER(F{row}),IF(AND(ROUND(F{row},6)>=\'1_진단 개요\'!$B$34,'
            f'\'3a_단계 신뢰도\'!G{row}="가능"),"보정","미보정"),"보류")'
        )
        book[REPORT][f"H{row}"] = (
            f'=IF(G{row}="보정",E{row}+\'1_진단 개요\'!$B$35,'
            f'IF(ISNUMBER(D{row}),D{row},IF(ISNUMBER(E{row}),E{row},"{PENDING}")))'
        )
        for target, source in zip("IJKLM", "CDEFH", strict=True):
            book[REPORT][f"{target}{row}"] = f'=IF(ISNUMBER({source}{row}),ROUND({source}{row},1),"{PENDING}")'
        count = f'COUNTIFS(\'{GRADES}\'!$B$5:$B$30,B{row},\'{GRADES}\'!$U$5:$U$30,">=1")'
        confidence = book["3a_단계 신뢰도"]
        confidence[f"C{row}"] = f'=COUNTIF(\'{GRADES}\'!$B$5:$B$30,B{row})'
        confidence[f"D{row}"] = f'=IF(C{row}>0,{count}/C{row},"{PENDING}")'
        confidence[f"E{row}"] = (
            f'=IF(D{row}>=\'1_진단 개요\'!$B$40,"높음",'
            f'IF(D{row}>=\'1_진단 개요\'!$B$41,"보통","낮음"))'
        )
        confidence[f"F{row}"] = f'="API "&{count}&"/"&C{row}&"개 확인"'
        confidence[f"G{row}"] = (
            f'=IF(AND({count}>0,MATCH(E{row},{{"낮음","보통","높음"}},0)>='
            'MATCH(\'1_진단 개요\'!$B$43,{"낮음","보통","높음"},0)),"가능","보류")'
        )
        for target, source in zip("HIJKL", "JKLGM", strict=True):
            confidence[f"{target}{row}"] = f"='{REPORT}'!{source}{row}"
        confidence[f"M{row}"] = f'=IF(ISNUMBER(L{row}),TEXT(L{row},"0.0"),"{PENDING}")'
    book[GRADES]["D41"] = f'=IFERROR(AVERAGE(K5:K30),"{PENDING}")'
    for column in "CDH":
        book[REPORT][f"{column}11"] = f'=IFERROR(AVERAGE({column}5:{column}10),"{PENDING}")'
    book[REPORT]["E11"] = f"='{GRADES}'!D41"
    for target, source in (("I", "C"), ("J", "D"), ("K", "E"), ("M", "H")):
        book[REPORT][f"{target}11"] = f'=IF(ISNUMBER({source}11),ROUND({source}11,1),"{PENDING}")'
    book[REPORT]["D20"] = '=COUNTIF(G5:G10,"보정")'
    docs = book["5_문서 실사"]
    for row in range(5, 67):
        docs[f"I{row}"] = (
            f'=IF(D{row}="N","N",IF(AND(D{row}="Y",OR(F{row}="Y",F{row}="N"),'
            f'OR(G{row}="Y",G{row}="N"),ISNUMBER(E{row})),'
            f'IF(AND(F{row}="Y",G{row}="Y",H{row}>=0,H{row}<=\'1_진단 개요\'!$B$36),"Y","N"),"{PENDING}"))'
        )


def build_report_values(book: Workbook) -> ReportValues:
    result = ReportValues()
    caps = [_numeric(book, address, integer=True) for address in ("B37", "B38", "B39")]
    if any(not 1 <= value <= 5 for value in caps):
        raise ValueError("수동 평가 증적 상한은 1~5 정수여야 합니다.")
    gap = _numeric(book, "B34")
    addition = _numeric(book, "B35")
    high, medium = _numeric(book, "B40"), _numeric(book, "B41")
    if not 0 <= medium <= high <= 1 or gap < 0 or addition < 0:
        raise ValueError("괴리·가산·정보 확인 기준값 범위를 확인하세요.")
    minimum_name = book["1_진단 개요"]["B43"].value
    if minimum_name not in ("높음", "보통", "낮음"):
        raise ValueError("보정 적용 최소 신뢰도 기준값이 올바르지 않습니다.")
    minimum = high if minimum_name == "높음" else medium if minimum_name == "보통" else 0
    responses: dict[tuple[str, str], list[int]] = {}
    manual: dict[tuple[str, str], list[float]] = {}
    totals: dict[str, int] = {}
    for row in range(5, 59):
        code = str(book[PROCESS].cell(row, 3).value or "")
        pieces = code.split("-")
        if len(pieces) != 3 or pieces[0] not in {area[0] for area in AREAS} or pieces[1] not in ("PR", "PE", "DA", "TE"):
            raise ValueError(f"{PROCESS}!C{row}: 수동 문항 코드가 올바르지 않습니다.")
        prefix, kind = pieces[:2]
        totals[prefix] = totals.get(prefix, 0) + 1
        response = _score(book[PROCESS].cell(row, 6).value)
        cap = caps[0] if book[PROCESS].cell(row, 7).value != "Y" else (
            caps[1] if book[PROCESS].cell(row, 8).value != "Y" else
            caps[2] if book[PROCESS].cell(row, 9).value != "Y" else 5
        )
        result.cells[PROCESS, f"J{row}"] = cap if response is not None else None
        result.cells[PROCESS, f"K{row}"] = min(response, cap) if response is not None else None
        result.cells[PROCESS, f"L{row}"] = (
            "하향" if response is not None and response > cap else None
        )
        if response is not None:
            responses.setdefault((prefix, kind), []).append(response)
            manual.setdefault((prefix, kind), []).append(min(response, cap))
    for index, (_, _, _, english, _) in enumerate(AREAS):
        matching = [row for row in range(5, 59) if book[PROCESS].cell(row, 1).value == english]
        base = 83 + index
        result.cells[PROCESS, f"F{base}"] = len(matching)
        result.cells[PROCESS, f"G{base}"] = sum(
            result.cells[PROCESS, f"L{row}"] == "하향" for row in matching
        )
        for column, source_column in (("H", 7), ("I", 8), ("J", 9)):
            result.cells[PROCESS, f"{column}{base}"] = sum(
                book[PROCESS].cell(row, source_column).value == "Y" for row in matching
            )
    for column in "FGHIJ":
        result.cells[PROCESS, f"{column}89"] = sum(
            result.cells[PROCESS, f"{column}{row}"] for row in range(83, 89)
        )
    reference = book["1_진단 개요"]["B10"].value
    valid_days = _numeric(book, "B36", integer=True)
    if valid_days <= 0:
        raise ValueError("문서 유효 기간은 양수여야 합니다.")
    for row in range(5, 67):
        sheet = book["5_문서 실사"]
        submitted, changed, approved, applied = [sheet.cell(row, column).value for column in (4, 5, 6, 7)]
        age = (reference - changed).days if isinstance(reference, datetime) and isinstance(changed, datetime) else None
        result.cells["5_문서 실사", f"H{row}"] = age
        valid = (
            False if submitted == "N" else None if submitted != "Y"
            or approved not in ("Y", "N") or applied not in ("Y", "N") or age is None
            else approved == applied == "Y" and 0 <= age <= valid_days
        )
        result.cells["5_문서 실사", f"I{row}"] = "Y" if valid is True else "N" if valid is False else None
    for index, (_, _, _, english, _) in enumerate(AREAS):
        rows = [row for row in range(5, 67) if book["5_문서 실사"].cell(row, 1).value == english]
        known_submitted = all(book["5_문서 실사"].cell(row, 4).value in ("Y", "N") for row in rows)
        known_valid = all(result.cells["5_문서 실사", f"I{row}"] is not None for row in rows)
        submitted = sum(book["5_문서 실사"].cell(row, 4).value == "Y" for row in rows) if known_submitted else None
        valid = sum(result.cells["5_문서 실사", f"I{row}"] == "Y" for row in rows) if known_valid else None
        result.cells["5_문서 실사", f"D{71+index}"] = len(rows)
        result.cells["5_문서 실사", f"E{71+index}"] = submitted
        result.cells["5_문서 실사", f"F{71+index}"] = submitted / len(rows) if submitted is not None and rows else None
        result.cells["5_문서 실사", f"G{71+index}"] = valid
        result.cells["5_문서 실사", f"H{71+index}"] = valid / len(rows) if valid is not None and rows else None
    for column in ("D", "E", "G"):
        entries = [result.cells["5_문서 실사", f"{column}{row}"] for row in range(71, 77)]
        result.cells["5_문서 실사", f"{column}77"] = sum(entries) if all(value is not None for value in entries) else None
    system: dict[str, list[int]] = {}
    system_totals: dict[str, int] = {}
    group_scores: dict[str, list[int]] = {}
    grade_rows: dict[str, int] = {}
    for row in range(5, 31):
        code = str(book[GRADES].cell(row, 1).value or "")
        prefix = code[:2]
        if prefix not in totals or "-SY-" not in code:
            raise ValueError(f"{GRADES}!A{row}: SY 26개 코드가 올바르지 않습니다.")
        grade_rows[code] = row
        system_totals[prefix] = system_totals.get(prefix, 0) + 1
        score = _score(book[GRADES].cell(row, 21).value)
        ratio = book[GRADES].cell(row, 22).value if score is not None else None
        result.cells[GRADES, f"A{row}"] = code
        result.cells[GRADES, f"D{row}"] = str(book[GRADES].cell(row, 4).value or "")
        result.cells[GRADES, f"G{row}"] = ratio
        result.cells[GRADES, f"H{row}"] = f"{ratio:.2%}" if type(ratio) in (float, int) else None
        first = (row-5)*2+5
        result.cells["2_SE 원천데이터", f"F{first}"] = book["2_SE 원천데이터"].cell(first, 6).value
        result.cells["2_SE 원천데이터", f"F{first+1}"] = book["2_SE 원천데이터"].cell(first+1, 6).value
        result.cells[GRADES, f"I{row}"] = score if score is not None else "N/A"
        result.cells[GRADES, f"K{row}"] = score if score is not None else "N/A"
        if score is not None:
            system.setdefault(prefix, []).append(score)
            group_scores.setdefault(str(book[GRADES].cell(row, 3).value), []).append(score)
    raw_areas, process_areas, finals = [], [], []
    for index, (prefix, _, _, _english, _) in enumerate(AREAS):
        area = AreaScore(prefix)
        area.interview_total = totals.get(prefix, 0)
        area.interview_scored = sum(len(responses.get((prefix, kind), [])) for kind in ("PR", "PE", "DA", "TE"))
        raw_parts, capped_parts = [], []
        for column, kind in enumerate(("PR", "PE", "DA", "TE"), 6):
            raw_value = _average(responses.get((prefix, kind), []))
            capped = _average(manual.get((prefix, kind), []))
            result.cells[PROCESS, f"{chr(64 + column)}{63 + index}"] = capped
            result.cells[PROCESS, f"{chr(64 + column)}{73 + index}"] = raw_value
            area.perspectives[kind] = round1(capped) if capped is not None else None
            if raw_value is not None:
                raw_parts.append(raw_value)
            if capped is not None:
                capped_parts.append(capped)
        # Match the workbook: each present perspective has equal weight; missing ones remain provisional.
        raw_value = _average(raw_parts)
        process = _average(capped_parts)
        system_value = _average(system.get(prefix, []))
        area.interview = round1(process) if process is not None else None
        area.system = round1(system_value) if system_value is not None else None
        area.system_scored = len(system.get(prefix, []))
        area.system_total = system_totals.get(prefix, 0)
        area.perspectives["SY"] = area.system
        coverage = area.system_scored / area.system_total if area.system_total else 0
        difference = process - system_value if process is not None and system_value is not None else None
        rounded_gap = float(Decimal(str(difference)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)) if difference is not None else None
        corrected = rounded_gap is not None and rounded_gap >= gap and coverage >= minimum
        final = system_value + addition if corrected else process if process is not None else system_value
        area.final = round1(final) if final is not None else None
        area.status = (
            "인터뷰-실측 괴리" if corrected else "미보정" if difference is not None else
            "인터뷰 기준(실측 없음)" if process is not None else
            "실측 기준 잠정(인터뷰 미입력)" if system_value is not None else "판정 보류"
        )
        result.areas[prefix] = area
        if raw_value is not None:
            raw_areas.append(raw_value)
        if process is not None:
            process_areas.append(process)
        if final is not None:
            finals.append(final)
        row = index + 5
        for column, value in {
            "C": raw_value, "D": process, "E": system_value, "F": difference,
            "G": "보정" if corrected else "미보정" if difference is not None else "보류",
            "H": final, "I": round1(raw_value) if raw_value is not None else None,
            "J": area.interview, "K": area.system,
            "L": round1(difference) if difference is not None else None, "M": area.final,
        }.items():
            result.cells[REPORT, f"{column}{row}"] = value
        for base, value in ((63, process), (73, raw_value)):
            result.cells[PROCESS, f"J{base + index}"] = value
            result.cells[PROCESS, f"K{base + index}"] = round1(value) if value is not None else None
        result.cells[GRADES, f"D{35 + index}"] = system_value
        result.cells[GRADES, f"E{35 + index}"] = area.system
        result.cells[GRADES, f"C{35 + index}"] = area.system_total
        result.cells[GRADES, f"F{35 + index}"] = sum(score >= 3 for score in system.get(prefix, []))
        for column, value in {
            "C": area.system_total, "D": coverage if area.system_total else None,
            "E": "높음" if coverage >= high else "보통" if coverage >= medium else "낮음",
            "F": f"API {area.system_scored}/{area.system_total}개 확인",
            "G": "가능" if system_value is not None and coverage >= minimum else "보류",
            "H": area.interview, "I": area.system,
            "J": round1(difference) if difference is not None else None,
            "K": "보정" if corrected else "미보정" if difference is not None else "보류",
            "L": area.final, "M": f"{area.final:.1f}" if area.final is not None else PENDING,
        }.items():
            result.cells["3a_단계 신뢰도", f"{column}{row}"] = value
    result.overall = round1(mean(finals)) if finals else None
    complete = all(
        area.interview_scored == area.interview_total and area.system_scored == area.system_total
        and area.interview_total > 0 and area.system_total > 0 for area in result.areas.values()
    )
    result.overall_status = "6개 영역 집계" if complete else "잠정(미확인 영역 포함)"
    all_system = [score for scores in system.values() for score in scores]
    overall_system = _average(all_system)
    result.cells[GRADES, "D41"] = overall_system
    result.cells[GRADES, "E41"] = round1(overall_system) if overall_system is not None else None
    result.cells[GRADES, "C41"] = 26
    result.cells[GRADES, "F41"] = sum(score >= 3 for score in all_system)
    result.cells[REPORT, "D20"] = sum(area.status == "인터뷰-실측 괴리" for area in result.areas.values())
    for column, value in {
        "C": _average(raw_areas), "D": _average(process_areas), "E": overall_system,
        "H": _average(finals),
    }.items():
        result.cells[REPORT, column + "11"] = value
    for raw_column, display in (("C", "I"), ("D", "J"), ("E", "K"), ("H", "M")):
        value = result.cells[REPORT, raw_column + "11"]
        result.cells[REPORT, display + "11"] = round1(value) if isinstance(value, (int, float)) else None
    for index, group in enumerate(("T1", "T2", "T3", "T4", "T5"), 45):
        value = _average(group_scores.get(group, []))
        result.cells[GRADES, f"D{index}"] = value
        result.cells[GRADES, f"E{index}"] = round1(value) if value is not None else None
    for row, scores in ((54, [1]), (55, [2]), (56, [3]), (57, [4, 5])):
        result.cells[GRADES, f"C{row}"] = sum(score in scores for score in all_system)
    result.cells[GRADES, "C58"] = 26 - len(all_system)
    result.cells[GRADES, "C59"] = 26
    for shape, cell, kind in (
        (5, "M11", "level"), (8, "J11", "level"), (11, "K11", "level"),
        (14, "D20", "count"), (18, "I11", "level"), (21, "J11", "level"), (25, "M11", "level"),
    ):
        result.bindings.append(DisplayBinding(5, shape, REPORT, cell, kind))
    for index, (score_id, process_id, final_id, chart_id) in enumerate(zip(
        (18, 26, 33, 40, 47, 54), (19, 27, 34, 41, 48, 55),
        (20, 28, 35, 42, 49, 56), (25519, 25702, 25894, 26095, 26305, 2), strict=True,
    ), 5):
        result.bindings.extend((
            DisplayBinding(22, score_id, REPORT, f"K{index}"),
            DisplayBinding(22, process_id, REPORT, f"J{index}"),
            DisplayBinding(22, final_id, REPORT, f"M{index}"),
            DisplayBinding(15, chart_id, REPORT, f"K{index}"),
        ))
    for index, shape_id in enumerate((27152, 27404, 27665, 4, 28214), 45):
        result.bindings.append(DisplayBinding(15, shape_id, GRADES, f"E{index}", "level"))
    result.bindings.append(DisplayBinding(24, 42244, REPORT, "M11", "level"))
    return result
