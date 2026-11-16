"""Low-level helpers for editing the corporate deck template in place."""

from __future__ import annotations

import copy

from lxml import etree
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches


def element(shape):
    return getattr(shape, "_element", shape)


def _body(node):
    body = node.find(qn("p:txBody"))
    return body if body is not None else node.find(qn("a:txBody"))


def set_text(target, paragraphs, size=None, color=None, bold=None) -> None:
    """Replace the text while using the first existing paragraph as the formatting prototype."""
    body = _body(element(target))
    existing = body.findall(qn("a:p"))
    proto = copy.deepcopy(existing[0])
    for paragraph in existing:
        body.remove(paragraph)
    for text in [paragraphs] if isinstance(paragraphs, str) else paragraphs:
        paragraph = copy.deepcopy(proto)
        runs = paragraph.findall(qn("a:r"))
        for extra in runs[1:] + paragraph.findall(qn("a:br")) + paragraph.findall(qn("a:fld")):
            paragraph.remove(extra)
        if runs:
            run = runs[0]
        else:
            run = etree.Element(qn("a:r"))
            end = paragraph.find(qn("a:endParaRPr"))
            if end is not None:
                properties = copy.deepcopy(end)
                properties.tag = qn("a:rPr")
                run.append(properties)
                end.addprevious(run)
            else:
                paragraph.append(run)
            etree.SubElement(run, qn("a:t"))
        run.find(qn("a:t")).text = text
        properties = run.find(qn("a:rPr"))
        if properties is not None:
            if size:
                properties.set("sz", str(int(size * 100)))
            if bold is not None:
                properties.set("b", "1" if bold else "0")
            if color:
                for fill in properties.findall(qn("a:solidFill")):
                    properties.remove(fill)
                fill = etree.Element(qn("a:solidFill"))
                etree.SubElement(fill, qn("a:srgbClr")).set("val", color)
                properties.insert(0, fill)
        body.append(paragraph)


FILLS = ("a:solidFill", "a:gradFill", "a:noFill", "a:pattFill", "a:blipFill")


def _clear_fill(properties) -> None:
    for tag in FILLS:
        for fill in properties.findall(qn(tag)):
            properties.remove(fill)


def set_fill(shape, color: str) -> None:
    """Set a solid shape fill (on a:tcPr for table cells)."""
    node = element(shape)
    properties = node.find(qn("p:spPr"))
    if properties is None:
        properties = node.find(qn("a:tcPr"))
        _clear_fill(properties)
        fill = etree.SubElement(properties, qn("a:solidFill"))
        etree.SubElement(fill, qn("a:srgbClr")).set("val", color)
        return
    _clear_fill(properties)
    fill = etree.Element(qn("a:solidFill"))
    etree.SubElement(fill, qn("a:srgbClr")).set("val", color)
    properties.find(qn("a:prstGeom")).addnext(fill)


def set_outline(shape, color: str) -> None:
    line = element(shape).find(qn("p:spPr")).find(qn("a:ln"))
    if line is not None:
        for node in line.iter(qn("a:srgbClr")):
            node.set("val", color)


def _xfrm(node):
    properties = node.find(qn("p:spPr"))
    found = properties.find(qn("a:xfrm")) if properties is not None else None
    return found if found is not None else node.find(qn("p:xfrm"))


def place(shape, x=None, y=None, w=None, h=None) -> None:
    xfrm = _xfrm(element(shape))
    offset, extent = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
    for value, node, attribute in ((x, offset, "x"), (y, offset, "y"), (w, extent, "cx"), (h, extent, "cy")):
        if value is not None:
            node.set(attribute, str(int(Inches(value))))


def box(shape) -> tuple[float, float, float, float]:
    xfrm = _xfrm(element(shape))
    offset, extent = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
    return tuple(Emu(int(v)).inches for v in (offset.get("x"), offset.get("y"), extent.get("cx"), extent.get("cy")))


class Page:
    """Shape lookup by id, cloning and deletion for one slide."""

    def __init__(self, slide) -> None:
        self.slide = slide
        self.tree = slide.shapes._spTree

    def __call__(self, shape_id: int):
        for child in self.tree:
            node = child.find(".//" + qn("p:cNvPr"))
            if node is not None and node.get("id") == str(shape_id):
                return child
        raise KeyError(shape_id)

    def next_id(self) -> int:
        return max(int(node.get("id")) for node in self.tree.iter(qn("p:cNvPr"))) + 1

    def add(self, node, after=None):
        """Insert a detached shape copy with a fresh id; returns it."""
        for link in node.iter(qn("a:hlinkClick")):
            link.getparent().remove(link)
        node.find(".//" + qn("p:cNvPr")).set("id", str(self.next_id()))
        if after is None:
            self.tree.append(node)
        else:
            after.addnext(node)
        return node

    def clone(self, shape_ids, dx=0.0, dy=0.0) -> list:
        created: list = []
        for shape_id in shape_ids:
            node = self.add(copy.deepcopy(self(shape_id)), created[-1] if created else self(shape_ids[-1]))
            if dx or dy:
                x, y, _, _ = box(node)
                place(node, x + dx, y + dy)
            created.append(node)
        return created

    def delete(self, *shape_ids) -> None:
        for shape_id in shape_ids:
            try:
                node = self(shape_id)
            except KeyError:
                continue
            node.getparent().remove(node)


def duplicate_slide(prs, source):
    """Copy a slide's shapes, background and pictures (charts are skipped) into a new slide."""
    new = prs.slides.add_slide(source.slide_layout)
    for shape in list(new.shapes):
        shape._element.getparent().remove(shape._element)
    background = source._element.find(qn("p:cSld")).find(qn("p:bg"))
    if background is not None:
        new._element.find(qn("p:cSld")).insert(0, copy.deepcopy(background))
    for child in source.shapes._spTree:
        if child.tag in (qn("p:nvGrpSpPr"), qn("p:grpSpPr")):
            continue
        if child.tag == qn("p:graphicFrame") and child.find(".//{*}chart") is not None:
            continue
        node = copy.deepcopy(child)
        for link in node.iter(qn("a:hlinkClick")):
            link.getparent().remove(link)
        for blip in node.iter(qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            if rid:
                blip.set(qn("r:embed"), new.part.relate_to(source.part.related_part(rid), RT.IMAGE))
        new.shapes._spTree.append(node)
    return new
