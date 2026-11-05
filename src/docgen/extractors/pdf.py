from functools import partial
from pathlib import Path

import pdfplumber
from pdfplumber._typing import T_bbox, T_obj
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from docgen.errors import IntegrityError
from docgen.extractors.models import Readback, TableGrid
from docgen.models import Profile


def outside_tables(obj: T_obj, *, bounds: list[T_bbox]) -> bool:
    return obj.get("object_type") != "char" or not any(
        box[0] <= (float(obj["x0"]) + float(obj["x1"])) / 2 <= box[2]
        and box[1] <= (float(obj["top"]) + float(obj["bottom"])) / 2 <= box[3]
        for box in bounds
    )


def read_pdf(path: Path, layout_profile: Profile = "baseline") -> Readback:
    try:
        native = PdfReader(path)
        if native.is_encrypted:
            raise IntegrityError("Encrypted PDFs are not supported.")
        native_text = any(page.extract_text().strip() for page in native.pages)
        paragraphs: list[str] = []
        tables: list[TableGrid] = []
        columns = 1
        with pdfplumber.open(path) as document:
            for index, page in enumerate(document.pages, 1):
                if page.images:
                    raise IntegrityError("PDF contains rasterized business content.")
                found = page.find_tables()
                found.sort(
                    key=lambda table: (
                        int((table.bbox[0] + table.bbox[2]) / 2 >= page.width / 2)
                        if layout_profile == "complex"
                        else 0,
                        table.bbox[1],
                    )
                )
                bounds = [table.bbox for table in found]
                for table in found:
                    extracted = table.extract(x_tolerance=2, y_tolerance=2)
                    if not extracted or any(
                        cell is None or not cell.strip() for row in extracted for cell in row
                    ):
                        raise IntegrityError("PDF table contains missing or unextractable cells.")
                    rows = tuple(tuple(str(cell) for cell in row) for row in extracted)
                    tables.append(
                        TableGrid(
                            headers=rows[0],
                            rows=rows[1:],
                            location=f"page-{index}/table-{len(tables)}",
                        )
                    )
                prose = page.filter(partial(outside_tables, bounds=bounds))
                chars = prose.chars
                center = page.width / 2
                if (
                    any(float(char["x1"]) < center - 5 for char in chars)
                    and any(float(char["x0"]) > center + 5 for char in chars)
                    and not any(
                        float(char["x0"]) < center + 4 and float(char["x1"]) > center - 4
                        for char in chars
                    )
                ):
                    columns = 2
                regions = [(0.0, 0.0, page.width, page.height)]
                if layout_profile == "complex":
                    regions = [
                        (0.0, 0.0, page.width / 2, page.height),
                        (page.width / 2, 0.0, page.width, page.height),
                    ]
                for region in regions:
                    text = prose.crop(region).extract_text(x_tolerance=2, y_tolerance=3)
                    if text:
                        paragraphs.append(text)
                page.close()
        return Readback(
            paragraphs=(" ".join(paragraphs),),
            tables=tuple(tables),
            native_text=native_text,
            layout_features={"columns": columns, "pages": len(native.pages)},
        )
    except (OSError, PdfReadError, ValueError) as exc:
        raise IntegrityError("Invalid or unreadable native PDF.") from exc
