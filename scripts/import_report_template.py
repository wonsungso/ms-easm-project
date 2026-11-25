"""Import the supplied deck without changing slide content or formatting."""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation


def import_template(source: Path, destination: Path) -> None:
    content = source.read_bytes()
    presentation = Presentation(BytesIO(content))
    count = len(presentation.slides)
    if count not in (12, 27):
        raise ValueError("승인된 27장 또는 과거 12장 보고서 원본이 필요합니다.")
    expected = (
        ((0, 4), (5, 23790), (16, 28605), (26, 40874)) if count == 27
        else ((0, 23789), (1, 43667), (5, 28605), (11, 40874))
    )
    for page, shape_id in expected:
        if not any(shape.shape_id == shape_id for shape in presentation.slides[page].shapes):
            raise ValueError("보고서 원본의 도형 계약이 일치하지 않습니다.")
    output = BytesIO()
    with ZipFile(BytesIO(content)) as archive, ZipFile(output, "w") as target:
        for info in archive.infolist():
            if info.filename.startswith("docMetadata/"):
                continue
            payload = archive.read(info.filename)
            if info.filename == "docProps/core.xml":
                root = etree.fromstring(payload)
                for element in list(root):
                    if etree.QName(element).localname in ("creator", "lastModifiedBy", "lastPrinted"):
                        root.remove(element)
                payload = etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
            elif info.filename in ("_rels/.rels", "[Content_Types].xml"):
                root = etree.fromstring(payload)
                for element in list(root):
                    if element.get("Target", element.get("PartName", "")).lstrip("/").startswith("docMetadata/"):
                        root.remove(element)
                payload = etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
            target.writestr(info, payload)
    destination.write_bytes(output.getvalue())


def main() -> None:
    parser = argparse.ArgumentParser(description="슬라이드는 보존하고 작성자 개인 메타데이터만 제거합니다.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("docs") / "assessment-report-template.pptx")
    args = parser.parse_args()
    import_template(args.source, args.output)


if __name__ == "__main__":
    main()
