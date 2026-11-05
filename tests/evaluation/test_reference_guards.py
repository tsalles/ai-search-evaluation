import pytest

from docgen.errors import InputError, IntegrityError
from docgen.evaluation.models import Reference
from docgen.evaluation.reference import (
    build_reference,
    released_reference,
    review_intent,
    validate_reference,
)


def replace_intent(reference, changed):
    return reference.model_copy(
        update={
            "intents": tuple(
                changed if intent.id == changed.id else intent for intent in reference.intents
            ),
        }
    )


@pytest.mark.parametrize(
    "change,message",
    [
        (lambda intent: intent.model_copy(update={"split": "calibration"}), "split"),
        (lambda intent: intent.model_copy(update={"answerable": False}), "Answerability"),
        (lambda intent: intent.model_copy(update={"required_claims": ("unknown",)}), "grounded"),
        (
            lambda intent: intent.model_copy(
                update={
                    "queries": (
                        intent.queries[0].model_copy(update={"text": "No explicit entity here"}),
                        *intent.queries[1:],
                    )
                }
            ),
            "scope",
        ),
        (lambda intent: intent.model_copy(update={"judgments": intent.judgments[:-1]}), "Every"),
        (
            lambda intent: intent.model_copy(
                update={
                    "judgments": tuple(
                        judgment.model_copy(update={"grade": 0, "evidence_ids": ()})
                        for judgment in intent.judgments
                    )
                }
            ),
            "no supported positive",
        ),
        (
            lambda intent: intent.model_copy(
                update={
                    "judgments": (
                        intent.judgments[0].model_copy(
                            update={"evidence_ids": ("missing-evidence",)}
                        ),
                        *intent.judgments[1:],
                    )
                }
            ),
            "unknown",
        ),
        (
            lambda intent: intent.model_copy(
                update={
                    "judgments": tuple(
                        judgment.model_copy(update={"evidence_ids": ()})
                        for judgment in intent.judgments
                    )
                }
            ),
            "source evidence",
        ),
    ],
)
def test_invalid_scope_queries_judgments_or_evidence_cannot_be_released(
    staged_workspace,
    change,
    message,
):
    reference = released_reference(staged_workspace)
    altered = replace_intent(reference, change(reference.intents[0]))
    with pytest.raises(InputError, match=message):
        validate_reference(staged_workspace, altered, release=False)


def test_partial_evidence_cannot_be_upgraded_to_sufficient_or_no_answer_to_positive(
    staged_workspace,
):
    reference = released_reference(staged_workspace)
    intent = next(intent for intent in reference.intents if intent.task_type == "comparison")
    changed = intent.model_copy(
        update={
            "judgments": tuple(
                judgment.model_copy(update={"grade": 3}) if judgment.grade == 2 else judgment
                for judgment in intent.judgments
            )
        }
    )
    with pytest.raises(InputError, match="required source evidence"):
        validate_reference(staged_workspace, replace_intent(reference, changed), release=False)
    intent = next(intent for intent in reference.intents if not intent.answerable)
    changed = intent.model_copy(
        update={
            "judgments": (
                intent.judgments[0].model_copy(update={"grade": 2}),
                *intent.judgments[1:],
            )
        }
    )
    with pytest.raises(InputError, match="unanswerable"):
        validate_reference(staged_workspace, replace_intent(reference, changed), release=False)


def test_relabeling_templates_does_not_count_as_human_authorship(staged_workspace):
    reference = released_reference(staged_workspace)
    baseline = Reference.model_validate(staged_workspace.get("reference-baseline"))
    changed = reference.intents[0].model_copy(
        update={
            "queries": (
                baseline.intents[0].queries[0].model_copy(update={"authorship": "human"}),
                *reference.intents[0].queries[1:],
            )
        }
    )
    with pytest.raises(InputError, match="relabeled"):
        validate_reference(staged_workspace, replace_intent(reference, changed), release=False)


def test_reference_rebuild_preserves_human_edits_and_released_truth_cannot_be_reapproved(
    staged_workspace,
):
    reference = released_reference(staged_workspace)
    rebuilt = build_reference(staged_workspace)
    assert rebuilt.intents == reference.intents
    with pytest.raises(InputError, match="released"):
        review_intent(
            staged_workspace,
            intent_id=reference.intents[0].id,
            reviewer="Late Reviewer",
            certify_scope=True,
        )
    changed = reference.model_copy(update={"source_hash": "0" * 64})
    with pytest.raises(IntegrityError, match="lineage"):
        validate_reference(staged_workspace, changed, release=False)


def test_modified_released_qrels_cannot_be_silently_ignored(staged_workspace):
    path = staged_workspace.path / "qrels.trec"
    path.write_bytes(path.read_bytes() + b"unreviewed 0 fabricated 3\n")
    with pytest.raises(IntegrityError, match="qrels"):
        released_reference(staged_workspace)
