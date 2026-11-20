from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from lxml import etree
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pptx.util import Inches, Pt

from easm_agent import report_narrative as story
from easm_agent.cli import main
from easm_agent.deck_model import (
    LEVEL_NAMES,
    Assessment,
    Item,
    compute_scores,
    level_of,
    read_assessment,
)
from easm_agent.interview_samples import SAMPLES
from easm_agent.models import (
    Agent365Package,
    Collection,
    CostRecord,
    Finding,
    Issue,
    SecurityRecommendation,
    load_criteria,
)
from easm_agent.report import load_result
from easm_agent.report_backdata import ReportMetric, metrics_by_key
from easm_agent.report_excel import refresh_interview_summary
from easm_agent.report_interviews import (
    main as interview_responses_main,
)
from easm_agent.report_interviews import (
    write_interview_responses,
)
from easm_agent.report_pptx import (
    FOOTERS,
    TEMPLATE_NAME,
    DeckContext,
    build_cover,
    build_creation,
    build_identity,
    build_matrix,
    build_method,
    build_next,
    build_operations,
    build_overview,
    build_plan,
    build_scores,
    build_security,
    build_summary,
    context_from_workbook,
    notes_text,
    presentation_template_path,
    replace_text,
    write_presentation,
)
from easm_agent.report_story import DOMAINS, DeckData, em, fit, money, monthly_counts, pct
from easm_agent.report_template import RESULT_SHEET
from easm_agent.report_terms import GLOSSARY

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "three_subscriptions.json"
CODES = tuple(load_criteria()["items"])
NOW = datetime(2026, 11, 19, 7, 55, tzinfo=UTC)
FORBIDDEN = re.compile(
    r"N/A|feature_unavailable|not_found|permission_denied|license_missing|Excel|Backdata|증적 색인|"
    r"가상|예시|실제 고객|실측 별도|API 증적 별도|사유 코드"
)


def item(code: str, score: int | None) -> Item:
    return Item(code=code, area=code[:2], kind=code[3:5], row=5, text=code, levels=[""] * 5,
                evidence="", score=score, status="", detail="", memo="")


def area_items(prefix: str, interview: int | None, system: int | None) -> list[Item]:
    return [item(f"{prefix}-PR-01", interview), item(f"{prefix}-PE-02", interview),
            item(f"{prefix}-DA-03", interview), item(f"{prefix}-TE-04", interview),
            item(f"{prefix}-SE-05", system)]


def deck_text(path: Path) -> str:
    with ZipFile(path) as archive:
        return "\n".join(
            "\n".join(etree.fromstring(archive.read(name)).xpath("//*[local-name()='t']/text()"))
            for name in archive.namelist()
            if re.fullmatch(r"ppt/(?:slides/slide|notesSlides/notesSlide)\d+\.xml", name)
        )


def slide_text(presentation: Presentation) -> str:
    """Everything a viewer can read on the slides themselves (notes excluded)."""
    values = []
    for slide in presentation.slides:
        for target in slide.shapes:
            if target.has_text_frame:
                values.append(target.text_frame.text)
            if getattr(target, "has_table", False) and target.has_table:
                values += [cell.text for row in target.table.rows for cell in row.cells]
    return "\n".join(values)


def metrics_of(workbook: Path) -> dict[str, ReportMetric]:
    result = load_result(workbook.parent)
    return metrics_by_key(
        Collection.model_validate(result["collection"]),
        [Finding.model_validate(row) for row in result["findings"]], result["mode"],
    )


def collect(tmp_path: Path) -> Path:
    with patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("No Azure calls")):
        assert main(["collect", "--config", str(ROOT / "config" / "custom-config.yaml"),
                     "--fixture", str(FIXTURE), "--output-dir", str(tmp_path)]) == 0
    return next(tmp_path.rglob("report-*.xlsx"))


def level_for(ratio: float) -> int:
    return 5 if ratio == 1 else 4 if ratio >= 0.9 else 3 if ratio >= 0.8 else 2 if ratio > 0 else 1


def metric(key: str, value: float | int | str | None, unit: str = "") -> ReportMetric:
    return ReportMetric(
        key=key, label=key, value=value, unit=unit, status="observed" if value is not None else "unavailable",
        reason=None if value is not None else "not_found", limitation="로컬 합성 테스트",
    )


def synthetic(
    measures: dict[str, tuple[int, int] | None], *, interview: int | None = 3,
    collection: Collection | None = None, mode: str = "live", extra: dict[str, ReportMetric] | None = None,
) -> DeckData:
    """Build the narrative inputs without Azure data: a pair is numerator/denominator, None is pending."""
    items = [item(code, level_for(pair[0] / pair[1]) if pair else None)
             for code, pair in measures.items()]
    for prefix in {code[:2] for code in measures}:
        items += [item(f"{prefix}-{kind}-01", interview) for kind in ("PR", "PE", "DA", "TE")]
    areas, overall, status = compute_scores(items)
    assessment = Assessment(items, areas, overall, status, "", list(LEVEL_NAMES))
    metrics = {"run.mode": metric("run.mode", mode), "scope.subscriptions": metric("scope.subscriptions", 3)}
    for code, pair in measures.items():
        if pair is None:
            metrics["se." + code] = ReportMetric(
                key="se." + code, label=code, unit="ratio", status="unavailable", reason="not_found",
                limitation="로컬 합성 테스트",
            )
            continue
        metrics["se." + code] = metric("se." + code, pair[0] / pair[1], "ratio")
        metrics[f"se.{code}.numerator"] = metric(f"se.{code}.numerator", pair[0], "건")
        metrics[f"se.{code}.denominator"] = metric(f"se.{code}.denominator", pair[1], "건")
        metrics[f"se.{code}.l3_min"] = metric(f"se.{code}.l3_min", 0.8, "ratio")
    metrics.update(extra or {})
    return DeckData(assessment, metrics, collection, "<고객사>", NOW)


FULL = {code: (3, 3) for code in CODES}
FULL.update({"DS-SE-02": (0, 2), "BI-SE-08": (0, 2), "DS-SE-05": (0, 3), "BI-SE-14": (2, 4),
             "OE-SE-18": (2, 3), "DP-SE-15": (8, 10)})
PARTIAL = {**FULL, "DM-SE-01": None, "BI-SE-10": None, "OT-SE-24": None, "OT-SE-25": None}
HEALTHY = {code: (3, 3) for code in CODES}


def catalog_collection() -> Collection:
    stamps = [(2026, 6, 24), (2026, 7, 25), (2026, 11, 40)]
    packages = []
    for year, month, number in stamps:
        for index in range(number):
            built = index < 3 and month == 11
            packages.append(Agent365Package(
                package_id=f"{year}{month}-{index}", platform="Foundry" if built else "Not Available",
                created_at=datetime(year, month, 3, tzinfo=UTC), owner_count=1 if built else 0,
                detail_complete=built, total_sessions_30d=2 if built and index else 0,
                active_users_30d=0,
            ))
    return Collection(collected_at=NOW, agent365_packages=packages)


def all_story_text(data: DeckData) -> str:
    parts: list[str] = []
    for builder in (story.summary, story.overview, story.method_texts, story.next_texts):
        parts += [str(value) for value in builder(data).values()]
    for rows in (story.key_rows(data), story.method_rows(data), story.score_rows(data), story.matrix_rows(data),
                 story.creation_rows(data), story.identity_rows(data), story.ops_rows(data),
                 story.plan_rows(data), story.target_rows(data)):
        parts += [cell for row in rows for cell in row]
    parts += [story.headline_scores(data), story.score_box(data), story.headline_matrix(data),
              story.matrix_box(data), story.matrix_footer(data), story.headline_creation(data),
              story.creation_caption(data), story.creation_insight(data), story.headline_identity(data),
              story.identity_insight(data), story.identity_recommendations(data),
              story.headline_security(data), *story.security_box(data), story.headline_ops(data),
              story.ops_box(data), story.headline_plan(data), *story.phase_boxes(data),
              story.gap_box(data), *story.insights(data)]
    for code in story.security_cards(data):
        parts += story.card_texts(data, code).values()
    parts += story.security_cards(data)
    return "\n".join(parts)


def build_all(data: DeckData) -> Presentation:
    presentation = Presentation(presentation_template_path())
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
    return presentation


def test_scores_follow_sheet5_rules_for_correction_and_provisional_values() -> None:
    items = area_items("DM", 4, 2) + area_items("DS", 3, 3) + area_items("BI", None, 2) + area_items("DP", 4, None)
    areas, overall, status = compute_scores(items)
    assert (areas["DM"].final, areas["DM"].status) == (3.0, "인터뷰-실측 괴리")
    assert (areas["DS"].final, areas["DS"].status) == (3.0, "미보정")
    assert (areas["BI"].final, areas["BI"].status) == (2.0, "실측 기준 잠정(인터뷰 미입력)")
    assert (areas["DP"].final, areas["DP"].status) == (4.0, "인터뷰 기준(실측 없음)")
    assert areas["OT"].final is None and areas["OT"].status == "판정 보류"
    assert overall == 3.0 and status.startswith("잠정") and level_of(overall) == 3


def test_unavailable_scores_are_not_zero() -> None:
    areas, overall, status = compute_scores([item("DM-PR-01", None), item("DM-SE-01", None)])
    assert overall is None and status == "판정 보류"
    assert all(area.final is None for area in areas.values())


def test_overall_weights_valid_areas_equally_not_individual_system_items() -> None:
    items = [item("DM-SE-01", 1), *[item(f"DS-SE-{number:02}", 5) for number in range(2, 6)]]
    areas, overall, _status = compute_scores(items)
    assert areas["DM"].final == 1 and areas["DS"].final == 5
    assert overall == 3.0
    known = [row.score for row in items if row.score is not None]
    assert len(known) == len(items) and sum(known) / len(known) == 4.2
    assert areas["BI"].final is None


@pytest.mark.parametrize(("system_scores", "system_average"), [([4, 4, 3], 3.7), ([4, 4, 4, 3], 3.8)])
def test_lower_interview_final_is_a_separate_branch_not_a_changed_api_average(
    system_scores: list[int], system_average: float,
) -> None:
    items = [item(f"DS-{kind}-01", 2) for kind in ("PR", "PE", "DA", "TE")]
    items += [item(f"DS-SE-{index:02}", score) for index, score in enumerate(system_scores, 2)]
    areas, overall, _ = compute_scores(items)
    assert areas["DS"].system == system_average
    assert areas["DS"].interview == areas["DS"].final == overall == 2.0
    assert areas["DS"].status == "미보정"
    assert [row.score for row in items if row.is_system] == system_scores


def test_packaged_template_is_the_approved_twelve_slide_layout() -> None:
    assert presentation_template_path().name == TEMPLATE_NAME
    deck = Presentation(presentation_template_path())
    assert len(deck.slides) == 12
    assert (deck.slide_width, deck.slide_height) == (9904413, 6858000)
    assert any(shape.shape_id == 23789 for shape in deck.slides[0].shapes)
    with ZipFile(presentation_template_path()) as archive:
        core = etree.fromstring(archive.read("docProps/core.xml"))
        assert not core.xpath("//*[local-name()='creator' or local-name()='lastModifiedBy']")


def test_replacement_does_not_use_tiny_spacer_fonts_for_visible_text() -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    target = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(2))
    for index, (text, size) in enumerate((("제목", 14), ("\u00a0", 1), ("본문", 11))):
        paragraph = target.text_frame.paragraphs[0] if index == 0 else target.text_frame.add_paragraph()
        run = paragraph.add_run()
        run.text, run.font.size = text, Pt(size)
    replace_text(target, "새 제목\n첫 본문\n둘째 본문")
    assert [paragraph.runs[0].font.size.pt for paragraph in target.text_frame.paragraphs] == [14, 11, 11]


def test_domains_and_groups_partition_every_system_evidence_item() -> None:
    domain_codes = [code for *_rest, codes in DOMAINS for code in codes]
    assert sorted(domain_codes) == sorted(CODES)
    data = synthetic(FULL)
    groups = data.groups()
    assert [key for key, *_rest in groups] == ["T1", "T2", "T3", "T4", "T5"]
    assert sum(len(codes) for _key, _label, codes in groups) == len(CODES) == 26
    assert sorted(code for *_rest, codes in groups for code in codes) == sorted(CODES)
    assert [row[2] for row in story.method_rows(data)[1:]] == [str(len(codes)) for *_r, codes in groups]


def test_text_fitting_never_returns_empty_and_respects_limits() -> None:
    assert fit(["가나다", "라마바"], 4, sep=", ") == "가나다"
    assert fit(["가", "나"], 10) == "가, 나"
    assert em("가나") == 2 and em("ab") < 2
    assert story.pick(["아주 긴 문장 아주 긴 문장", "짧음"], 4) == "짧음"


@pytest.mark.parametrize("measures", [FULL, PARTIAL, HEALTHY])
def test_story_never_exposes_collection_codes_or_dashes_and_adapts_to_pending_items(
    measures: dict[str, tuple[int, int] | None],
) -> None:
    data = synthetic(measures, collection=catalog_collection())
    text = all_story_text(data)
    assert not FORBIDDEN.search(text)
    assert "\u2013" not in text and "\u2014" not in text
    pending = [code for code, pair in measures.items() if pair is None]
    assert len(data.pending) == len(pending)
    assert ("확인 중" in text) == bool(pending)
    buckets = story.distribution(data)
    assert sum(buckets) == 26 and buckets[4] == len(pending)
    assert f"측정 가능한 {26 - len(pending)}개 항목" in story.headline_matrix(data)


def test_pending_items_use_plain_notes_and_become_values_when_measured() -> None:
    partial, measured = synthetic(PARTIAL), synthetic({**PARTIAL, "OT-SE-24": (4, 5)})
    assert partial.fact("OT-SE-24") == "에이전트별 비용 구분 확인 중"
    assert partial.pending_note("OT-SE-24") == "청구 반영 후 판정"
    assert measured.fact("OT-SE-24") == "비용 구분 5건 중 4건"
    assert story.ops_rows(partial)[3][1:] == ["청구 반영 후 판정", "기준 충족 80% 이상", "확인 중"]
    assert story.ops_rows(measured)[3][1].startswith("비용 구분 5건 중 4건")
    assert story.ops_rows(measured)[3][3] == "L3"
    assert story.ops_bar(partial, "OT-SE-24")[1:] == ("확인 중", "청구 반영 후", None)
    assert story.ops_bar(measured, "OT-SE-24")[1] == "80%"
    assert story.matrix_rows(partial)[1][1:3] == ["-", "확인 중"]
    assert "확인 중 4개" in story.matrix_footer(partial) and "확인 중" not in story.matrix_footer(synthetic(FULL))
    assert any(row["measured"] is False for row in partial.tasks()) and all(
        row["measured"] for row in synthetic(FULL).tasks())


def test_roadmap_phases_follow_the_weakest_item_of_each_theme() -> None:
    data = synthetic({**HEALTHY, "DS-SE-02": (0, 2), "BI-SE-14": (2, 4), "DP-SE-15": (8, 10), "OT-SE-24": None})
    phases = {row["short"]: row["phase"] for row in data.tasks()}
    assert phases == {
        "데이터 유출 방지 규칙 적용": 1, "비용 구분 체계 수립": 1, "규칙 위반 자원 정리": 2,
        "청사진 연결 확대 L4 상향": 3,
    }
    assert [row["phase"] for row in data.tasks()] == [1, 1, 2, 3]
    assert [row["short"] for row in data.tasks()][:2] == ["데이터 유출 방지 규칙 적용", "비용 구분 체계 수립"]
    healthy = synthetic(HEALTHY)
    assert healthy.tasks() == [] and story.plan_rows(healthy)[1][1] == "현 수준 유지 · 정기 재점검"
    assert "현 수준 유지" in story.headline_plan(healthy)
    many = synthetic({code: (0, 2) for code in CODES})
    assert len(story.plan_rows(many)) - 1 <= 8


@pytest.mark.parametrize("measures", [FULL, PARTIAL, HEALTHY, {**FULL, "OT-SE-24": (399, 400)}])
def test_roadmap_never_lists_an_item_whose_current_value_already_exceeds_the_target(
    measures: dict[str, tuple[int, int] | None],
) -> None:
    data = synthetic(measures)
    for row in data.tasks():
        for code in row["codes"]:
            ratio = data.ratio(code)
            assert ratio is None or ratio < row["floor"], (row["short"], code, ratio, row["floor"])
            if row["raise"]:
                assert data.score(code) == 3 and row["floor"] == 0.9 and row["target"].count("90%")
            else:
                assert data.score(code) is None or data.score(code) < 3
    texts = [cell for rows in (story.plan_rows(data),) for line in rows for cell in line]
    raising = any(row["raise"] for row in data.tasks())
    assert ("L4 상향" in " ".join(texts)) == raising
    assert "확보" not in story.headline_plan(data)
    if data.tasks():
        assert "목표(안)" in story.headline_plan(data) or "확인 필요" in story.headline_plan(data)


def test_roadmap_owners_are_the_template_cxo_roles_and_iterations_follow_the_template() -> None:
    for data in (synthetic(FULL), synthetic(PARTIAL), synthetic({code: (0, 2) for code in CODES})):
        assert {row[3] for row in story.plan_rows(data)[1:]} <= {"CIO", "CAIO", "CISO"}
        assert {row[0] for row in story.plan_rows(data)[1:]} <= {"Phase 1", "Phase 2", "Phase 3"}
        rows = story.target_rows(data)
        assert [row[3] for row in rows[1:]] == ["Iteration 1", "Iteration 1", "Iteration 2", "Iteration 2",
                                                 "Iteration 3"]
        assert all(row[2].startswith("L") for row in rows[1:])


def test_target_path_is_a_transparent_plan_not_a_forecast() -> None:
    data = synthetic(FULL, interview=3)
    path = data.target_path()
    assert path is not None and path[-1] == round(max(3.0, data.overall) + 0.3, 1)
    assert path == sorted(path) and path[0] > data.overall
    empty = DeckData(Assessment([], compute_scores([])[0], None, "판정 보류", "", []))
    assert empty.target_path() is None and empty.overall_label == "확인 중"


def test_interview_vs_evidence_branches() -> None:
    items = area_items("DM", 4, 2) + area_items("DS", 2, 4) + area_items("BI", 3, 3)
    areas, overall, status = compute_scores(items)
    data = DeckData(Assessment(items, areas, overall, status, "", []))
    assert data.corrected() == ["DM"] and [prefix for prefix, _gap in data.ahead()] == ["DS"]
    assert "점수를 낮춰 보정" in story.divergence(data)[0] and "다름" in story.score_box(data)
    aligned = DeckData(Assessment(*[
        (items := area_items("DM", 3, 3)), (r := compute_scores(items))[0], r[1], r[2], "", [],
    ]))
    assert aligned.corrected() == [] and aligned.ahead() == []
    assert "대체로 일치" in story.divergence(aligned)[0]
    ahead_only = DeckData(Assessment(*[
        (items := area_items("DS", 2, 4)), (r := compute_scores(items))[0], r[1], r[2], "", [],
    ]))
    assert "업무 절차" in story.divergence(ahead_only)[0]
    assert "인터뷰 기준" in story.divergence(ahead_only)[1]


def test_catalog_months_split_built_agents_from_provided_apps() -> None:
    data = synthetic(FULL, collection=catalog_collection())
    catalog = data.catalog
    assert catalog is not None and catalog.source == "Agent 365 목록"
    assert [(row[0], row[1]) for row in catalog.months] == [(2026, month) for month in range(6, 12)]
    assert [row[2] for row in catalog.months] == [24, 25, 0, 0, 0, 40]
    assert [row[3] for row in catalog.months] == [0, 0, 0, 0, 0, 3] and catalog.partial_last
    assert catalog.total == 89 and catalog.built == 3 and catalog.growth == pytest.approx(40 / 24)
    assert data.usage is not None and (data.usage.active, data.usage.idle) == (2, 1)
    assert data.usage.provided == 86 and data.usage.unobserved == 0
    assert data.catalog_owner_clause() == "소유자 지정 3/3"
    assert "월 24개 → 40개" in story.summary(data)[43672] or "24개 → 40개" in story.headline_overview(data)
    assert synthetic(FULL).catalog is None and synthetic(FULL).usage is None


def test_story_without_collection_keeps_plain_wording_and_hides_missing_charts() -> None:
    data = synthetic(PARTIAL)
    assert story.catalog_clause(data) is None
    assert "등록 목록 수집 후 표시" in story.creation_caption(data)
    presentation = build_all(data)
    text = slide_text(presentation)
    assert not FORBIDDEN.search(text)
    assert "신규 에이전트 등록 이력은 등록 목록 수집 후 표시됩니다" in text
    assert "사용 지표 수집 후 표시됩니다" in text


@pytest.mark.parametrize("measures", [FULL, PARTIAL, HEALTHY])
def test_slides_hide_unknown_values_and_keep_readable_font_sizes(measures: dict) -> None:
    data = synthetic(measures, collection=catalog_collection())
    presentation = build_all(data)
    text = slide_text(presentation)
    assert not FORBIDDEN.search(text)
    sizes = [
        run.font.size.pt for slide in presentation.slides for target in slide.shapes
        for run in (r for p in (target.text_frame.paragraphs if target.has_text_frame else [])
                    for r in p.runs) if run.font.size and run.text.strip()
    ]
    table_sizes = [
        run.font.size.pt for slide in presentation.slides for target in slide.shapes
        if getattr(target, "has_table", False) and target.has_table
        for row in target.table.rows for cell in row.cells for p in cell.text_frame.paragraphs
        for run in p.runs if run.font.size and run.text.strip()
    ]
    assert min(sizes + table_sizes) >= 8
    pending = [code for code, pair in measures.items() if pair is None]
    matrix = next(s.table for s in presentation.slides[5].shapes if s.has_table)
    cells = [cell.text for row in matrix.rows for cell in row.cells]
    assert cells.count("확인 중") == len(pending)
    for code in pending:
        assert any(cell.startswith(code) for cell in cells)
    ops = {s.shape_id: s for s in presentation.slides[9].shapes}
    hidden = ops[38673]._element.find(".//{*}spPr/{*}noFill") is not None
    assert hidden == ("OT-SE-24" in pending)
    assert ops[38818].text_frame.text == ("확인 중" if "OT-SE-24" in pending else "100%")


def test_creation_chart_uses_catalog_months_and_template_bar_geometry() -> None:
    presentation = build_all(synthetic(FULL, collection=catalog_collection()))
    slide = presentation.slides[6]
    shapes = {s.shape_id: s for s in slide.shapes}
    assert [shapes[i].text_frame.text for i in (29337, 29542, 29772, 30027, 30307, 30612)] == [
        "24", "25", "0", "0", "0", "40"]
    assert shapes[30676].text_frame.text == "11월*" and shapes[29376].text_frame.text == "6월"
    assert shapes[30487].text_frame.text == "3"
    assert shapes[30549].height > shapes[29299].height > 0
    assert shapes[29092].text_frame.text == "직접 제작·구성"
    assert shapes[31081].text_frame.text == "10개" or shapes[31081].text_frame.text == "확인 중"


def test_identity_bars_follow_measured_ratio_and_leave_no_orphan_sample_bar() -> None:
    template = {s.shape_id for s in Presentation(presentation_template_path()).slides[7].shapes}
    presentation = build_all(synthetic({**FULL, "OE-SE-19": (0, 3), "OE-SE-17": None}))
    slide = presentation.slides[7]
    shapes = {s.shape_id: s for s in slide.shapes}
    assert shapes[32796].text_frame.text == "80%" and shapes[34623].text_frame.text == "확인 중"
    assert shapes[33978].text_frame.text == "100%"
    added = [s for s in slide.shapes if s.shape_id not in template]
    assert added == []
    assert shapes[34404].width == Inches(0) or shapes[34404]._element.find(".//{*}spPr/{*}noFill") is not None
    healthy = build_all(synthetic(HEALTHY)).slides[7]
    assert len([s for s in healthy.shapes if s.shape_id not in template]) == 1


def test_security_cards_pick_the_weakest_measured_controls_and_pending_when_short() -> None:
    assert story.security_cards(synthetic(FULL)) == ["BI-SE-09", "DS-SE-05", "BI-SE-14"]
    assert story.security_cards(synthetic(PARTIAL)) == ["BI-SE-09", "DS-SE-05", "BI-SE-14"]
    short = synthetic({**HEALTHY, "BI-SE-14": None, "DS-SE-05": None, "BI-SE-10": None, "OT-SE-25": None,
                       "BI-SE-11": None})
    cards = story.security_cards(short)
    assert cards[0] == "BI-SE-09" and all(short.score(code) is None for code in cards[1:])
    assert story.card_texts(short, cards[1])["value"] == "확인 중"


def test_amount_formats_use_one_currency_rule_and_never_round_a_partial_result_to_full() -> None:
    assert money(0.397342, "USD") == "$0.40" and money(12.346, "USD") == "$12.35"
    assert money(12345.6, "USD") == "$12,346" and money(0.001, "USD") == "$0.01 미만"
    assert money(0, "USD") == "$0.00" and money(1234567.4, "KRW") == "1,234,567원"
    assert pct(0.99847) == "99.8%" and pct(1) == "100%" and pct(0.5) == "50%" and pct(0.001) == "0.1%"


def amount_deck() -> DeckData:
    """Cost attribution measured in USD (not counts) with a single billed month, as in a fresh lab run."""
    months = ("202606", "202607", "202608", "202609", "202610", "202611")
    extra = {
        "se.OT-SE-24": metric("se.OT-SE-24", 0.9984727683561392, "ratio"),
        "se.OT-SE-24.numerator": metric("se.OT-SE-24.numerator", 0.39734181799999996, "USD"),
        "se.OT-SE-24.denominator": metric("se.OT-SE-24.denominator", 0.39794957919, "USD"),
        "cost.history": metric("cost.history", ",".join(months), "series"),
        "cost.currency": metric("cost.currency", "USD", "currency"),
    }
    for month in months[:-1]:
        extra[f"cost.month.{month}.total"] = metric(f"cost.month.{month}.total", None, "USD")
    extra["cost.month.202611.total"] = metric("cost.month.202611.total", 0.39794957919, "USD")
    return synthetic({**FULL, "OT-SE-24": (399, 400)}, collection=catalog_collection(), extra=extra)


def test_amount_measurements_are_shown_as_currency_everywhere_never_as_raw_counts() -> None:
    data = amount_deck()
    assert data.currency("OT-SE-24") == "USD" and data.currency("DS-SE-02") is None
    assert data.fraction("OT-SE-24") == "$0.40/$0.40" and data.percent("OT-SE-24") == "99.8%"
    assert data.fact("OT-SE-24") == "비용 청구 $0.40 중 $0.40 직접 귀속"
    assert story.ops_rows(data)[3][1] == "비용 청구 $0.40 중 $0.40 직접 귀속(99.8%)"
    assert any("$0.40/$0.40 (99.8%)" in row for row in story.matrix_rows(data))
    assert "$0.40" in story.insights(data)[0] and "건" not in story.insights(data)[0]
    assert "$0.40" in story.headline_ops(data) and story.cost_note(data)
    presentation = build_all(data)
    texts = [slide_text(presentation)]
    for page in range(1, 12):
        texts.append(notes_text(data, page, ""))
    text = "\n".join(texts)
    assert not re.search(r"\d\.\d{4,}", text) and not re.search(r"\d\.\d+\s?건", text)
    assert "$0.40" in text and "99.8%" in text and "청구 금액이 아직 적어 비율은 참고용" in text
    ops = {s.shape_id: s for s in presentation.slides[9].shapes}
    assert [ops[i].text_frame.text for i in (37293, 37548, 37828, 38133, 38463)] == ["청구 내역 없음"] * 5
    assert ops[38818].text_frame.text == "$0.40" and ops[38967].text_frame.text == "식별 99.8%"
    assert ops[38673].height > 0 and ops[38745].height < ops[38673].height
    assert "USD" in ops[37107].text_frame.text


def test_large_and_won_amounts_keep_readable_units_and_small_amount_note_disappears() -> None:
    data = amount_deck()
    data.metrics["se.OT-SE-24.numerator"] = metric("se.OT-SE-24.numerator", 90000.0, "KRW")
    data.metrics["se.OT-SE-24.denominator"] = metric("se.OT-SE-24.denominator", 100000.0, "KRW")
    assert data.fraction("OT-SE-24") == "90,000원/100,000원" and not story.cost_note(data)
    assert "원" in data.fact("OT-SE-24") and not re.search(r"\d\.\d{3,}", data.fact("OT-SE-24", short=False))


MISLEADING = re.compile(
    r"Microsoft 제공 앱|제공 앱|배포 전 평가|제작 권한 통제|체계 확보|활성화 후 판정|책임 소재 기록|"
    r"누가 만들고 책임지는지|Agent 수|배포 전 품질 평가"
)


def advisory_collection(confirmed: int, waiting: int) -> Collection:
    """Subscriptions whose AI security advisories exist vs. are not generated yet (as Defender reports it)."""
    subs = [f"sub-{index}" for index in range(confirmed + waiting)]
    return catalog_collection().model_copy(update={
        "subscriptions": subs,
        "security": [SecurityRecommendation(subscription_id=s, resource_id="r", assessment_id="a",
                                            severity="High", status="Healthy") for s in subs[:confirmed]],
        "issues": [Issue(subscription_id=s, collector="security", target=s, reason="feature_unavailable",
                         detail="AI 리소스 연결 권고 없음") for s in subs[confirmed:]],
    })


@pytest.mark.parametrize("measures", [FULL, PARTIAL, HEALTHY])
def test_labels_follow_what_each_indicator_really_measures(measures: dict) -> None:
    data = synthetic(measures, collection=advisory_collection(1, 2))
    presentation = build_all(data)
    text = slide_text(presentation) + "\n" + "\n".join(notes_text(data, page, "") for page in range(1, 12))
    assert not MISLEADING.search(text)
    assert data.fact("DM-SE-01") == ("역할 할당 확인 환경 확인 중" if measures.get("DM-SE-01") is None
                                     else "역할 할당이 확인된 환경 3곳 중 3곳")
    assert data.label("BI-SE-09") == "프로젝트 평가 실행 이력"
    assert "에이전트 ID 청사진에 연결되지 않음" in data.long_fact("DP-SE-15") or measures["DP-SE-15"] == (3, 3)
    assert "모델 업그레이드 설정" in data.fact("DS-SE-04")


def test_agent_365_monthly_figures_are_packages_including_store_apps_not_agents() -> None:
    data = synthetic(FULL, collection=catalog_collection(),
                     extra={"inventory.azure": metric("inventory.azure", 10)})
    headline, first = story.headline_overview(data), story.insights(data)[0]
    assert "Agent 365 목록 패키지" in headline and "스토어 앱" in headline and "직접 제작·구성" in headline
    assert first.startswith("Agent 365 목록 패키지가 월") and "에이전트가" not in first
    presentation = build_all(data)
    creation = {s.shape_id: s for s in presentation.slides[6].shapes}
    assert creation[29157].text_frame.text == "플랫폼 미확인 앱·기타"
    text = slide_text(presentation)
    assert "플랫폼 미확인 앱(스토어 앱 포함)" in text and "서로 다른 모집단" in text
    assert "등록일은 이 테넌트 등록일과 다를 수 있음" in text
    assert "사용 비율은 사용 현황이 확인된" in text
    assert story.overview(data)[23825].startswith("40개\n월 신규 목록 패키지")


def test_months_are_cut_in_kst_not_utc() -> None:
    boundary = datetime(2026, 6, 30, 16, 0, tzinfo=UTC)  # 07-01 01:00 KST
    before = datetime(2026, 6, 30, 14, 59, tzinfo=UTC)  # 06-30 23:59 KST
    collected = datetime(2026, 11, 30, 15, 30, tzinfo=UTC)  # 12-01 00:30 KST
    rows, partial = monthly_counts([(boundary, True), (before, False), (collected, False)], collected)
    assert [(row[0], row[1]) for row in rows] == [(2026, month) for month in (7, 8, 9, 10, 11, 12)]
    by_month = {(row[0], row[1]): row[2:] for row in rows}
    assert by_month[(2026, 7)] == (1, 1) and (2026, 6) not in by_month
    assert by_month[(2026, 12)] == (1, 0) and partial
    utc_rows, _ = monthly_counts([(boundary, True)], datetime(2026, 11, 20, tzinfo=UTC))
    assert {(row[0], row[1]): row[2] for row in utc_rows}[(2026, 7)] == 1


def test_one_verdict_drives_summary_key_findings_and_control_box() -> None:
    data = synthetic(FULL, collection=catalog_collection())
    state, code = story.control_state(data, ("DS-SE-03", "DP-SE-15", "OE-SE-16"))
    assert (state, code) == ("partial", "DP-SE-15")
    summary = story.summary(data)[43694]
    assert "목표(L3) 충족" in summary and "나머지 보완 필요" in summary and "청사진에 연결되지 않은 에이전트 2개" in summary
    rows = story.key_rows(data)
    assert rows[2][0].endswith("목표 충족 · 보완 필요") and rows[2][2] == "목표(80%) 충족, 나머지는 보완 필요"
    assert "L3 충족 · 청사진 연결 에이전트 8/10" in story.gap_box(data)
    healthy = synthetic(HEALTHY, collection=catalog_collection())
    assert story.row_status(healthy, ("DS-SE-03", "DP-SE-15", "OE-SE-16")) == "양호"
    assert "체계 확보" not in "".join(cell for row in story.key_rows(healthy) for cell in row)


def test_security_advisory_wait_is_explained_per_subscription_in_both_cases() -> None:
    waiting = synthetic({**FULL, "BI-SE-10": None}, collection=advisory_collection(1, 2))
    assert waiting.pending_note("BI-SE-10") == "보안 권고 1개 구독 확인, 2개 구독 반영 대기"
    assert waiting.pending_reason("BI-SE-10") == "Defender 보안 권고 반영 대기"
    text = slide_text(build_all(waiting))
    assert "보안 권고 1개 구독 확인, 2개 구독 반영 대기(Defender 평가 반영 후 판정)" in text
    assert "활성화 후 판정" not in text and "Defender 보안 권고 반영 대기 후 판정" in text
    judged = synthetic({**FULL, "BI-SE-10": (3, 3)}, collection=advisory_collection(3, 0))
    assert not judged.pending and story.security_notes(judged) == ""
    judged_text = slide_text(build_all(judged))
    assert "반영 대기" not in judged_text and "Defender 평가 반영" not in judged_text
    unknown = synthetic({**FULL, "BI-SE-10": None}, collection=catalog_collection())
    assert "반영 대기" in unknown.pending_note("BI-SE-10")


def test_cost_chart_says_no_billing_and_states_what_the_month_amount_covers() -> None:
    rows = [CostRecord(subscription_id="s", resource_id=f"/subscriptions/s/resourcegroups/r/providers/{kind}/x",
                       amount=amount, currency="USD", usage_date="20261119")
            for kind, amount in (("microsoft.web/serverfarms", 0.39), ("microsoft.cognitiveservices/accounts", 0.001))]
    data = amount_deck()
    data.collection = data.collection.model_copy(update={"costs": rows})
    notes = story.cost_notes(data)
    assert any("11월 금액은 수집된 청구 11/19 하루치" in line for line in notes)
    assert any("6~10월은 조회 기간 안에 청구 내역이 없음" in line for line in notes)
    assert any("리소스 단위 귀속" in line and "호스팅 요금" in line for line in notes)
    text = slide_text(build_all(data))
    assert "청구 내역 없음" in text and "확인 중" not in "".join(
        s.text_frame.text for s in build_all(data).slides[9].shapes if s.shape_id in (37293, 37548))


def test_report_only_evidence_replaces_catalog_fallbacks_when_it_is_observed() -> None:
    extra = {
        "creation.history": metric("creation.history", "202611,202612"),
        "creation.month.202611.total": metric("creation.month.202611.total", 4),
        "creation.month.202611.approved": metric("creation.month.202611.approved", 3),
        "creation.month.202612.total": metric("creation.month.202612.total", 6),
        "creation.month.202612.approved": metric("creation.month.202612.approved", 3),
        "evaluation.predeploy": metric("evaluation.predeploy", 0.5, "ratio"),
        "evaluation.deployed": metric("evaluation.deployed", 4),
        "evaluation.evaluated": metric("evaluation.evaluated", 2),
        "evaluation.missing": metric("evaluation.missing", 2),
    }
    data = synthetic(FULL, collection=catalog_collection(), extra=extra)
    slide = build_all(data).slides
    shapes = {s.shape_id: s for s in slide[6].shapes}
    assert [shapes[i].text_frame.text for i in (29337, 29542)] == ["4", "6"]
    assert shapes[29092].text_frame.text == "승인 매칭" and shapes[29376].text_frame.text == "2026.11"
    assert story.security_cards(data)[0] == "BI-SE-29"
    assert {s.shape_id: s for s in slide[8].shapes}[36182].text_frame.text == "50%"


@pytest.mark.parametrize("measures", [FULL, PARTIAL])
def test_footnotes_explain_only_terms_used_on_the_slide_with_readable_size(measures: dict) -> None:
    presentation = build_all(synthetic(measures, collection=catalog_collection()))
    labels = {entry[1] for entry in GLOSSARY}
    seen = 0
    for page, footer_id in FOOTERS.items():
        slide = presentation.slides[page]
        footer = next(s for s in slide.shapes if s.shape_id == footer_id)
        body = "\n".join(
            s.text_frame.text for s in slide.shapes if s.has_text_frame and s.shape_id != footer_id
        ) + "\n".join(cell.text for s in slide.shapes if getattr(s, "has_table", False) and s.has_table
                      for row in s.table.rows for cell in row.cells)
        for number, label in re.findall(r"(\d)\) ([^:\n]+?) : ", footer.text_frame.text):
            if label.strip() not in labels:
                continue
            seen += 1
            assert label.strip() in body, (page, label)
            assert "¹²³⁴⁵⁶⁷⁸⁹"[int(number) - 1] in body, (page, number)
        sizes = [run.font.size.pt for p in footer.text_frame.paragraphs for run in p.runs
                 if run.font.size and run.text.strip()]
        assert not sizes or min(sizes) >= 8, page
    assert seen >= 15


def test_levels_and_template_labels_are_written_as_in_the_template() -> None:
    data = synthetic(FULL, collection=catalog_collection())
    assert data.overall_label == "L3.0" and data.level("DS-SE-02") == "L1"
    assert synthetic(PARTIAL).level("OT-SE-24") == "확인 중"
    text = slide_text(build_all(data))
    assert not re.search(r"\d\s?단계", text)
    for phrase in ("L1 Initial", "L2 Managed", "L3 Defined (목표)", "L4 Governed", "L5 Optimized"):
        assert phrase in text
    for phrase in ("Executive Summary", "CxO별 시사점", "CIO : 자산 · 비용 관리", "CAIO : 수요 · 품질 관리",
                   "CISO : 신원 · 보안 통제", "Lifecycle 단계"):
        assert phrase in text
    assert not re.search(r"관점 [123]|핵심 시사점 3가지|핵심 요약|시스템 확인|확인값", text)
    assert len(story.insights(data)) == 3 and all(story.insights(data))
    assert not re.search(r"[A-Z]{2}-SE-\d{2}", "\n".join(story.insights(data)) + story.headline_overview(data))


def squash(text: str) -> str:
    """Compare template wording: footnote marks, dash variants and spacing are not wording."""
    text = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁾]+\)?", "", text).replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", text).strip()


# Titles, headings, labels and table headers that must stay exactly as the approved template has them.
FIXED_SHAPES = {
    1: ("Rectangle 43666", "Rectangle 43668", "Rectangle 43680", "Rectangle 43710"),
    2: ("Rectangle 23791", "Rectangle 23798", "Rectangle 23843", "Rectangle 23881", "Rectangle 23912",
        "Rectangle 23947", "Rectangle 23986"),
    3: ("Rectangle 24076", "Rectangle 24183", "Rectangle 24276"),
    4: ("Rectangle 24694", "Rectangle 24783", "Rectangle 24924", "Rectangle 25023", "Rectangle 25126",
        "Rectangle 25233", "Rectangle 25344", "Rectangle 25578", "Rectangle 25764", "Rectangle 25959",
        "Rectangle 26163", "Rectangle 26376", "Rectangle 26598", "Rectangle 26751", "Rectangle 26829",
        "Rectangle 28308"),
    5: ("Rectangle 28611", "Rectangle 28623", "Rectangle 28640", "Rectangle 28673", "Rectangle 28715",
        "Rectangle 28766"),
    6: ("Rectangle 28946", "Rectangle 31521"),
    7: ("Rectangle 31920", "Rectangle 32087", "Rectangle 32258", "Rectangle 32345", "Rectangle 35420",
        "Rectangle 35777"),
    8: ("Rectangle 36148", "Rectangle 36155"),
    9: ("Rectangle 36782", "Rectangle 40394"),
    10: ("Rectangle 40873", "Rectangle 41072", "Rectangle 41587", "Rectangle 41801", "Rectangle 42356",
         "Rectangle 42701", "Rectangle 43055", "Rectangle 43418"),
    11: ("Rectangle 40873", "Rectangle 43756", "Rectangle 43786", "Rectangle 43840", "Rectangle 43881",
         "Rectangle 43926", "Rectangle 44001", "Rectangle 44146"),
}
FIXED_TABLE_HEADERS = (2, 3, 4, 5, 6, 9, 10, 11)  # slide 8 (index 7) mixes counts of agents and resources
# Shapes whose first line is a fixed label while the following lines carry data.
FIXED_FIRST_LINES = {
    3: ("Arrow: Pentagon 24343", "Arrow: Chevron 24378", "Arrow: Chevron 24414", "Arrow: Chevron 24451",
        "Arrow: Chevron 24489"),
    10: ("Arrow: Pentagon 41275", "Arrow: Chevron 41378", "Arrow: Chevron 41482"),
    11: ("Arrow: Pentagon 44056", "Arrow: Chevron 44085", "Arrow: Chevron 44115"),
}


def test_template_titles_headings_labels_and_table_headers_are_kept_verbatim() -> None:
    template = Presentation(presentation_template_path())
    result = build_all(synthetic(FULL, collection=catalog_collection()))
    for page, names in FIXED_SHAPES.items():
        before = {s.name: s for s in template.slides[page].shapes}
        after = {s.name: s for s in result.slides[page].shapes}
        for name in names:
            assert squash(after[name].text_frame.text) == squash(before[name].text_frame.text), (page, name)
    for page, names in FIXED_FIRST_LINES.items():
        before = {s.name: s for s in template.slides[page].shapes}
        after = {s.name: s for s in result.slides[page].shapes}
        for name in names:
            first = squash(before[name].text_frame.text.split("\n")[0])
            assert squash(after[name].text_frame.text.split("\n")[0]) == first, (page, name)
    for page in FIXED_TABLE_HEADERS:
        before = next(s.table for s in template.slides[page].shapes if s.has_table)
        after = next(s.table for s in result.slides[page].shapes if s.has_table)
        assert [squash(c.text) for c in after.rows[0].cells] == [squash(c.text) for c in before.rows[0].cells], page
    cover = next(s for s in result.slides[0].shapes if s.name == "Rectangle 23788")
    assert squash(cover.text_frame.text).endswith("- System Evidence 분석 결과 보고서 -")
    table = next(s.table for s in result.slides[5].shapes if s.has_table)
    assert table.cell(1, 2).text.startswith("L") or table.cell(1, 2).text == "확인 중"
    title = next(s for s in result.slides[5].shapes if s.name == "Rectangle 28604")
    assert squash(title.text_frame.text) == "4. System Evidence 26개 항목별 판정 결과"


def test_run_preserves_static_package_parts_and_replaces_all_sample_results(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    deck = next(workbook.parent.glob("EASM-report-*.pptx"))
    presentation = Presentation(deck)
    assert len(presentation.slides) == 12
    text = deck_text(deck)
    visible = slide_text(presentation)
    assessment = read_assessment(workbook)
    assert [row.code for row in assessment.system_items] == list(CODES)
    rendered = set(re.findall(r"\b[A-Z]{2}-SE-\d{2}\b", visible))
    assert set(CODES) <= rendered
    assert not re.search(r"\b[A-Z]{2}-SY-\d{2}\b", text)
    assert "<고객사>" in visible and "- System Evidence 분석 결과 보고서 -" in visible
    assert not FORBIDDEN.search(re.sub("합성 데모 - 실제 진단 결과 아님", "", visible))
    assert "합성 데모 - 실제 진단 결과 아님" in visible
    assert not any(value in text for value in ("307개", "412개", "95개", "A사", "가상 데이터 기반 보고서 예시"))
    assert "\u2013" not in text and "\u2014" not in text
    with ZipFile(presentation_template_path()) as template, ZipFile(deck) as result:
        assert set(template.namelist()) == set(result.namelist())
        for name in template.namelist():
            if not re.fullmatch(r"ppt/(?:slides/slide|notesSlides/notesSlide)\d+\.xml", name):
                assert template.read(name) == result.read(name), name
    source, output = Presentation(presentation_template_path()), presentation
    for page, identifier in ((2, 23792), (7, 31921), (9, 36783)):
        before = next(shape for shape in source.slides[page].shapes if shape.shape_id == identifier)
        after = next(shape for shape in output.slides[page].shapes if shape.shape_id == identifier)
        assert before._element.spPr.xml == after._element.spPr.xml
        assert before.text_frame.paragraphs[0].runs[0].font.size == after.text_frame.paragraphs[0].runs[0].font.size
    matrix = next(shape.table for shape in output.slides[5].shapes if shape.has_table)
    assert len(matrix.rows) == 14 and len(matrix.columns) == 6
    notes = output.slides[5].notes_slide.notes_text_frame.text
    assert "[발표 메모]" in notes and "근거 항목" in notes and not FORBIDDEN.search(notes)
    for page in (5, 10, 11):
        table = next(target.table for target in output.slides[page].shapes if target.has_table)
        assert all(run.font.size.pt == 9 for row in table.rows for cell in row.cells
                   for paragraph in cell.text_frame.paragraphs for run in paragraph.runs
                   if run.text and run.font.size)


def test_template_shapes_keep_their_geometry_when_only_text_changes(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    output = Presentation(next(workbook.parent.glob("EASM-report-*.pptx")))
    source = Presentation(presentation_template_path())
    footers = set(FOOTERS.values())
    for page in (0, 1, 2, 3, 11):
        resized = {s.shape_id for s in output.slides[page].shapes if s.has_table} | footers
        for before in source.slides[page].shapes:
            if before.shape_id in resized or before.shape_id not in {s.shape_id for s in output.slides[page].shapes}:
                continue
            after = next(s for s in output.slides[page].shapes if s.shape_id == before.shape_id)
            assert (before.left, before.top, before.width, before.height) == (
                after.left, after.top, after.width, after.height), (page, before.shape_id)


def test_unknown_workbook_code_is_rejected(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    book = load_workbook(workbook)
    book["4. 질문별 평가 기준"]["B5"] = "DM-XX-01"
    book.save(workbook)
    with pytest.raises(ValueError, match="지원되지 않는 평가 코드"):
        read_assessment(workbook)


def test_interview_responses_fill_every_pending_row_without_changing_api_rows_or_labels(tmp_path: Path) -> None:
    source = collect(tmp_path)
    originals = {path: path.read_bytes() for path in source.parent.iterdir() if path.is_file()}
    workbook, output = tmp_path / "responses.xlsx", tmp_path / "responses.pptx"
    with patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("No Azure calls")):
        assert interview_responses_main([
            "--workbook", str(source), "--output-workbook", str(workbook), "--output-pptx", str(output),
            "--raw-json", str(next(source.parent.glob("raw-data-*.json"))),
        ]) == 0
    assert all(path.read_bytes() == payload for path, payload in originals.items())
    with ZipFile(source) as before, ZipFile(workbook) as after:
        changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
        assert changed == ["xl/worksheets/sheet6.xml"]
    before_book, after_book = load_workbook(source), load_workbook(workbook)
    before, after = before_book[RESULT_SHEET], after_book[RESULT_SHEET]
    criteria = after_book["4. 질문별 평가 기준"]
    interview_rows = []
    for row in range(5, before.max_row + 1):
        code = str(before.cell(row, 2).value or "")
        if "-SE-" in code:
            assert [(cell.value, cell.style_id, cell.data_type) for cell in before[row]] == [
                (cell.value, cell.style_id, cell.data_type) for cell in after[row]
            ]
        elif re.fullmatch(r"[A-Z]{2}-(?:PR|PE|DA|TE)-\d+", code):
            interview_rows.append(row)
            sample = SAMPLES[code]
            assert [after.cell(row, column).value for column in (7, 8, 10, 11, 13, 14)] == [
                "인터뷰 완료", sample.metric, sample.basis, "인터뷰 응답", sample.level, sample.memo,
            ]
            judgement = str(after.cell(row, 9).value)
            assert judgement.startswith(f"Level {sample.level} (")
            assert " ".join(str(criteria.cell(row, 6 + sample.level).value).split()) in judgement
            next_step = str(after.cell(row, 12).value)
            if sample.level < 5:
                assert next_step.startswith(f"Level {sample.level + 1}: ")
                assert " ".join(str(criteria.cell(row, 7 + sample.level).value).split()) in next_step
            else:
                assert next_step == "Level 5 유지 - 지속 개선 주기 점검"
            assert after.row_dimensions[row].height == before.row_dimensions[row].height
    assert len(interview_rows) == 54
    assert "답변 완료 54개" in after["B2"].value
    presentation = Presentation(output)
    assert len(presentation.slides) == 12
    text = deck_text(output)
    assert not FORBIDDEN.search(re.sub("합성 데모 - 실제 진단 결과 아님", "", text))
    assert "- System Evidence 분석 결과 보고서 -" in text
    cells = [
        str(cell.value) for sheet in after_book.worksheets[5:] for row in sheet.iter_rows() for cell in row
        if cell.value
    ]
    assert not any(re.search(r"가상|예시 인터뷰|실제 고객|실측 별도|API 증적 별도", value) for value in cells)
    interviewed = read_assessment(workbook)
    assert sum(row.score is not None for row in interviewed.interview_items) == 54
    assert interviewed.overall_status != "예시 인터뷰 포함 - 실제 종합 판정 아님"
    assert {key: value.system for key, value in read_assessment(source).areas.items()} == {
        key: value.system for key, value in interviewed.areas.items()
    }
    score_table = next(s.table for s in presentation.slides[4].shapes if s.has_table)
    assert score_table.cell(1, 1).text != "응답 대기"
    recorded = load_result(source.parent)
    refresh_interview_summary(
        workbook, Collection.model_validate(recorded["collection"]),
        [Finding.model_validate(row) for row in recorded["findings"]],
    )
    refreshed = load_workbook(workbook)[RESULT_SHEET]
    assert "답변 완료 54개" in refreshed["B2"].value and "예시" not in refreshed["B2"].value
    assert refreshed["G5"].value == "인터뷰 완료" and refreshed["M5"].value == after["M5"].value


def test_interview_responses_never_overwrite_source_existing_outputs_or_human_inputs(tmp_path: Path) -> None:
    source = collect(tmp_path)
    book = load_workbook(source)
    sheet = book[RESULT_SHEET]
    sheet["M5"], sheet["N5"] = 4, "실제 검토 메모"
    sheet["J6"] = "사용자가 이미 입력한 답변"
    sheet["M7"] = "수동 확인 중"
    sheet["H8"] = "사용자가 입력한 추가 지표"
    book.save(source)
    original = source.read_bytes()
    with pytest.raises(FileExistsError):
        write_interview_responses(source, source)
    existing = tmp_path / "existing.xlsx"
    existing.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        write_interview_responses(source, existing)
    assert existing.read_bytes() == b"keep"
    output = tmp_path / "responses.xlsx"
    filled = write_interview_responses(source, output)
    assert len(filled) == 50 and source.read_bytes() == original
    after = load_workbook(output)[RESULT_SHEET]
    assert after["M5"].value == 4 and after["N5"].value == "실제 검토 메모"
    assert after["J6"].value == "사용자가 이미 입력한 답변" and after["M6"].value is None
    assert after["M7"].value == "수동 확인 중"
    assert after["H8"].value == "사용자가 입력한 추가 지표" and after["M8"].value is None
    assert after["M9"].value == SAMPLES[str(after["B9"].value)].level
    pending = tmp_path / "pending.xlsx"
    with pytest.raises(FileExistsError):
        interview_responses_main([
            "--workbook", str(source), "--output-workbook", str(pending), "--output-pptx", str(existing),
        ])
    assert not pending.exists() and existing.read_bytes() == b"keep"


@pytest.mark.parametrize(("column_offset", "value"), [(0, None), (1, None), (None, "DM-PR-99")])
def test_interview_responses_reject_missing_or_misaligned_criteria_without_creating_output(
    tmp_path: Path, column_offset: int | None, value: str | None,
) -> None:
    source = collect(tmp_path)
    book = load_workbook(source)
    level = SAMPLES["DM-PR-01"].level
    cell = "B5" if column_offset is None else f"{get_column_letter(6 + level + column_offset)}5"
    book["4. 질문별 평가 기준"][cell] = value
    book.save(source)
    original = source.read_bytes()
    output = tmp_path / "invalid.xlsx"
    with pytest.raises(ValueError):
        write_interview_responses(source, output)
    assert not output.exists() and source.read_bytes() == original


def test_deck_command_uses_workbook_interviews_without_rewriting_other_sheets(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    book = load_workbook(workbook)
    sheet = book[RESULT_SHEET]
    for row in range(5, sheet.max_row + 1):
        code = str(sheet.cell(row, 2).value or "")
        if code and "-SE-" not in code:
            sheet.cell(row, 13).value = 4
    book.save(workbook)
    with ZipFile(workbook) as archive:
        originals = {name: archive.read(name) for name in archive.namelist()
                     if name.startswith("xl/worksheets/") and name != "xl/worksheets/sheet6.xml"}
    assert main(["deck", "--output-dir", str(tmp_path), "--customer", "Fabrikam"]) == 0
    text = deck_text(next(tmp_path.rglob("EASM-report-*.pptx")))
    assert "Fabrikam AI Agent Governance Readiness 진단" in text
    assert "4.0" in text
    updated = load_workbook(workbook)[RESULT_SHEET]
    assert "답변 완료 54개" in updated["B2"].value
    with ZipFile(workbook) as archive:
        assert all(archive.read(name) == content for name, content in originals.items())


def test_deck_command_reports_missing_workbook(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    workbook.unlink()
    assert main(["deck", "--output-dir", str(tmp_path)]) == 1


def test_cover_discloses_only_synthetic_or_unrecorded_data(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    plain = tmp_path / "no-metrics.pptx"
    write_presentation(workbook, plain)
    assert "데이터 구분 미기록" in deck_text(plain)
    live = tmp_path / "live.pptx"
    metrics = metrics_of(workbook)
    metrics["run.mode"] = metrics["run.mode"].model_copy(update={"value": "live"})  # Local synthetic data only.
    write_presentation(workbook, live, context_from_workbook(workbook, "Contoso", metrics))
    text = deck_text(live)
    assert "Contoso AI Agent" in text and "합성 데모" not in text and "데이터 구분 미기록" not in text
    assert "고객명 미입력" not in text and "읽기 전용 API" not in text.splitlines()[0]


def test_context_date_uses_collection_time_in_korean_standard_time() -> None:
    data = synthetic(FULL, extra={"run.collected_at": metric("run.collected_at", "2026-11-19T20:30:00+00:00")})
    assert data.collected_label() == "2026년 11월 20일"
    assert DeckContext().customer == "<고객사>"
