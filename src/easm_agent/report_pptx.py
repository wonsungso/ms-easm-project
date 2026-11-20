"""Populate the approved 12-slide report without rebuilding its Office package.

The template's slide masters, layouts, theme, media and shape geometry stay byte-identical; only
text, table cells and bar sizes are replaced with the story computed in report_narrative.
"""

from __future__ import annotations

import copy
import math
import re
import sysconfig
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.shapes.autoshape import Shape
from pptx.shapes.graphfrm import GraphicFrame
from pptx.slide import Slide
from pptx.table import _Cell
from pptx.text.text import TextFrame
from pptx.util import Inches, Pt

from easm_agent import report_narrative as story
from easm_agent.deck_model import AREAS, TARGET_LEVEL, read_assessment
from easm_agent.models import Collection
from easm_agent.report_backdata import ReportMetric
from easm_agent.report_story import (
    DEFAULT_CUSTOMER,
    PENDING_LABEL,
    DeckData,
    em,
    glossary_lines,
    glossary_matches,
    money,
    pct,
    superscript,
)
from easm_agent.report_terms import GROUP_LABEL

TEMPLATE_NAME = "assessment-report-template.pptx"
GRAY = "666666"
RED = "C00000"
BLUE = "0070C0"
MID_GRAY = "A6A6A6"
PENDING_TEXT = PENDING_LABEL
DASHES = str.maketrans({"\u2013": "-", "\u2014": "-"})
FOOTERS = {1: 43744, 2: 24030, 3: 24610, 4: 28602, 5: 28896, 6: 31758, 7: 36146, 8: 36712, 9: 40679,
           10: 43666, 11: 44179}
RESERVED_NOTES = {2: 1, 4: 2}  # footnote numbers already used by the template's own 1) 2) marks
FOOTER_ROWS = {6: 5, 9: 5, 11: 3}  # rows that fit above the content of that slide
FOOTER_BOTTOM = 7.08


@dataclass
class DeckContext:
    customer: str = DEFAULT_CUSTOMER
    collected_at: datetime | None = None
    subscriptions: int | None = None
    agents: int | None = None
    metrics: dict[str, ReportMetric] | None = None
    collection: Collection | None = None


def presentation_template_path() -> Path:
    source = Path(__file__).resolve().parents[2] / "docs" / TEMPLATE_NAME
    installed = Path(sysconfig.get_path("data")) / "share" / "easm-agent" / TEMPLATE_NAME
    path = source if source.is_file() else installed
    if not path.is_file():
        raise FileNotFoundError(f"보고서 PPT 템플릿을 찾을 수 없습니다: {path}")
    return path


def context_from_workbook(
    workbook: Path, customer: str = DEFAULT_CUSTOMER, metrics: dict[str, ReportMetric] | None = None,
    collection: Collection | None = None,
) -> DeckContext:
    context = DeckContext(customer=customer, metrics=metrics, collection=collection)
    stamp = re.search(r"(\d{8}T\d{6})\d*Z", workbook.name)
    if stamp:
        context.collected_at = datetime.strptime(stamp[1], "%Y%m%dT%H%M%S")
    return context


def replace_text(target: Shape | _Cell | TextFrame, text: str, *, size: float | None = None) -> None:
    """Keep paragraph/run styles; only duplicate a paragraph when new lines require it."""
    frame = target if isinstance(target, TextFrame) else target.text_frame
    body = frame._txBody
    originals = [copy.deepcopy(paragraph._p) for paragraph in frame.paragraphs]
    visible = [
        paragraph for paragraph in originals
        if "".join(paragraph.itertext()).strip()
    ] or originals
    spacers = [paragraph for paragraph in originals if not "".join(paragraph.itertext()).strip()]
    for paragraph in list(body.findall(qn("a:p"))):
        body.remove(paragraph)
    content_index = 0
    for line in text.split("\n"):
        prototype = (
            visible[min(content_index, len(visible) - 1)] if line.strip()
            else spacers[0] if spacers else visible[-1]
        )
        paragraph = copy.deepcopy(prototype)
        if line.strip():
            content_index += 1
        for node in list(paragraph):
            if node.tag in (qn("a:br"), qn("a:fld")):
                paragraph.remove(node)
        runs = paragraph.findall(qn("a:r"))
        if not runs:
            run = etree.Element(qn("a:r"))
            properties = paragraph.find(qn("a:endParaRPr"))
            if properties is not None:
                properties = copy.deepcopy(properties)
                properties.tag = qn("a:rPr")
                run.append(properties)
            etree.SubElement(run, qn("a:t"))
            paragraph.append(run)
            runs = [run]
        for run_index, run in enumerate(runs):
            node = run.find(qn("a:t"))
            if node is None:
                node = etree.SubElement(run, qn("a:t"))
            node.text = line if run_index == 0 else ""
            if size is not None:
                properties = run.find(qn("a:rPr"))
                if properties is None:
                    properties = etree.Element(qn("a:rPr"))
                    run.insert(0, properties)
                properties.set("sz", str(round(size * 100)))
        if size is not None:
            for properties in paragraph.findall(qn("a:endParaRPr")):
                properties.set("sz", str(round(size * 100)))
        body.append(paragraph)


def shape(slide: Slide, identifier: int) -> Shape:
    for target in slide.shapes:
        if target.shape_id == identifier:
            if not isinstance(target, Shape):
                raise ValueError(f"보고서 텍스트·막대 도형 형식이 다릅니다: {identifier}")
            return target
    raise KeyError(f"보고서 원본 도형을 찾을 수 없습니다: {identifier}")


def texts(slide: Slide, values: dict[int, str]) -> None:
    for identifier, value in values.items():
        replace_text(shape(slide, identifier), value)


def text_color(target: Shape, color: str = "000000") -> None:
    for paragraph in target.text_frame.paragraphs:
        for run in paragraph.runs:
            run.font.color.rgb = RGBColor.from_string(color)


def gray_pending(slide: Slide, identifiers: tuple[int, ...] = ()) -> None:
    """Pending values are shown neutrally; they are neither a pass nor a failure."""
    frames = [shape(slide, identifier).text_frame for identifier in identifiers]
    frames += [
        cell.text_frame for target in slide.shapes if target.has_table
        for row in target.table.rows for cell in row.cells
    ]
    for frame in frames:
        text = frame.text.strip()
        if text in (PENDING_LABEL, "-") or text.endswith("후 판정"):
            for paragraph in frame.paragraphs:
                for run in paragraph.runs:
                    run.font.color.rgb = RGBColor.from_string(GRAY)


def compact_table(slide: Slide) -> None:
    for row in table_shape(slide).table.rows:
        for cell in row.cells:
            cell.margin_top = cell.margin_bottom = Inches(0.005)
            cell.margin_left = cell.margin_right = Inches(0.04)
            for paragraph in cell.text_frame.paragraphs:
                paragraph.line_spacing = 1.0
                paragraph.space_before = paragraph.space_after = Pt(0)


def no_wrap_breaks(slide: Slide) -> None:
    for row in table_shape(slide).table.rows:
        for cell in row.cells:
            for paragraph in cell.text_frame.paragraphs:
                paragraph._p.get_or_add_pPr().set("eaLnBrk", "0")


def hide(slide: Slide, identifiers: tuple[int, ...] | list[int]) -> None:
    """Do not leave a sample bar visible when its actual value is unknown."""
    for identifier in identifiers:
        target = shape(slide, identifier)
        target.fill.background()
        target.line.fill.background()
        if target.has_text_frame:
            replace_text(target, "")


def add_bar(slide: Slide, prototype: etree._Element) -> Shape:
    node = copy.deepcopy(prototype)
    identifier = max(s.shape_id for s in slide.shapes) + 1
    properties = node.find(".//" + qn("p:cNvPr"))
    if properties is None:
        raise ValueError("원본 막대 도형에 식별 속성이 없습니다.")
    properties.set("id", str(identifier))
    slide.shapes._spTree.insert_element_before(node, "p:extLst")
    return shape(slide, identifier)


def restore_shapes(slide: Slide, prototypes: dict[int, etree._Element], identifiers: tuple[int, ...]) -> None:
    for identifier in identifiers:
        node = shape(slide, identifier)._element
        node.getparent().replace(node, copy.deepcopy(prototypes[identifier]))


def table_shape(slide: Slide) -> GraphicFrame:
    tables = [s for s in slide.shapes if isinstance(s, GraphicFrame) and s.has_table]
    if len(tables) != 1:
        raise ValueError("보고서 원본 슬라이드에는 데이터 표가 하나 있어야 합니다.")
    return tables[0]


def table_rows(slide: Slide, values: list[list[str]], *, size: float | None = None) -> None:
    target = table_shape(slide)
    table = target.table
    height = target.height
    while len(table.rows) < len(values):
        table._tbl.append(copy.deepcopy(table._tbl.tr_lst[-1]))
    while len(table.rows) > len(values):
        table._tbl.remove(table._tbl.tr_lst[-1])
    for row, row_values in zip(table.rows, values, strict=True):
        if len(row_values) != len(row.cells):
            raise ValueError("원본 PPT 표의 열 계약이 일치하지 않습니다.")
        row.height = height // len(values)
        for cell, value in zip(row.cells, row_values, strict=True):
            replace_text(cell, value, size=size)
    target.height = height


def set_widths(slide: Slide, widths: tuple[float, ...]) -> None:
    columns = list(table_shape(slide).table.columns)
    for column, width in zip(columns, widths, strict=True):
        column.width = Inches(width)


def number(value: float | int | None) -> str:
    return PENDING_LABEL if value is None else f"{value:.1f}"


def fit_size(target: Shape, size: float) -> None:
    replace_text(target, target.text, size=size)


def text_frames(slide: Slide, footer_id: int) -> list[TextFrame]:
    """Readable text frames of a slide in reading order, footnote excluded."""
    rows: list[tuple[tuple[int, int, int, int], TextFrame]] = []
    for target in slide.shapes:
        band = round(target.top / Inches(0.3))
        if getattr(target, "has_table", False) and target.has_table:
            for r, row in enumerate(target.table.rows):
                rows += [((band, target.left, r, c), cell.text_frame) for c, cell in enumerate(row.cells)]
        elif target.has_text_frame and target.shape_id != footer_id:
            rows.append(((band, target.left, 0, 0), target.text_frame))
    return [frame for _key, frame in sorted(rows, key=lambda row: row[0])]


def term_order(slide: Slide, footer_id: int, reserved: int) -> list[int]:
    """Glossary indexes in order of first use on the slide (at most nine footnote numbers)."""
    order: list[int] = []
    for frame in text_frames(slide, footer_id):
        for _start, _end, index in glossary_matches(frame.text):
            if index not in order and reserved + len(order) < 9:
                order.append(index)
    return order


def mark_terms(slide: Slide, footer_id: int, reserved: int, keep: list[int]) -> None:
    """Number the first use of every kept glossary term on the slide."""
    numbers = {index: reserved + position + 1 for position, index in enumerate(keep)}
    done: set[int] = set()
    for frame in text_frames(slide, footer_id):
        text = frame.text
        marks = []
        for _start, end, index in glossary_matches(text):
            if index in numbers and index not in done:
                done.add(index)
                marks.append((end, numbers[index]))
        if marks:
            for end, number_ in sorted(marks, reverse=True):
                text = text[:end] + superscript(number_) + text[end:]
            replace_text(frame, text)


def footer_pass(slide: Slide, page: int, lines: list[str]) -> None:
    """Write the slide footnote: its own notes first, then a one-line explanation per unfamiliar term."""
    footer_id = FOOTERS[page]
    reserved = RESERVED_NOTES.get(page, 0)
    base = [line for line in lines if line]
    base = [part for line in base for part in line.split("\n") if part]
    keep = term_order(slide, footer_id, reserved)
    # Terms that would push the footnote into the content above it are left without a footnote.
    while keep and len(base) + len(glossary_lines(keep, reserved + 1, 88)) > FOOTER_ROWS.get(page, 6):
        keep.pop()
    mark_terms(slide, footer_id, reserved, keep)
    notes = glossary_lines(keep, reserved + 1, 88)
    rows = base + notes
    target = shape(slide, footer_id)
    if not notes and len(rows) <= 1 and all(em(line) <= 78 for line in rows):
        replace_text(target, "\n".join(rows))
        return
    replace_text(target, "\n".join(rows), size=8)
    height = Inches(0.135 * len(rows) + 0.07)
    target.height = height
    target.top = Inches(FOOTER_BOTTOM) - height
    target.text_frame.vertical_anchor = MSO_ANCHOR.BOTTOM
    target.text_frame.word_wrap = True


# ---- slide builders ---------------------------------------------------------------------------
def build_cover(slide: Slide, data: DeckData) -> None:
    texts(slide, {
        10: data.collected_label() or "수집 일시 기록 없음",
        23789: f"{data.customer} AI Agent Governance Readiness 진단\n- System Evidence 분석 결과 보고서 -",
    })
    replace_text(shape(slide, 10), shape(slide, 10).text, size=14)
    if data.disclosure:
        notice = slide.shapes.add_textbox(Inches(0.4), Inches(6.95), Inches(10), Inches(0.25))
        notice.name = "Report data disclosure"
        run = notice.text_frame.paragraphs[0].add_run()
        run.text = data.disclosure
        run.font.size = Pt(9)


def build_summary(slide: Slide, data: DeckData) -> None:
    values = story.summary(data)
    footer = values.pop(43744)
    texts(slide, values)
    footer_pass(slide, 1, [footer])


def build_overview(slide: Slide, data: DeckData) -> None:
    values = story.overview(data)
    footer = values.pop(24030)
    texts(slide, values)
    if data.overall is not None and data.overall >= TARGET_LEVEL:
        shape(slide, 23810).text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor.from_string(BLUE)
    table_rows(slide, story.key_rows(data))
    compact_table(slide)
    set_widths(slide, (1.95, 2.85, 2.42))
    no_wrap_breaks(slide)
    gray_pending(slide)
    footer_pass(slide, 2, [footer])


def build_method(slide: Slide, data: DeckData) -> None:
    values = story.method_texts(data)
    footer = values.pop(24610)
    texts(slide, values)
    for identifier in (24344, 24379, 24415, 24452, 24490):
        fit_size(shape(slide, identifier), 10)
    table_rows(slide, story.method_rows(data))
    footer_pass(slide, 3, [footer])


def build_scores(slide: Slide, data: DeckData) -> None:
    texts(slide, {
        24652: story.headline_scores(data),
        28503: story.score_box(data),
    })
    system = {prefix: data.assessment.areas[prefix].system for prefix, *_ in AREAS}
    ranked = sorted(value for value in system.values() if value is not None)
    for prefix, bar_id, label_id in zip(
        (row[0] for row in AREAS),
        (25460, 25640, 25829, 26027, 26234, 26450),
        (25519, 25702, 25894, 26095, 26305, 26524), strict=True,
    ):
        value = system[prefix]
        bar, label = shape(slide, bar_id), shape(slide, label_id)
        if value is None:
            hide(slide, [bar_id])
            label.top = Inches(3.48)
            replace_text(label, PENDING_LABEL, size=9)
            text_color(label, GRAY)
            continue
        bar.height = Inches(value / 5 * 1.86)
        bar.top = Inches(3.83) - bar.height
        label.top = bar.top - Inches(0.25)
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor.from_string(
            RED if value < TARGET_LEVEL and value == ranked[0] else MID_GRAY
        )
        bar.line.fill.background()
        replace_text(label, number(value) + ("*" if story.partial_area(data, prefix) else ""))
        text_color(label)
    last, previous = system["OT"], shape(slide, 26234)
    if last is not None and last > TARGET_LEVEL:
        # The last bar would cover the target label, so it moves into the gap before that bar.
        target = shape(slide, 26752)
        target.left = previous.left + previous.width
        target.width = shape(slide, 26450).left - target.left
        target.text_frame.margin_left = target.text_frame.margin_right = 0
        target.text_frame.word_wrap = False
        for paragraph in target.text_frame.paragraphs:
            paragraph.alignment = PP_ALIGN.CENTER
    for (key, _label, codes), label_id, score_id in zip(
        data.groups(), (27070, 27319, 27577, 27844, 28120), (27152, 27404, 27665, 27935, 28214), strict=True,
    ):
        score = data.average(codes)
        measured = sum(data.score(code) is not None for code in codes)
        texts(slide, {
            label_id: f"{key} {GROUP_LABEL[key]}",
            score_id: PENDING_LABEL if score is None else f"L{score:.1f}" + ("*" if measured < len(codes) else ""),
        })
        fit_size(shape(slide, score_id), 11)
        text_color(shape(slide, score_id), GRAY if score is None else "000000")
    shape(slide, 27490).line.color.rgb = RGBColor.from_string(MID_GRAY)
    table_rows(slide, story.score_rows(data))
    gray_pending(slide)
    footer_pass(slide, 4, [
        "1) 단계 점수 = 단계 내 항목 판정 평균 (확인 중 제외, *는 일부 항목만 반영)",
        f"2) 인터뷰가 System Evidence보다 {story.CORRECTION_GAP:g}점 이상 높으면 최종 = System Evidence + 1.0으로 하향 보정",
        story.coverage_note(data),
    ])


def build_matrix(slide: Slide, data: DeckData) -> None:
    distribution_prototype = copy.deepcopy(shape(slide, 28732)._element)
    table_rows(slide, story.matrix_rows(data), size=9)
    compact_table(slide)
    set_widths(slide, (1.7, 1.35, 0.56) * 2)
    buckets = story.distribution(data)
    for label_id, value in zip((28662, 28701, 28749, 28786, 28849), buckets, strict=True):
        replace_text(shape(slide, label_id), f"{value}개")
    replace_text(shape(slide, 28806), PENDING_LABEL)
    fit_size(shape(slide, 28806), 8.5)
    for bar_id, label_id, value in zip(
        (28651, 28687, 28732, 28827), (28662, 28701, 28749, 28849),
        (buckets[0], buckets[1], buckets[2], buckets[4]), strict=True,
    ):
        bar, label = shape(slide, bar_id), shape(slide, label_id)
        if value:
            bar.width = Inches(value / max(buckets) * 1.2)
        else:
            hide(slide, [bar_id])
            bar.width = 1
        label.left = bar.left + bar.width + Inches(0.03)
    if buckets[3]:
        bar = add_bar(slide, distribution_prototype)
        bar.left, bar.top = Inches(8.44), Inches(3.07)
        bar.width = Inches(buckets[3] / max(buckets) * 1.2)
        shape(slide, 28786).left = bar.left + bar.width + Inches(0.03)
    texts(slide, {
        28603: story.headline_matrix(data),
        28605: f"4. System Evidence {len(data.items)}개 항목별 판정 결과",
        28872: story.matrix_box(data),
    })
    fit_size(shape(slide, 28872), 10)
    gray_pending(slide)
    footer_pass(slide, 5, [story.matrix_footer(data)])


@dataclass
class Column:
    label: str
    total: float | None
    part: float | None
    total_text: str
    part_text: str


def draw_columns(
    slide: Slide, columns: list[Column], layout: dict[str, tuple[int, ...] | tuple[tuple[int, int], ...]],
    prototypes: dict[int, etree._Element], chart_height: float, maximum: float, *, inside: bool,
) -> None:
    height = Inches(chart_height)
    for index, column in enumerate(columns):
        first_id, second_id = layout["bars"][index]
        total_id, month_id, component_id = (
            layout["totals"][index], layout["months"][index], layout["components"][index],
        )
        restore_shapes(slide, prototypes, (first_id, second_id, total_id, month_id, component_id))
        first, second = shape(slide, first_id), shape(slide, second_id)
        baseline = first.top + first.height
        replace_text(shape(slide, month_id), column.label, size=9)
        total_shape, component = shape(slide, total_id), shape(slide, component_id)
        if column.total is not None and column.part is None and maximum:
            hide(slide, [first_id])
            second.height = max(1, round(height * column.total / maximum))
            second.top = baseline - second.height
            if column.total == 0:
                hide(slide, [second_id])
            total_shape.top = baseline - round(height * column.total / maximum) - Inches(0.27)
            replace_text(total_shape, column.total_text, size=10)
            replace_text(component, column.part_text, size=9)
            continue
        if column.total is None or column.part is None or not maximum:
            hide(slide, [first_id, second_id])
            total_shape.top = baseline - Inches(0.27)
            replace_text(total_shape, column.total_text, size=9 if len(column.total_text) > 4 else 10)
            replace_text(component, column.part_text, size=9)
            continue
        first.height = max(1, round(height * column.part / maximum))
        second.height = max(1, round(height * (column.total - column.part) / maximum))
        first.top = baseline - first.height
        second.top = first.top - second.height
        if column.part == 0:
            hide(slide, [first_id])
        if column.part == column.total:
            hide(slide, [second_id])
        total_shape.top = baseline - round(height * column.total / maximum) - Inches(0.27)
        replace_text(total_shape, column.total_text, size=10)
        replace_text(component, column.part_text, size=9)
        if inside and column.part:
            component.top = first.top + (first.height - component.height) // 2


def column_layout(slide: Slide, groups: dict[str, tuple[int, ...]], pairs: tuple[tuple[int, int], ...]):
    layout = {"bars": pairs, **groups}
    identifiers = [i for pair in pairs for i in pair]
    for key in ("totals", "months", "components"):
        identifiers += list(groups[key])
    prototypes = {i: copy.deepcopy(shape(slide, i)._element) for i in identifiers}
    return layout, prototypes


def history_columns(data: DeckData, prefix: str, *, cost: bool) -> list[Column] | None:
    history = data.value(prefix + ".history")
    if not isinstance(history, str):
        return None
    component = "attributed" if cost else "approved"
    currency = str(data.value("cost.currency") or "")
    months = history.split(",")[-6:]
    columns = []
    for month in months:
        total = data.value(f"{prefix}.month.{month}.total")
        part = data.value(f"{prefix}.month.{month}.{component}")
        total = total if isinstance(total, (int, float)) else None
        if cost and part is None and month == months[-1]:
            part = direct_attribution(data, total, currency)
        part = part if isinstance(part, (int, float)) and total is not None and 0 <= part <= total else None
        label = f"{month[:4]}.{month[4:]}"
        if cost and total is None:
            columns.append(Column(label, None, None, "청구 내역 없음", ""))
        elif cost:
            text = f"식별 {pct(part / total)}" if part is not None and total else "식별 확인 중"
            columns.append(Column(label, total, part, money(total, currency), text))
        else:
            columns.append(Column(label, total, part, f"{total:g}" if total is not None else PENDING_TEXT,
                                  f"{part:g}" if part is not None else ""))
    return columns


def direct_attribution(data: DeckData, total: float | int | None, currency: str) -> float | None:
    """Directly attributed amount of the latest month, taken from the cost-attribution result.

    Only used when that result covers exactly the billed amount of the month in the same currency.
    """
    pair = data.counts("OT-SY-24")
    if pair is None or total is None or not currency or data.currency("OT-SY-24") != currency:
        return None
    return pair[0] if math.isclose(pair[1], total, rel_tol=1e-6) else None


def build_creation(slide: Slide, data: DeckData) -> None:
    pairs = ((29226, 29299), (29416, 29499), (29631, 29724), (29871, 29974), (30136, 30249), (30426, 30549))
    layout, prototypes = column_layout(slide, {
        "totals": (29337, 29542, 29772, 30027, 30307, 30612),
        "months": (29376, 29586, 29821, 30081, 30366, 30676),
        "components": (29262, 29457, 29677, 29922, 30192, 30487),
    }, pairs)
    history = history_columns(data, "creation", cost=False)
    catalog = data.catalog
    columns: list[Column] | None = history
    legend = ("승인 매칭", "미매칭")
    if columns is None and catalog is not None:
        legend = (("직접 제작·구성", "플랫폼 미확인 앱·기타") if catalog.source.startswith("Agent 365")
                  else ("Azure 에이전트", ""))
        columns = [
            Column(f"{month}월" + ("*" if catalog.partial_last and index == len(catalog.months) - 1 else ""),
                   total, built, str(total), str(built) if built else "")
            for index, (_year, month, total, built) in enumerate(catalog.months)
        ]
    chart_title = "I. 월별 신규 생성 Agent 추이" + (
        " (승인 매칭)" if history else "" if catalog and catalog.source.startswith("Agent") else " (Azure)")
    if history is None and catalog is not None and catalog.source.startswith("Agent 365"):
        chart_title = "I. 월별 신규 목록 패키지 (Agent 365 목록)"
    if columns is None:
        hide(slide, [i for pair in pairs for i in pair] + [29061, 29124])
        for identifier in (*layout["totals"], *layout["months"], *layout["components"], 29092, 29157):
            replace_text(shape(slide, identifier), "")
        missing = shape(slide, 29337)
        missing.left, missing.top, missing.width, missing.height = Inches(0.6), Inches(2.7), Inches(5), Inches(0.6)
        replace_text(missing, "신규 에이전트 등록 이력은 등록 목록 수집 후 표시됩니다", size=12)
        chart_title = "I. 월별 신규 생성 Agent 추이"
    else:
        maximum = max((c.total for c in columns if c.total is not None), default=0) or 1
        draw_columns(slide, columns, layout, prototypes, 1.7, maximum, inside=True)
        texts(slide, {29092: legend[0], 29157: legend[1]})
        if len(legend[1]) > 6:
            shape(slide, 29157).width += Inches(0.9)
        if not legend[1]:
            hide(slide, [29124, 29157])
    registry = registry_panel(data)
    gray = shape(slide, 31011)
    blue, miss = shape(slide, 31224), shape(slide, 31297)
    texts(slide, {
        28921: story.headline_creation(data),
        29002: chart_title,
        30741: story.creation_caption(data),
        30807: "II. 에이전트 청사진 연결 현황" if not registry["registry"] else "II. Registry - 등록부 대조",
        30942: registry["top"], 31152: registry["bottom"], 31081: registry["top_value"],
        31371: registry["bottom_value"], 31446: registry["bullets"],
        31678: story.creation_insight(data),
    })
    if registry["matched"] is None or not registry["total"]:
        hide(slide, [31011, 31224, 31297])
    else:
        ratio = registry["matched"] / registry["total"]
        blue.width = max(1, round(gray.width * ratio))
        miss.left, miss.width = blue.left + blue.width, gray.width - blue.width
        if registry["total"] == registry["matched"]:
            hide(slide, [31297])
        else:
            replace_text(miss, f"{registry['missing_label']} {registry['total'] - registry['matched']:g}", size=9)
    table_rows(slide, story.creation_rows(data))
    set_widths(slide, (2.45, 2.4, 1.5, 0.87))
    gray_pending(slide, (31081, 31371))
    is_package = bool(catalog and catalog.source.startswith("Agent"))
    footer_pass(slide, 6, [
        story.footer(data, 7, "* 수집일까지 집계" if catalog and catalog.partial_last else ""),
        *story.creation_notes(data),
    ] if is_package else [story.footer(
        data, 7, "* 수집일까지 집계" if catalog and catalog.partial_last else "")])


def registry_panel(data: DeckData) -> dict[str, object]:
    observed, registered = data.value("registry.observed"), data.value("registry.registered")
    match = data.rate("registry.match")
    if match is not None and isinstance(observed, (int, float)) and isinstance(registered, (int, float)):
        missing = data.value("registry.missing")
        metadata = data.value("registry.metadata_missing")
        return {
            "registry": True, "top": "Agent Registry (실측)", "bottom": "공식 등록부 (고객 관리)",
            "top_value": f"{observed:g}개", "bottom_value": f"{registered:g}개",
            "total": observed, "matched": registered, "missing_label": "미등록",
            "bullets": f"· 등록부 일치 {match:.0%} (목표 {data.rate('report.target.registry.match') or 0.9:.0%} 이상)"
                       f"\n· 등록 누락 {missing if missing is not None else '-'} / 필수 정보 누락 "
                       f"{metadata if metadata is not None else '-'}",
        }
    pair = data.counts("DP-SY-15")
    if pair is None:
        return {"registry": False, "top": "Azure에서 확인된 에이전트", "bottom": "청사진에 연결된 에이전트",
                "top_value": PENDING_TEXT, "bottom_value": PENDING_TEXT, "total": None, "matched": None,
                "missing_label": "미연결", "bullets": data.pending_note("DP-SY-15")}
    owners = data.fraction("BI-SY-13")
    lines = [f"· 에이전트 {pair[1]:g}개 중 {pair[0]:g}개가 청사진에 연결 (기준 {data.l3_min('DP-SY-15'):.0%} 이상)"]
    if owners and data.score("BI-SY-13") is not None:
        lines.append(f"· 담당자 · 환경 · 비용 정보 기록 {owners}")
    return {
        "registry": False, "top": "Azure에서 확인된 에이전트", "bottom": "청사진에 연결된 에이전트",
        "top_value": f"{pair[1]:g}개", "bottom_value": f"{pair[0]:g}개", "total": pair[1], "matched": pair[0],
        "missing_label": "미연결", "bullets": "\n".join(lines),
    }


def build_identity(slide: Slide, data: DeckData) -> None:
    prototype = copy.deepcopy(shape(slide, 32613)._element)
    rows = zip(
        story.IDENTITY_BARS, (32434, 32983, 33568, 34189, 34846), (32613, 33174, 33771, 34404, None),
        (32704, 33271, 33874, 34513, 35073), (32796, 33369, 33978, 34623, 35188),
        (32889, 33468, 34083, 34734, 35304), strict=True,
    )
    for code, name_id, bar_id, marker_id, value_id, target_id in rows:
        ratio = data.ratio(code) if data.score(code) is not None else None
        minimum = data.l3_min(code)
        texts(slide, {
            name_id: story.IDENTITY_NAMES[code],
            value_id: pct(ratio) if ratio is not None else PENDING_TEXT,
            target_id: f"{minimum:.0%} 이상",
        })
        text_color(shape(slide, value_id), "000000" if ratio is not None else GRAY)
        frame = shape(slide, value_id).text_frame
        frame.margin_left = frame.margin_right = 0
        frame.word_wrap = False
        target = shape(slide, target_id)
        target.text_frame.margin_left = target.text_frame.margin_right = 0
        target.text_frame.word_wrap = False
        replace_text(target, target.text, size=9)
        if ratio is None or ratio == 0:
            if bar_id is not None:
                hide(slide, [bar_id])
        elif bar_id is None:
            bar = add_bar(slide, prototype)
            bar.top = Inches(4.23)
            bar.width = Inches(2.57 * ratio)
        else:
            shape(slide, bar_id).width = Inches(2.57 * ratio)
        marker = shape(slide, marker_id)
        marker.left = Inches(2.56 + 2.57 * minimum)
        slide.shapes._spTree.insert_element_before(marker._element, "p:extLst")
    texts(slide, {
        31839: story.headline_identity(data),
        35658: story.identity_insight(data),
        36022: story.identity_recommendations(data),
    })
    fit_size(shape(slide, 36022), 10)
    table_rows(slide, story.identity_rows(data))
    gray_pending(slide)
    footer_pass(slide, 7, [story.footer(
        data, 8, "접속 조건 제한은 명시 대상 구성만 확인" if data.conditional_access else "")])


def build_security(slide: Slide, data: DeckData) -> None:
    cards = story.security_cards(data)
    ids = (
        (36167, 36182, 36191, 36201, 36212, 36224), (36237, 36266, 36282, 36299, 36317, 36336),
        (36356, 36399, 36422, 36446, 36471, 36497),
    )
    for code, (title_id, value_id, detail_id, first_id, second_id, target_id) in zip(cards, ids, strict=True):
        card = story.card_texts(data, code)
        texts(slide, {title_id: card["title"], value_id: card["value"], detail_id: card["detail"],
                      target_id: card["target"]})
        text_color(shape(slide, value_id), GRAY if card["value"] == PENDING_LABEL else "000000")
        ratio = story.card_ratio(data, code)
        first, second = shape(slide, first_id), shape(slide, second_id)
        start, width = first.left, first.width + second.width
        if ratio is None:
            hide(slide, [first_id, second_id])
            continue
        first.width = max(1, round(width * ratio))
        second.left = start + first.width
        second.width = max(1, width - first.width)
        replace_text(first, card["good"] if ratio >= 0.25 else "", size=9)
        replace_text(second, card["bad"] if ratio <= 0.75 else "", size=9)
        if ratio == 1:
            hide(slide, [second_id])
        if ratio == 0:
            hide(slide, [first_id])
    box_first, box_second = story.security_box(data)
    rows = story.exposure_rows(data) or story.defender_rows(data) or story.fallback_security_rows(data)
    texts(slide, {
        36147: story.headline_security(data),
        36524: "II. 고위험 민감 데이터 노출 유형" if story.exposure_rows(data) else (
            "II. 보안 점검 서비스(Defender) 적용 현황" if story.defender_rows(data) else "II. 품질 · 보안 점검 항목"),
        36582: "III. 외부 도구 연결 보호",
        36645: box_first, 36678: box_second,
    })
    table_rows(slide, rows)
    gray_pending(slide, tuple(c[1] for c in ids))
    security_note = story.security_notes(data)
    footer_pass(slide, 8, [story.footer(data, 9), f"※ {security_note}" if security_note else ""])


def build_operations(slide: Slide, data: DeckData) -> None:
    pairs = ((37198, 37245), (37443, 37495), (37713, 37770), (38008, 38070), (38328, 38395), (38673, 38745))
    layout, prototypes = column_layout(slide, {
        "totals": (37293, 37548, 37828, 38133, 38463, 38818),
        "months": (37342, 37602, 37887, 38197, 38532, 38892),
        "components": (37392, 37657, 37947, 38262, 38602, 38967),
    }, pairs)
    legends = (36937, 37020, 36978, 37063)
    for identifier in legends:
        prototypes[identifier] = copy.deepcopy(shape(slide, identifier)._element)
    history = history_columns(data, "cost", cost=True)
    if history is not None:
        maximum = max((c.total for c in history if c.total is not None), default=0) or 1
        draw_columns(slide, history, layout, prototypes, 1.45, maximum, inside=False)
        currency = data.value("cost.currency")
        unknown = [c for c in history if c.total and c.part is None]
        known = [c for c in history if c.total and c.part is not None]
        remainder = ("귀속 불가" if not unknown else "총액·식별 미확인" if not known else "귀속 불가·식별 미확인")
        texts(slide, {36858: "I. 월별 Agent 소비 비용 (OT-SY-24)", 36978: "Agent별 식별", 37063: remainder,
                      37107: f"{currency} · 빨강=최근월" if currency else "조회 범위 실제 청구"})
        notes = ["식별 미확인 월의 회색은 총액"] if unknown else []
    else:
        notes = []
        columns = []
        for code in story.OPS_BARS:
            name, value, fraction, ratio = story.ops_bar(data, code)
            columns.append(Column(name, 1 if ratio is not None else None, ratio, value, fraction))
        draw_columns(slide, columns, layout, prototypes, 1.45, 1, inside=False)
        texts(slide, {36858: "I. 기록 · 알림 · 비용 설정 충족 비율", 36978: "충족", 37063: "미충족",
                      37107: "(항목별 충족 비율)"})
        for identifier in (37107,):
            fit_size(shape(slide, identifier), 9)
    for identifier in (36978, 37063):
        fit_size(shape(slide, identifier), 9)
    observed_usage = usage_buckets(slide, data, prototypes)
    texts(slide, {
        36747: story.headline_ops(data),
        39120: "II. Agent 사용 현황" + ("" if observed_usage else " (최근 30일)"),
        40583: story.ops_box(data),
    })
    table_rows(slide, story.ops_rows(data))
    set_widths(slide, (2.2, 2.7, 1.45, 0.87))
    gray_pending(slide, (40583,))
    package_note = "Agent 365 목록 기준 · 플랫폼 미확인 앱(스토어 앱 포함)" if data.usage else ""
    lines = [story.footer(data, 10, package_note), *story.cost_notes(data)]
    extra = [text for text in (*notes, story.usage_note(data), story.cost_note(data)) if text]
    if extra:
        lines.append("※ " + ", ".join(extra))
    footer_pass(slide, 9, lines)


def usage_buckets(slide: Slide, data: DeckData, prototypes: dict[int, etree._Element]) -> bool:
    total = data.value("usage.total")
    counts = [data.value("usage." + key + ".count") for key in ("active30", "active31_90", "inactive90")]
    bars = ((39277, 39357, 39772, 39858, "30일 내 활성"), (39438, 39520, 39945, 40033, "31~90일"),
            (39603, 39687, 40122, 40212, "90일+ 미사용"))
    for bar_id, label_id, marker_id, _text_id, _label in bars:
        for identifier in (bar_id, marker_id):
            prototypes.setdefault(identifier, copy.deepcopy(shape(slide, identifier)._element))
        prototypes.setdefault(label_id, copy.deepcopy(shape(slide, label_id)._element))
    complete = (
        isinstance(total, (int, float)) and total > 0
        and all(isinstance(count, (int, float)) for count in counts)
    )
    left = Inches(6.17)
    if complete:
        if any(count < 0 for count in counts) or sum(counts) != total:
            raise ValueError("Agent 사용 이력의 구간별 합계가 전체 관측 수와 일치하지 않습니다.")
        for (bar_id, label_id, marker_id, text_id, label), count in zip(bars, counts, strict=True):
            restore_shapes(slide, prototypes, (bar_id, marker_id))
            bar = shape(slide, bar_id)
            bar.left, bar.width = left, max(1, round(Inches(4.21) * count / total))
            target = shape(slide, label_id)
            target.left, target.width = bar.left, bar.width
            replace_text(target, f"{count:g}" if count / total >= 0.1 else "", size=10)
            if count == 0:
                hide(slide, [bar_id])
            left += bar.width
            replace_text(shape(slide, text_id), f"{label} : {count:g}개 ({count / total:.0%})")
        replace_text(shape(slide, 40303), "30/90일 전체 확인 에이전트만 · 비율 반올림")
        return True
    lines = story.usage_lines(data)
    usage = data.usage
    if lines is None or usage is None:
        hide(slide, [bar_id for bar_id, *_rest in bars] + [bars[i][2] for i in range(3)])
        for _bar, label_id, _marker, text_id, _label in bars:
            replace_text(shape(slide, label_id), "")
            replace_text(shape(slide, text_id), "")
        replace_text(shape(slide, bars[0][3]), "사용 현황은 Agent 365 사용 지표 수집 후 표시됩니다")
        replace_text(shape(slide, 40303), "")
        return False
    sizes = (usage.active, usage.idle, usage.unobserved)
    whole = sum(sizes)
    for index, ((bar_id, label_id, marker_id, text_id, _label), count) in enumerate(zip(bars, sizes, strict=True)):
        bar = shape(slide, bar_id)
        bar.left, bar.width = left, max(1, round(Inches(4.21) * count / whole)) if whole else 1
        fill = (BLUE, MID_GRAY, "D9D9D9")[index]
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor.from_string(fill)
        marker = shape(slide, marker_id)
        marker.fill.solid()
        marker.fill.fore_color.rgb = RGBColor.from_string(fill)
        marker.line.fill.background()
        target = shape(slide, label_id)
        target.left, target.width = bar.left, bar.width
        replace_text(target, f"{count:g}" if whole and count / whole >= 0.1 else "", size=10)
        if index == 2:
            text_color(target, "000000")
        if count == 0:
            hide(slide, [bar_id])
        left += bar.width
        replace_text(shape(slide, text_id), lines[index], size=10)
        text_color(shape(slide, text_id), "000000")
        replace_text(shape(slide, 40303), "직접 만든 에이전트 기준 · 90일 미사용은 기간이 쌓인 뒤 판단")
    return False


def build_plan(slide: Slide, data: DeckData) -> None:
    path = data.target_path()
    boxes = story.phase_boxes(data)
    texts(slide, {
        40776: story.headline_plan(data),
        41276: boxes[0], 41379: boxes[1], 41483: boxes[2],
        42244: number(data.overall) if data.overall is not None else PENDING_LABEL,
    })
    for identifier in (42244, 42586, 42937, 43297):
        fit_size(shape(slide, identifier), 9)
        shape(slide, identifier).text_frame.word_wrap = False
    current = shape(slide, 42132)
    scale = 3.13 / 5
    if data.overall is None:
        hide(slide, [42132])
    else:
        current.height = Inches(data.overall * scale)
        current.top = Inches(6.23) - current.height
        current.fill.solid()
        current.fill.fore_color.rgb = RGBColor.from_string(RED if data.overall < TARGET_LEVEL else MID_GRAY)
        shape(slide, 42244).top = current.top - Inches(0.25)
        replace_text(shape(slide, 42244), f"L{data.overall:.1f}")
    for value, bar_id, label_id in zip(path or (), (42471, 42819, 43176), (42586, 42937, 43297), strict=False):
        bar = shape(slide, bar_id)
        bar.height = Inches(value * scale)
        bar.top = Inches(6.23) - bar.height
        label = shape(slide, label_id)
        label.top = bar.top - Inches(0.25)
        replace_text(label, f"L{value:.1f}")
    if path is None:
        hide(slide, [42471, 42819, 43176])
        for identifier in (42586, 42937, 43297):
            replace_text(shape(slide, identifier), "")
    table_rows(slide, story.plan_rows(data), size=9)
    compact_table(slide)
    set_widths(slide, (0.7, 2.6, 1.55, 0.8, 1.57))
    no_wrap_breaks(slide)
    footer_pass(slide, 10, ["※ 목표 수준은 계획(안) - 현재 수준에서 L3보다 0.3 높은 수준까지 Phase 1~3 균등 상향을 "
                            "가정하며 달라질 수 있음"])


def build_next(slide: Slide, data: DeckData) -> None:
    values = story.next_texts(data)
    footer = values.pop(44179)
    texts(slide, values)
    table_rows(slide, story.target_rows(data), size=9)
    compact_table(slide)
    set_widths(slide, (2.05, 3.0, 0.97, 1.2))
    no_wrap_breaks(slide)
    gray_pending(slide)
    footer_pass(slide, 11, [footer])


# ---- notes -------------------------------------------------------------------------------------
def notes_text(data: DeckData, page: int, headline: str) -> str:
    codes = story.NOTE_CODES.get(page, ())
    lines = ["[발표 메모]", headline, ""]
    if codes:
        lines.append("근거 항목")
        for code in codes:
            if code not in data.items:
                continue
            if data.score(code) is None:
                lines.append(f"- {code} {data.label(code)} : 확인 중 ({data.pending_note(code)})")
                continue
            fraction = data.fraction(code)
            lines.append(f"- {code} {data.label(code)} : {data.level(code)}"
                         + (f" ({fraction} 충족, {data.percent(code)})" if fraction else ""))
        lines.append("")
    lines += story.note_limits(data, page)
    refs = story.note_refs(data, page)
    if refs:
        lines += ["", f"증적 참조 ({len(refs)}건)", ", ".join(refs)]
    return "\n".join(lines).strip()


def sanitize(slide_element: etree._Element) -> None:
    for node in slide_element.iter(qn("a:t")):
        if node.text:
            node.text = node.text.translate(DASHES)


def write_presentation(workbook: Path, output: Path, context: DeckContext | None = None) -> None:
    context = context or context_from_workbook(workbook)
    data = DeckData(
        read_assessment(workbook), context.metrics, context.collection, context.customer, context.collected_at,
    )
    source = presentation_template_path().read_bytes()
    presentation = Presentation(BytesIO(source))
    if len(presentation.slides) != 12:
        raise ValueError("보고서 생성기는 승인된 12장 원본 템플릿을 사용합니다.")
    slides = list(presentation.slides)
    build_cover(slides[0], data)
    build_summary(slides[1], data)
    build_overview(slides[2], data)
    build_method(slides[3], data)
    build_scores(slides[4], data)
    build_matrix(slides[5], data)
    build_creation(slides[6], data)
    build_identity(slides[7], data)
    build_security(slides[8], data)
    build_operations(slides[9], data)
    build_plan(slides[10], data)
    build_next(slides[11], data)
    changed = {}
    for page, slide in enumerate(slides):
        headline = next((
            target.text for target in slide.shapes
            if target.has_text_frame and target.shape_id in story.HEADLINE_IDS.get(page, ())
        ), "")
        if slide.has_notes_slide:
            frame = slide.notes_slide.notes_text_frame
            if frame is not None:
                replace_text(frame, notes_text(data, page, headline))
            sanitize(slide.notes_slide._element)
            changed[str(slide.notes_slide.part.partname).lstrip("/")] = etree.tostring(
                slide.notes_slide._element, encoding="UTF-8", xml_declaration=True, standalone=True,
            )
        sanitize(slide._element)
        changed[str(slide.part.partname).lstrip("/")] = etree.tostring(
            slide._element, encoding="UTF-8", xml_declaration=True, standalone=True,
        )
    payload = BytesIO()
    with ZipFile(BytesIO(source)) as archive, ZipFile(payload, "w") as target:
        for info in archive.infolist():
            target.writestr(info, changed.get(info.filename, archive.read(info.filename)))
    output.write_bytes(payload.getvalue())
