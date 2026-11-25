"""Read the filled assessment workbook and compute area scores (sheet 5 rules)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from openpyxl import load_workbook

from easm_agent.report_template import CRITERIA_SHEET, RESULT_SHEET

AREAS = [
    ("DM", "1. Demand", "수요", "Demand", "Agent 필요성 정의, 사업 요구 관리"),
    ("DS", "2. Design", "설계", "Design", "업무 및 기술 설계"),
    ("BI", "3. Build", "구축", "Build", "개발 및 검증"),
    ("DP", "4. Deploy", "배포", "Deploy", "배포 및 운영 전환"),
    ("OE", "5. Operate", "운영", "Operate", "운영 및 변경 관리"),
    ("OT", "6. Optimize", "최적화", "Optimize", "현황·비용·성과 관리, 감사 및 포트폴리오"),
]
KINDS = [("PR", "Process"), ("PE", "People"), ("DA", "Data"), ("TE", "Technology"), ("SY", "System Evidence")]
LEVEL_NAMES = ["Initial", "Managed", "Defined", "Governed", "Optimized"]
TARGET_LEVEL = 3.0
CORRECTION_GAP = 1.5
CORRECTION_ADD = 1.0
THRESHOLDS = [1.0, 1.5, 2.5, 3.5, 4.5]


@dataclass
class Item:
    code: str
    area: str
    kind: str
    row: int
    text: str
    levels: list[str]
    evidence: str
    score: int | None
    status: str
    detail: str
    memo: str
    metric: str = ""

    @property
    def is_system(self) -> bool:
        return self.kind == "SY"

    @property
    def number(self) -> str:
        return self.code.rsplit("-", 1)[1]

    @property
    def title(self) -> str:
        return self.text.splitlines()[0].strip("▸ ").strip() if self.text else self.code


@dataclass
class AreaScore:
    prefix: str
    perspectives: dict[str, float | None] = field(default_factory=dict)
    interview: float | None = None
    system: float | None = None
    final: float | None = None
    status: str = "판정 보류"
    interview_scored: int = 0
    interview_total: int = 0
    system_scored: int = 0
    system_total: int = 0

    @property
    def level(self) -> int | None:
        return level_of(self.final)

    @property
    def gap(self) -> float | None:
        return None if self.final is None else round(TARGET_LEVEL - self.final, 1)


@dataclass
class Assessment:
    items: list[Item]
    areas: dict[str, AreaScore]
    overall: float | None
    overall_status: str
    summary: str
    level_names: list[str]

    @property
    def interview_items(self) -> list[Item]:
        return [item for item in self.items if not item.is_system]

    @property
    def system_items(self) -> list[Item]:
        return [item for item in self.items if item.is_system]


def round1(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def level_of(score: float | None) -> int | None:
    if score is None:
        return None
    level = 1
    for index, lower in enumerate(THRESHOLDS, 1):
        if score >= lower:
            level = index
    return level


def _score(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and float(value).is_integer() and 1 <= value <= 5:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit() and 1 <= int(value.strip()) <= 5:
        return int(value.strip())
    return None


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _average(values: list[int]) -> float | None:
    return round1(sum(values) / len(values)) if values else None


def compute_scores(items: list[Item]) -> tuple[dict[str, AreaScore], float | None, str]:
    areas: dict[str, AreaScore] = {}
    for prefix, *_ in AREAS:
        area = AreaScore(prefix)
        for kind, _label in KINDS:
            rows = [item for item in items if item.area == prefix and item.kind == kind]
            scores = [item.score for item in rows if item.score is not None]
            area.perspectives[kind] = _average(scores)
            if kind == "SY":
                area.system_total, area.system_scored = len(rows), len(scores)
            else:
                area.interview_total += len(rows)
                area.interview_scored += len(scores)
        persp = [area.perspectives[kind] for kind, _ in KINDS[:4]]
        area.system = area.perspectives["SY"]
        if all(value is not None for value in persp):
            area.interview = round1(sum(persp) / 4)
        if area.interview is not None and area.system is not None:
            if area.interview - area.system >= CORRECTION_GAP:
                area.final, area.status = round1(area.system + CORRECTION_ADD), "인터뷰-실측 괴리"
            else:
                area.final, area.status = area.interview, "미보정"
        elif area.interview is not None:
            area.final, area.status = area.interview, "인터뷰 기준(실측 없음)"
        elif area.system is not None:
            area.final, area.status = area.system, "실측 기준 잠정(인터뷰 미입력)"
        areas[prefix] = area
    finals = [area.final for area in areas.values() if area.final is not None]
    overall = round1(sum(finals) / len(finals)) if finals else None
    complete = len(finals) == len(areas) and all(
        area.status in ("미보정", "인터뷰-실측 괴리") for area in areas.values()
    )
    status = "6개 영역 집계" if complete else "잠정(인터뷰·실측 미완료 영역 포함)" if finals else "판정 보류"
    return areas, overall, status


def read_assessment(path: Path) -> Assessment:
    book = load_workbook(path, rich_text=False)
    from easm_agent.report_integrated import GRADES, PROCESS, is_integrated

    if is_integrated(book):
        from easm_agent.report_values import build_report_values

        contract = build_report_values(book)
        items = []
        for row in range(5, 59):
            sheet = book[PROCESS]
            code = _text(sheet.cell(row, 3).value)
            if not re.fullmatch(r"[A-Z]{2}-(?:PR|PE|DA|TE)-\d+", code):
                raise ValueError(f"통합 템플릿의 수동 평가 코드가 올바르지 않습니다: {code}")
            response = _score(sheet.cell(row, 6).value)
            items.append(Item(
                code=code, area=code[:2], kind=code[3:5], row=row,
                text=_text(sheet.cell(row, 4).value), levels=[""] * 5,
                evidence="문서·시스템·개선 이력", score=_score(contract.cells[PROCESS, f"K{row}"]),
                status="답변 완료" if response else "인터뷰 필요",
                detail=_text(sheet.cell(row, 13).value), memo=_text(sheet.cell(row, 13).value),
            ))
        sheet = book[GRADES]
        for row in range(5, 31):
            code = _text(sheet.cell(row, 1).value)
            if not re.fullmatch(r"[A-Z]{2}-SY-\d+", code):
                raise ValueError(f"통합 템플릿의 System Evidence 코드가 올바르지 않습니다: {code}")
            score = _score(sheet.cell(row, 21).value)
            value = sheet.cell(row, 22).value
            items.append(Item(
                code=code, area=code[:2], kind="SY", row=row,
                text=_text(sheet.cell(row, 4).value),
                levels=[_text(sheet.cell(row, column).value) for column in range(16, 21)],
                evidence=_text(sheet.cell(row, 5).value), score=score,
                status="판정 보류" if score is None else "수집됨",
                detail=_text(sheet.cell(row, 13).value),
                memo=_text(sheet.cell(row, 25).value),
                metric=f"{value:.2%}" if type(value) in (float, int) else "",
            ))
        summary = _text(book["0_안내"]["A2"].value)
        book.close()
        return Assessment(items, contract.areas, contract.overall, contract.overall_status, summary, list(LEVEL_NAMES))
    criteria, result = book[CRITERIA_SHEET], book[RESULT_SHEET]
    items: list[Item] = []
    for row in range(5, criteria.max_row + 1):
        code = _text(criteria.cell(row, 2).value)
        if not re.fullmatch(r"[A-Z]{2}-[A-Z]{2}-\d+", code):
            continue
        kind = code.split("-")[1]
        if kind not in {key for key, _ in KINDS}:
            raise ValueError(f"지원되지 않는 평가 코드입니다: {code}")
        score = _score(result.cell(row, 13).value)
        detail = _text(result.cell(row, 10).value)
        items.append(Item(
            code=code, area=code[:2], kind=kind, row=row, text=_text(criteria.cell(row, 6).value),
            levels=[_text(criteria.cell(row, 6 + n).value) for n in range(1, 6)],
            evidence=_text(criteria.cell(row, 12).value), score=score,
            status=_text(result.cell(row, 7).value), detail=detail,
            memo=_text(result.cell(row, 14).value),
            metric=_text(result.cell(row, 8).value),
        ))
    names = list(LEVEL_NAMES)
    if "3. 성숙도 정의" in book.sheetnames:
        for row in book["3. 성숙도 정의"].iter_rows(min_row=4, max_row=8):
            values = [_text(cell.value) for cell in row if cell.value is not None]
            match = re.fullmatch(r"Level (\d)", values[0]) if values else None
            if match and len(values) >= 4:
                names[int(match[1]) - 1] = values[1]
    areas, overall, status = compute_scores(items)
    book.close()
    return Assessment(items, areas, overall, status, _text(result["B2"].value), names)
