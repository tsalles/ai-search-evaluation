import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from docgen.errors import InputError, IntegrityError
from docgen.models import Table
from docgen.text import value_text

FONT_NAME = "DocgenVera"


def font_assets() -> tuple[Path, Path]:
    root = Path(reportlab.__file__).parent / "fonts"
    font, license_file = root / "Vera.ttf", root / "bitstream-vera-license.txt"
    if not font.is_file() or not license_file.is_file():
        raise IntegrityError("The packaged portable font and its license are missing.")
    return font, license_file


@lru_cache(maxsize=1)
def portable_font() -> str:
    font, _ = font_assets()
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(font)))
    bold = font.with_name("VeraBd.ttf")
    if not bold.is_file():
        raise IntegrityError("The packaged portable bold font is missing.")
    pdfmetrics.registerFont(TTFont(FONT_NAME + "Bold", str(bold)))
    pdfmetrics.registerFontFamily(FONT_NAME, normal=FONT_NAME, bold=FONT_NAME + "Bold")
    return FONT_NAME


def layout_text(text: str) -> str:
    return (
        unicodedata.normalize("NFC", text)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\t", "    ")
    )


@lru_cache(maxsize=1)
def portable_latin_characters() -> str:
    font = pdfmetrics.getFont(portable_font())
    if not isinstance(font, TTFont):
        raise IntegrityError("The portable font registry is inconsistent.")
    return "".join(
        char for point in sorted(font.face.charWidths)
        if (char := chr(point)).isprintable()
        and (not char.isalpha() or unicodedata.name(char, "").startswith("LATIN"))
        and char not in "{}<>|`"
    ) + "\n"


def column_minimums(table: Table, locale: str, size: float = 10) -> list[float]:
    name = portable_font()
    result = []
    for index, column in enumerate(table.columns):
        header = column.name + (f" ({column.unit})" if column.unit else "")
        values = [header, *(value_text(row[index].value, locale) for row in table.rows)]
        longest = max(
            pdfmetrics.stringWidth(word, name, size) * 1.12
            for value in values
            for word in re.findall(r"\S+", layout_text(value))
        )
        result.append(max(36.0, longest + 12))
    return result


def wrap_lines(text: str, width: float, size: float, label: str) -> list[str]:
    name = portable_font()
    font = pdfmetrics.getFont(name)
    if not isinstance(font, TTFont):
        raise IntegrityError("The portable font registry is inconsistent.")
    text = layout_text(text)
    if any(ord(char) not in font.face.charWidths for char in text if char not in "\n\t"):
        raise InputError(f"Portable font cannot represent all glyphs in {label}.")
    lines: list[str] = []
    line = ""
    for token in re.findall(r"\n|[^\S\n]+|[^\s]+", text):
        if token == "\n":
            lines.append(line + token)
            line = ""
        elif token.isspace():
            line += token
        else:
            if pdfmetrics.stringWidth(token, name, size) * 1.12 > width:
                raise InputError(f"Unbreakable text exceeds the available width: {label}.")
            if line and pdfmetrics.stringWidth(line + token, name, size) * 1.12 > width:
                lines.append(line)
                line = token
            else:
                line += token
    if line or text.endswith("\n"):
        lines.append(line)
    return lines
