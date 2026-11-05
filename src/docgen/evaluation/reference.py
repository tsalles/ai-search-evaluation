import hashlib
import math
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from docgen.errors import InputError, IntegrityError
from docgen.evaluation.corpus import sources
from docgen.evaluation.models import Claim, Evidence, Intent, Judgment, Query, Reference, Review
from docgen.evaluation.state import Workspace, digest
from docgen.facts import canonical_fact
from docgen.families import referenced_entities
from docgen.models import Record
from docgen.persistence import safe_child
from docgen.sampling import derived_seed
from docgen.text import business_units, value_text

ProvisionalPolicy = Literal["automated_smoke", "automated_pilot", "automated_study"]
type ReferenceNeed = tuple[
    str, tuple[str, ...], tuple[str, ...], tuple[str, str], tuple[str, str],
]


def _saas_needs(first: str, second: str) -> tuple[ReferenceNeed, ...]:
    return (
        (
            "subscription-price", ("price-a",), (first,),
            (
                f"Quanto custa por mes a assinatura {first}?",
                f"Qual cobranca mensal em BRL foi definida para o plano {first}?",
            ),
            (
                f"How much does the {first} subscription cost per month?",
                f"What monthly BRL charge is specified for the {first} plan?",
            ),
        ),
        (
            "response-sla", ("sla-a",), (first,),
            (
                f"Qual o prazo de primeira resposta de suporte do plano {first}?",
                f"Em quantas horas o atendimento da assinatura {first} "
                "deve responder inicialmente?",
            ),
            (
                f"What is the initial support response target for the {first} plan?",
                f"Within how many hours should support initially respond for {first}?",
            ),
        ),
        (
            "service-exclusion", ("restriction-a",), (first,),
            (
                f"Qual situacao fica fora do compromisso de atendimento do plano {first}?",
                f"Que restricao altera a prioridade de suporte da assinatura {first}?",
            ),
            (
                f"What situation is excluded from the {first} support commitment?",
                f"What restriction changes support priority for the {first} subscription?",
            ),
        ),
        (
            "plan-comparison", ("price-a", "price-b", "sla-a", "sla-b"), (first, second),
            (
                f"Compare o preco mensal e a primeira resposta de suporte de {first} e {second}.",
                f"Como {first} e {second} diferem em mensalidade e prazo inicial de atendimento?",
            ),
            (
                f"Compare monthly price and initial support response for {first} and {second}.",
                f"How do {first} and {second} differ in subscription charge and initial response?",
            ),
        ),
        (
            "activation-and-ownership", ("activation-a", "workflow-a"), (first,),
            (
                f"O que precisa estar pronto para ativar {first} e quem confirma a ativacao?",
                f"Quais pre-requisitos e responsabilidades iniciam o uso da assinatura {first}?",
            ),
            (
                f"What must be ready to activate {first}, and who confirms activation?",
                f"What prerequisites and responsibilities start use of the {first} subscription?",
            ),
        ),
        (
            "unanswerable", (), (first,),
            (
                f"Em qual pais os dados da assinatura {first} ficam hospedados?",
                f"Qual e a localizacao geografica do armazenamento de dados de {first}?",
            ),
            (
                f"In which country is data for the {first} subscription hosted?",
                f"What is the geographic data-storage location for {first}?",
            ),
        ),
    )


def load_record[T: Record](path: Path, model: type[T]) -> T:
    try:
        if path.is_symlink() or path.is_junction():
            raise IntegrityError("Reference/state files cannot be filesystem links.")
        return model.model_validate_json(path.read_bytes())
    except (OSError, ValidationError):
        raise InputError("Cannot load the typed reference or review file.") from None


def build_reference(workspace: Workspace) -> Reference:
    saved = workspace.get("reference-baseline")
    if saved is not None:
        path = safe_child(workspace.path, "reference-draft.json")
        committed = workspace.get("reference")
        draft = (
            load_record(path, Reference)
            if path.exists()
            else Reference.model_validate(committed if committed is not None else saved)
        )
        validate_reference(workspace, draft, release=False)
        if not path.exists():
            workspace.export("reference-draft.json", draft)
        return draft
    documents, contents = sources(workspace)
    generation = workspace.protocol.generation_config.generation
    if generation is None or generation.families is None:
        raise IntegrityError("Fresh generation has no family reference plan.")
    claims = tuple(
        Claim(
            id=f"{family.id}-{fact.id}",
            family_id=family.id,
            fact=canonical_fact(fact, generation.locale),
        )
        for family in generation.families
        for fact in family.facts
    )
    evidence: list[Evidence] = []
    for content in contents:
        family_id = content.blueprint.family_id
        for block in content.blocks:
            for fact_id in block.fact_refs:
                if block.text is not None:
                    evidence.append(
                        Evidence(
                            id=f"evidence-{len(evidence) + 1:06}",
                            claim_id=f"{family_id}-{fact_id}",
                            doc_id=content.blueprint.content_id,
                            block_id=block.id,
                            quote=block.text,
                        )
                    )
            for index, item in enumerate(block.items or ()):
                for fact_id in item.fact_refs:
                    evidence.append(
                        Evidence(
                            id=f"evidence-{len(evidence) + 1:06}",
                            claim_id=f"{family_id}-{fact_id}",
                            doc_id=content.blueprint.content_id,
                            block_id=block.id,
                            quote=item.text,
                            item_index=index,
                        )
                    )
            if block.table is not None:
                for row_index, row in enumerate(block.table.rows):
                    for column, cell in zip(block.table.columns, row, strict=True):
                        if cell.fact_id:
                            evidence.append(
                                Evidence(
                                    id=f"evidence-{len(evidence) + 1:06}",
                                    claim_id=f"{family_id}-{cell.fact_id}",
                                    doc_id=content.blueprint.content_id,
                                    block_id=block.id,
                                    quote=value_text(cell.value, content.blueprint.locale),
                                    table_row=row_index,
                                    column_id=column.id,
                                )
                            )
    by_document = {document.id: document for document in documents}
    grounded = {item.claim_id for item in evidence}
    claims = tuple(claim for claim in claims if claim.id in grounded)
    claim_entities = {claim.id: claim.fact.entity for claim in claims}
    for content in contents:
        text = " ".join(business_units(content)).casefold()
        for family in generation.families:
            if family.id != content.blueprint.family_id and any(
                entity.casefold() in text for entity in family.entities
            ):
                raise InputError(
                    "Cross-family entity references require a broader relevance audit."
                )
    intents = []
    portuguese = generation.language == "pt"
    for family in generation.families:
        first, second = family.entities
        needs: tuple[ReferenceNeed, ...] = (
            (
                "fee",
                ("fee-a",),
                (first,),
                (
                    f"Qual e o valor em BRL informado para a {first}?",
                    f"Que valor monetario o documento apresenta para a {first}?",
                ),
                (
                    f"What amount in BRL is stated for {first}?",
                    f"What monetary amount does the document give for {first}?",
                ),
            ),
            (
                "age",
                ("age-a",),
                (first,),
                (
                    f"Qual e o requisito de idade informado para a {first}?",
                    f"Que idade o documento informa para solicitar a {first}?",
                ),
                (
                    f"What age requirement is stated for {first}?",
                    f"What age does the document give for requesting {first}?",
                ),
            ),
            (
                "exception",
                ("exception-a",),
                (first,),
                (
                    f"Qual excecao de cadastro se aplica a {first}?",
                    f"Na {first}, o que muda se o cadastro estiver suspenso?",
                ),
                (
                    f"What registration exception applies to {first}?",
                    f"What changes for suspended registration on {first}?",
                ),
            ),
            (
                "comparison",
                ("fee-a", "fee-b"),
                (first, second),
                (
                    f"Compare os valores em BRL informados para a {first} e a {second}.",
                    f"Qual valor monetario e apresentado para cada uma: {first} e {second}?",
                ),
                (
                    f"Compare the stated amounts in BRL for {first} and {second}.",
                    f"What monetary amount is given for each: {first} and {second}?",
                ),
            ),
            (
                "conditions-and-process",
                ("condition-a", "steps-a"),
                (first,),
                (
                    f"Quais condicoes e responsabilidades valem para solicitar a {first}?",
                    f"Para pedir a {first}, o que preciso apresentar e quem confirma o pedido?",
                ),
                (
                    f"What conditions and responsibilities apply to requesting {first}?",
                    f"What must I provide for {first} and who confirms the request?",
                ),
            ),
            (
                "unanswerable",
                (),
                (first,),
                (
                    f"Qual o prazo maximo do emprestimo pessoal da {first}?",
                    f"Por quantos meses posso parcelar um emprestimo pessoal na {first}?",
                ),
                (
                    f"What is the maximum personal loan term for {first}?",
                    f"Over how many months can a personal loan on {first} be repaid?",
                ),
            ),
        )
        if family.domain == "saas":
            needs = _saas_needs(first, second)
        for name, fact_ids, entities, pt, en in needs:
            identifier = f"{family.id}-{name}"
            required = tuple(f"{family.id}-{fact_id}" for fact_id in fact_ids)
            judgments = []
            for document in documents:
                if document.family_id != family.id:
                    continue
                occurrences = [
                    item
                    for item in evidence
                    if item.doc_id == document.id and item.claim_id in required
                ]
                supported = {item.claim_id for item in occurrences}
                scoped_context = any(
                    item.doc_id == document.id and claim_entities[item.claim_id] in entities
                    for item in evidence
                )
                grade = (
                    3
                    if required and supported == set(required)
                    else 2
                    if supported
                    else 1
                    if required and scoped_context
                    else 0
                )
                judgments.append(
                    Judgment(
                        doc_id=document.id,
                        grade=grade,
                        evidence_ids=tuple(item.id for item in occurrences),
                        rationale="Source-anchor draft; human judgment and scope audit required.",
                    )
                )
            answer = "; ".join(
                claim.fact.entity + ": " + claim.fact.display
                for claim in claims
                if claim.id in required
            )
            intents.append(
                Intent(
                    id=identifier,
                    family_id=family.id,
                    split=family.split,
                    task_type=name,
                    answerable=bool(required),
                    required_claims=required,
                    reference_answer=answer or None,
                    entities=entities,
                    queries=tuple(
                        Query(id=f"{identifier}-{suffix}", text=text)
                        for suffix, text in zip(
                            ("direct", "paraphrase"), pt if portuguese else en, strict=True
                        )
                    ),
                    judgments=tuple(judgments),
                )
            )
    reference = Reference(
        protocol_id=workspace.protocol.id,
        source_hash=digest([document.model_dump(mode="json") for document in documents]),
        documents=documents,
        claims=claims,
        evidence=tuple(evidence),
        intents=tuple(intents),
    )
    if set(by_document) != {content.blueprint.content_id for content in contents}:
        raise IntegrityError("Reference source identities are incomplete.")
    workspace.record("reference-baseline", reference)
    workspace.export("reference-draft.json", reference)
    return reference


def review_hash(intent: Intent) -> str:
    return digest(intent.model_copy(update={"reviews": ()}))


def needs_second_review(workspace: Workspace, intent: Intent) -> bool:
    return (
        not intent.answerable
        or len(intent.required_claims) > 1
        or derived_seed(workspace.protocol.config.seed, "review:" + intent.id) % 5 == 0
    )


def review_intent(
    workspace: Workspace,
    *,
    intent_id: str,
    reviewer: str,
    certify_scope: bool,
) -> Reference:
    if workspace.get("reference") is not None:
        raise InputError("Reference is released; start a new experiment to change sealed truth.")
    path = safe_child(workspace.path, "reference-draft.json")
    draft = load_record(path, Reference)
    intent = next((intent for intent in draft.intents if intent.id == intent_id), None)
    if intent is None:
        raise InputError("Unknown draft intent ID.")
    review = Review(
        reviewer=reviewer,
        payload_hash=review_hash(intent),
        scope_certified=certify_scope,
    )
    current = tuple(item for item in intent.reviews if item.payload_hash == review.payload_hash)
    if any(item.reviewer.casefold() == review.reviewer.casefold() for item in current):
        raise InputError("A reviewer cannot independently approve the same intent twice.")
    updated = intent.model_copy(update={"reviews": (*current, review)})
    result = draft.model_copy(
        update={
            "intents": tuple(updated if item.id == intent_id else item for item in draft.intents),
        }
    )
    workspace.record(f"review:{intent_id}:{digest(review)}", review)
    workspace.replace_draft("reference-draft.json", result.model_dump_json(indent=2).encode())
    return result


def validate_reference(
    workspace: Workspace,
    reference: Reference,
    *,
    release: bool,
) -> None:
    baseline = workspace.get("reference-baseline")
    if baseline is None:
        raise InputError("Build the fresh source reference first.")
    original = Reference.model_validate(baseline)
    documents, _ = sources(workspace)
    if (
        reference.protocol_id != workspace.protocol.id
        or reference.source_hash
        != digest([document.model_dump(mode="json") for document in documents])
        or reference.documents != original.documents
        or reference.claims != original.claims
        or reference.evidence != original.evidence
        or {intent.id for intent in reference.intents} != {intent.id for intent in original.intents}
        or len(reference.intents) != len(original.intents)
    ):
        raise IntegrityError("Reference lineage, source evidence or intent membership differs.")
    docs = {document.id: document for document in reference.documents}
    claims = {claim.id: claim for claim in reference.claims}
    occurrences = {item.id: item for item in reference.evidence}
    entity_labels = {entity for document in reference.documents for entity in document.entities}
    query_ids: set[str] = set()
    human_authored = 0
    original_intents = {intent.id: intent for intent in original.intents}
    for intent in reference.intents:
        initial = original_intents[intent.id]
        if (intent.family_id, intent.split, intent.entities) != (
            initial.family_id,
            initial.split,
            initial.entities,
        ):
            raise InputError("Intent scope or split differs from its frozen family.")
        if intent.answerable != bool(intent.required_claims):
            raise InputError("Answerability must match supported required claims.")
        if len(set(intent.required_claims)) != len(intent.required_claims) or any(
            claim not in claims or claims[claim].family_id != intent.family_id
            for claim in intent.required_claims
        ):
            raise InputError("Required claims must be unique and grounded in this family.")
        for query in intent.queries:
            if query.id in query_ids or (
                referenced_entities(query.text, entity_labels) != frozenset(intent.entities)
            ):
                raise InputError(
                    "Query identity is duplicated or its explicit entity scope differs."
                )
            query_ids.add(query.id)
        if any(query.authorship == "human" for query in intent.queries):
            old = {query.text for query in initial.queries}
            if any(query.authorship == "human" and query.text in old for query in intent.queries):
                raise InputError("Human-authored queries must be edited, not relabeled templates.")
            human_authored += 1
        expected = {doc.id for doc in docs.values() if doc.family_id == intent.family_id}
        if {item.doc_id for item in intent.judgments} != expected or (
            len(intent.judgments) != len(expected)
        ):
            raise InputError("Every in-family document needs exactly one judgment.")
        positives = 0
        for judgment in intent.judgments:
            if not intent.answerable and judgment.grade >= 2:
                raise InputError("An unanswerable intent cannot have substantive positives.")
            cited = []
            for evidence_id in judgment.evidence_ids:
                item = occurrences.get(evidence_id)
                if item is None or item.doc_id != judgment.doc_id:
                    raise InputError("Judgment cites unknown or wrong-document evidence.")
                cited.append(item.claim_id)
            if judgment.grade >= 2:
                positives += 1
                supported = set(cited) & set(intent.required_claims)
                if (
                    not supported
                    or judgment.grade == 3
                    and supported != set(intent.required_claims)
                ):
                    raise InputError("Positive judgment lacks its required source evidence.")
        if intent.answerable and positives == 0:
            raise InputError("Answerable intent has no supported positive document.")
        if release:
            needed = 2 if needs_second_review(workspace, intent) else 1
            if len({item.reviewer.casefold() for item in intent.reviews}) < needed or any(
                item.payload_hash != review_hash(intent)
                or not item.scope_certified
                or workspace.get(f"review:{intent.id}:{digest(item)}")
                != item.model_dump(mode="json")
                for item in intent.reviews
            ):
                raise InputError(
                    "Human review is missing, stale, unaudited or lacks independent double review."
                )
    if release and human_authored < math.ceil(len(reference.intents) * 0.2):
        raise InputError("At least 20% of intents require genuinely edited human-authored queries.")


def _require_provisional_smoke(
    workspace: Workspace, reference: Reference | None = None,
) -> None:
    workspace.require_valid()
    config = workspace.protocol.config
    configured = (
        config.family_count <= 2
        and config.generation.count <= 12
        and config.split_weights.get("test") == 1
    )
    observed = reference is None or (
        len(reference.documents) <= 12
        and len({document.family_id for document in reference.documents}) <= 2
        and all(intent.split == "test" for intent in reference.intents)
    )
    if not configured or not observed:
        raise InputError(
            "Provisional release is limited to all-test smoke experiments "
            "with at most 2 families and 12 documents."
        )


def _require_provisional_sample(
    workspace: Workspace, reference: Reference | None = None, *, study: bool = False,
) -> None:
    workspace.require_valid()
    if study:
        workspace.protocol.require_pipeline_only()
    config = workspace.protocol.config
    generation = workspace.protocol.generation_config.generation
    label = "study" if study else "pilot"
    minimum_families, maximum_families = (51, 166) if study else (3, 50)
    minimum_documents, maximum_documents = minimum_families * 6, maximum_families * 6
    if generation is None or generation.families is None:
        raise IntegrityError(f"The frozen {label} family plan is missing.")
    test_families = {family.id for family in generation.families if family.split == "test"}
    configured = (
        minimum_families <= config.family_count <= maximum_families
        and minimum_documents <= config.generation.count <= maximum_documents
        and len(test_families) >= 2
    )
    observed = reference is None or (
        minimum_documents <= len(reference.documents) <= maximum_documents
        and minimum_families
        <= len({document.family_id for document in reference.documents})
        <= maximum_families
        and len({intent.family_id for intent in reference.intents if intent.split == "test"}) >= 2
    )
    if not configured or not observed:
        raise InputError(
            f"Provisional {label} release requires {minimum_documents} to {maximum_documents} "
            f"documents in {minimum_families} to {maximum_families} families "
            "and at least 2 test families."
        )


def _require_provisional_scope(
    workspace: Workspace, policy: ProvisionalPolicy, reference: Reference | None = None,
) -> None:
    if policy == "automated_smoke":
        _require_provisional_smoke(workspace, reference)
    else:
        _require_provisional_sample(workspace, reference, study=policy == "automated_study")


def provisional_policy(workspace: Workspace, reference: Reference) -> ProvisionalPolicy:
    value = workspace.get("provisional-reference")
    if not isinstance(value, dict):
        raise IntegrityError("Stored reference lacks its explicit provisional release record.")
    mode = value.get("mode")
    policy: ProvisionalPolicy
    if mode == "automated_smoke":
        policy = "automated_smoke"
    elif mode == "automated_pilot":
        policy = "automated_pilot"
    elif mode == "automated_study":
        policy = "automated_study"
    else:
        raise IntegrityError("Stored reference has an unknown provisional release policy.")
    _require_provisional_scope(workspace, policy, reference)
    if value != {
        "mode": policy,
        "reference_hash": digest(reference),
        "human_review_certified": False,
    }:
        raise IntegrityError("Stored reference lacks its explicit provisional release record.")
    return policy


def release_reference(
    workspace: Workspace, *, provisional: bool = False, provisional_pilot: bool = False,
    provisional_study: bool = False,
) -> Reference:
    flags = (provisional, provisional_pilot, provisional_study)
    if any(not isinstance(flag, bool) for flag in flags):
        raise InputError("The provisional release flags must be Boolean.")
    if sum(flags) > 1:
        raise InputError("Choose only one provisional release policy.")
    automated = any(flags)
    mode: ProvisionalPolicy = (
        "automated_study" if provisional_study
        else "automated_pilot" if provisional_pilot
        else "automated_smoke"
    )
    status = "provisional" if automated else "released"
    saved = workspace.get("reference")
    if saved is not None and Reference.model_validate(saved).status != status:
        raise InputError(
            "Reference release mode is immutable; start a new experiment to change it."
        )
    if saved is not None and automated:
        saved_policy = workspace.get("provisional-reference")
        if not isinstance(saved_policy, dict) or saved_policy.get("mode") != mode:
            raise InputError(
                "Reference release mode is immutable; start a new experiment to change it."
            )
    if automated:
        _require_provisional_scope(workspace, mode)
    draft = load_record(safe_child(workspace.path, "reference-draft.json"), Reference)
    validate_reference(workspace, draft, release=not automated)
    released = draft.model_copy(update={"status": status})
    if automated:
        _require_provisional_scope(workspace, mode, released)
        workspace.put(
            "provisional-reference",
            {
                "mode": mode,
                "reference_hash": digest(released),
                "human_review_certified": False,
            },
        )
    workspace.record("reference", released)
    workspace.export("reference.json", released)
    rows: list[str] = []
    for intent in released.intents:
        grades = {judgment.doc_id: judgment.grade for judgment in intent.judgments}
        for query in intent.queries:
            rows.extend(
                f"{query.id} 0 {document.id} {grades.get(document.id, 0)}"
                for document in released.documents
            )
    raw = ("\n".join(rows) + "\n").encode()
    workspace.export_bytes("qrels.trec", raw)
    workspace.put(
        "reference-complete",
        {
            "reference_hash": digest(released),
            "qrels_hash": hashlib.sha256(raw).hexdigest(),
        },
    )
    return released


def released_reference(workspace: Workspace) -> Reference:
    value = workspace.get("reference")
    if value is None:
        raise InputError("A released reference is required before Azure ingestion.")
    reference = Reference.model_validate(value)
    if reference.status == "provisional":
        provisional_policy(workspace, reference)
        validate_reference(workspace, reference, release=False)
    elif reference.status == "released":
        validate_reference(workspace, reference, release=True)
    else:
        raise IntegrityError("Stored reference is not released.")
    seal = workspace.get("reference-complete")
    if not isinstance(seal, dict) or seal.get("reference_hash") != digest(reference):
        raise InputError("Finish reference release before ingestion, collection or scoring.")
    for filename, expected in (
        ("reference.json", seal["reference_hash"]),
        ("qrels.trec", seal.get("qrels_hash")),
    ):
        path = safe_child(workspace.path, filename)
        if not path.is_file():
            raise IntegrityError(
                f"Released {filename} export is missing; repeat reference release."
            )
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise IntegrityError(f"Released {filename} export differs from sealed truth.")
    return reference
