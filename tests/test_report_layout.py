from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation

from easm_agent.models import Collection
from easm_agent.report import presentation_name, report_name
from easm_agent.report_layout import PLATFORM_SHEET, remap_formula, reorder_platform_parts


def test_platform_reference_remapping_is_sheet_specific():
    assert remap_formula("=IF(G14>0,P14/G14,0)", PLATFORM_SHEET) == "=IF(I14>0,G14/I14,0)"
    assert remap_formula("=SUM('1a_플랫폼 기준'!$P$5:$P$11)", "other") == "=SUM('1a_플랫폼 기준'!$G$5:$G$11)"
    assert remap_formula("=G14+P14", "other") == "=G14+P14"


def test_platform_columns_move_values_comments_validations_and_formulas():
    book = Workbook()
    sheet = book.active
    sheet.title = PLATFORM_SHEET
    for column, title, value in (
        ("F", "Agent 수", 15), ("G", "Agent ID 보유", 15), ("O", "Entra Agent ID 보유", 8),
        ("P", "생성·등록·배포 확인", 13), ("Q", "미게시·미확인", 2),
    ):
        sheet[f"{column}4"], sheet[f"{column}14"] = title, value
    sheet["G4"].comment = Comment("Native ID", "EASM")
    sheet["A1"] = "Title"
    sheet.merge_cells("A1:N1")
    sheet["B20"] = '="G14 "&$G$14'
    sheet["D20"] = "G14(원본 ID)"
    sheet["I5"] = "=J5+K5"
    sheet["I6"] = "=J6+K6"
    validation = DataValidation(type="whole")
    sheet.add_data_validation(validation)
    validation.add("F5:G11")
    other = book.create_sheet("other")
    other["A1"] = "=SUM('1a_플랫폼 기준'!P5:P11)"
    other["A2"] = "1a_플랫폼 기준!G14"
    stream = BytesIO()
    book.save(stream)
    with ZipFile(stream) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    root = etree.fromstring(parts["xl/worksheets/sheet1.xml"])
    base = root.find(f".//{main}c[@r='I5']/{main}f")
    base.attrib.update({"t": "shared", "si": "1", "ref": "I5:I6"})
    follower = root.find(f".//{main}c[@r='I6']/{main}f")
    follower.attrib.update({"t": "shared", "si": "1"})
    follower.text = None
    parts["xl/worksheets/sheet1.xml"] = etree.tostring(root)
    reorder_platform_parts(parts)
    once = dict(parts)
    reorder_platform_parts(parts)
    assert parts == once
    result = BytesIO()
    with ZipFile(result, "w", ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    moved = load_workbook(result)
    sheet = moved[PLATFORM_SHEET]
    assert [sheet[f"{column}14"].value for column in "FGHIJ"] == [15, 13, 2, 15, 8]
    assert sheet["I4"].comment.text == "Native ID"
    assert sheet["B20"].value == '="I14 "&$I$14'
    assert sheet["D20"].value == "I14(원본 ID)"
    assert sheet["L5"].value == "=M5+N5"
    assert sheet["L6"].value == "=M6+N6"
    assert str(sheet.data_validations.dataValidation[0].sqref) == "F5:F11 I5:I11"
    assert moved["other"]["A1"].value == "=SUM('1a_플랫폼 기준'!G5:G11)"
    assert moved["other"]["A2"].value == "1a_플랫폼 기준!I14"
    assert "A1:Q1" in {str(area) for area in sheet.merged_cells.ranges}


def test_report_names_share_actual_kst_collection_date():
    data = Collection(collected_at=datetime(2026, 11, 27, 18, tzinfo=UTC))
    expected = "AI Agent Governance Readiness 진단 결과 보고서 (프로세스·System 통합)_20261128"
    assert report_name(data) == expected + ".xlsx"
    assert presentation_name(data) == expected + ".pptx"
    assert presentation_name(data.model_dump(mode="json")) == expected + ".pptx"
