import unicodedata
from datetime import date
from decimal import Decimal

from docgen.models import Content


def synthetic_notice(language: str) -> str:
    return (
        "Conte\u00fado sint\u00e9tico para pesquisa de recupera\u00e7\u00e3o."
        if language == "pt" else "Synthetic content for retrieval research."
    )


def value_text(value: str | Decimal | date | bool, locale: str) -> str:
    if isinstance(value, bool):
        return ("Sim" if value else "N\u00e3o") if locale == "pt-BR" else ("Yes" if value else "No")
    if isinstance(value, Decimal):
        text = format(value, "f")
        return text.replace(".", ",") if locale == "pt-BR" else text
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y") if locale == "pt-BR" else value.isoformat()
    return value


def business_units(content: Content) -> tuple[str, ...]:
    result = [content.title]
    for block in content.blocks:
        if block.text:
            result.append(block.text)
        result.extend(item.text for item in block.items or ())
        if block.table:
            result.extend(
                column.name + (f" ({column.unit})" if column.unit else "")
                for column in block.table.columns
            )
            result.extend(
                value_text(cell.value, content.blueprint.locale)
                for row in block.table.rows for cell in row
            )
    return tuple(result)


def word_count(content: Content) -> int:
    return len(unicodedata.normalize("NFC", " ".join(business_units(content))).split())
