"""Executive PowerPoint summary generated from the graded collection result."""

from __future__ import annotations

import sysconfig
from collections import Counter
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.lang import MSO_LANGUAGE_ID
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from easm_agent.models import Collection, Finding, load_criteria
from easm_agent.proposals import azure_agents

TEMPLATE_NAME = "assessment-report-template.pptx"
TITLE = "EASM (Enterprise Agent Service Management) 점검 결과 보고서"
NAVY, BLUE, CYAN, TEAL = "243A5E", "0078D4", "50E6FF", "008575"
LIGHT, INK, MUTED, RED, AMBER = "F2F2F2", "262626", "595959", "D83B01", "B85C00"
LEVEL_COLORS = {"L5": TEAL, "L4": BLUE, "L3": CYAN, "L2": "FFB900", "L1": RED, "N/A": "BDBDBD"}
AREAS = {"DM": "수요", "DS": "설계", "BI": "구축", "DP": "배포", "OE": "운영", "OT": "최적화"}
REASONS = {
    "permission_denied": "권한 또는 라이선스 문제로 조회 거부",
    "license_missing": "필요 라이선스 없음",
    "feature_unavailable": "기능 미제공 또는 미설치",
    "not_found": "확인할 자료 없음",
    "error": "조회 중 오류 발생",
}
SOLID_TABLE_STYLE = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"


def presentation_template_path() -> Path:
    source = Path(__file__).resolve().parents[2] / "docs" / TEMPLATE_NAME
    installed = Path(sysconfig.get_path("data")) / "share" / "easm-agent" / TEMPLATE_NAME
    path = source if source.is_file() else installed
    if not path.is_file():
        raise FileNotFoundError(f"보고서 PPT 템플릿을 찾을 수 없습니다: {path}")
    return path


def _rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value)


def _style_run(run, size=None, bold=None, color=None) -> None:
    run.font.language_id = MSO_LANGUAGE_ID.KOREAN
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color:
        run.font.color.rgb = _rgb(color)


def _paragraph(frame, index: int, options: dict):
    paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
    properties = paragraph._p.get_or_add_pPr()
    properties.set("eaLnBrk", "0")
    properties.set("latinLnBrk", "0")
    if options.get("space_after") is not None:
        paragraph.space_after = Pt(options["space_after"])
    return paragraph


def _set_text(shape, paragraphs, size=None, bold=None, color=None) -> None:
    frame = shape.text_frame
    frame.clear()
    for index, item in enumerate(paragraphs if isinstance(paragraphs, list) else [paragraphs]):
        text, options = item if isinstance(item, tuple) else (item, {})
        run = _paragraph(frame, index, options).add_run()
        run.text = text
        _style_run(run, options.get("size", size), options.get("bold", bold), options.get("color", color))


def _textbox(slide, x, y, w, h, paragraphs, size=14, bold=False, color=INK, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP, bullets=False):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = shape.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    for index, item in enumerate(paragraphs if isinstance(paragraphs, list) else [paragraphs]):
        text, options = item if isinstance(item, tuple) else (item, {})
        paragraph = _paragraph(frame, index, options)
        paragraph.alignment = options.get("align", align)
        run = paragraph.add_run()
        run.text = text
        _style_run(run, options.get("size", size), options.get("bold", bold), options.get("color", color))
        if options.get("bullet", bullets):
            properties = paragraph._p.get_or_add_pPr()
            properties.set("marL", str(Inches(0.2)))
            properties.set("indent", str(-Inches(0.2)))
            etree.SubElement(properties, qn("a:buChar")).set("char", "-")
    return shape


def _rect(slide, x, y, w, h, fill, shape=MSO_SHAPE.RECTANGLE):
    item = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    item.fill.solid()
    item.fill.fore_color.rgb = _rgb(fill)
    item.line.fill.background()
    item.shadow.inherit = False
    return item


def _cell_border(cell) -> None:
    properties = cell._tc.get_or_add_tcPr()
    for side in ("l", "r", "t", "b"):
        tag = qn(f"a:ln{side.upper()}")
        for old in properties.findall(tag):
            properties.remove(old)
        line = etree.SubElement(properties, tag)
        if side == "b":
            line.set("w", "9525")
            etree.SubElement(etree.SubElement(line, qn("a:solidFill")), qn("a:srgbClr")).set("val", "BFBFBF")
        else:
            line.set("w", "0")
            etree.SubElement(line, qn("a:noFill"))
    for tag in ("a:solidFill", "a:noFill"):
        for fill in properties.findall(qn(tag)):
            properties.remove(fill)
            properties.append(fill)


def _fill_cell(cell, text, size, bold, color) -> None:
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    cell.margin_left = cell.margin_right = Inches(0.1)
    cell.margin_top = cell.margin_bottom = Inches(0.04)
    cell.text_frame.word_wrap = True
    paragraph = _paragraph(cell.text_frame, 0, {})
    run = paragraph.add_run()
    run.text = text
    _style_run(run, size, bold, color)


def _table(slide, x, y, widths, header, rows, row_height, size=13, colored_column=None):
    shape = slide.shapes.add_table(len(rows) + 1, len(widths), Inches(x), Inches(y),
                                   Inches(sum(widths)), Inches(0.45 + row_height * len(rows)))
    grid = shape._element.graphic.graphicData.tbl
    grid.tblPr.set("firstRow", "0")
    grid.tblPr.set("bandRow", "0")
    style = grid.tblPr.find(qn("a:tableStyleId"))
    if style is not None:
        style.text = SOLID_TABLE_STYLE
    for index, width in enumerate(widths):
        shape.table.columns[index].width = Inches(width)
    shape.table.rows[0].height = Inches(0.45)
    for row in list(shape.table.rows)[1:]:
        row.height = Inches(row_height)
    for column, title in enumerate(header):
        cell = shape.table.cell(0, column)
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(NAVY)
        _fill_cell(cell, title, size, True, "FFFFFF")
    for r, values in enumerate(rows, 1):
        for column, value in enumerate(values):
            cell = shape.table.cell(r, column)
            cell.fill.background()
            color, bold = INK, column == 0
            if colored_column == column and isinstance(value, tuple):
                value, color = value
                bold = True
            _fill_cell(cell, value, size, bold, color)
            _cell_border(cell)


def _drop_empty_placeholders(slide) -> None:
    for shape in list(slide.placeholders):
        if shape.has_text_frame and not shape.text_frame.text.strip():
            shape._element.getparent().remove(shape._element)


def _short(items: list[str], limit: int = 3) -> str:
    text = ", ".join(items[:limit])
    return text + (f" 외 {len(items) - limit}개" if len(items) > limit else "")


def _count(row: Finding) -> str:
    measurement = row.measurement
    if measurement is None or measurement.numerator is None or measurement.denominator is None:
        return f"{row.metric_value:.0%}" if row.metric_value is not None else "-"
    if measurement.unit == "count":
        return f"{measurement.numerator:g}/{measurement.denominator:g}"
    return f"{row.metric_value:.1%}" if row.metric_value is not None else "-"


def _next_goal(row: Finding) -> str:
    text = row.next_step or ""
    return text.removeprefix("다음 단계 조건: ") or "-"


def write_presentation(data: Collection, findings: list[Finding], path: Path) -> None:
    """Build the executive deck from the graded findings and the corporate template."""
    titles = {code: item["title"] for code, item in load_criteria()["items"].items()}
    name = {row.se_code: titles.get(row.se_code, row.se_code) for row in findings}
    graded = [row for row in findings if row.level != "N/A"]
    pending = [row for row in findings if row.level == "N/A"]
    levels = Counter(row.level for row in findings)
    gaps = sorted((row for row in graded if row.level in ("L1", "L2")),
                  key=lambda row: (row.metric_value or 0, row.se_code))
    strong = sorted((row for row in graded if row.level == "L5"),
                    key=lambda row: (-(row.measurement.denominator or 0) if row.measurement else 0, row.se_code))
    domains = []
    for prefix, label in AREAS.items():
        rows = [row for row in findings if row.se_code.startswith(prefix + "-")]
        scored = [int(row.level[1:]) for row in rows if row.level != "N/A"]
        domains.append((label, rows, sum(scored) / len(scored) if scored else None, len(scored)))
    reason_counts = Counter(row.reason or "not_found" for row in pending)

    prs = Presentation(presentation_template_path())
    slide_ids = prs.slides._sldIdLst
    for slide_id in list(slide_ids):
        prs.part.drop_rel(slide_id.rId)
        slide_ids.remove(slide_id)
    layouts = {layout.name: layout for layout in prs.slide_layouts}

    # 1. Title
    slide = prs.slides.add_slide(layouts["제목 슬라이드"])
    _set_text(slide.placeholders[0], TITLE)
    _drop_empty_placeholders(slide)

    # 2. Executive summary
    slide = prs.slides.add_slide(layouts["Title and text side by side 5"])
    _set_text(slide.placeholders[0],
              f"{len(findings)}개 점검 항목 중 {len(graded)}개를 진단했고, {levels['L5']}개가 최고 수준(L5)입니다")
    summary = [(f"읽기 전용 API로 Azure 구독 {len(data.subscriptions)}개, Azure Agent {len(azure_agents(data))}개를 점검했습니다.",
                {"space_after": 14})]
    ranked = [domain for domain in domains if domain[2] is not None]
    if ranked:
        low = min(ranked, key=lambda domain: domain[2])
        summary.append((f"영역별 평균이 가장 낮은 곳은 {low[0]}({low[2]:.1f})입니다.", {"space_after": 14}))
    if gaps:
        summary.append((f"L1-L2 보완 항목 {len(gaps)}개: " + _short([name[row.se_code] for row in gaps]) + ".",
                        {"space_after": 14}))
    if pending:
        summary.append((f"{len(pending)}개 항목은 조회가 완료되지 않아 평가를 보류했습니다.", {}))
    _set_text(slide.placeholders[11], summary, size=20)

    # 3. Key numbers
    slide = prs.slides.add_slide(layouts["Project Profile"])
    _set_text(slide.placeholders[0], "진단 결과 한눈에 보기")
    _set_text(slide.placeholders[10], [
        ("공식 읽기 API로 확인한 구성·기록을 항목별로 평가했습니다.", {"space_after": 12}),
        ("충족률 L1(0%)부터 L5(100%)까지 5단계입니다.", {}),
    ], size=16)
    for idx, text in ((11, f"{len(graded)}/{len(findings)}"), (12, f"{levels['L5']}개"), (13, f"{len(gaps)}개")):
        _set_text(slide.placeholders[idx], text)
    for idx, text in ((14, ["진단 완료", "항목"]), (15, ["최고 수준", "(L5)"]), (16, ["보완 필요", "(L1-L2)"])):
        _set_text(slide.placeholders[idx], text, size=12, color=MUTED)
    _set_text(slide.placeholders[17], "잘 갖춘 영역", size=20, bold=True, color=NAVY)
    _set_text(slide.placeholders[18],
              (_short([name[row.se_code] for row in strong], 4) + " 등 " if strong else "")
              + f"{levels['L5']}개 항목이 기준을 100% 충족합니다.", size=15, color=INK)
    _set_text(slide.placeholders[19], "먼저 보완할 영역", size=20, bold=True, color=NAVY)
    _set_text(slide.placeholders[20],
              (_short([name[row.se_code] for row in gaps], 4) + " 등 " if gaps else "")
              + (f"{len(gaps)}개 항목이 80% 미만입니다." if gaps else "80% 미만 항목이 없습니다."),
              size=15, color=INK)

    # 4. Domain maturity
    slide = prs.slides.add_slide(layouts["Header Line Blank"])
    _set_text(slide.shapes.title, "영역별 성숙도(평균 수준 1-5)")
    chart_data = CategoryChartData()
    chart_data.categories = [f"{label}\n({scored}/{len(rows)} 평가)" for label, rows, _, scored in domains]
    chart_data.add_series("평균 수준", [average or 0 for _, _, average, _ in domains])
    chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.64), Inches(1.6),
                                   Inches(8.0), Inches(5.2), chart_data).chart
    chart.has_legend = chart.has_title = False
    axis = chart.value_axis
    axis.maximum_scale, axis.minimum_scale, axis.major_unit = 5.6, 0, 1
    axis.major_gridlines.format.line.color.rgb = _rgb("E6E6E6")
    axis.format.line.fill.background()
    axis.tick_labels.font.size = Pt(12)
    axis.tick_labels.font.color.rgb = _rgb(MUTED)
    chart.category_axis.tick_labels.font.size = Pt(12)
    plot = chart.plots[0]
    plot.gap_width = 60
    plot.has_data_labels = True
    plot.data_labels.font.size = Pt(14)
    plot.data_labels.font.bold = True
    plot.data_labels.number_format = "0.0"
    plot.data_labels.number_format_is_linked = False
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    for index, (_, rows, _, scored) in enumerate(domains):
        point = plot.series[0].points[index]
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = _rgb(BLUE if scored == len(rows) else CYAN)
    notes = [("읽는 방법", {"bold": True, "size": 16, "color": NAVY, "space_after": 6}),
             ("막대는 평가한 항목의 평균 수준입니다(5=최고).", {"size": 14, "space_after": 14})]
    if ranked:
        low = min(ranked, key=lambda domain: domain[2])
        low_gaps = [name[row.se_code] for row in gaps if row.se_code.startswith(
            next(prefix for prefix, label in AREAS.items() if label == low[0]) + "-")]
        notes += [("낮은 영역", {"bold": True, "size": 16, "color": NAVY, "space_after": 6}),
                  (f"{low[0]} {low[2]:.1f}" + (": " + _short(low_gaps) + " 항목이 평균을 낮춥니다." if low_gaps else ""),
                   {"size": 14, "space_after": 14})]
    partial = [label for label, rows, _, scored in domains if scored < len(rows)]
    if partial:
        notes += [("해석 주의", {"bold": True, "size": 16, "color": NAVY, "space_after": 6}),
                  (", ".join(partial) + " 영역은 일부 항목만 평가된 값입니다.", {"size": 14})]
    _rect(slide, 9.0, 1.75, 0.08, 3.9, BLUE)
    _textbox(slide, 9.3, 1.7, 3.4, 3.9, notes)
    _rect(slide, 9.3, 5.95, 0.22, 0.22, BLUE)
    _textbox(slide, 9.62, 5.9, 3.0, 0.32, [("해당 영역 전체 항목 평가", {"size": 13, "color": MUTED})])
    _rect(slide, 9.3, 6.35, 0.22, 0.22, CYAN)
    _textbox(slide, 9.62, 6.3, 3.0, 0.32, [("일부 항목만 평가", {"size": 13, "color": MUTED})])

    # 5. Level distribution
    slide = prs.slides.add_slide(layouts["2_Title and text side by side 3"])
    _set_text(slide.placeholders[0], "등급 분포")
    _set_text(slide.placeholders[11], [
        (f"평가한 {len(graded)}개 항목의 구성·기록 충족률 기준입니다.", {"space_after": 14}),
        ("조회 실패·권한 부족은 L1이나 0점이 아닌 '평가 보류'로 구분합니다.", {}),
    ], size=16, color="FFFFFF")
    legend = [("L5", "L5 (100%)"), ("L4", "L4 (90-100%)"), ("L3", "L3 (80-90%)"),
              ("L2", "L2 (80% 미만)"), ("L1", "L1 (0%)"), ("N/A", "평가 보류")]
    chart_data = CategoryChartData()
    chart_data.categories = [label for _, label in legend]
    chart_data.add_series("항목 수", [levels[key] for key, _ in legend])
    chart = slide.shapes.add_chart(XL_CHART_TYPE.DOUGHNUT, Inches(5.3), Inches(1.0),
                                   Inches(4.6), Inches(5.4), chart_data).chart
    chart.has_legend = chart.has_title = False
    plot = chart.plots[0]
    for index, (key, _) in enumerate(legend):
        point = plot.series[0].points[index]
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = _rgb(LEVEL_COLORS[key])
        point.format.line.color.rgb = _rgb("FFFFFF")
    hole = plot._element.find(qn("c:holeSize"))
    if hole is None:
        hole = etree.SubElement(plot._element, qn("c:holeSize"))
    hole.set("val", "62")
    _textbox(slide, 6.6, 3.15, 2.0, 1.0, [
        (str(len(graded)), {"size": 40, "bold": True, "color": NAVY, "align": PP_ALIGN.CENTER}),
        (f"진단 완료 / {len(findings)}", {"size": 12, "color": MUTED, "align": PP_ALIGN.CENTER})])
    for index, (key, label) in enumerate(legend):
        y = 1.55 + index * 0.82
        _rect(slide, 10.2, y + 0.05, 0.28, 0.28, LEVEL_COLORS[key])
        _textbox(slide, 10.65, y - 0.02, 2.2, 0.45, [(label, {"size": 14, "color": "404040"})])
        _textbox(slide, 10.65, y + 0.3, 1.9, 0.5, [(f"{levels[key]}개", {"size": 22, "bold": True, "color": NAVY})])

    # 6. Priority gaps
    if gaps:
        slide = prs.slides.add_slide(layouts["Header Line Blank"])
        _set_text(slide.shapes.title, "우선 보완 항목(L1-L2)")
        shown = gaps[:6]
        _table(slide, 0.64, 1.6, (3.2, 1.5, 3.9, 3.45), ("점검 항목", "현황", "현재 수준", "다음 단계 목표"),
               [(name[row.se_code], (f"{row.level} | {_count(row)}", RED if row.level == "L1" else AMBER),
                 row.level_criterion or "-", _next_goal(row)) for row in shown],
               row_height=0.78, size=13, colored_column=1)
        if len(gaps) > len(shown):
            _textbox(slide, 0.64, 6.55, 12.05, 0.4,
                     [(f"외 {len(gaps) - len(shown)}개 항목은 Excel 보고서 6번 시트에서 확인할 수 있습니다.",
                       {"size": 12, "color": MUTED})])

    # 7. Strengths
    if strong:
        slide = prs.slides.add_slide(layouts["Header Line Blank"])
        _set_text(slide.shapes.title, f"잘 갖춘 통제: {levels['L5']}개 항목이 기준 100% 충족")
        for index, row in enumerate(strong[:6]):
            x, y = 0.64 + (index % 3) * 4.15, 1.65 + (index // 3) * 2.65
            _rect(slide, x, y, 3.75, 2.35, LIGHT)
            _rect(slide, x, y, 0.08, 2.35, TEAL)
            _textbox(slide, x + 0.3, y + 0.15, 3.3, 0.75, [(_count(row), {"size": 36, "bold": True, "color": NAVY})])
            _textbox(slide, x + 0.3, y + 0.9, 3.3, 0.6, [(name[row.se_code], {"size": 16, "bold": True})])
            _textbox(slide, x + 0.3, y + 1.6, 3.25, 0.7,
                     [(row.level_criterion or "", {"size": 13, "color": "404040"})])
        if len(strong) > 6:
            _textbox(slide, 0.64, 6.95, 12.05, 0.3,
                     [(f"외 {len(strong) - 6}개 항목도 기준을 100% 충족합니다.", {"size": 12, "color": MUTED})])

    # 8. Items pending evaluation
    if pending:
        slide = prs.slides.add_slide(layouts["Header Line Blank"])
        _set_text(slide.shapes.title, f"평가 보류 {len(pending)}개 항목")
        shown = pending[:5]
        _table(slide, 0.64, 1.6, (3.8, 6.2, 2.05), ("점검 항목", "사유", "현재 상태"),
               [(name[row.se_code], REASONS.get(row.reason or "not_found", "확인할 자료 없음"), "평가 보류")
                for row in shown], row_height=0.6, size=13)
        box_y = 1.6 + 0.45 + 0.6 * len(shown) + 0.35
        _rect(slide, 0.64, box_y, 12.05, 1.4, LIGHT)
        _rect(slide, 0.64, box_y, 0.08, 1.4, BLUE)
        causes = ", ".join(f"{REASONS.get(reason, reason)} {count}건" for reason, count in reason_counts.most_common())
        extra = f" 표에는 {len(shown)}개만 표시했고 나머지는 Excel 보고서에 있습니다." if len(pending) > len(shown) else ""
        _textbox(slide, 1.0, box_y + 0.05, 11.4, 1.3, [
            ("원인과 조치", {"size": 16, "bold": True, "color": NAVY, "space_after": 6}),
            (f"사유: {causes}. 조회 실패는 0점으로 처리하지 않고 평가 보류로 남깁니다. "
             f"권한·라이선스를 확인한 뒤 다시 점검하면 점수를 산출할 수 있습니다.{extra}", {"size": 14}),
        ], anchor=MSO_ANCHOR.MIDDLE)

    # 9. Roadmap
    slide = prs.slides.add_slide(layouts["Header Line Blank"])
    _set_text(slide.shapes.title, "개선 로드맵")
    l1 = [row for row in gaps if row.level == "L1"]
    l2 = [row for row in gaps if row.level == "L2"]
    mid = l2 + [row for row in graded if row.level in ("L3", "L4")]
    phases = [
        ("0-30일", "즉시 조치", RED, l1, "미충족(L1) 항목의 책임자 지정과 구성 적용"),
        ("30-60일", "구성 정비", BLUE, mid, "80% 미만(L2)과 L3-L4 항목의 잔여 대상 보완"),
        ("60-90일", "가시성 확대", TEAL, pending, "조회 권한·라이선스 확보 후 재점검"),
    ]
    for index, (period, label, color, rows, empty) in enumerate(phases):
        x = 0.64 + index * 4.15
        _rect(slide, x, 1.65, 3.75, 0.95, color)
        _textbox(slide, x + 0.25, 1.72, 3.3, 0.85, [(period, {"size": 26, "bold": True, "color": "FFFFFF"}),
                                                    (label, {"size": 14, "color": "FFFFFF"})],
                 anchor=MSO_ANCHOR.MIDDLE)
        _rect(slide, x, 2.6, 3.75, 4.0, LIGHT)
        bullets = [f"{name[row.se_code]} ({_count(row)})" if row.level != "N/A" else name[row.se_code]
                   for row in rows[:5]]
        if len(rows) > 5:
            bullets.append(f"외 {len(rows) - 5}개 항목")
        _textbox(slide, x + 0.25, 2.85, 3.3, 3.0,
                 [(item, {"size": 14, "bullet": True, "space_after": 10}) for item in bullets]
                 or [("해당 항목이 없습니다.", {"size": 14, "color": MUTED})])
        _textbox(slide, x + 0.25, 6.0, 3.3, 0.5, [("목표", {"size": 12, "bold": True, "color": NAVY}),
                                                  (empty, {"size": 12, "color": MUTED})])

    # 10. Decisions
    slide = prs.slides.add_slide(layouts["Header Line Blank"])
    _set_text(slide.shapes.title, "경영진 의사결정 요청")
    decisions = []
    if pending:
        decisions.append(("평가 보류 항목의 조회 권한·라이선스 확보",
                          f"{len(pending)}개 항목은 조회가 완료되지 않아 점수를 산출하지 못했습니다.",
                          "확보 후 전체 항목 재점검"))
    if gaps:
        decisions.append(("L1-L2 항목 개선 책임자 지정",
                          f"{len(gaps)}개 항목은 적용 범위와 예외 기준에 대한 승인과 담당자가 필요합니다.",
                          "지정 후 0-60일 개선 착수"))
    decisions.append(("정기 진단 승인", "읽기 전용 자동 진단을 정기적으로 실행해 개선 추이를 경영진에게 보고합니다.",
                      "다음 분기부터 정례화"))
    for index, (title, description, timing) in enumerate(decisions):
        y = 1.8 + index * 1.75
        _rect(slide, 0.64, y + 0.2, 0.9, 0.9, BLUE, shape=MSO_SHAPE.OVAL)
        _textbox(slide, 0.64, y + 0.2, 0.9, 0.9, [(str(index + 1), {"size": 30, "bold": True, "color": "FFFFFF",
                                                                  "align": PP_ALIGN.CENTER})],
                 anchor=MSO_ANCHOR.MIDDLE)
        _textbox(slide, 1.9, y, 10.7, 0.5, [(title, {"size": 20, "bold": True, "color": NAVY})])
        _textbox(slide, 1.9, y + 0.5, 10.7, 0.5, [(description, {"size": 15, "color": "404040"})])
        _textbox(slide, 1.9, y + 1.05, 10.7, 0.35, [(timing, {"size": 13, "bold": True, "color": BLUE})])

    # 11. Appendix
    slide = prs.slides.add_slide(layouts["Header Line Blank"])
    _set_text(slide.shapes.title, "부록: 진단 범위와 해석 시 유의사항")
    _table(slide, 0.64, 1.6, (2.2, 9.85), ("구분", "내용"), [
        ("진단 범위", f"Azure 구독 {len(data.subscriptions)}개, Azure Agent {len(azure_agents(data))}개. "
                  f"점검 항목은 System Evidence {len(findings)}개입니다."),
        ("수집 방식", "읽기 전용 권한(Reader 중심)으로 공식 API만 조회합니다. 쓰기·삭제·배포를 하지 않고 "
                  "비밀·토큰·개인 식별 정보는 저장하지 않습니다."),
        ("평가 기준", "API로 확인한 구성·기록의 충족률로 L1(0%)부터 L5(100%)까지 부여합니다. 조회 실패는 평가 보류로 남깁니다."),
        ("해석 한계", "L5는 해당 구성의 충족률 100%이며 정책의 실효성이나 조직 전체의 성숙도를 증명하지 않습니다."),
        ("세부 자료", "항목별 계산값·대상별 판정·증적은 Excel 보고서 6~7번 시트와 원본 JSON에서 확인할 수 있습니다."),
    ], row_height=0.95, size=14)

    # 12. Closing
    slide = prs.slides.add_slide(layouts["End Slide Color Bkg"])
    _set_text(slide.shapes.title, "감사합니다")

    prs.save(path)
