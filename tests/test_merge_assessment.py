from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock

from easm_agent.models import load_criteria
from scripts.assessment_descriptions import ITEM_DETAILS
from scripts.merge_assessment import (
    ROOT,
    SOURCE_SHEET,
    merge_assessment,
    xml_bytes,
)

UNTOUCHED = (
    "xl/worksheets/sheet1.xml", "xl/worksheets/sheet3.xml",
    "xl/sharedStrings.xml", "xl/theme/theme1.xml",
)
LEGACY_TEMPLATE = Path(__file__).parent / "fixtures" / "legacy-assessment-template.xlsx"


def test_office_compatibility_prefixes_survive_serialization() -> None:
    raw = (
        b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        b'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        b'xmlns:x15="http://schemas.microsoft.com/office/spreadsheetml/2010/11/main" '
        b'xmlns:xr="http://schemas.microsoft.com/office/spreadsheetml/2014/revision" '
        b'mc:Ignorable="x15 xr"><mc:AlternateContent><mc:Choice Requires="x15"/>'
        b'<mc:Choice xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main" Requires="x14"/>'
        b'</mc:AlternateContent></workbook>'
    )
    serialized = xml_bytes(ET.fromstring(raw), raw)
    namespaces = dict(value for _, value in ET.iterparse(BytesIO(serialized), events=("start-ns",)))
    assert {"mc", "x15", "xr", "x14"} <= namespaces.keys()
    root = ET.fromstring(serialized)
    compatibility = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    assert root.get(f"{{{compatibility}}}Ignorable") == "x15 xr"
    choice = root.find(f"{{{compatibility}}}AlternateContent/{{{compatibility}}}Choice")
    assert choice is not None and choice.get("Requires") == "x15"


def test_rejects_source_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "model.xlsx"
    source.write_bytes(b"not used")
    with pytest.raises(ValueError, match="덮어쓰기"):
        merge_assessment(source, tmp_path / "." / "model.xlsx")
    assert source.read_bytes() == b"not used"


def test_delivered_workbook_preserves_user_formatting_and_is_idempotent(tmp_path: Path) -> None:
    delivered = LEGACY_TEMPLATE
    rebuilt = tmp_path / "rebuilt.xlsx"
    merge_assessment(delivered, rebuilt)
    with ZipFile(delivered) as old, ZipFile(rebuilt) as new:
        assert old.namelist() == new.namelist()
        for name in UNTOUCHED:
            assert old.read(name) == new.read(name), name
    before, after = load_workbook(delivered, rich_text=True), load_workbook(rebuilt, rich_text=True)
    for old_sheet, new_sheet in zip(before, after, strict=True):
        for row in old_sheet:
            for cell in row:
                updated = new_sheet[cell.coordinate]
                assert cell.style_id == updated.style_id
                assert cell.value == updated.value


def test_delivered_criteria_and_scoring_include_every_system_evidence() -> None:
    book = load_workbook(LEGACY_TEMPLATE)
    sheet = book[SOURCE_SHEET]
    rows = {row[1].value: row for row in sheet if "-SY-" in str(row[1].value)}
    assert len(rows) == 26
    for code, config in load_criteria()["items"].items():
        assert [rows[code][i].value for i in range(6, 11)] == list(config["levels"].values())
    formulas = [cell.value for row in book.worksheets[4].iter_rows(min_row=64, max_row=69) for cell in row if cell.data_type == "f"]
    for row in rows.values():
        assert sum(f"'{SOURCE_SHEET}'!M{row[1].row}" in formula for formula in formulas) == 1
    for domain, number in zip(
        ("1. Demand", "2. Design", "3. Build", "4. Deploy", "5. Operate", "6. Optimize"),
        range(64, 70), strict=True,
    ):
        formula = book.worksheets[4].cell(number, 7).value
        references = {int(value) for value in re.findall(r"!M(\d+)", formula)}
        assert references == {
            row[1].row for row in rows.values() if row[2].value == domain
        }
    assert str(sheet.data_validations.dataValidation[0].sqref) == "M5:M84"
    assert "N/A" in sheet.data_validations.dataValidation[0].formula1
    assert rows.keys() == load_criteria()["items"].keys()
    assert "실행 로그" in rows["OE-SY-18"][5].value
    assert "관리 ID" in rows["OE-SY-19"][5].value
    assert "조건부 접근" not in str(book.worksheets[1]["H8"].value)


def test_only_implemented_evidence_has_bold_titles_and_bullet_descriptions() -> None:
    book = load_workbook(LEGACY_TEMPLATE, rich_text=True)
    sheet = book[SOURCE_SHEET]
    rows = {row[1].value: row for row in sheet.iter_rows(min_row=5) if row[1].value}
    assert len(rows) == 80
    assert len(ITEM_DETAILS) == 26
    assert ITEM_DETAILS.keys() == load_criteria()["items"].keys()
    for code, row in rows.items():
        content = row[5].value
        if code not in ITEM_DETAILS:
            assert isinstance(content, str)
            assert "\n- " not in content
            continue
        assert isinstance(content, CellRichText)
        assert len(content) == 2 and all(isinstance(part, TextBlock) for part in content)
        assert content[0].text and content[0].font.b is True
        assert content[1].font.b is False
        bullets = content[1].text.splitlines()[1:]
        assert bullets and all(line.startswith("- ") for line in bullets)
        assert "\n".join(line[2:] for line in bullets) == ITEM_DETAILS[code]
        assert not any(line.endswith(("합니다.", "않습니다.", "아닙니다.")) for line in bullets)
        assert row[5].alignment.wrap_text
    summary = "\n".join(str(cell.value) for row in book.worksheets[1] for cell in row)
    assert not any(detail in summary for detail in ITEM_DETAILS.values())


def test_integrated_template_is_validated_without_reformatting(tmp_path: Path) -> None:
    source = ROOT / "docs" / "assessment-result-template.xlsx"
    target = tmp_path / "integrated.xlsx"
    result = merge_assessment(source, target)
    assert result["merged_proposals"] == 26
    assert source.read_bytes() == target.read_bytes()
