import random
from typing import Any

from docgen.models import Block, Blueprint, Cell, Column, Content, ListItem, Table
from docgen.profiles import WORD_BANDS
from docgen.text import word_count
from tests.test_content_contract import example_content


def quality_content(
    genre: str = "explainer",
    *,
    words: int = 200,
    profile: str = "baseline",
    language: str = "pt",
) -> Content:
    data = example_content()
    data["facts"] = []
    data["title"] = "Orientacao sobre servicos" if language == "pt" else "Guidance about services"
    data["blueprint"].update(
        genre=genre,
        structure_profile=profile,
        language=language,
        locale="pt-BR" if language == "pt" else "en-US",
    )
    blocks = [Block(id="intro", kind="heading", text="Introducao", level=1)]
    table = Table(
        id="options",
        columns=tuple(
            Column(id=f"col-{key}", name=key, kind="text")
            for key in ("produto", "elegibilidade", "canal")
        ),
        rows=tuple(
            tuple(Cell(kind="text", value=value) for value in row)
            for row in (
                ("Aurora", "adultos", "agencia"),
                ("Horizonte", "estudantes", "digital"),
                ("Jardim", "familias", "telefone"),
            )
        ),
    )
    if genre == "explainer":
        blocks.extend(
            [
                Block(id="details", kind="heading", text="Detalhes", level=2),
                Block(id="conditions", kind="heading", text="Condicoes", level=2),
            ]
        )
    elif genre == "procedure":
        blocks.append(
            Block(
                id="steps",
                kind="ordered_list",
                items=tuple(
                    ListItem(text=text)
                    for text in (
                        "Confira a identidade",
                        "Apresente o contrato",
                        "Leia as condicoes",
                        "Confirme a assinatura",
                        "Guarde o comprovante",
                    )
                ),
            )
        )
    elif genre == "faq":
        for index, question in enumerate(
            (
                "Como funciona?",
                "Quais os requisitos?",
                "Como solicitar?",
                "Como obter ajuda?",
            )
        ):
            blocks.extend(
                [
                    Block(id=f"q-{index}", kind="heading", text=question, level=2),
                    Block(id=f"a-{index}", kind="paragraph", text="Consulte a equipe responsavel."),
                ]
            )
    elif genre == "comparison":
        blocks.append(Block(id="comparison", kind="table", table=table))
    if profile == "complex":
        blocks.append(
            Block(
                id="exceptions",
                kind="unordered_list",
                items=(
                    ListItem(text="Confira as excecoes"),
                    ListItem(text="Pequenas empresas", level=2),
                ),
            )
        )
        if genre != "comparison":
            blocks.append(Block(id="comparison", kind="table", table=table))
    data["blocks"] = blocks
    content = Content.model_validate(data)
    remaining = words - word_count(content)
    if remaining < 1:
        raise ValueError("Requested fixture word target is too small.")
    for index in range(0, remaining, 100):
        count = min(100, remaining - index)
        blocks.append(
            Block(
                id=f"body-{index}",
                kind="paragraph",
                text=" ".join(["apoio" if language == "pt" else "support"] * count),
            )
        )
    return Content.model_validate({**data, "blocks": blocks})


def diverse_content(blueprint: Blueprint, seed: int = 0) -> Content:
    low, _ = WORD_BANDS[blueprint.length_band]
    base = quality_content(
        blueprint.genre,
        words=low,
        profile=blueprint.structure_profile,
        language=blueprint.language,
    )
    blocks = [block for block in base.blocks if not block.id.startswith("body-")]
    data = base.model_dump()
    data.update(blueprint=blueprint, blocks=blocks)
    original = Content.model_validate(data)
    randomizer = random.Random(seed * 10000 + blueprint.ordinal)
    areas = [
        "cr\u00e9dito",
        "cadastro",
        "pagamentos",
        "poupan\u00e7a",
        "seguran\u00e7a",
        "transfer\u00eancias",
        "atendimento",
        "contratos",
        "investimentos",
        "cobran\u00e7a",
    ]
    people = [
        "estudantes",
        "empreendedores",
        "fam\u00edlias",
        "profissionais",
        "aposentados",
        "clientes",
        "representantes",
        "associados",
        "servidores",
        "comerciantes",
    ]
    actions = [
        "revisar os documentos",
        "confirmar a solicita\u00e7\u00e3o",
        "ler as condi\u00e7\u00f5es",
        "consultar o contrato",
        "proteger as informa\u00e7\u00f5es",
        "registrar a autoriza\u00e7\u00e3o",
        "verificar as assinaturas",
        "acompanhar o atendimento",
        "avaliar as op\u00e7\u00f5es",
    ]
    contexts = [
        "durante uma visita \u00e0 ag\u00eancia",
        "antes de concluir a opera\u00e7\u00e3o",
        "quando houver d\u00favidas sobre o produto",
        "ao atualizar os dados pessoais",
        "ap\u00f3s receber uma orienta\u00e7\u00e3o",
        "antes de utilizar o canal digital",
    ]
    if blueprint.language == "en":
        areas = [
            "credit", "registration", "payments", "savings", "security",
            "transfers", "service", "contracts", "investments", "billing",
        ]
        people = [
            "students", "entrepreneurs", "families", "professionals", "retirees",
            "customers", "representatives", "associates", "employees", "merchants",
        ]
        actions = [
            "review the documents", "confirm the request", "read the conditions",
            "consult the contract", "protect the information", "record the authorization",
            "verify the signatures", "follow the service", "evaluate the options",
        ]
        contexts = [
            "during a visit to the branch", "before completing the operation",
            "when there are questions about the product", "when updating personal details",
            "after receiving guidance", "before using the digital channel",
        ]
    words = []
    needed = low + 20 - word_count(original)
    while len(words) < needed:
        if blueprint.language == "en":
            sentence = (
                f"The {randomizer.choice(areas)} team guides {randomizer.choice(people)} "
                f"to {randomizer.choice(actions)} {randomizer.choice(contexts)}. "
                f"This explanation clarifies {randomizer.choice(areas)} "
                f"and helps {randomizer.choice(people)} to {randomizer.choice(actions)}."
            )
        else:
            sentence = (
                f"A equipe de {randomizer.choice(areas)} orienta {randomizer.choice(people)} "
                f"a {randomizer.choice(actions)} {randomizer.choice(contexts)}. "
                f"Essa explica\u00e7\u00e3o esclarece {randomizer.choice(areas)} "
                f"e ajuda {randomizer.choice(people)} com {randomizer.choice(actions)}."
            )
        words.extend(sentence.split())
    words = words[:needed]
    for index in range(0, len(words), 100):
        blocks.append(
            Block(id=f"body-{index}", kind="paragraph", text=" ".join(words[index : index + 100]))
        )
    return Content.model_validate({**data, "blocks": blocks})


def structured_content(blueprint: Blueprint, seed: int = 0) -> Content:
    plan = blueprint.structure_plan
    if plan is None:
        return diverse_content(blueprint, seed)
    reference = diverse_content(blueprint.model_copy(update={"structure_plan": None}), seed)
    randomizer = random.Random(seed * 10000 + blueprint.ordinal)
    labels = ("Alfa", "Beta", "Gama", "Delta", "Epsilon", "Zeta", "Eta", "Teta")
    words = [
        word for block in reference.blocks if block.kind == "paragraph"
        for word in (block.text or "").split()
    ]
    blocks = []
    for slot in plan.slots:
        if slot.kind == "heading":
            text = "Como obter orientacao?" if slot.question else "Condicoes de atendimento"
            block = Block(id=slot.id, kind="heading", text=text, level=slot.level)
        elif slot.item_levels:
            block = Block(
                id=slot.id, kind=slot.kind,
                items=tuple(
                    ListItem(text="Confira a orientacao", level=level) for level in slot.item_levels
                ),
            )
        elif slot.kind == "table":
            assert slot.columns is not None and slot.rows is not None
            block = Block(
                id=slot.id, kind="table",
                table=Table(
                    id=f"table-{slot.id}",
                    columns=tuple(
                        Column(id=f"col-{index}", name=f"Campo {labels[index]}", kind="text")
                        for index in range(slot.columns)
                    ),
                    rows=tuple(
                        tuple(
                            Cell(kind="text", value=randomizer.choice(labels))
                            for _ in range(slot.columns)
                        )
                        for _ in range(slot.rows)
                    ),
                ),
            )
        else:
            block = Block(id=slot.id, kind=slot.kind, text="Consulte as condicoes.")
        blocks.append(block)
    data = {
        **reference.model_dump(), "blueprint": blueprint,
        "blocks": [block.model_dump() for block in blocks],
    }
    content = Content.model_validate(data)
    needed = max(0, WORD_BANDS[blueprint.length_band][0] + 20 - word_count(content))
    targets: list[tuple[dict[str, Any], str, int]] = []
    table_targets: list[tuple[dict[str, Any], str, int]] = []
    for raw in data["blocks"]:
        if raw["kind"] in {"paragraph", "callout"}:
            targets.append((raw, "text", 2048))
        for item in raw["items"] or ():
            targets.append((item, "text", 2048))
        if raw["table"]:
            limit = 120 if len(raw["table"]["columns"]) >= 5 else 240
            table_targets.extend(
                (cell, "value", limit) for row in raw["table"]["rows"] for cell in row
            )
    for index in range(needed):
        word = words[index % len(words)]
        placed = False
        for pool in (targets, table_targets):
            for offset in range(len(pool)):
                target, key, limit = pool[(index + offset) % len(pool)]
                if len(target[key]) + len(word) + 1 <= limit:
                    target[key] += " " + word
                    placed = True
                    break
            if placed:
                break
        if not placed:
            raise ValueError("The fixture word budget exceeds the planned text/cell capacities.")
    return Content.model_validate(data)


def content_wire(content: Content) -> dict[str, Any]:
    result: dict[str, Any] = {
        "title": content.title, "blocks": [], "list_items": [], "columns": [],
        "cells": [], "facts": [],
    }
    if content.facts:
        raise ValueError("This server fixture only converts content without quantitative facts.")
    for block in content.blocks:
        result["blocks"].append({
            "id": block.id, "kind": block.kind, "text": block.text, "level": block.level,
            "table_id": block.table.id if block.table else None,
        })
        for item in block.items or ():
            result["list_items"].append({
                "block_id": block.id, "text": item.text, "level": item.level,
            })
        if block.table:
            for column in block.table.columns:
                result["columns"].append({
                    **column.model_dump(), "table_id": block.table.id,
                })
            for index, row in enumerate(block.table.rows):
                for column, cell in zip(block.table.columns, row, strict=True):
                    result["cells"].append({
                        "table_id": block.table.id, "row": index, "column_id": column.id,
                        "value": str(cell.value), "fact_id": cell.fact_id,
                    })
    return result
