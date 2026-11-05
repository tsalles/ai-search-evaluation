import random
import re
from collections.abc import Collection, Mapping
from decimal import Decimal
from typing import Literal

from docgen.config import GenerationConfig
from docgen.errors import InputError
from docgen.facts import normalized
from docgen.models import Blueprint, Content, Fact, ScenarioFamily
from docgen.sampling import derived_seed, expand, quotas
from docgen.text import business_units

ROLE_FACTS = (
    ("fee-a", "condition-a"),
    ("age-a", "steps-a"),
    ("fee-a", "exception-a"),
    ("fee-a", "fee-b"),
    ("fee-b", "age-b", "condition-b"),
    ("condition-a", "exception-a"),
)
ROLE_BRIEFS = (
    "Explain the first account's price and eligibility conditions.",
    "Explain the first account's procedure, responsibilities and age requirement.",
    "Answer questions about the first account's price and exception.",
    "Compare the two accounts' prices with explicit account labels.",
    "Describe the similar second account without mixing its values with the first account.",
    "Explain the first account's applicable conditions and exception.",
)
SAAS_ROLE_FACTS = (
    ("price-a", "activation-a"),
    ("sla-a", "workflow-a"),
    ("price-a", "restriction-a"),
    ("price-a", "price-b", "sla-a", "sla-b"),
    ("price-b", "sla-b", "activation-b"),
    ("activation-a", "restriction-a"),
)
SAAS_ROLE_BRIEFS = (
    "Describe the first SaaS subscription's monthly price and activation prerequisites.",
    "Explain the first SaaS plan's initial-response commitment and onboarding responsibilities.",
    "Answer commercial questions about the first SaaS plan's price and service exclusions.",
    "Compare both SaaS plans' monthly prices and initial-response commitments "
    "with explicit labels.",
    "Describe the second SaaS plan's price, support commitment and activation prerequisites.",
    "Explain activation prerequisites and exclusions from the first SaaS plan's "
    "support commitment.",
)


def role_fact_ids(family: ScenarioFamily, role: int) -> tuple[str, ...]:
    return (SAAS_ROLE_FACTS if family.domain == "saas" else ROLE_FACTS)[role]


def role_brief(family: ScenarioFamily, role: int) -> str:
    return (SAAS_ROLE_BRIEFS if family.domain == "saas" else ROLE_BRIEFS)[role]


def _saas_families(
    count: int, *, seed: int, language: str, split_weights: Mapping[str, float | Decimal],
) -> tuple[ScenarioFamily, ...]:
    splits = expand(
        quotas(count, {key: Decimal(str(value)) for key, value in split_weights.items()}),
        derived_seed(seed, "saas-family-splits-v1"),
    )
    randomizer = random.Random(derived_seed(seed, "saas-family-facts-v1"))
    brand_randomizer = random.Random(derived_seed(seed, "saas-vendor-v1"))
    vendor = "".join(
        brand_randomizer.choice((
            "arvo", "celi", "dori", "evo", "fara", "gali", "hori", "ilia",
            "jova", "kori", "luma", "mira", "nora", "olia", "pera", "riva",
            "sora", "tera", "vela", "zeni",
        ))
        for _ in range(3)
    ).capitalize()
    names = [
        (brand, area)
        for brand in (
            "Orbita", "Vetor", "Nexo", "Prisma", "Metrica", "Ritmo", "Pulso",
            "Trama", "Nucleo", "Malha", "Fusao", "Eixo", "Sigma", "Fluxo",
        )
        for area in (
            "Operacoes", "Projetos", "Atendimento", "Analitica", "Integracoes",
            "Inventario", "Qualidade", "Automacao", "Coordenacao", "Suporte",
            "Planejamento", "Monitoramento", "Arquivos", "Catalogo",
        )
    ]
    randomizer.shuffle(names)
    portuguese = language == "pt"
    result = []
    for index in range(count):
        brand, area = names[index]
        base = f"{vendor} Suite {brand} {area}"
        entities = (
            base + (" Equipe" if portuguese else " Team"),
            base + (" Organizacao" if portuguese else " Organization"),
        )
        facts = []
        for suffix, entity in zip(("a", "b"), entities, strict=True):
            amount = Decimal(randomizer.randrange(25, 800) * 10 + 9)
            hours = Decimal(randomizer.choice((1, 2, 4, 8, 12)))
            activation = randomizer.choice((
                "dominio corporativo verificado e administrador designado",
                "ambiente homologado e aceite do termo de uso",
                "cadastro da organizacao validado e responsavel tecnico identificado",
            )) if portuguese else randomizer.choice((
                "verified corporate domain and designated administrator",
                "approved workspace and acceptance of the terms of use",
                "validated organization registration and identified technical owner",
            ))
            restriction = randomizer.choice((
                "integracao em manutencao suspende a meta de primeira resposta",
                "incidente em ambiente de teste fica fora da janela prioritaria",
                "solicitacao sem impacto comprovado segue a fila convencional",
            )) if portuguese else randomizer.choice((
                "integration maintenance suspends the initial-response target",
                "test-environment incidents are outside the priority window",
                "requests without demonstrated impact use the standard queue",
            ))
            workflow = (
                "gestor cadastra o espaco de trabalho e a equipe de suporte confirma a ativacao"
                if portuguese else
                "the manager registers the workspace and the support team confirms activation"
            )
            for name, kind, value, unit, display in (
                ("price", "decimal", amount, "BRL", f"{amount} BRL"),
                (
                    "sla", "decimal", hours,
                    ("hora" if hours == 1 else "horas") if portuguese
                    else ("hour" if hours == 1 else "hours"),
                    str(hours) + (
                        (" hora" if hours == 1 else " horas") if portuguese
                        else (" hour" if hours == 1 else " hours")
                    ),
                ),
                ("activation", "text", activation, None, activation),
                ("restriction", "text", restriction, None, restriction),
                ("workflow", "text", workflow, None, workflow),
            ):
                facts.append(Fact.model_validate({
                    "id": f"{name}-{suffix}", "entity": entity,
                    "kind": kind, "value": value, "unit": unit, "display": display,
                }))
        result.append(ScenarioFamily.model_validate({
            "id": f"saas-family-{index + 1:04}", "domain": "saas",
            "entities": entities, "facts": tuple(facts), "split": splits[index],
        }))
    return tuple(result)


def create_families(
    count: int,
    *,
    seed: int,
    language: str,
    split_weights: Mapping[str, float | Decimal],
    domain: Literal["banking", "saas"] = "banking",
) -> tuple[ScenarioFamily, ...]:
    if domain == "saas":
        return _saas_families(
            count, seed=seed, language=language, split_weights=split_weights,
        )
    if domain != "banking":
        raise InputError("Unsupported experiment family domain.")
    splits = expand(
        quotas(count, {key: Decimal(str(value)) for key, value in split_weights.items()}),
        derived_seed(seed, "family-splits-v1"),
    )
    randomizer = random.Random(derived_seed(seed, "family-facts-v1"))
    trees = (
        "Acacia",
        "Cedro",
        "Ipe",
        "Limoeiro",
        "Oliveira",
        "Palmeira",
        "Pinheiro",
        "Salgueiro",
        "Carvalho",
        "Jacaranda",
        "Castanheira",
        "Figueira",
        "Magnolia",
        "Cerejeira",
    )
    places = (
        "Vale",
        "Campo",
        "Lago",
        "Monte",
        "Serra",
        "Vila",
        "Praia",
        "Bosque",
        "Jardim",
        "Rio",
        "Ilha",
        "Ponte",
        "Sol",
        "Luar",
    )
    names = [(left, right) for left in trees for right in places]
    randomizer.shuffle(names)
    result = []
    for index in range(count):
        left, right = names[index]
        base = (
            f"Conta Aurora {left} {right}" if language == "pt" else f"Aurora {left} {right} account"
        )
        entities = (base, base + " Plus")
        facts = []
        for suffix, entity in zip(("a", "b"), entities, strict=True):
            amount = Decimal(randomizer.randrange(5, 50)) + Decimal("0.90")
            age = Decimal(randomizer.choice((18, 21, 25)))
            for name, kind, value, unit, display in (
                ("fee", "decimal", amount, "BRL", f"{amount} BRL"),
                (
                    "age",
                    "decimal",
                    age,
                    "anos" if language == "pt" else "years",
                    str(age) + (" anos" if language == "pt" else " years"),
                ),
                (
                    "condition",
                    "text",
                    "cadastro ativo e comprovante de residencia"
                    if language == "pt"
                    else "active registration and proof of residence",
                    None,
                    None,
                ),
                (
                    "exception",
                    "text",
                    "cadastro suspenso exige revisao presencial"
                    if language == "pt"
                    else "suspended registration requires an in-person review",
                    None,
                    None,
                ),
                (
                    "steps",
                    "text",
                    "a equipe confere os documentos e o titular confirma a solicitacao"
                    if language == "pt"
                    else (
                        "the team checks the documents and the account holder confirms the request"
                    ),
                    None,
                    None,
                ),
            ):
                facts.append(
                    Fact.model_validate(
                        {
                            "id": f"{name}-{suffix}",
                            "entity": entity,
                            "kind": kind,
                            "value": value,
                            "unit": unit,
                            "display": display or value,
                        }
                    )
                )
        result.append(
            ScenarioFamily.model_validate(
                {
                    "id": f"family-{index + 1:04}",
                    "entities": entities,
                    "facts": facts,
                    "split": splits[index],
                }
            )
        )
    return tuple(result)


def family_for(blueprint: Blueprint, config: GenerationConfig) -> ScenarioFamily | None:
    if blueprint.family_id is None:
        return None
    family = next(
        (family for family in config.families or () if family.id == blueprint.family_id),
        None,
    )
    if family is None:
        raise InputError("Blueprint references an unknown experiment family.")
    return family


def referenced_entities(text: str, entities: Collection[str]) -> frozenset[str]:
    labels = {normalized(entity): entity for entity in entities}
    if not labels:
        return frozenset()
    pattern = (
        r"(?<!\w)(?:"
        + "|".join(
            re.escape(label) for label in sorted(labels, key=lambda value: (-len(value), value))
        )
        + r")(?!\w)"
    )
    return frozenset(labels[match.group()] for match in re.finditer(pattern, normalized(text)))


def scoped_facts(blueprint: Blueprint, config: GenerationConfig) -> tuple[Fact, ...]:
    family = family_for(blueprint, config)
    if family is None:
        return config.shared_facts
    required = set(blueprint.required_fact_ids or ())
    selected = tuple(fact for fact in family.facts if fact.id in required)
    if len(selected) != len(required):
        raise InputError("Blueprint references an unknown family fact.")
    return (*config.shared_facts, *selected)


def validate_family(content: Content, config: GenerationConfig) -> None:
    family = family_for(content.blueprint, config)
    if family is None:
        return
    expected = scoped_facts(content.blueprint, config)
    actual = {fact.id: fact for fact in content.facts}
    mentioned = referenced_entities(" ".join(business_units(content)), family.entities)
    if set(actual) != {fact.id for fact in expected}:
        raise ValueError("Experimental documents must use only their scoped frozen facts.")
    for fact in expected:
        observed = actual.get(fact.id)
        if observed is None or (
            observed.kind,
            observed.value,
            observed.unit,
            observed.entity,
            observed.valid_from,
            observed.valid_until,
        ) != (
            fact.kind,
            fact.value,
            fact.unit,
            fact.entity,
            fact.valid_from,
            fact.valid_until,
        ):
            raise ValueError(f"Required frozen family fact is absent or changed: {fact.id}.")
        if fact.entity not in mentioned:
            raise ValueError(
                f"Frozen family fact has no correctly scoped visible entity: {fact.id}. "
                f"Use the complete literal name {fact.entity!r}; do not change its spelling "
                "or accents."
            )
        used = any(
            fact.id in block.fact_refs
            or any(fact.id in item.fact_refs for item in block.items or ())
            or block.table is not None
            and any(cell.fact_id == fact.id for row in block.table.rows for cell in row)
            for block in content.blocks
        )
        if not used:
            raise ValueError(f"Required family fact has no visible evidence: {fact.id}.")
