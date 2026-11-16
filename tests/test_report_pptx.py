from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from pptx import Presentation

from easm_agent.cli import main
from easm_agent.deck_model import Item, compute_scores, level_of, read_assessment
from easm_agent.report_pptx import TEMPLATE_NAME, presentation_template_path, write_presentation
from easm_agent.report_template import RESULT_SHEET

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "three_subscriptions.json"


def item(code: str, score: int | None) -> Item:
    return Item(code=code, area=code[:2], kind=code[3:5], row=5, text=code, levels=[""] * 5,
                evidence="", score=score, status="", detail="", memo="")


def area_items(prefix: str, interview: int | None, system: int | None) -> list[Item]:
    return [item(f"{prefix}-PR-01", interview), item(f"{prefix}-PE-02", interview),
            item(f"{prefix}-DA-03", interview), item(f"{prefix}-TE-04", interview),
            item(f"{prefix}-SY-05", system)]


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
    areas, overall, status = compute_scores([item("DM-PR-01", None), item("DM-SY-02", None)])
    assert overall is None and status == "판정 보류"
    assert all(area.final is None for area in areas.values())


def test_packaged_template_is_available() -> None:
    assert presentation_template_path().name == TEMPLATE_NAME


def test_run_creates_deck_that_marks_interviews_as_not_entered(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    deck = workbook.parent / workbook.name.replace("report-", "EASM-report-").replace(".xlsx", ".pptx")
    assert deck.is_file() and len(Presentation(deck).slides) == 15
    text = deck_text(deck)
    assert "점검 결과 보고서" in text and "<고객사>" in text
    assert "인터뷰 54개 중 0개 입력" in text
    assert not any(word in text for word in ("Contoso", "AI READINESS", "Lorem", "Click to"))


def test_deck_command_uses_interview_scores_entered_in_the_workbook(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    book = load_workbook(workbook)
    sheet = book[RESULT_SHEET]
    for row in range(5, sheet.max_row + 1):
        code = str(sheet.cell(row, 2).value or "")
        if code and "-SY-" not in code:
            sheet.cell(row, 13).value = 4
    book.save(workbook)
    assert sum(i.score == 4 for i in read_assessment(workbook).interview_items) == 54
    assert main(["deck", "--output-dir", str(tmp_path), "--customer", "Fabrikam"]) == 0
    text = deck_text(next(tmp_path.rglob("EASM-report-*.pptx")))
    assert "Fabrikam" in text and "인터뷰 54개 중 54개 입력" in text and "<고객사>" not in text


def test_deck_command_reports_missing_workbook(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    workbook.unlink()
    assert main(["deck", "--output-dir", str(tmp_path)]) == 1


def test_write_presentation_accepts_a_workbook_path(tmp_path: Path) -> None:
    workbook = collect(tmp_path)
    output = tmp_path / "again.pptx"
    write_presentation(workbook, output)
    assert len(Presentation(output).slides) == 15
