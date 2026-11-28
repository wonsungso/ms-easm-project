from __future__ import annotations

import json
import posixpath
import re
import sysconfig
from copy import deepcopy
from pathlib import Path
from typing import Any

from lxml import etree
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.formula.translate import Translator
from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries

PLATFORM_SHEET = "1a_플랫폼 기준"
PLATFORM_ORDER = (1, 2, 3, 4, 5, 6, 16, 17, 7, 15, 8, 9, 10, 11, 12, 13, 14)
PLATFORM_COLUMNS = {old: new for new, old in enumerate(PLATFORM_ORDER, 1)}
MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
CELL = re.compile(r"(\$?)([A-Z]{1,3})(\$?\d*)")


def load_report_layout() -> dict[str, Any]:
    source = Path(__file__).resolve().parents[2] / "config" / "report-layout.json"
    installed = Path(sysconfig.get_path("data")) / "share" / "easm-agent" / "report-layout.json"
    value = json.loads((source if source.is_file() else installed).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("sheets"), dict):
        raise ValueError("보고서 레이아웃의 시트 정의가 올바르지 않습니다.")
    return value["sheets"]


def mapped_cell(address: str) -> str:
    match = CELL.fullmatch(address)
    if not match:
        return address
    column = column_index_from_string(match[2])
    return match[1] + get_column_letter(PLATFORM_COLUMNS.get(column, column)) + match[3]


def mapped_ranges(address: str) -> list[str]:
    if ":" not in address:
        return [mapped_cell(address)]
    left, right = address.split(":", 1)
    start, end = CELL.fullmatch(left), CELL.fullmatch(right)
    if start is None or end is None:
        return [address]
    columns = sorted(PLATFORM_COLUMNS.get(col, col) for col in range(
        column_index_from_string(start[2]), column_index_from_string(end[2]) + 1,
    ))
    groups = []
    first = last = columns[0]
    for column in columns[1:]:
        if column != last + 1:
            groups.append((first, last))
            first = column
        last = column
    groups.append((first, last))
    return [
        start[1] + get_column_letter(first) + start[3] + ":"
        + end[1] + get_column_letter(last) + end[3]
        for first, last in groups
    ]


def remap_formula(formula: str, owner: str) -> str:
    equals = formula.startswith("=")
    tokens = Tokenizer(formula if equals else "=" + formula).items
    functions = {token.value.rstrip("(").upper() for token in tokens if token.type == "FUNC" and token.subtype == "OPEN"}
    for token in tokens:
        if token.type != "OPERAND" or token.subtype != "RANGE":
            continue
        prefix, separator, address = token.value.rpartition("!")
        explicit_sheet = prefix.strip("'").replace("''", "'") if separator else owner
        if explicit_sheet != PLATFORM_SHEET:
            continue
        qualifier = prefix + "!" if separator else ""
        ranges = [qualifier + value for value in mapped_ranges(address)]
        if len(ranges) > 1 and functions - {"SUM", "COUNT", "COUNTA", "COUNTBLANK", "MAX", "MIN", "AVERAGE"}:
            raise ValueError("이동 후 분리되는 다중 열 범위를 해당 수식에서 안전하게 변환할 수 없습니다.")
        token.value = ranges[0] if len(ranges) == 1 else "(" + ",".join(ranges) + ")"
    return ("=" if equals else "") + "".join(token.value for token in tokens)


def reorder_platform_parts(parts: dict[str, bytes]) -> None:
    workbook = etree.fromstring(parts["xl/workbook.xml"])
    relations = etree.fromstring(parts["xl/_rels/workbook.xml.rels"])
    sheets = []
    platform_part = None
    platform_id = None
    for sheet in workbook.find(MAIN + "sheets"):
        target = next(node.get("Target") for node in relations if node.get("Id") == sheet.get(REL + "id"))
        part = target.lstrip("/") if target.startswith("/") else "xl/" + target
        sheets.append((sheet.get("name"), part))
        if sheet.get("name") == PLATFORM_SHEET:
            platform_part = part
            platform_id = sheet.get("sheetId")
    if platform_part is None:
        return
    platform = etree.fromstring(parts[platform_part])
    shared = etree.fromstring(parts["xl/sharedStrings.xml"]).findall(MAIN + "si") if "xl/sharedStrings.xml" in parts else []
    header = platform.find(f".//{MAIN}c[@r='G4']")
    header_text = "".join(header.itertext()) if header is not None else ""
    if header is not None and header.get("t") == "s":
        header_text = "".join(shared[int(header.find(MAIN + "v").text)].itertext())
    if "생성·등록·배포" in header_text:
        return
    for owner, part in sheets:
        root = platform if part == platform_part else etree.fromstring(parts[part])
        original_cells = {cell.get("r"): cell for cell in root.iter(MAIN + "c")}
        shared_formulas = {
            formula.get("si"): (cell.get("r"), formula.text)
            for cell in original_cells.values()
            for formula in (cell.find(MAIN + "f"),)
            if formula is not None and formula.get("t") == "shared" and formula.text
        }
        for cell in original_cells.values():
            formula = cell.find(MAIN + "f")
            if formula is not None and formula.get("t") == "shared":
                origin, value = shared_formulas[formula.get("si")]
                formula.text = Translator("=" + value, origin=origin).translate_formula(cell.get("r"))[1:]
                formula.attrib.clear()
        for cell in root.iter(MAIN + "c"):
            if cell.get("t") != "s":
                continue
            value = shared[int(cell.find(MAIN + "v").text)]
            text = "".join(value.itertext())
            if re.fullmatch(r"'?1a_플랫폼 기준'?!\$?[A-Z]+\$?\d+(?::\$?[A-Z]+\$?\d+)?", text) \
                    or owner == PLATFORM_SHEET and cell.get("r") == "D20" and text.startswith("G14("):
                cell.set("t", "inlineStr")
                cell.remove(cell.find(MAIN + "v"))
                inline = etree.SubElement(cell, MAIN + "is")
                inline.extend(deepcopy(child) for child in value)
        for formula in root.iter(MAIN + "f"):
            if formula.text:
                formula.text = remap_formula(formula.text, owner)
        for text in root.iter(MAIN + "t"):
            if text.text and re.fullmatch(r"'?1a_플랫폼 기준'?!\$?[A-Z]+\$?\d+(?::\$?[A-Z]+\$?\d+)?", text.text):
                prefix, _, address = text.text.rpartition("!")
                text.text = ",".join(prefix + "!" + span for span in mapped_ranges(address))
        for cell in root.iter(MAIN + "c"):
            if owner != PLATFORM_SHEET:
                continue
            cell.set("r", mapped_cell(cell.get("r")))
        if owner == PLATFORM_SHEET:
            for row in root.findall(f"{MAIN}sheetData/{MAIN}row"):
                cells = list(row)
                for cell in cells:
                    row.remove(cell)
                row.extend(sorted(cells, key=lambda cell: column_index_from_string(
                    CELL.fullmatch(cell.get("r"))[2],
                )))
            columns = root.find(MAIN + "cols")
            if columns is not None:
                moved = []
                for original in columns:
                    for column in range(int(original.get("min")), int(original.get("max")) + 1):
                        node = deepcopy(original)
                        index = PLATFORM_COLUMNS.get(column, column)
                        node.set("min", str(index))
                        node.set("max", str(index))
                        moved.append(node)
                columns.clear()
                columns.extend(sorted(moved, key=lambda node: int(node.get("min"))))
            for merge in root.findall(f"{MAIN}mergeCells/{MAIN}mergeCell"):
                old_left, top, old_right, bottom = range_boundaries(merge.get("ref"))
                mapped_columns = {PLATFORM_COLUMNS.get(col, col) for col in range(old_left, old_right + 1)}
                inverse = {new: old for old, new in PLATFORM_COLUMNS.items()}
                for column in range(min(mapped_columns), max(mapped_columns) + 1):
                    if column in mapped_columns:
                        continue
                    for row in range(top, bottom + 1):
                        old = original_cells.get(get_column_letter(inverse.get(column, column)) + str(row))
                        if old is not None and any(child.tag in (MAIN + "f", MAIN + "v", MAIN + "is") for child in old):
                            raise ValueError("병합 셀 이동 범위에 다른 지표 값이 있어 변환을 중단합니다.")
                spans = mapped_ranges(merge.get("ref"))
                left = spans[0].split(":")[0]
                right = spans[-1].split(":")[-1]
                merge.set("ref", left + ":" + right)
            for tag in ("dataValidation", "conditionalFormatting"):
                for node in root.iter(MAIN + tag):
                    node.set("sqref", " ".join(span for old in node.get("sqref", "").split()
                                              for span in mapped_ranges(old)))
                    for child in node.iter():
                        if child.tag in (MAIN + "formula", MAIN + "formula1", MAIN + "formula2") and child.text:
                            child.text = remap_formula(child.text, owner)
            for link in root.findall(f"{MAIN}hyperlinks/{MAIN}hyperlink"):
                link.set("ref", mapped_cell(link.get("ref")))
            for node in root.iter(MAIN + "t"):
                if node.text and node.text.startswith("G14("):
                    node.text = "I14(" + node.text[4:]
            cell = root.find(f".//{MAIN}c[@r='B20']/{MAIN}f")
            if cell is not None and cell.text:
                cell.text = cell.text.replace('"G14 "', '"I14 "')
        for link in root.findall(f"{MAIN}hyperlinks/{MAIN}hyperlink"):
            location = link.get("location")
            if location and PLATFORM_SHEET in location:
                prefix = "#" if location.startswith("#") else ""
                link.set("location", prefix + remap_formula(location.removeprefix("#"), ""))
        parts[part] = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    for name in workbook.findall(f"{MAIN}definedNames/{MAIN}definedName"):
        if name.text:
            name.text = remap_formula(name.text, "")
    parts["xl/workbook.xml"] = etree.tostring(workbook, encoding="UTF-8", xml_declaration=True)
    for link in relations:
        if link.get("Type", "").endswith("/calcChain"):
            target = link.get("Target")
            part = target.lstrip("/") if target.startswith("/") else "xl/" + target
            chain = etree.fromstring(parts[part])
            current_id = None
            for cell in chain:
                current_id = cell.get("i", current_id)
                if current_id == platform_id:
                    cell.set("r", mapped_cell(cell.get("r")))
            parts[part] = etree.tostring(chain, encoding="UTF-8", xml_declaration=True)
    rel_part = posixpath.join(posixpath.dirname(platform_part), "_rels", posixpath.basename(platform_part) + ".rels")
    if rel_part in parts:
        links = etree.fromstring(parts[rel_part])
        for link in links:
            target = link.get("Target")
            part = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
                posixpath.join(posixpath.dirname(platform_part), target),
            )
            if link.get("Type", "").endswith("/comments"):
                comments = etree.fromstring(parts[part])
                for comment in comments.iter(MAIN + "comment"):
                    comment.set("ref", mapped_cell(comment.get("ref")))
                parts[part] = etree.tostring(comments, encoding="UTF-8", xml_declaration=True)
            elif link.get("Type", "").endswith("/vmlDrawing"):
                drawing = etree.fromstring(parts[part])
                ns = "{urn:schemas-microsoft-com:office:excel}"
                for data in drawing.iter(ns + "ClientData"):
                    column = data.find(ns + "Column")
                    if column is not None and column.text:
                        old = int(column.text) + 1
                        new = PLATFORM_COLUMNS.get(old, old)
                        column.text = str(new - 1)
                parts[part] = etree.tostring(drawing, encoding="UTF-8", xml_declaration=True)
