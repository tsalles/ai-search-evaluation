import hashlib
import random
from decimal import Decimal
from fractions import Fraction

from docgen.config import check_mix


def quotas[Key: str](count: int, weights: dict[Key, Decimal]) -> dict[Key, int]:
    check_mix(weights)
    total = sum(Fraction(weight) for weight in weights.values())
    ideals = {key: Fraction(count) * Fraction(weight) / total for key, weight in weights.items()}
    result = {key: ideal.numerator // ideal.denominator for key, ideal in ideals.items()}
    ranked = sorted(ideals, key=lambda key: (-(ideals[key] - result[key]), key))
    for key in ranked[:count - sum(result.values())]:
        result[key] += 1
    return dict(sorted(result.items()))


def derived_seed(seed: int, stream: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{stream}".encode()).digest(), "big")


def expand[Key: str](counts: dict[Key, int], seed: int) -> list[Key]:
    result = [key for key, count in sorted(counts.items()) for _ in range(count)]
    random.Random(seed).shuffle(result)
    return result
