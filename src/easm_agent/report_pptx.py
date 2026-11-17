"""Executive PowerPoint report built on the corporate assessment deck template.

The deck is generated from the filled assessment workbook, so System Evidence scores and
interview scores entered in the workbook are reflected together.
"""

from __future__ import annotations

import copy
import re
import sysconfig
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from easm_agent.deck_model import (
    AREAS,
    KINDS,
    TARGET_LEVEL,
    Assessment,
    Item,
    level_of,
    read_assessment,
)
from easm_agent.deck_xml import (
    Page,
    duplicate_slide,
    place,
    set_fill,
    set_outline,
    set_text,
)
from easm_agent.report_template import COLLECTION_METHODS

TEMPLATE_NAME = "assessment-report-template.pptx"
DEFAULT_CUSTOMER = "<고객사>"
PRESENTATION_FONT = "맑은 고딕"
LEVEL_COLORS = ["D13438", "F2A900", "107C10", "008575", "00566B"]
PASTEL = ["F4C7C3", "FCE8B2", "CDE8C4", "B7E1DD", "A9CCE3"]
PASTEL_TEXT = ["7A1F1F", "6B4A00", "1E5B1E", "0B5A52", "0B3F58"]
GRAY = "9AA0A6"
KIND_NAMES = {"PR": "프로세스", "PE": "사람·조직", "DA": "데이터·기록", "TE": "도구·기술", "SY": "시스템 실측"}
KIND_SHORT = {"PR": "Process", "PE": "People", "DA": "Data", "TE": "Tech", "SY": "SE"}


@dataclass
class DeckContext:
    customer: str = DEFAULT_CUSTOMER
    collected_at: datetime | None = None
    subscriptions: int | None = None
    agents: int | None = None


def presentation_template_path() -> Path:
    source = Path(__file__).resolve().parents[2] / "docs" / TEMPLATE_NAME
    installed = Path(sysconfig.get_path("data")) / "share" / "easm-agent" / TEMPLATE_NAME
    path = source if source.is_file() else installed
    if not path.is_file():
        raise FileNotFoundError(f"보고서 PPT 템플릿을 찾을 수 없습니다: {path}")
    return path


def apply_presentation_font(path: Path) -> None:
    """Apply the report font to slides, tables, charts, layouts and themes."""
    output = BytesIO()
    with ZipFile(path) as source, ZipFile(output, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename.endswith(".xml"):
                root = etree.fromstring(content)
                for node in root.iter():
                    if "typeface" in node.attrib:
                        node.set("typeface", PRESENTATION_FONT)
                content = etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
            target.writestr(info, content)
    path.write_bytes(output.getvalue())


def context_from_workbook(workbook: Path, customer: str = DEFAULT_CUSTOMER) -> DeckContext:
    context = DeckContext(customer=customer)
    stamp = re.search(r"(\d{8}T\d{6})\d*Z", workbook.name)
    if stamp:
        context.collected_at = datetime.strptime(stamp[1], "%Y%m%dT%H%M%S")
    match = re.search(r"구독 (\d+)개, Azure Agent (\d+)개", read_assessment(workbook).summary)
    if match:
        context.subscriptions, context.agents = int(match[1]), int(match[2])
    return context


# --- content helpers -------------------------------------------------------------------------

def clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,.·(") + "…"


def area_label(prefix: str, short: bool = False) -> str:
    for code, _sheet, korean, english, _description in AREAS:
        if code == prefix:
            return korean if short else f"{korean} ({english})"
    return prefix


def color_of(level: int | None) -> str:
    return LEVEL_COLORS[level - 1] if level else GRAY


def tint(color: str, amount: float = 0.3) -> str:
    parts = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return "".join(f"{int(v + (255 - v) * amount):02X}" for v in parts)


def on_color(level: int | None) -> str:
    """Readable text color for a Level fill (amber needs dark text)."""
    return "2B2100" if level == 2 else "FFFFFF"


def level_text(assessment: Assessment, level: int | None) -> str:
    return f"Level {level} {assessment.level_names[level - 1]}" if level else "판정 보류"


def counts(assessment: Assessment) -> dict[str, int]:
    system, interview = assessment.system_items, assessment.interview_items
    return {
        "se_total": len(system), "se_scored": sum(i.score is not None for i in system),
        "int_total": len(interview), "int_scored": sum(i.score is not None for i in interview),
    }


def is_provisional(assessment: Assessment) -> bool:
    return assessment.overall_status != "6개 영역 집계"


def next_condition(item: Item) -> str:
    if item.score is None:
        return item.levels[int(TARGET_LEVEL) - 1]
    return "현재 수준 유지" if item.score >= 5 else item.levels[item.score]


def pick_distinct(items: list[Item], count: int = 3) -> list[Item]:
    chosen: list[Item] = []
    seen: set[str] = set()
    for item in items:
        if item.area not in seen:
            chosen.append(item)
            seen.add(item.area)
        if len(chosen) == count:
            return chosen
    for item in items:
        if item not in chosen:
            chosen.append(item)
        if len(chosen) == count:
            break
    return chosen


def priority_items(assessment: Assessment, prefix: str, limit: int) -> list[Item]:
    rows = [item for item in assessment.items if item.area == prefix]
    scored = sorted((i for i in rows if i.score is not None), key=lambda i: (i.score, i.is_system, i.code))
    below = [i for i in scored if i.score < 4]
    unscored = [i for i in rows if i.score is None]
    return (below + unscored + [i for i in scored if i not in below])[:limit]


def node_ids(nodes) -> list[int]:
    return [int(node.find(".//" + qn("p:cNvPr")).get("id")) for node in nodes]


def paragraphs_of(shape):
    node = getattr(shape, "_element", shape)
    body = node.find(qn("p:txBody"))
    return (body if body is not None else node.find(qn("a:txBody"))).findall(qn("a:p"))


def align(shape, value: str) -> None:
    for paragraph in paragraphs_of(shape):
        properties = paragraph.find(qn("a:pPr"))
        if properties is None:
            properties = paragraph.makeelement(qn("a:pPr"), {})
            paragraph.insert(0, properties)
        properties.set("algn", value)


def restyle(paragraph, size=None, bold=None) -> None:
    for run in paragraph.findall(qn("a:r")):
        properties = run.find(qn("a:rPr"))
        if size:
            properties.set("sz", str(int(size * 100)))
        if bold is not None:
            properties.set("b", "1" if bold else "0")


def centered_label(shape, text: str, size: float, color: str) -> None:
    body = shape.find(qn("p:txBody")).find(qn("a:bodyPr"))
    for key, value in (("anchor", "ctr"), ("lIns", "0"), ("rIns", "0"), ("tIns", "0"), ("bIns", "0")):
        body.set(key, value)
    set_text(shape, text, size=size, color=color, bold=True)
    align(shape, "ctr")


# --- deck ------------------------------------------------------------------------------------

def write_presentation(workbook: Path, output: Path, context: DeckContext | None = None) -> None:
    context = context or context_from_workbook(workbook)
    assessment = read_assessment(workbook)
    prs = Presentation(presentation_template_path())
    originals = list(prs.slides)
    cover, agenda, status, key, method, matrix, heat, area_base, plan = originals[:9]
    appendix = duplicate_slide(prs, matrix)
    area_slides = [duplicate_slide(prs, area_base) for _ in AREAS]

    build_cover(cover, context)
    build_agenda(agenda)
    build_status(status, assessment, context)
    build_key(key, assessment)
    build_method(method, assessment)
    build_matrix(matrix, assessment)
    build_heatmap(heat, assessment)
    for slide, (prefix, *_rest) in zip(area_slides, AREAS, strict=True):
        build_area(slide, assessment, prefix)
    build_plan(plan, assessment)
    build_appendix(appendix, assessment)

    order = [cover, agenda, status, key, method, matrix, heat, *area_slides, plan, appendix]
    id_list = prs.slides._sldIdLst
    elements = {slide.slide_id: node for slide, node in zip(prs.slides, list(id_list), strict=True)}
    keep = [slide.slide_id for slide in order]
    for node in list(id_list):
        id_list.remove(node)
    for slide_id in keep:
        id_list.append(elements[slide_id])
    for slide_id, node in elements.items():
        if slide_id not in keep:
            prs.part.drop_rel(node.get(qn("r:id")))
    # Sections would still point at the removed template slides and make PowerPoint repair the file.
    for ext in list(prs.part._element.iter(qn("p:ext"))):
        if ext.find("{http://schemas.microsoft.com/office/powerpoint/2010/main}sectionLst") is not None:
            ext.getparent().remove(ext)
    format_appendix_tables(prs)
    prs.save(output)
    apply_presentation_font(output)


def build_cover(slide, context: DeckContext) -> None:
    page = Page(slide)
    set_text(page(9), ["EASM (Enterprise Agent", "Service Management)", "점검 결과 보고서"], size=34)
    place(page(9), y=2.6, h=2.3)
    place(page(10), y=5.1)
    set_text(page(10), ["Prepared for", context.customer])


def build_agenda(slide) -> None:
    page = Page(slide)
    set_text(page(3), "EASM ASSESSMENT")
    rows = [
        (99, 101, "점검 대상 현황", "점검 범위, 평가 구성 및 진행 현황"),
        (107, 109, "핵심 진단 결과", "종합 성숙도 및 핵심 시사점"),
        (115, 117, "진단 방법", "평가 영역, 관점 및 5단계 척도"),
        (123, 125, "영역별 성숙도 평가", "6개 영역 × 5개 관점 평가 결과"),
        (131, 133, "개선 권고사항", "영역별 우선 개선 항목"),
        (139, 141, "후속 실행 계획", "영역별 후속 실행 과제"),
        (147, 149, "부록", "평가 보류 및 인터뷰 미입력 현황"),
    ]
    for title_id, sub_id, title, sub in rows:
        set_text(page(title_id), title)
        set_text(page(sub_id), sub)
    page.delete(151, 153, 155, 157)


def build_status(slide, assessment: Assessment, context: DeckContext) -> None:
    page = Page(slide)
    c = counts(assessment)
    set_text(page(6), "EASM 점검 결과")
    set_text(page(7), "점검 대상 현황")
    set_text(page(9), clip(context.customer, 12))
    date = context.collected_at.strftime("%Y-%m-%d") if context.collected_at else "-"
    scope = (f"Azure 구독 {context.subscriptions}개 · Agent {context.agents}개"
             if context.subscriptions is not None else "-")
    level = level_of(assessment.overall)
    overall = "판정 보류" if not level else (
        f"{level_text(assessment, level)} ({assessment.overall:.1f}점)" + (" 잠정" if is_provisional(assessment) else ""))
    for label_id, value_id, label, value in (
        (11, 12, "점검 일자", date), (14, 15, "점검 범위", scope), (17, 18, "종합 성숙도", overall),
    ):
        set_text(page(label_id), label)
        set_text(page(value_id), value)
    pending = c["se_total"] - c["se_scored"]
    l5 = sum(i.score == 5 for i in assessment.system_items)
    low = sum(i.score is not None and i.score <= 2 for i in assessment.system_items)
    unfilled = c["int_total"] - c["int_scored"]
    by_area = ", ".join(f"{area_label(a.prefix, True)} {a.interview_scored}/{a.interview_total}"
                        for a in assessment.areas.values())
    boxes = [
        (22, 23, "System Evidence 수집 현황", [
            f"{c['se_total']}개 중 {c['se_scored']}개 진단, {pending}개 평가 보류",
            f"충족률 100%(Level 5) {l5}개, Level 1-2 {low}개",
            "조회 실패·미확인은 0점이 아닌 '평가 보류'로 구분",
        ]),
        (27, 28, "인터뷰 진행 현황", [
            f"인터뷰 {c['int_total']}개 중 답변 완료 {c['int_scored']}개",
            "영역별 답변 완료: " + by_area,
            "Excel 6번 시트 M열에 1~5점 입력 후 보고서 재생성" if unfilled else "인터뷰 전체 답변 완료",
        ]),
        (32, 33, "점검 범위와 방식", [
            "읽기 전용 공식 API로 구성·기록 확인(쓰기·삭제·배포 없음)",
            "6개 영역 × 5개 관점(Process·People·Data·Technology·System Evidence)",
            "영역 점수는 인터뷰 4개 관점 평균, 실측과 1.5점 이상 괴리 시 보정",
        ]),
        (37, 38, "제약 및 고려사항", [
            "Level 5는 구성·기록의 충족이며 정책의 실효성을 증명하지 않음",
            "인터뷰 미입력 영역의 점수는 실측 기준 잠정값" if unfilled else "인터뷰·실측 점수를 함께 반영",
            "Level 3 이상은 문서 증적, Level 4 이상은 시스템 증적 필요",
        ]),
    ]
    for title_id, body_id, title, lines in boxes:
        set_text(page(title_id), title)
        set_text(page(body_id), lines, size=10)
    set_text(page(40), "성숙도 5단계:  " + "  ·  ".join(
        f"L{n} {name}" + ("(목표 최소)" if n == 3 else "") for n, name in enumerate(assessment.level_names, 1)))


def build_key(slide, assessment: Assessment) -> None:
    page = Page(slide)
    c = counts(assessment)
    level = level_of(assessment.overall)
    color = color_of(level)
    chip_selected = [copy.deepcopy(page(16)), copy.deepcopy(page(17))]
    chip_other = [copy.deepcopy(page(18)), copy.deepcopy(page(19))]
    page.delete(*range(16, 24))
    set_fill(page(8), color)
    ink = on_color(level)
    set_text(page(9), "종합 성숙도" + (" (잠정)" if is_provisional(assessment) else ""), color=ink)
    set_text(page(10), f"Level {level}" if level else "판정 보류", size=40 if level else 30, color=ink)
    set_text(page(11), (assessment.level_names[level - 1] + f" · {assessment.overall:.1f}점") if level else "-",
             color=ink)
    set_text(page(12), assessment.level_definitions[level - 1] if level else "점수가 산출된 영역이 없습니다.",
             color=ink)
    gap = None if assessment.overall is None else round(TARGET_LEVEL - assessment.overall, 1)
    set_text(page(13), "목표 대비", color=ink)
    set_text(page(14), "목표 Level 3 달성" if gap is None or gap > 0 else "목표 Level 3 충족", size=15, color=ink)
    set_text(page(15), "→ 갭이 큰 영역부터 개선" if gap is None or gap > 0 else "→ 현재 수준 유지·고도화",
             color=ink)
    for n in range(1, 6):
        shape, text = (copy.deepcopy(node) for node in (chip_selected if level == n else chip_other))
        page.add(shape)
        page.add(text)
        x = 0.93 + (n - 1) * 0.66
        place(shape, x, 6.27, 0.56, 0.34)
        place(text, x, 6.27, 0.56, 0.34)
        set_fill(shape, "FFFFFF" if level == n else tint(color, 0.3))
        set_text(text, str(n), color=color if level == n else "FFFFFF")
    scored = [i for i in assessment.items if i.score is not None]
    strong = pick_distinct(sorted(scored, key=lambda i: (-i.score, i.is_system, i.code)))
    weak = pick_distinct(sorted(scored, key=lambda i: (i.score, i.is_system, i.code)))
    set_text(page(25), clip(
        f"System Evidence {c['se_scored']}/{c['se_total']} 진단, 인터뷰 답변 완료 {c['int_scored']}/{c['int_total']}개"
        + (" - 인터뷰 입력 후 종합 성숙도가 확정됩니다." if c["int_scored"] < c["int_total"] else ""), 80))
    for text_id, item in zip((31, 33, 35), strong + [None] * 3, strict=False):
        set_text(page(text_id), f"{clip(item.title, 32)} (Level {item.score})" if item else "해당 항목 없음")
    for text_id, item in zip((37, 39, 41), weak + [None] * 3, strict=False):
        set_text(page(text_id), f"{clip(item.title, 32)} (Level {item.score})" if item else "해당 항목 없음")
    ranked = sorted((a for a in assessment.areas.values() if a.final is not None and (a.gap or 0) > 0),
                    key=lambda a: -(a.gap or 0))
    steps = []
    for area in ranked[:3]:
        top = priority_items(assessment, area.prefix, 1)
        steps.append((area_label(area.prefix, True) + " 영역 보완",
                      f"현재 {area.final:.1f} → 목표 {TARGET_LEVEL:.1f}. " + (clip(top[0].title, 30) if top else "")))
    if c["int_scored"] < c["int_total"] and len(steps) < 3:
        steps.append(("인터뷰 점수 입력", f"미입력 {c['int_total'] - c['int_scored']}개를 입력해 영역 점수 확정"))
    if c["se_scored"] < c["se_total"] and len(steps) < 3:
        steps.append(("평가 보류 재점검", f"{c['se_total'] - c['se_scored']}개 항목 조회 권한·라이선스 확인"))
    while len(steps) < 3:
        steps.append(("정기 재점검", "분기별 재점검으로 개선 추이 확인"))
    set_text(page(43), "목표 Level 3 대비 갭이 큰 순서")
    for (title_id, desc_id), (title, desc) in zip(((45, 46), (49, 50), (53, 54)), steps, strict=True):
        set_text(page(title_id), clip(title, 14))
        set_text(page(desc_id), clip(desc, 52))


def build_method(slide, assessment: Assessment) -> None:
    page = Page(slide)
    set_text(page(6), "EASM 평가 방식")
    set_text(page(8), "6대 평가 영역 × 5개 관점")
    rows = [(10, 11, 12, 13), (14, 15, 16, 17), (18, 19, 20, 21), (22, 23, 24, 25), (26, 27, 28, 29)]
    rows.append(tuple(node_ids(page.clone([26, 27, 28, 29]))))
    for index, ((circle, icon, title, desc), area) in enumerate(zip(rows, AREAS, strict=True)):
        y = 2.0 + index * 0.88
        place(page(circle), y=y + 0.08)
        place(page(icon), y=y + 0.185)
        place(page(title), y=y)
        place(page(desc), y=y + 0.34)
        set_text(page(title), f"{index + 1}. {area[2]} ({area[3]})")
        set_text(page(desc), area[4])
    place(page(9), y=2.3, h=4.35)
    set_text(page(30), "5단계 성숙도 척도로 평가")
    stairs = [(31, 32, 33), (34, 35, 36), (37, 38, 39), (40, 41, 42)]
    stairs.append(tuple(node_ids(page.clone([40, 41, 42]))))
    for index, (shape, title, desc) in enumerate(stairs):
        y, width = 2.2 + index * 1.0, 2.2 + index * 0.75
        place(page(shape), y=y, w=width, h=0.86)
        place(page(title), y=y + 0.1, w=width - 0.5)
        place(page(desc), y=y + 0.47, w=width - 0.5)
        set_fill(page(shape), LEVEL_COLORS[index])
        ink = on_color(index + 1)
        set_text(page(title), f"Level {index + 1} {assessment.level_names[index]}"
                 + (" (목표 최소)" if index == 2 else ""), color=ink)
        set_text(page(desc), assessment.level_keywords[index], color=ink)


def build_matrix(slide, assessment: Assessment) -> None:
    page = Page(slide)
    level = level_of(assessment.overall)
    set_text(page(6), "평가 영역별 종합 현황")
    set_text(page(7), "영역별 성숙도 평가")
    set_text(page(9), "성숙도 척도")
    legend = [(10, 11), (12, 13), (14, 15), (16, 17), tuple(node_ids(page.clone([16, 17])))]
    for index, (square, label) in enumerate(legend):
        x = 1.85 + index * 1.4
        place(page(square), x)
        place(page(label), x + 0.27, w=1.1)
        set_fill(page(square), LEVEL_COLORS[index])
        set_text(page(label), f"Level {index + 1}")
    scored_areas = [a for a in assessment.areas.values() if a.final is not None]
    set_text(page(18), (
        f"종합 {level_text(assessment, level)}" + (" (잠정)" if is_provisional(assessment) else "")
        + ". 영역 점수는 인터뷰 4개 관점 평균이며 실측과 1.5점 이상 차이 나면 실측+1.0으로 보정합니다. "
        "인터뷰 미입력 영역은 실측 기준 잠정값입니다.") if scored_areas else "산출된 영역 점수가 없습니다.")
    set_fill(page(19), color_of(level))
    ink = on_color(level)
    set_text(page(20), "종합 수준" + (" (잠정)" if is_provisional(assessment) else ""), color=ink)
    set_text(page(21), level_text(assessment, level), size=18, color=ink)
    set_text(page(22), (f"종합 {assessment.overall:.1f}점 · " if assessment.overall is not None else "")
             + (assessment.level_keywords[level - 1] if level else "인터뷰·실측 점수 입력 필요"), color=ink)
    set_text(page(23), "진단 항목 레벨 분포")
    chart = [s for s in slide.shapes if s.shape_id == 24][0].chart
    data = CategoryChartData()
    data.categories = [f"Level {n}" for n in range(1, 6)]
    data.add_series("항목 수", [sum(i.score == n for i in assessment.items) for n in range(1, 6)])
    chart.replace_data(data)
    labels = chart.plots[0].series[0].data_labels
    labels.show_value, labels.show_category_name, labels.show_percentage = True, False, False
    labels.show_legend_key = False
    labels.font.size = Pt(9)
    labels.font.bold = True
    labels.font.color.rgb = RGBColor.from_string("FFFFFF")
    for index in range(5):
        point = chart.plots[0].series[0].points[index]
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = RGBColor.from_string(LEVEL_COLORS[index])
    rows = []
    for prefix, *_rest in AREAS:
        area = assessment.areas[prefix]
        text = f"{area.final:.1f}점 · {area.status}" if area.final is not None else "판정 보류"
        rows.append([
            area_label(prefix), level_text(assessment, area.level),
            f"{text} | 실측 {area.system_scored}/{area.system_total} · 답변 완료 {area.interview_scored}/{area.interview_total}",
            area.level,
        ])
    fill_table(slide, 26, ["평가 영역", "성숙도", "점수 · 근거"], rows, [2.5, 1.5, 4.2], 0.6, chip_column=1)


def fill_table(slide, shape_id: int, header, rows, widths, row_height, chip_column=None) -> None:
    frame = [s for s in slide.shapes if s.shape_id == shape_id][0]
    table = frame._element.find(".//" + qn("a:tbl"))
    trs = table.findall(qn("a:tr"))
    proto = copy.deepcopy(trs[1])
    for tr in trs[1:]:
        table.remove(tr)
    for tc, text in zip(trs[0].findall(qn("a:tc")), header, strict=True):
        set_text(tc, text)
    for grid, width in zip(table.find(qn("a:tblGrid")).findall(qn("a:gridCol")), widths, strict=True):
        grid.set("w", str(int(width * 914400)))
    trs[0].set("h", str(int(0.4 * 914400)))
    for values in rows:
        row = copy.deepcopy(proto)
        row.set("h", str(int(row_height * 914400)))
        for column, (tc, text) in enumerate(zip(row.findall(qn("a:tc")), values[:3], strict=True)):
            if chip_column == column:
                set_fill(tc, color_of(values[3]))
                set_text(tc, text, color=on_color(values[3]), bold=True)
            else:
                set_fill(tc, "FFFFFF")
                set_text(tc, text)
        table.append(row)
    place(frame, w=sum(widths), h=0.4 + row_height * len(rows))


def format_appendix_tables(prs) -> None:
    """Keep appendix questions left-aligned and separate every item identifier from its score."""
    for slide in prs.slides:
        for shape in slide.shapes:
            if not shape.has_table:
                continue
            table = shape.table
            headers = [cell.text.strip() for cell in table.rows[0].cells]
            score_headers = {
                "항목 · 실측 점수": ("수집 항목", "실측 점수"),
                "문항 · 평가 점수": ("인터뷰 질문", "평가 점수"),
            }
            split = score_headers.get(headers[0])
            if len(headers) == 3 and split and headers[1] == split[0]:
                old_width = table.columns[0].width
                code_width, score_width = Inches(1.15), Inches(1)
                item_width = table.columns[1].width - (code_width + score_width - old_width)
                if item_width <= 0:
                    raise ValueError("수집 항목 열의 너비가 부족합니다.")
                grid = table._tbl.find(qn("a:tblGrid"))
                columns = list(grid)
                columns[0].set("w", str(code_width))
                columns[1].set("w", str(item_width))
                grid.insert(1, etree.Element(qn("a:gridCol"), w=str(score_width)))
                for index, row in enumerate(table._tbl.findall(qn("a:tr"))):
                    first = row.find(qn("a:tc"))
                    score = copy.deepcopy(first)
                    if index == 0:
                        set_text(first, "항목")
                        set_text(score, split[1])
                    else:
                        code, separator, level = table.cell(index, 0).text.partition("\n")
                        if not separator:
                            raise ValueError("점수와 항목 번호를 구분할 수 없습니다.")
                        set_text(first, code)
                        set_text(score, level)
                    align(score, "ctr")
                    first.addnext(score)
                headers = [cell.text.strip() for cell in table.rows[0].cells]
            for column, header in enumerate(headers):
                if header not in ("인터뷰 질문", "수집 항목"):
                    continue
                for row in table.rows:
                    align(row.cells[column]._tc, "l")


def build_heatmap(slide, assessment: Assessment) -> None:
    page = Page(slide)
    panel, strip, header = (copy.deepcopy(page(i)) for i in (13, 14, 15))
    cell, cell_text = copy.deepcopy(page(16)), copy.deepcopy(page(17))
    square, square_text = copy.deepcopy(page(5)), copy.deepcopy(page(6))
    page.delete(*range(5, 90))
    set_text(page(2), "EASM 점검 — 영역별 세부 항목 평가")
    set_text(page(4), "항목 점수 (Level 1-5)")
    for index in range(6):
        x = 7.95 + index * 0.85
        marker, label = copy.deepcopy(square), copy.deepcopy(square_text)
        page.add(marker)
        page.add(label)
        place(marker, x, 0.58)
        place(label, x + 0.27, 0.56, 0.55)
        fill, line, text = (PASTEL[index], LEVEL_COLORS[index], f"L{index + 1}") if index < 5 else (
            "F2F2F2", "B0B0B0", "미평가")
        set_fill(marker, fill)
        set_outline(marker, line)
        set_text(label, text)
    for index, (prefix, *_rest) in enumerate(AREAS):
        x, y = 0.40 + (index % 3) * 4.24, 1.14 + (index // 3) * 2.98
        area = assessment.areas[prefix]
        for node, height in ((panel, 2.84), (strip, 0.42)):
            copy_node = copy.deepcopy(node)
            page.add(copy_node)
            place(copy_node, x, y, 4.04, height)
        head = copy.deepcopy(header)
        page.add(head)
        place(head, x + 0.1, y, 3.84, 0.42)
        set_text(head, area_label(prefix) + (f" · {area.final:.1f}점" if area.final is not None else ""))
        for row_index, (kind, _label) in enumerate(KINDS):
            row_y = y + 0.52 + row_index * 0.46
            label = copy.deepcopy(cell_text)
            page.add(label)
            place(label, x + 0.08, row_y, 0.7, 0.4)
            set_text(label, KIND_SHORT[kind], size=8, color="595959", bold=True)
            align(label, "l")
            for col, item in enumerate(i for i in assessment.items if i.area == prefix and i.kind == kind):
                shape, text = copy.deepcopy(cell), copy.deepcopy(cell_text)
                page.add(shape)
                page.add(text)
                cx = x + 0.82 + col * 0.45
                place(shape, cx, row_y, 0.42, 0.4)
                place(text, cx, row_y, 0.42, 0.4)
                if item.score is None:
                    set_fill(shape, "F2F2F2")
                    set_outline(shape, "B0B0B0")
                    set_text(text, [item.number, "-"], size=8, color="808080")
                else:
                    set_fill(shape, PASTEL[item.score - 1])
                    set_outline(shape, LEVEL_COLORS[item.score - 1])
                    set_text(text, [item.number, str(item.score)], size=8, color=PASTEL_TEXT[item.score - 1])
                    restyle(paragraphs_of(text)[1], size=11, bold=True)
    set_text(page(90), "셀: 항목 번호 / 점수(Level). 회색은 인터뷰 미입력 또는 평가 보류 항목입니다.")


def build_area(slide, assessment: Assessment, prefix: str) -> None:
    page = Page(slide)
    area = assessment.areas[prefix]
    set_text(page(6), "개선 권고사항")
    set_text(page(7), area_label(prefix))
    extra_segment, extra_label = node_ids(page.clone([14, 15]))
    segments, labels = [8, 10, 12, 14, extra_segment], [9, 11, 13, 15, extra_label]
    bounds = [1.0, 1.5, 2.5, 3.5, 4.5, 5.0]

    def position(score: float) -> float:
        return 0.60 + (score - 1.0) / 4.0 * 12.13

    for index, (segment, label) in enumerate(zip(segments, labels, strict=True)):
        left, right = position(bounds[index]), position(bounds[index + 1])
        place(page(segment), left, w=right - left)
        place(page(label), left + 0.04, w=max(right - left - 0.08, 0.7))
        set_fill(page(segment), LEVEL_COLORS[index])
        set_text(page(label), f"L{index + 1} {assessment.level_names[index]}", color=LEVEL_COLORS[index])
        align(page(label), "l")
    if area.final is not None:
        px = position(area.final)
        place(page(16), px - 0.02)
        place(page(17), min(max(px - 2.2, 0.6), 12.73 - 4.4), w=4.4)
        label = f"{level_text(assessment, area.level)} · {area.final:.1f}점" + (
            "" if area.status in ("미보정", "인터뷰-실측 괴리") else " (잠정)")
        set_text(page(17), label, color=color_of(area.level))
        align(page(17), "ctr" if 2.8 < px < 10.5 else "l" if px <= 2.8 else "r")
    else:
        page.delete(16)
        place(page(17), 0.6, w=12.13)
        set_text(page(17), "점수 미산정 - 인터뷰 점수와 System Evidence가 모두 없습니다.", color="595959")
    items = priority_items(assessment, prefix, 5)
    for index in range(5):
        ids = list(range(54 + 16 * index, 70 + 16 * index, 2))
        if index >= len(items):
            page.delete(*ids)
            continue
        _card, accent, circle, icon, title, sub, desc, ref = ids
        item = items[index]
        page.delete(icon)
        set_fill(page(accent), color_of(item.score))
        set_fill(page(circle), color_of(item.score))
        centered_label(page(circle), f"L{item.score}" if item.score else "-", 11, on_color(item.score))
        set_text(page(title), clip(item.title, 17) if item.is_system else item.code, size=12)
        state = f" · Level {item.score}" if item.score else (" · 평가 보류" if item.is_system else " · 미입력")
        set_text(page(sub), ("실측" if item.is_system else KIND_NAMES[item.kind]) + state)
        if item.is_system:
            first = f"현재: {item.levels[item.score - 1]}" if item.score else "조회 결과가 확보되지 않아 평가 보류"
        else:
            first = item.title
        second = ("다음 단계: " + next_condition(item)) if item.score else ("목표 Level 3: " + item.levels[2])
        set_text(page(desc), [clip(first, 70), clip(second, 70)], size=9.5)
        evidence = COLLECTION_METHODS.get(item.code) if item.is_system else item.evidence
        set_text(page(ref), ["확인 증적", clip(evidence or "-", 70)], size=9)
        restyle(paragraphs_of(page(ref))[0], size=9, bold=True)


def build_plan(slide, assessment: Assessment) -> None:
    page = Page(slide)
    set_text(page(88), "영역별 후속 실행 과제: 목표 Level 3 대비 갭이 큰 항목부터 개선합니다.")
    groups = [[118 + 10 * k + 2 * j for j in range(5)] for k in range(5)]
    groups.append(node_ids(page.clone(groups[4])))
    for index, (ids, area) in enumerate(zip(groups, AREAS, strict=True)):
        header, circle, number, title, body = ids
        x = 0.35 + index * 2.13
        place(page(header), x, w=2.03)
        place(page(circle), x + 0.12)
        place(page(number), x + 0.12)
        place(page(title), x + 0.5, w=1.45)
        place(page(body), x + 0.02, w=1.98)
        set_text(page(number), str(index + 1))
        set_text(page(title), area[2])
        lines = [f"{clip(item.title, 16) if item.is_system else item.code}: " + clip(next_condition(item), 40)
                 for item in priority_items(assessment, area[0], 4) if item.score is not None and item.score < 5]
        unfilled = sum(i.score is None and not i.is_system for i in assessment.items if i.area == area[0])
        pending = sum(i.score is None and i.is_system for i in assessment.items if i.area == area[0])
        if unfilled:
            lines.append(f"인터뷰 {unfilled}개 점수 입력")
        if pending:
            lines.append(f"평가 보류 {pending}개 조회 권한·라이선스 확인 후 재점검")
        set_text(page(body), lines or ["현재 수준 유지·고도화"], size=10.5)


def build_appendix(slide, assessment: Assessment) -> None:
    page = Page(slide)
    page.delete(*range(9, 24))
    set_text(page(6), "부록")
    set_text(page(7), "평가 보류 및 인터뷰 미입력 현황")
    rows: list[list] = []
    pending = [i for i in assessment.system_items if i.score is None]
    for item in pending[:6]:
        reason = re.search(r"조회 제한: ([^\n]+)", item.detail)
        rows.append([item.code, clip(item.title, 40), clip(reason[1] if reason else item.status or "조회 결과 없음", 60), None])
    if len(pending) > 6:
        rows.append(["외", f"{len(pending) - 6}개 항목", "Excel 6번 시트에서 확인", None])
    if not pending:
        rows.append(["System Evidence", "평가 보류 없음", "전체 항목 진단 완료", None])
    for area in assessment.areas.values():
        missing = area.interview_total - area.interview_scored
        if missing:
            rows.append([f"인터뷰 · {area_label(area.prefix, True)}", f"답변 완료 {area.interview_scored}/{area.interview_total}개",
                         f"미입력 {missing}개 - Excel 6번 시트 M열에 1~5점 입력", None])
    fill_table(slide, 26, ["구분", "항목", "상태 · 조치"], rows, [2.4, 3.6, 6.1], 0.34)
