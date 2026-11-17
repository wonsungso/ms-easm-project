from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from lxml import etree
from openpyxl import load_workbook
from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from easm_agent.cli import main
from easm_agent.deck_model import Item, compute_scores, level_of, read_assessment
from easm_agent.models import load_criteria
from easm_agent.report_pptx import (
    PRESENTATION_FONT,
    TEMPLATE_NAME,
    format_appendix_tables,
    presentation_template_path,
    write_presentation,
)
from easm_agent.report_template import RESULT_SHEET

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "three_subscriptions.json"


def item(code: str, score: int | None) -> Item:
    return Item(code=code, area=code[:2], kind=code[3:5], row=5, text=code, levels=[""] * 5,
                evidence="", score=score, status="", detail="", memo="")


def area_items(prefix: str, interview: int | None, system: int | None) -> list[Item]:
    return [item(f"{prefix}-PR-01", interview), item(f"{prefix}-PE-02", interview),
            item(f"{prefix}-DA-03", interview), item(f"{prefix}-TE-04", interview),
            item(f"{prefix}-SE-05", system)]


def deck_text(path: Path) -> str:
    return "\n".join(
        shape.text_frame.text for slide in Presentation(path).slides for shape in slide.shapes
        if shape.has_text_frame
    )


def collect(tmp_path: Path) -> Path:
    with patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("No Azure calls")):
        assert main(["collect", "--config", str(ROOT / "config" / "custom-config.yaml"),
                     "--fixture", str(FIXTURE), "--output-dir", str(tmp_path)]) == 0
    return next(tmp_path.rglob("report-*.xlsx"))


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


def test_packaged_template_is_available() -> None:
    assert presentation_template_path().name == TEMPLATE_NAME


def test_appendix_tables_left_align_questions_and_split_system_scores() -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    system = slide.shapes.add_table(3, 3, Inches(0.5), Inches(1), Inches(12.1), Inches(3)).table
    for column, width in zip(system.columns, (1.65, 4.25, 6.2), strict=True):
        column.width = Inches(width)
    values = [
        ["항목 · 실측 점수", "수집 항목", "원본 실측 판정"],
        ["DS-SE-06\nLevel 5", "MCP 도구 필수 승인 모드", "실측 충족률 100%"],
        ["DM-SE-01\n평가 보류", "환경 역할 할당", "permission_denied"],
    ]
    for row, texts in zip(system.rows, values, strict=True):
        for cell, text in zip(row.cells, texts, strict=True):
            cell.text = text
            cell.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    first = system.cell(1, 0).text_frame.paragraphs[0].runs[0]
    first.font.bold, first.font.size = True, Pt(11)
    second = prs.slides.add_slide(prs.slide_layouts[6])
    interview = second.shapes.add_table(2, 3, Inches(0.5), Inches(1), Inches(12.1), Inches(2)).table
    for row, texts in zip(interview.rows, (
        ["문항 · 평가 점수", "인터뷰 질문", "답변 · 확인 증적"],
        ["DM-PR-01\nLevel 3", "수요 접수 절차가 있는가?", "표준 접수 절차 운영"],
    ), strict=True):
        for cell, text in zip(row.cells, texts, strict=True):
            cell.text = text
            cell.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    width = sum(column.width for column in system.columns)
    format_appendix_tables(prs)
    assert [cell.text for cell in system.rows[0].cells] == ["항목", "실측 점수", "수집 항목", "원본 실측 판정"]
    assert [cell.text for cell in system.rows[1].cells] == [
        "DS-SE-06", "Level 5", "MCP 도구 필수 승인 모드", "실측 충족률 100%",
    ]
    assert system.cell(2, 1).text == "평가 보류"
    assert system.cell(1, 1).text_frame.paragraphs[0].runs[0].font.bold
    assert sum(column.width for column in system.columns) == width
    assert [cell.text for cell in interview.rows[0].cells] == ["항목", "평가 점수", "인터뷰 질문", "답변 · 확인 증적"]
    assert [cell.text for cell in interview.rows[1].cells] == [
        "DM-PR-01", "Level 3", "수요 접수 절차가 있는가?", "표준 접수 절차 운영",
    ]
    for table, column in ((system, 2), (interview, 2)):
        assert all(cell.text_frame.paragraphs[0].alignment == PP_ALIGN.LEFT
                   for cell in (row.cells[column] for row in table.rows))
    once = slide._element.xml
    format_appendix_tables(prs)
    assert slide._element.xml == once


def test_run_creates_deck_that_marks_interviews_as_not_entered(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    deck = workbook.parent / workbook.name.replace("report-", "EASM-report-").replace(".xlsx", ".pptx")
    assert deck.is_file() and len(Presentation(deck).slides) == 15
    text = deck_text(deck)
    assessment = read_assessment(workbook)
    assert [item.code for item in assessment.system_items] == list(load_criteria()["items"])
    assert len(assessment.interview_items) == 54
    with ZipFile(deck) as archive:
        slides = "\n".join(
            archive.read(name).decode("utf-8") for name in archive.namelist()
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        )
    rendered_codes = set(re.findall(r"\b[A-Z]{2}-SE-\d{2}\b", slides))
    assert rendered_codes and rendered_codes <= set(load_criteria()["items"])
    assert "점검 결과 보고서" in text and "<고객사>" in text
    presentation = Presentation(deck)
    status = presentation.slides[2]
    badge = next(shape for shape in status.shapes if shape.shape_id == 9)
    logo = next(shape for shape in status.shapes if shape.shape_id == 2)
    assert badge.text == "<고객사>"
    assert Inches(0) < logo.left - (badge.left + badge.width) < Inches(0.3)
    assert abs(badge.top - logo.top) < Inches(0.1)
    assert not any(shape.name == "Fictional interview disclosure" for slide in presentation.slides for shape in slide.shapes)
    assert "인터뷰 54개 중 답변 완료 0개" in text
    assert not any(word in text for word in ("Contoso", "AI READINESS", "Lorem", "Click to"))
    with ZipFile(deck) as archive:
        fonts = [
            node.get("typeface") for name in archive.namelist() if name.endswith(".xml")
            for node in etree.fromstring(archive.read(name)).iter() if "typeface" in node.attrib
        ]
    assert fonts and set(fonts) == {PRESENTATION_FONT}


def test_unknown_workbook_code_is_rejected(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    book = load_workbook(workbook)
    book["4. 질문별 평가 기준"]["B5"] = "DM-XX-01"
    book.save(workbook)
    with pytest.raises(ValueError, match="지원되지 않는 평가 코드"):
        read_assessment(workbook)


def test_fictional_interview_notice_is_bottom_right_on_every_slide(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    book = load_workbook(workbook)
    book[RESULT_SHEET]["M5"] = 4
    book[RESULT_SHEET]["N5"] = "[가상 인터뷰 - 보고서 예시]"
    book.save(workbook)
    output = tmp_path / "example.pptx"
    write_presentation(workbook, output)
    deck = Presentation(output)
    for slide in deck.slides:
        notice, = [shape for shape in slide.shapes if shape.name == "Fictional interview disclosure"]
        assert "가상 인터뷰 1개 + 실측 SE 26개" in notice.text
        assert notice.text_frame.paragraphs[0].alignment == PP_ALIGN.RIGHT
        assert Inches(0.2) <= deck.slide_width - notice.left - notice.width <= Inches(0.3)
        assert Inches(0.03) <= deck.slide_height - notice.top - notice.height <= Inches(0.1)
        assert notice.top > deck.slide_height - Inches(0.3)


def test_deck_command_uses_interview_scores_entered_in_the_workbook(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    book = load_workbook(workbook)
    sheet = book[RESULT_SHEET]
    for row in range(5, sheet.max_row + 1):
        code = str(sheet.cell(row, 2).value or "")
        if code and "-SE-" not in code:
            sheet.cell(row, 13).value = 4
    book.save(workbook)
    assert sum(i.score == 4 for i in read_assessment(workbook).interview_items) == 54
    with ZipFile(workbook) as archive:
        original_sheets = {name: archive.read(name) for name in archive.namelist()
                           if name.startswith("xl/worksheets/") and name != "xl/worksheets/sheet6.xml"}
    assert main(["deck", "--output-dir", str(tmp_path), "--customer", "Fabrikam"]) == 0
    text = deck_text(next(tmp_path.rglob("EASM-report-*.pptx")))
    assert "Fabrikam" in text and "인터뷰 54개 중 답변 완료 54개" in text and "<고객사>" not in text
    updated = load_workbook(workbook, rich_text=True)[RESULT_SHEET]
    for row in range(5, updated.max_row + 1):
        code = str(updated.cell(row, 2).value or "")
        if code and "-SE-" not in code:
            assert updated.cell(row, 7).value == "답변 완료"
            assert updated.cell(row, 13).value == 4
    assert "인터뷰 54개 항목(답변 완료 54개)" in updated["B2"].value
    assert "\n수집 대상 : 구독 3개, Azure Agent 3개." in updated["B2"].value
    assert updated["B3"].value.startswith("참고 -")
    with ZipFile(workbook) as archive:
        assert all(archive.read(name) == content for name, content in original_sheets.items())


def test_deck_command_reports_missing_workbook(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    workbook.unlink()
    assert main(["deck", "--output-dir", str(tmp_path)]) == 1


def test_deck_only_marks_valid_interview_scores_complete(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    book = load_workbook(workbook)
    sheet = book[RESULT_SHEET]
    sheet["M5"], sheet["M6"], sheet["M7"] = 3, "N/A", 0
    book.save(workbook)
    assert main(["deck", "--output-dir", str(tmp_path)]) == 0
    result = load_workbook(workbook)[RESULT_SHEET]
    assert result["G5"].value == "답변 완료"
    assert result["G6"].value == result["G7"].value == "인터뷰 필요"
    assert "답변 완료 1개" in result["B2"].value
    assert result["M6"].value == "N/A" and result["M7"].value == 0


def test_write_presentation_accepts_a_workbook_path(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    output = tmp_path / "again.pptx"
    write_presentation(workbook, output)
    assert len(Presentation(output).slides) == 15
