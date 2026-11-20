"""평가 모델의 SY 기준과 실제 점수 집계를 같은 시트/서식으로 반영한다.

원본 zip의 평가 XML과 지정된 행 높이·SY 배경색만 고친다.
다른 시트·민감도 레이블·점수·메모와 나머지 셀 서식은 보존한다.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from easm_agent.models import load_criteria
from easm_agent.proposals import DOMAINS, PRODUCTS
from easm_agent.report_template import format_assessment_workbook
from scripts.assessment_descriptions import ITEM_DETAILS

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHEET = "4. 질문별 평가 기준"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
Q = f"{{{NS}}}"
SHEET_QUESTIONS = "xl/worksheets/sheet2.xml"
SHEET_CRITERIA = "xl/worksheets/sheet4.xml"
DOMAIN_COLUMN = {"2. Design": "E", "3. Build": "F", "4. Deploy": "G", "5. Operate": "H", "6. Optimize": "I"}
NOTE = (
    "- System Evidence 26개를 시트 4에서 평가하고 시트 5 실제 집계에 반영. "
    "미확보·조회 실패·대상 없음은 N/A이며 L1 또는 0점으로 환산하지 않음"
)
FIRST_DATA_ROW = 5
SHEET_SCORING = "xl/worksheets/sheet5.xml"


def xml_bytes(root: ET.Element, original: bytes) -> bytes:
    """직렬화 후에도 Office 호환 네임스페이스 접두사(mc:Ignorable 등)가 유지되게 한다."""
    namespaces = {}
    for _, value in ET.iterparse(BytesIO(original), events=("start-ns",)):
        prefix, uri = value
        namespaces[prefix] = uri
        ET.register_namespace(prefix, uri)
    rendered = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    declared = {prefix for _, (prefix, _) in ET.iterparse(BytesIO(rendered), events=("start-ns",))}
    for prefix, uri in namespaces.items():
        if prefix not in declared:
            root.set(f"xmlns:{prefix}" if prefix else "xmlns", uri)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def cell_ref(ref: str) -> tuple[str, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    return match.group(1), int(match.group(2))


def shared_strings(archive: ZipFile) -> list[str]:
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.itertext()) for node in root.findall(f"{Q}si")]


def text_cell(ref: str, style: str, text: str) -> ET.Element:
    cell = ET.Element(f"{Q}c", {"r": ref, "s": style, "t": "inlineStr"})
    inline = ET.SubElement(cell, f"{Q}is")
    ET.SubElement(inline, f"{Q}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = text
    return cell


def merge_assessment(source: Path, output: Path) -> dict[str, str | int]:
    if source.resolve() == output.resolve():
        raise ValueError("원본 덮어쓰기는 허용하지 않습니다.")
    raw = source.read_bytes()
    with ZipFile(BytesIO(raw)) as archive:
        if SOURCE_SHEET not in archive.read("xl/workbook.xml").decode("utf-8"):
            raise ValueError("질문별 평가 기준 시트가 있는 원본 평가 모델이 필요합니다.")
        patched = review_parts(archive, {})
        result = BytesIO()
        with ZipFile(result, "w", ZIP_DEFLATED) as out:
            for entry in archive.infolist():
                out.writestr(entry, patched.get(entry.filename, archive.read(entry.filename)))
    if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(raw).digest():
        raise ValueError("작업 중 원본이 변경되었습니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result.getvalue())
    format_assessment_workbook(output)
    return {"merged_proposals": len(DOMAINS), "source_sha256": hashlib.sha256(raw).hexdigest()}


def replace_text(row: ET.Element, column: str, text: str) -> None:
    number = row.get("r")
    cell = row.find(f"{Q}c[@r='{column}{number}']")
    if cell is None:
        raise ValueError(f"필수 셀 없음: {column}{number}")
    replacement = text_cell(cell.get("r"), cell.get("s", "0"), text)
    row.insert(list(row).index(cell), replacement)
    row.remove(cell)


def replace_question(row: ET.Element, title: str, description: str) -> None:
    ref = f"F{row.get('r')}"
    cell = row.find(f"{Q}c[@r='{ref}']")
    if cell is None:
        raise ValueError(f"필수 셀 없음: {ref}")
    replacement = text_cell(ref, cell.get("s", "0"), "")
    inline = replacement.find(f"{Q}is")
    inline.clear()
    bullets = "\n".join("- " + point for point in description.splitlines())
    for text, bold in ((title, "1"), ("\n" + bullets, "0")):
        run = ET.SubElement(inline, f"{Q}r")
        properties = ET.SubElement(run, f"{Q}rPr")
        ET.SubElement(properties, f"{Q}b", {"val": bold})
        ET.SubElement(run, f"{Q}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = text
    row.insert(list(row).index(cell), replacement)
    row.remove(cell)


def review_parts(archive: ZipFile, patched: dict[str, bytes]) -> dict[str, bytes]:
    strings = shared_strings(archive)

    def value(cell: ET.Element | None) -> str:
        if cell is None:
            return ""
        if cell.get("t") == "inlineStr":
            return "".join(cell.find(f"{Q}is").itertext())
        node = cell.find(f"{Q}v")
        return strings[int(node.text)] if cell.get("t") == "s" else node.text if node is not None else ""

    raw = patched.get(SHEET_CRITERIA, archive.read(SHEET_CRITERIA))
    root = ET.fromstring(raw)
    data = root.find(f"{Q}sheetData")

    criteria = load_criteria()["items"]
    groups: dict[tuple[str, str], list[int]] = {}
    seen = set()
    for row in data.findall(f"{Q}row"):
        number = int(row.get("r"))
        code = value(row.find(f"{Q}c[@r='B{number}']"))
        if number >= FIRST_DATA_ROW and code:
            domain = value(row.find(f"{Q}c[@r='C{number}']"))
            perspective = value(row.find(f"{Q}c[@r='E{number}']"))
            groups.setdefault((domain, perspective), []).append(number)
            if code in criteria:
                if code not in ITEM_DETAILS:
                    raise ValueError(f"수집 항목 설명이 없습니다: {code}")
                replace_question(row, criteria[code]["title"], ITEM_DETAILS[code])
        if code not in criteria:
            continue
        seen.add(code)
        replace_text(row, "L", criteria[code]["evidence"])
        for column, text in zip("GHIJK", criteria[code]["levels"].values(), strict=True):
            replace_text(row, column, text)
        if code in DOMAINS:
            replace_text(row, "L", criteria[code]["evidence"])
            memo = row.find(f"{Q}c[@r='N{number}']")
            if value(memo) == "초안 - 점수 산정 제외":
                replace_text(row, "N", "")
    if seen != criteria.keys():
        raise ValueError("System Evidence 26개 코드가 정확히 일치하지 않습니다.")
    rows = {int(row.get("r")): row for row in data}
    replace_text(rows[3], "B", "인터뷰 54개 + SY 26개 = 80개. 1~5 정수 또는 N/A. 미확보·대상 없음은 N/A, L1은 확인된 부재. 비율 임계값은 본 진단 기준이며 Microsoft 인증 기준 아님")
    validation = root.find(f"{Q}dataValidations/{Q}dataValidation")
    validation.set("type", "custom")
    validation.set("sqref", f"M5:M{max(rows)}")
    validation.set("error", "1~5 정수 또는 N/A만 입력하세요.")
    validation.set("prompt", "미확보·조회 실패·대상 없음은 N/A")
    validation.attrib.pop("operator", None)
    validation.find(f"{Q}formula1").text = 'OR(M5="",M5="N/A",AND(ISNUMBER(M5),M5=INT(M5),M5>=1,M5<=5))'
    second = validation.find(f"{Q}formula2")
    if second is not None:
        validation.remove(second)
    patched[SHEET_CRITERIA] = xml_bytes(root, raw)

    raw = patched.get(SHEET_QUESTIONS, archive.read(SHEET_QUESTIONS))
    root = ET.fromstring(raw)
    for row in root.findall(f"{Q}sheetData/{Q}row"):
        for cell in list(row):
            text = value(cell)
            if "▸ Agent 대상 조건부 접근" in text:
                text = "\n\n".join(
                    block for block in text.split("\n\n")
                    if not block.startswith("▸ Agent 대상 조건부 접근")
                )
                replace_text(row, cell_ref(cell.get("r"))[0], text)
            if "▸ 적대적 시험" in text:
                text = "\n\n".join(
                    block for block in text.split("\n\n") if "▸ 적대적 시험" not in block
                )
                replace_text(row, cell_ref(cell.get("r"))[0], text)
            if "(추가 제안)" in text:
                replace_text(row, cell_ref(cell.get("r"))[0], text.replace(" (추가 제안)", ""))
            elif "점수 산정" in text and "포함하지 않음" in text:
                lines = [
                    line for line in text.splitlines()
                    if not any(marker in line for marker in ("추가 제안 12개", "추가 제안 13개"))
                ]
                replace_text(row, cell_ref(cell.get("r"))[0], "\n".join([*lines, NOTE]))
    summary_row = root.find(f"{Q}sheetData/{Q}row[@r='8']")
    for domain, column in {"1. Demand": "D", **DOMAIN_COLUMN}.items():
        summaries = []
        for row in data:
            number = row.get("r")
            code = value(row.find(f"{Q}c[@r='B{number}']"))
            if code in criteria and value(row.find(f"{Q}c[@r='C{number}']")) == domain:
                product = PRODUCTS.get(code) or criteria[code].get("product") or (
                    "Microsoft Entra Agent ID" if criteria[code].get("requires") else "Azure API"
                )
                summaries.append(f"▸ {code} {criteria[code]['title']}\n  [{product}]")
        if summaries and summary_row is not None:
            replace_text(summary_row, column, "\n\n".join(summaries))
    notes_row = root.find(f"{Q}sheetData/{Q}row[@r='10']")
    if notes_row is not None:
        replace_text(notes_row, "B", NOTE + "\n- API 구성·기록의 항목별 충족률로 평가. 제품별 조회 범위와 분모는 기준표 참조")
    patched[SHEET_QUESTIONS] = xml_bytes(root, raw)

    raw = archive.read(SHEET_SCORING)
    root = ET.fromstring(raw)
    data = root.find(f"{Q}sheetData")
    # Rows 1-58 remain the original worked example; the actual assessment is separate.
    for row in list(data):
        if int(row.get("r")) >= 61:
            data.remove(row)
    new_formulas: list[str] = []

    def append(number: int, values: dict[str, str]) -> None:
        row = ET.SubElement(data, f"{Q}row", {"r": str(number), "ht": "40", "customHeight": "1"})
        for column, text in values.items():
            ref = f"{column}{number}"
            if text.startswith("="):
                cell = ET.SubElement(row, f"{Q}c", {"r": ref, "s": "51"})
                ET.SubElement(cell, f"{Q}f").text = text[1:]
                new_formulas.append(ref)
            else:
                row.append(text_cell(ref, "23" if number == 63 else "61", text))

    append(61, {"B": "실제 평가 집계 - 시트 4 입력 점수 연동 (인터뷰 54개 + System Evidence 26개)"})
    append(62, {"B": "빈칸·N/A는 평균 제외. 4개 인터뷰 관점과 SY 확보 시 영역 산정, 6개 영역 확보 시 종합 산정. 미확보는 0점 아님"})
    headers = ("영역", "Process", "People", "Data", "Technology", "System Evidence", "인터뷰 평균", "괴리", "최종 점수", "Level", "상태")
    append(63, dict(zip("BCDEFGHIJKL", headers, strict=True)))
    for number, domain in enumerate(("1. Demand", "2. Design", "3. Build", "4. Deploy", "5. Operate", "6. Optimize"), 64):
        values = {"B": domain}
        for column, perspective in zip("CDEFG", headers[1:6], strict=True):
            numbers = groups[(domain, perspective)]
            refs = ",".join(f"'{SOURCE_SHEET}'!M{n}" for n in numbers)
            values[column] = f'=IF(COUNT({refs})=0,"",ROUND(AVERAGE({refs}),1))'
        values.update({
            "H": f'=IF(COUNT(C{number}:F{number})<4,"",ROUND(AVERAGE(C{number}:F{number}),1))',
            "I": f'=IF(COUNT(G{number}:H{number})<2,"",H{number}-G{number})',
            "J": f'=IF(COUNT(G{number}:H{number})<2,"",IF(I{number}>=$C$29,ROUND(G{number}+$C$30,1),H{number}))',
            "K": f'=IF(COUNT(J{number})=0,"",LOOKUP(J{number},$C$21:$C$25,$D$21:$D$25))',
            "L": f'=IF(COUNT(J{number})=0,"판정 보류",IF(I{number}>=$C$29,"인터뷰-실측 괴리","미보정"))',
        })
        append(number, values)
    append(71, {
        "B": "종합 점수",
        "J": '=IF(COUNT(J64:J69)<6,"",ROUND(AVERAGE(J64:J69),1))',
        "K": '=IF(COUNT(J71)=0,"",LOOKUP(J71,$C$21:$C$25,$D$21:$D$25))',
        "L": '=IF(COUNT(J64:J69)<6,"판정 보류","6개 영역 집계")',
    })
    merges = root.find(f"{Q}mergeCells")
    for ref in ("B61:L61", "B62:L62"):
        if not any(cell.get("ref") == ref for cell in merges):
            ET.SubElement(merges, f"{Q}mergeCell", {"ref": ref})
    merges.set("count", str(len(merges)))
    root.find(f"{Q}dimension").set("ref", "B2:L71")
    columns = root.find(f"{Q}cols")
    for index in range(10, 13):
        if not any(int(col.get("min")) <= index <= int(col.get("max")) for col in columns):
            ET.SubElement(columns, f"{Q}col", {"min": str(index), "max": str(index), "width": "22", "customWidth": "1"})
    patched[SHEET_SCORING] = xml_bytes(root, raw)
    raw = archive.read("xl/workbook.xml")
    root = ET.fromstring(raw)
    calc = root.find(f"{Q}calcPr")
    if calc is None:
        calc = ET.SubElement(root, f"{Q}calcPr")
    calc.attrib.update({"calcMode": "auto", "fullCalcOnLoad": "1", "forceFullCalc": "1"})
    patched["xl/workbook.xml"] = xml_bytes(root, raw)
    if "xl/calcChain.xml" in archive.namelist():
        raw = archive.read("xl/calcChain.xml")
        root = ET.fromstring(raw)
        for cell in list(root):
            if cell.get("r") in new_formulas and cell.get("i") == "5":
                root.remove(cell)
        for ref in new_formulas:
            ET.SubElement(root, f"{Q}c", {"r": ref, "i": "5"})
        patched["xl/calcChain.xml"] = xml_bytes(root, raw)
    return patched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(merge_assessment(args.source, args.output))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
