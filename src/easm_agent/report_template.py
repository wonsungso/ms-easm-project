from __future__ import annotations

import re
import sysconfig
import xml.etree.ElementTree as ET
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import quoteattr
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree
from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook

TEMPLATE_NAME = "assessment-result-template.xlsx"
CRITERIA_SHEET = "4. 질문별 평가 기준"
RESULT_SHEET = "6. 수집 결과"
CRITERIA_ROW_HEIGHT = 80
RESULT_ROW_HEIGHT = 150
SYSTEM_EVIDENCE_COLOR = "FFEAF3FB"
COLLECTION_METHODS = {
    "DM-SY-01": "M365 Admin Center → Agents → Settings",
    "DM-SY-02": "Power Platform Admin Center → Environments → 권한",
    "DM-SY-03": "M365 Admin Center → Agents → All agents",
    "DS-SY-04": "Power Platform Admin Center → Policies → Data policies",
    "DS-SY-05": "Entra → Agents → Agent identities / Blueprints",
    "DS-SY-06": "Azure → Microsoft Foundry → Model deployments",
    "DS-SY-07": "Azure → Foundry / App Service → Networking",
    "DS-SY-08": "Microsoft Foundry → Agents → Tools",
    "DS-SY-09": "Microsoft Foundry → Agents → Tools",
    "BI-SY-10": "Power Platform Admin Center → Environments",
    "BI-SY-11": "Microsoft Foundry → Evaluation",
    "BI-SY-12": "Azure → Defender for Cloud → Recommendations",
    "BI-SY-13": "Azure → Microsoft Foundry → Content filters",
    "BI-SY-14": "Foundry → Agent versions / App Service → Configuration",
    "BI-SY-15": "Foundry → Agent metadata / Azure → Tags",
    "BI-SY-16": "Azure → Policy → Compliance",
    "DP-SY-17": "M365 Admin Center → Agents → All agents (Agent 365)",
    "DP-SY-18": "M365 Admin Center → Agents → Details / Users",
    "DP-SY-19": "Entra → Agents → Blueprints / Foundry → Agents",
    "OE-SY-20": "Entra → Agents → Owners / Sponsors",
    "OE-SY-21": "Entra → Agents → Permissions",
    "OE-SY-22": "Azure → Monitor → Diagnostic settings",
    "OE-SY-23": "Azure → Foundry / App Service → Identity / IAM",
    "OE-SY-24": "Azure → Monitor → Alerts",
    "OE-SY-25": "Azure → Monitor → Action groups",
    "OE-SY-26": "Azure → Resource overview / Log Analytics → Retention",
    "OT-SY-27": "Agent 365 → Shadow AI Detection",
    "OT-SY-28": "Azure → Monitor → Metrics",
    "OT-SY-29": "Azure → Cost Management → Cost analysis",
    "OT-SY-30": "Azure → Microsoft Defender for Cloud → Environment settings → Defender plans",
    "OT-SY-31": "Azure → Cost Management → Budgets",
}
_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def assessment_template_path() -> Path:
    source = Path(__file__).resolve().parents[2] / "docs" / TEMPLATE_NAME
    installed = Path(sysconfig.get_path("data")) / "share" / "easm-agent" / TEMPLATE_NAME
    path = source if source.is_file() else installed
    if not path.is_file():
        raise FileNotFoundError(f"평가 결과 템플릿을 찾을 수 없습니다: {path}")
    return path


def load_report_template() -> tuple[Workbook, bytes]:
    content = assessment_template_path().read_bytes()
    book = load_workbook(BytesIO(content), keep_links=False, rich_text=True)
    if len(book.worksheets) != 5 or CRITERIA_SHEET not in book.sheetnames:
        raise ValueError("평가 결과 템플릿에는 원본 1~5번 시트와 질문별 평가 기준이 필요합니다.")
    return book, content


def format_assessment_workbook(path: Path) -> None:
    """Apply assessment formatting, preserving data, rich text and cached formulas."""
    content = path.read_bytes()
    book = load_workbook(BytesIO(content), read_only=True)
    rows_by_sheet = {
        name: {
            row[1].row: "-SY-" in str(row[1].value)
            for row in book[name].iter_rows(min_row=5, max_col=2)
            if re.fullmatch(r"[A-Z]{2}-(?:PR|PE|DA|TE|SY)-\d+", str(row[1].value))
        }
        for name in (CRITERIA_SHEET, RESULT_SHEET) if name in book.sheetnames
    }
    book.close()
    changed = {}
    with ZipFile(BytesIO(content)) as archive:
        styles = etree.fromstring(archive.read("xl/styles.xml"))
        fills = styles.find(f"{_MAIN}fills")
        xfs = styles.find(f"{_MAIN}cellXfs")
        blue = next((
            index for index, fill in enumerate(fills)
            if fill.find(f"{_MAIN}patternFill[@patternType='solid']/{_MAIN}fgColor") is not None
            and fill.find(f"{_MAIN}patternFill/{_MAIN}fgColor").get("rgb", "").upper() == SYSTEM_EVIDENCE_COLOR
        ), None)
        added_fill = blue is None
        if added_fill:
            blue = len(fills)
            fill = etree.SubElement(fills, f"{_MAIN}fill")
            pattern = etree.SubElement(fill, f"{_MAIN}patternFill", patternType="solid")
            etree.SubElement(pattern, f"{_MAIN}fgColor", rgb=SYSTEM_EVIDENCE_COLOR)
            fills.set("count", str(len(fills)))
        original_count = len(xfs)
        mapped = {}

        def assessment_style(style_id: int, fill_id: int | None, centered: bool) -> int:
            key = (style_id, fill_id, centered)
            if key not in mapped:
                original = xfs[style_id]
                alignment = original.find(f"{_MAIN}alignment")
                same_fill = fill_id is None or int(original.get("fillId", "0")) == fill_id
                same_alignment = not centered or (
                    alignment is not None and alignment.get("horizontal") == "center"
                    and alignment.get("vertical") == "center"
                )
                if same_fill and same_alignment:
                    mapped[key] = style_id
                    return style_id
                style = deepcopy(original)
                if fill_id is not None:
                    style.set("fillId", str(fill_id))
                if centered:
                    alignment = style.find(f"{_MAIN}alignment")
                    if alignment is None:
                        alignment = etree.Element(f"{_MAIN}alignment")
                        protection = style.find(f"{_MAIN}protection")
                        if protection is None:
                            style.append(alignment)
                        else:
                            protection.addprevious(alignment)
                    alignment.set("horizontal", "center")
                    alignment.set("vertical", "center")
                candidate = etree.tostring(style)
                existing = next((i for i, xf in enumerate(xfs) if etree.tostring(xf) == candidate), None)
                if existing is None:
                    existing = len(xfs)
                    xfs.append(style)
                mapped[key] = existing
            return mapped[key]

        workbook = etree.fromstring(archive.read("xl/workbook.xml"))
        rels = etree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {node.get("Id"): node.get("Target") for node in rels}
        for sheet in workbook.iter(f"{_MAIN}sheet"):
            name = sheet.get("name")
            if name not in rows_by_sheet:
                continue
            target = targets[sheet.get(f"{_DOC_REL}id")]
            part = target.lstrip("/") if target.startswith("/") else "xl/" + target
            root = etree.fromstring(archive.read(part))
            dirty = False
            height = CRITERIA_ROW_HEIGHT if name == CRITERIA_SHEET else RESULT_ROW_HEIGHT
            for row in root.iter(f"{_MAIN}row"):
                number = int(row.get("r"))
                question = number in rows_by_sheet[name]
                if not question and not (name == CRITERIA_SHEET and number == 4):
                    continue
                if question and (float(row.get("ht", "0")) != height or row.get("customHeight") != "1"):
                    row.set("ht", str(height))
                    row.set("customHeight", "1")
                    dirty = True
                system = rows_by_sheet[name].get(number, False)
                fill_id = blue if system else 0 if question and name == RESULT_SHEET else None
                for cell in row.findall(f"{_MAIN}c"):
                    address = cell.get("r", "")
                    if not re.fullmatch(r"[B-N]\d+", address):
                        continue
                    centered = name == CRITERIA_SHEET and address.startswith("M")
                    if fill_id is None and not centered:
                        continue
                    old = int(cell.get("s", "0"))
                    new = assessment_style(old, fill_id, centered)
                    if old != new:
                        cell.set("s", str(new))
                        dirty = True
            if dirty:
                changed[part] = etree.tostring(root, encoding="utf-8", xml_declaration=True, standalone=True)
        if len(xfs) != original_count or added_fill:
            xfs.set("count", str(len(xfs)))
            changed["xl/styles.xml"] = etree.tostring(styles, encoding="utf-8", xml_declaration=True, standalone=True)
        if not changed:
            return
        output = BytesIO()
        with ZipFile(output, "w") as result:
            for info in archive.infolist():
                result.writestr(info, changed.get(info.filename, archive.read(info.filename)))
    path.write_bytes(output.getvalue())


def preserve_template_parts(path: Path, template: bytes) -> None:
    """Keep source metadata and formula caches that openpyxl does not round-trip."""
    with ZipFile(BytesIO(template)) as source, ZipFile(path) as generated:
        parts = {name: generated.read(name) for name in generated.namelist()}
        changed = {
            "[Content_Types].xml", "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels", "xl/styles.xml",
        }
        for name in source.namelist():
            if name not in changed:
                parts[name] = source.read(name)
        workbook = source.read("xl/workbook.xml").decode("utf-8")
        new_workbook = ET.fromstring(generated.read("xl/workbook.xml"))
        sheets = new_workbook.find(f"{_MAIN}sheets")
        if sheets is None or len(sheets) < 6:
            raise ValueError("수집 결과 시트가 생성되지 않았습니다.")
        additions = "".join(
            "<sheet name=" + quoteattr(sheet.attrib["name"])
            + " sheetId=" + quoteattr(sheet.attrib["sheetId"])
            + " r:id=" + quoteattr(sheet.attrib[_DOC_REL + "id"]) + "/>"
            for sheet in list(sheets)[5:]
        )
        workbook, replaced = re.subn(r"</sheets>", additions + "</sheets>", workbook, count=1)
        if replaced != 1:
            raise ValueError("원본 템플릿의 시트 목록을 확장할 수 없습니다.")
        workbook = re.sub(r'\bactiveTab="\d+"', 'activeTab="5"', workbook, count=1)
        parts["xl/workbook.xml"] = workbook.encode("utf-8")
        for index in range(1, 6):
            name = f"xl/worksheets/sheet{index}.xml"
            parts[name] = re.sub(rb'\btabSelected="1"', b'tabSelected="0"', parts[name])
        relationships = ET.fromstring(generated.read("xl/_rels/workbook.xml.rels"))
        original_rels = ET.fromstring(source.read("xl/_rels/workbook.xml.rels"))
        for index, relation in enumerate(original_rels):
            kind = relation.attrib["Type"].rsplit("/", 1)[-1]
            if kind in ("sharedStrings", "calcChain"):
                relation = deepcopy(relation)
                relation.set("Id", f"templatePreserved{index}")
                relationships.append(relation)
            elif kind not in ("worksheet", "styles", "theme"):
                raise ValueError(f"지원되지 않는 템플릿 통합 문서 관계: {kind}")
        parts["xl/_rels/workbook.xml.rels"] = ET.tostring(relationships, encoding="utf-8")
        types = ET.fromstring(generated.read("[Content_Types].xml"))
        keys = {(item.tag, item.get("PartName"), item.get("Extension")) for item in types}
        for item in ET.fromstring(source.read("[Content_Types].xml")):
            key = (item.tag, item.get("PartName"), item.get("Extension"))
            if key not in keys:
                types.append(deepcopy(item))
                keys.add(key)
        parts["[Content_Types].xml"] = ET.tostring(types, encoding="utf-8")
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    path.write_bytes(output.getvalue())
