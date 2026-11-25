from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from lxml import etree
from openpyxl import load_workbook
from pptx import Presentation

from easm_agent.cli import main
from easm_agent.deck_model import Assessment, read_assessment
from easm_agent.models import Collection, Finding
from easm_agent.report import load_result
from easm_agent.report_backdata import ReportMetric, metrics_by_key
from easm_agent.report_biz_pptx import _measured_text, _walk, workbook_metrics
from easm_agent.report_interviews import result_cell_updates
from easm_agent.report_pptx import (
    context_from_workbook,
    presentation_template_path,
    write_presentation,
)
from easm_agent.report_story import PENDING_LABEL, DeckData
from scripts.import_report_template import import_template

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def workbook(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("biz-report")
    with patch("easm_agent.cli.DefaultAzureCredential", side_effect=AssertionError("Azure 호출 금지")):
        assert main([
            "collect", "--fixture", str(ROOT / "tests" / "fixtures" / "three_subscriptions.json"),
            "--output-dir", str(directory),
        ]) == 0
    return next(directory.rglob("report-*.xlsx"))


def all_text(deck: Presentation) -> str:
    return "\n".join(
        target.text if target.has_text_frame else "\n".join(
            cell.text for row in target.table.rows for cell in row.cells
        ) if target.has_table else ""
        for slide in deck.slides for target in _walk(slide.shapes)
    )


def test_default_is_the_approved_27_slide_business_template() -> None:
    path = presentation_template_path()
    deck = Presentation(path)
    assert len(deck.slides) == 27
    assert any("비즈니스 연결" in target.text for target in deck.slides[23].shapes if target.has_text_frame)
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read("docProps/core.xml"))
        assert not root.xpath("//*[local-name()='creator' or local-name()='lastModifiedBy']/text()")
        assert not any(name.startswith("docMetadata/") for name in archive.namelist())


def test_generated_deck_covers_all_26_codes_and_preserves_original_design_parts(workbook: Path) -> None:
    path = next(workbook.parent.glob("EASM-report-*.pptx"))
    deck = Presentation(path)
    assessment = read_assessment(workbook)
    assert len(deck.slides) == 27
    table = next(target.table for target in deck.slides[16].shapes if target.has_table)
    assert len(table.rows) == 14 and len(table.columns) == 6
    cells = [cell.text for row in table.rows for cell in row.cells]
    codes = [re.match(r"[A-Z]{2}-SY-\d+", text)[0] for text in cells if re.match(r"[A-Z]{2}-SY-\d+", text)]
    assert len(codes) == len(set(codes)) == 26
    assert set(codes) == {item.code for item in assessment.system_items}
    for row in table.rows:
        for offset in (0, 3):
            match = re.match(r"[A-Z]{2}-SY-\d+", row.cells[offset].text)
            if match:
                item = next(item for item in assessment.system_items if item.code == match[0])
                assert row.cells[offset + 2].text == ("확인 중" if item.score is None else f"L{item.score}")
    with ZipFile(presentation_template_path()) as source, ZipFile(path) as output:
        for name in source.namelist():
            if name.startswith(("ppt/theme/", "ppt/slideMasters/", "ppt/slideLayouts/", "ppt/media/")):
                assert source.read(name) == output.read(name), name
    text = all_text(deck)
    assert "System 실측 (20개 항목)" not in text
    api_text = "\n".join(
        target.text for page in (1, 5, *range(13, 21)) for target in _walk(deck.slides[page].shapes)
        if target.has_text_frame
    )
    assert not any(sample in api_text for sample in ("1,850명", "Shadow Agent 117", "고아 Agent 95", "월 31개"))
    assert "제공 Excel 입력 유지" in text
    cross = "\n".join(target.text for target in _walk(deck.slides[22].shapes) if target.has_text_frame)
    assert "고아 23%" not in cross and "비용 식별 45%" not in cross


def test_provided_manual_and_business_reference_prose_is_preserved(workbook: Path) -> None:
    deck = Presentation(next(workbook.parent.glob("EASM-report-*.pptx")))
    source = Presentation(presentation_template_path())
    for page in (10, 11):
        text = "\n".join(target.text for target in _walk(deck.slides[page].shapes) if target.has_text_frame)
        book = load_workbook(workbook)
        offset = 0 if page == 10 else 6
        for row in range(5+offset, 11+offset):
            quote = book["6_인터뷰 기록"].cell(row, 3).value
            if quote:
                assert quote.replace("\v", "\n") in text.replace("\v", "\n")
    executive = "\n".join(target.text for target in _walk(deck.slides[1].shapes) if target.has_text_frame)
    assert "L2.4" not in executive and "307개" not in executive and "퇴사자 소유 Agent 33개" not in executive
    for page in (2,):
        text = "\n".join(target.text for target in _walk(deck.slides[page].shapes) if target.has_text_frame)
        original = "\n".join(target.text for target in _walk(source.slides[page].shapes) if target.has_text_frame)
        assert text == original.translate(str.maketrans({"\u2013": "-", "\u2014": "-"}))


def test_xlsx_only_conversion_retains_observed_api_values_without_raw_json(workbook: Path, tmp_path: Path) -> None:
    output = tmp_path / "xlsx-only.pptx"
    metrics = workbook_metrics(workbook)
    assert any(key.startswith("se.") and metric.status == "observed" for key, metric in metrics.items())
    write_presentation(workbook, output)
    text = all_text(Presentation(output))
    assert "26개" in text and len(Presentation(output).slides) == 27
    assert "저장 API 관측" in text


def test_entered_interview_values_and_actual_quotes_are_reflected_without_excel_cache(
    workbook: Path, tmp_path: Path,
) -> None:
    filled = tmp_path / "filled.xlsx"
    filled.write_bytes(result_cell_updates(workbook, {
        "F5": 5, "G5": "Y", "H5": "N", "I5": "N", "M5": "사용자 입력 근거",
    }, sheet_name="4_프로세스 점수"))
    filled.write_bytes(result_cell_updates(filled, {
        "B5": "입력된 직무", "C5": "실제 입력 인용", "E5": "입력된 시사점", "F5": "입력된 조치",
    }, sheet_name="6_인터뷰 기록"))
    output = tmp_path / "filled.pptx"
    write_presentation(filled, output)
    text = all_text(Presentation(output))
    assert all(value in text for value in ("입력된 직무", "실제 입력 인용", "입력된 시사점", "입력된 조치"))
    assert read_assessment(filled).interview_items[0].score == 3
    assert sum(item.score is not None for item in read_assessment(filled).interview_items) == 54
    assert load_workbook(filled)["4_프로세스 점수"]["F5"].value == 5


def test_tables_and_crosscheck_numbers_stay_in_their_display_regions(workbook: Path) -> None:
    deck = Presentation(next(workbook.parent.glob("EASM-report-*.pptx")))
    for page in (15, 16, 17, 18, 19, 20, 24):
        for target in deck.slides[page].shapes:
            if target.has_table:
                assert target.top + sum(row.height for row in target.table.rows) <= 6.7 * 914400
    table = next(target for target in deck.slides[25].shapes if target.has_table)
    assert table.top + sum(row.height for row in table.table.rows) < 3.5 * 914400
    slide = deck.slides[22]
    for identifier in (18, 26, 33, 40, 47, 54):
        target = next(target for target in slide.shapes if target.shape_id == identifier)
        assert 1.5 * 914400 <= target.left <= 6.3 * 914400
    for page, footer_id in ((17, 31758), (20, 40679)):
        slide = deck.slides[page]
        footer = next(target for target in slide.shapes if target.shape_id == footer_id)
        table = next(target for target in slide.shapes if target.has_table)
        assert table.top + sum(row.height for row in table.table.rows) + .08 * 914400 < footer.top
    assert {42586, 42937, 43297} <= {target.shape_id for target in deck.slides[24].shapes}
    headline = next(target.text for target in deck.slides[15].shapes if target.shape_id == 24652)
    assert "일치" not in headline
    assert any("20개 문항" in target.text for target in _walk(deck.slides[7].shapes) if target.has_text_frame)


def test_orphan_table_reuses_measured_overprivileged_role_breakdown_not_pending(workbook: Path) -> None:
    book = load_workbook(next(workbook.parent.glob("report-*.xlsx")))
    detail = book["2b_세부 내역"]
    labels = [detail.cell(row, 1).value for row in range(12, 16)]
    counts = [detail.cell(row, 2).value for row in range(12, 16)]
    deck = Presentation(next(workbook.parent.glob("EASM-report-*.pptx")))
    table = next(target for target in deck.slides[18].shapes if target.shape_id == 46).table
    rows = list(table.rows)
    if all(isinstance(count, (int, float)) for count in counts[:3]):
        for offset, label in zip(range(1, 5), labels, strict=True):
            assert rows[offset].cells[2].text == str(label)
        assert rows[4].cells[3].text == f"{sum(counts[:3]):g}"
    # "소유자 퇴사" needs separate HR data this system never collects - stays pending regardless.
    assert rows[2].cells[1].text == PENDING_LABEL


def test_import_and_package_deck_round_trip_use_new_template(workbook: Path, tmp_path: Path) -> None:
    imported = tmp_path / "template.pptx"
    import_template(presentation_template_path(), imported)
    with ZipFile(imported) as output, ZipFile(presentation_template_path()) as source:
        for name in source.namelist():
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                assert output.read(name) == source.read(name)
    data = load_result(workbook.parent)
    context = context_from_workbook(
        workbook, metrics=metrics_by_key(
            Collection.model_validate(data["collection"]),
            [Finding.model_validate(row) for row in data["findings"]], data["mode"],
        ),
    )
    expected_time = Collection.model_validate(data["collection"]).collected_at
    assert context_from_workbook(workbook, collection=Collection.model_validate(data["collection"])).collected_at == expected_time
    assert context_from_workbook(workbook).collected_at == expected_time
    output = tmp_path / "roundtrip.pptx"
    write_presentation(workbook, output, context)
    assert len(Presentation(output).slides) == 27


@pytest.mark.parametrize(("numerator", "denominator", "expected"), [
    (.4, .4006, "99.85%"), (.0000001, 1, "<0.01%"), (.99999, 1, ">99.99%·<100%"),
])
def test_cost_display_explains_equal_rounded_amounts_without_rounding_to_full_compliance(
    numerator: float, denominator: float, expected: str,
) -> None:
    code = "OT-SY-24"
    values = [
        ("se." + code, numerator / denominator, "ratio"),
        (f"se.{code}.numerator", numerator, "USD"),
        (f"se.{code}.denominator", denominator, "USD"),
    ]
    data = DeckData(Assessment([], {}, None, "판정 보류", "", []), {
        key: ReportMetric(key=key, label=code, value=value, unit=unit,
                          status="observed", reason=None, limitation="통화 표시 정밀도 테스트")
        for key, value, unit in values
    })
    assert expected in _measured_text(data, code)
