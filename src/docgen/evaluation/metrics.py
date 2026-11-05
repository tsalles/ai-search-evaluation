import math
from collections.abc import Mapping, Sequence

from docgen.errors import InputError


def parent_metrics(
    ranking: Sequence[str],
    judgments: Mapping[str, int],
    *,
    cutoffs: tuple[int, ...] = (5, 10, 20),
) -> dict[str, float]:
    from ir_measures import RR, P, R, nDCG
    from ir_measures.providers import registry

    if any(type(grade) is not int or not 0 <= grade <= 3 for grade in judgments.values()):
        raise InputError("Judgment grades must be integers in [0, 3].")
    if not judgments or not any(grade >= 2 for grade in judgments.values()):
        raise InputError("Answerable metric inputs require at least one substantive positive.")
    if not cutoffs or any(type(cutoff) is not int or cutoff < 1 for cutoff in cutoffs):
        raise InputError("Metric cutoffs must be positive integers.")
    parents = list(dict.fromkeys(ranking))
    if any(parent not in judgments for parent in parents):
        raise InputError("Unjudged returned parent; primary scoring is forbidden.")
    provider = registry["pytrec_eval"]
    if not provider.is_available():
        raise InputError("The pinned pytrec_eval metric provider is unavailable.")
    qrels = {"q": dict(judgments)}
    result: dict[str, float] = {}
    for cutoff in cutoffs:
        prefix = parents[:cutoff]
        run = {"q": {parent: float(-rank) for rank, parent in enumerate(prefix, 1)}}
        if not prefix:
            values = [0.0] * 4
        else:
            measures = [
                P(rel=2) @ cutoff,
                R(rel=2) @ cutoff,
                RR(rel=2),
                nDCG(dcg="log2", gains={0: 0, 1: 1, 2: 3, 3: 7}) @ cutoff,
            ]
            observed = provider.calc_aggregate(measures, qrels, run)
            values = [float(observed[measure]) for measure in measures]
        for name, value in zip(("precision", "recall", "mrr", "ndcg"), values, strict=True):
            if not math.isfinite(value):
                raise InputError("Metric provider returned a nonfinite value.")
            result[f"{name}_at_{cutoff}"] = value
    return result
