from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from docgen.errors import IntegrityError
from docgen.extractors.models import Readback, TableGrid
from docgen.extractors.ooxml import check_office, part_target, xml_part

P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def text_content(element: ET.Element) -> str:
    return "\n".join(
        "".join(
            node.text or "" if node.tag == A + "t" else "\n"
            for node in paragraph.iter()
            if node.tag in {A + "t", A + "br"}
        )
        for paragraph in element.findall(A + "p")
    )


def geometry(shape: ET.Element, width: int, height: int, issues: list[str]) -> None:
    transform = (
        shape.find(P + "spPr/" + A + "xfrm") if shape.tag == P + "sp" else shape.find(P + "xfrm")
    )
    if transform is None:
        issues.append("PPTX shape has no explicit geometry.")
        return
    offset, extent = transform.find(A + "off"), transform.find(A + "ext")
    if offset is None or extent is None:
        issues.append("PPTX shape has incomplete geometry.")
        return
    x, y = int(offset.attrib["x"]), int(offset.attrib["y"])
    cx, cy = int(extent.attrib["cx"]), int(extent.attrib["cy"])
    if x < 0 or y < 0 or cx <= 0 or cy <= 0 or x + cx > width + 127 or y + cy > height + 127:
        issues.append("PPTX shape overflows the slide bounds.")


def font_issues(element: ET.Element, issues: list[str]) -> None:
    for paragraph in element.findall(".//" + A + "p"):
        if not any(node.text for node in paragraph.iter(A + "t")):
            continue
        sizes = [int(node.attrib["sz"]) for node in paragraph.iter() if "sz" in node.attrib]
        if not sizes:
            issues.append("PPTX business text has no explicit font size.")
        elif min(sizes) < 1400:
            issues.append("PPTX font is smaller than the minimum fourteen points.")


def read_presentation(archive: ZipFile) -> Readback:
    check_office(archive)
    document = xml_part(archive, "ppt/presentation.xml")
    size = document.find(P + "sldSz")
    if size is None:
        raise IntegrityError("PPTX slide size is missing.")
    width, height = int(size.attrib["cx"]), int(size.attrib["cy"])
    links = xml_part(archive, "ppt/_rels/presentation.xml.rels")
    targets = {node.attrib["Id"]: node.attrib["Target"] for node in links}
    paragraphs: list[str] = []
    groups: dict[str, int] = {}
    tables: list[TableGrid] = []
    issues: list[str] = []
    heading_levels: list[int] = []
    list_levels: list[int] = []
    section_starts: list[str] = []
    slide_count = 0
    for name in archive.namelist():
        if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml"):
            if any(
                node.text and node.text.strip() for node in xml_part(archive, name).iter(A + "t")
            ):
                raise IntegrityError("PPTX contains notes-only text outside the visible corpus.")
    for slide_number, reference in enumerate(document.findall(P + "sldIdLst/" + P + "sldId"), 1):
        slide_count += 1
        part = part_target("ppt/presentation.xml", targets[reference.attrib[R + "id"]])
        root = xml_part(archive, part)
        tree = root.find(P + "cSld/" + P + "spTree")
        if tree is None:
            raise IntegrityError("PPTX slide has no native shape tree.")
        if any(node.tag in {P + "pic", P + "oleObj"} for node in tree.iter()):
            raise IntegrityError("PPTX body contains rasterized or embedded business content.")
        for shape in tree:
            if shape.tag not in {P + "sp", P + "graphicFrame"}:
                continue
            geometry(shape, width, height, issues)
            font_issues(shape, issues)
            properties = next(iter(shape.iter(P + "cNvPr")), None)
            if properties is None:
                raise IntegrityError("PPTX shape metadata is missing.")
            if properties.get("hidden") in {"1", "true"}:
                raise IntegrityError("PPTX has hidden business shapes.")
            name = properties.attrib["name"]
            table = shape.find(".//" + A + "tbl")
            if table is not None:
                rows = []
                for row in table.findall(A + "tr"):
                    values = []
                    for cell in row.findall(A + "tc"):
                        if any(
                            cell.get(attr) not in {None, "1"} for attr in ("gridSpan", "rowSpan")
                        ) or any(cell.get(attr) in {"1", "true"} for attr in ("hMerge", "vMerge")):
                            raise IntegrityError("Merged PPTX data cells are not supported.")
                        body = cell.find(A + "txBody")
                        if body is None:
                            raise IntegrityError("PPTX table cell has no native text body.")
                        values.append(text_content(body))
                    rows.append(tuple(values))
                if not rows or any(len(row) != len(rows[0]) for row in rows):
                    raise IntegrityError("PPTX table is empty or nonrectangular.")
                tables.append(
                    TableGrid(
                        headers=rows[0],
                        rows=tuple(rows[1:]),
                        location=f"slide-{slide_number}/{name}",
                    )
                )
            elif name != "docgen-decoration":
                body = shape.find(P + "txBody")
                if body is None:
                    continue
                text = text_content(body)
                if not text:
                    continue
                if name.startswith("docgen-body:") and name.endswith(":0"):
                    paragraph = body.find(A + "p")
                    properties = paragraph.find(A + "pPr") if paragraph is not None else None
                    level = int(properties.get("lvl", "0")) + 1 if properties is not None else 1
                    sizes = [int(node.attrib["sz"]) for node in body.iter() if "sz" in node.attrib]
                    if sizes and min(sizes) == 2400:
                        heading_levels.append(level)
                        offset = shape.find(P + "spPr/" + A + "xfrm/" + A + "off")
                        if offset is not None and int(offset.get("y", "0")) == 1422400:
                            section_starts.append(name[len("docgen-body:"):-2])
                    if properties is not None and (
                        properties.find(A + "buAutoNum") is not None
                        or properties.find(A + "buChar") is not None
                    ):
                        list_levels.append(level)
                group = name.rsplit(":", 1)[0] if name.startswith("docgen-body:") else name
                if group in groups:
                    paragraphs[groups[group]] += text
                else:
                    groups[group] = len(paragraphs)
                    paragraphs.append(text)
    return Readback(
        paragraphs=tuple(paragraphs), tables=tuple(tables), structural_issues=tuple(issues),
        heading_levels=tuple(heading_levels), list_levels=tuple(list_levels),
        layout_features={"slides": slide_count}, section_starts=tuple(section_starts),
    )


def read_pptx(path: Path) -> Readback:
    try:
        with ZipFile(path) as archive:
            return read_presentation(archive)
    except (BadZipFile, OSError, ValueError, KeyError) as exc:
        raise IntegrityError("Invalid native PowerPoint package or slide data.") from exc
