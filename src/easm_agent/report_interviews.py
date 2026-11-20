"""Fill unanswered interview rows of the result sheet from sample interview responses."""

from __future__ import annotations

import argparse
import re
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string

from easm_agent.report_template import CRITERIA_SHEET, RESULT_SHEET

INTERVIEW_CODE = re.compile(r"[A-Z]{2}-(?:PR|PE|DA|TE)-\d+")
PENDING_BASIS = "인터뷰를 통해 확인하는 수동 심사 항목"
CellValue = str | int | tuple[str, str]


def result_cell_updates(path: Path, updates: dict[str, CellValue]) -> bytes:
    """Patch result-sheet cells in the raw XML, retaining styles and cached formulas.

    A (bold, rest) tuple is written as a rich text with a bold leading label.
    """
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    output = BytesIO()
    with ZipFile(path) as source, ZipFile(output, "w") as target:
        workbook = etree.fromstring(source.read("xl/workbook.xml"))
        result = next(node for node in workbook.iter(f"{{{main}}}sheet") if node.get("name") == RESULT_SHEET)
        relationships = etree.fromstring(source.read("xl/_rels/workbook.xml.rels"))
        sheet_target = next(node.get("Target") for node in relationships if node.get("Id") == result.get(f"{{{rel}}}id"))
        part = sheet_target.lstrip("/") if sheet_target.startswith("/") else "xl/" + sheet_target
        root = etree.fromstring(source.read(part))
        rows = {int(row.get("r")): row for row in root.iter(f"{{{main}}}row")}
        for address, value in updates.items():
            if isinstance(value, str) and len(value) > 32767:
                raise ValueError(f"{address}: 입력이 Excel 셀 상한을 초과합니다.")
            match = re.fullmatch(r"([A-Z]+)(\d+)", address)
            if match is None:
                raise ValueError("유효하지 않은 보고서 셀 주소입니다.")
            row = rows[int(match[2])]
            cell = next((cell for cell in row if cell.get("r") == address), None)
            if cell is None:
                cell = etree.Element(f"{{{main}}}c", r=address)
                column = column_index_from_string(match[1])
                position = next((
                    index for index, existing in enumerate(row)
                    if column_index_from_string(re.sub(r"\d+", "", existing.get("r"))) > column
                ), len(row))
                row.insert(position, cell)
            for child in list(cell):
                cell.remove(child)
            if isinstance(value, int):
                cell.set("t", "n")
                etree.SubElement(cell, f"{{{main}}}v").text = str(value)
            elif isinstance(value, tuple):
                cell.set("t", "inlineStr")
                inline = etree.SubElement(cell, f"{{{main}}}is")
                bold = etree.SubElement(etree.SubElement(inline, f"{{{main}}}r"), f"{{{main}}}rPr")
                etree.SubElement(bold, f"{{{main}}}b")
                etree.SubElement(bold.getparent(), f"{{{main}}}t").text = value[0]
                rest = etree.SubElement(etree.SubElement(inline, f"{{{main}}}r"), f"{{{main}}}t")
                rest.text = value[1]
                rest.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            else:
                cell.set("t", "inlineStr")
                inline = etree.SubElement(cell, f"{{{main}}}is")
                etree.SubElement(inline, f"{{{main}}}t").text = value
            if address in ("B2", "B3"):
                row.set("ht", "45")
                row.set("customHeight", "1")
        changed = {part: root}
        for info in source.infolist():
            target.writestr(
                info,
                etree.tostring(changed[info.filename], encoding="UTF-8", xml_declaration=True, standalone=True)
                if info.filename in changed else source.read(info.filename),
            )
    return output.getvalue()


def normalized(text: object) -> str:
    return " ".join(str(text or "").split())


def write_interview_responses(source: Path, output: Path) -> list[tuple[str, str, str]]:
    """Fill untouched interview rows from SAMPLES in a new workbook copy; API evidence stays as is."""
    from easm_agent.interview_samples import SAMPLES

    if source.resolve() == output.resolve() or output.exists():
        raise FileExistsError("인터뷰 응답 출력은 원본과 다른, 존재하지 않는 Excel 경로여야 합니다.")
    book = load_workbook(source, rich_text=False)
    sheet, criteria = book[RESULT_SHEET], book[CRITERIA_SHEET]
    updates: dict[str, CellValue] = {}
    filled = []
    try:
        for row in range(5, sheet.max_row + 1):
            code = str(sheet.cell(row, 2).value or "")
            if not INTERVIEW_CODE.fullmatch(code):
                continue
            if (
                sheet.cell(row, 7).value != "인터뷰 필요"
                or any(sheet.cell(row, col).value not in (None, "") for col in (8, 9, 11, 12, 13, 14))
                or sheet.cell(row, 10).value not in (None, "", PENDING_BASIS)
            ):
                continue
            if str(criteria.cell(row, 2).value or "") != code:
                raise ValueError(f"{code}: 평가 기준과 결과 행이 일치하지 않습니다.")
            sample = SAMPLES.get(code)
            if sample is None:
                raise ValueError(f"{code}: 인터뷰 응답 샘플이 없습니다.")
            if type(sample.level) is not int or not 1 <= sample.level <= 5:
                raise ValueError(f"{code}: 인터뷰 점수는 1~5 정수여야 합니다.")
            criterion = normalized(criteria.cell(row, 6 + sample.level).value)
            if not criterion:
                raise ValueError(f"{code}: L{sample.level} 기준 문장이 없습니다.")
            if sample.level < 5:
                condition = normalized(criteria.cell(row, 7 + sample.level).value)
                if not condition:
                    raise ValueError(f"{code}: L{sample.level + 1} 기준 문장이 없습니다.")
                next_step: CellValue = (f"Level {sample.level + 1}", ": " + condition)
            else:
                next_step = "Level 5 유지 - 지속 개선 주기 점검"
            updates.update({
                f"G{row}": "인터뷰 완료",
                f"H{row}": sample.metric,
                f"I{row}": (f"Level {sample.level}", f" ({criterion})"),
                f"J{row}": sample.basis,
                f"K{row}": "인터뷰 응답",
                f"L{row}": next_step,
                f"M{row}": sample.level,
                f"N{row}": sample.memo,
            })
            filled.append((code, f"M{row}", f"J{row}"))
        if not filled:
            raise ValueError("원문 입력을 보존하면서 채울 미입력 인터뷰 항목이 없습니다.")
        summary = str(sheet["B2"].value or "")
        total_done = sum(
            INTERVIEW_CODE.fullmatch(str(sheet.cell(row, 2).value or "")) is not None
            and (sheet.cell(row, 13).value not in (None, "") or f"M{row}" in updates)
            for row in range(5, sheet.max_row + 1)
        )
        updates["B2"] = re.sub(r"답변 완료 \d+개", f"답변 완료 {total_done}개", summary)
    finally:
        book.close()
    payload = result_cell_updates(source, updates)
    with output.open("xb") as target:
        target.write(payload)
    return filled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="샘플 인터뷰 응답 기입 - 기존 결과를 수정하지 않고 사본 생성")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output-workbook", type=Path, required=True)
    parser.add_argument("--output-pptx", type=Path, required=True)
    parser.add_argument("--customer", default="<고객사>")
    parser.add_argument("--raw-json", type=Path, help="보고서 지표 계산에 사용할 raw-data-<타임스탬프>.json")
    args = parser.parse_args(argv)
    if (
        args.output_pptx.exists()
        or args.output_pptx.resolve() in (args.workbook.resolve(), args.output_workbook.resolve())
    ):
        raise FileExistsError("출력 PPT는 다른, 존재하지 않는 경로여야 합니다.")
    from easm_agent.models import Collection, Finding
    from easm_agent.report import latest_raw, load_result
    from easm_agent.report_backdata import metrics_by_key
    from easm_agent.report_pptx import context_from_workbook, write_presentation

    metrics = None
    collection = None
    if args.raw_json is not None:
        raw = args.raw_json.resolve()
        found = latest_raw(raw.parent)
        if found is None or found.resolve() != raw:
            raise ValueError("--raw-json은 같은 폴더에서 가장 최근의 raw-data JSON이어야 합니다.")
        result = load_result(raw.parent)
        collection = Collection.model_validate(result["collection"])
        findings = [Finding.model_validate(row) for row in result["findings"]]
        metrics = metrics_by_key(collection, findings, result.get("mode") or collection.facts.get("data_mode") or "live")
    filled = write_interview_responses(args.workbook, args.output_workbook)
    write_presentation(
        args.output_workbook, args.output_pptx,
        context_from_workbook(args.output_workbook, args.customer, metrics, collection),
    )
    print(f"샘플 인터뷰 응답 기입 - {len(filled)}개")
    for code, score_cell, answer_cell in filled:
        print(f"{code}: {RESULT_SHEET}!{score_cell} (점수), {answer_cell} (근거)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
