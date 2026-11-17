from __future__ import annotations

import math
import random
from collections.abc import Mapping


def mean_reciprocal_rank(ranked_ids: list[str], relevant_ids: set[str]) -> float | None:
    if not relevant_ids:
        return None
    for rank, candidate in enumerate(ranked_ids, start=1):
        if candidate in relevant_ids:
            return 1 / rank
    return 0.0


def paired_scenario_differences(
    reference: Mapping[str, float],
    comparison: Mapping[str, float],
) -> dict[str, float]:
    common = sorted(reference.keys() & comparison.keys())
    return {scenario: comparison[scenario] - reference[scenario] for scenario in common}


def match_level_bootstrap_mean(
    values_by_match: Mapping[str, float],
    repetitions: int = 2000,
    seed: int = 20261012,
    confidence: float = 0.95,
) -> dict[str, float | int]:
    """Percentile bootstrap over independent match-level values, never delivery rows."""
    if not values_by_match:
        raise ValueError("At least one match-level value is required")
    if repetitions < 1 or not 0 < confidence < 1:
        raise ValueError("Invalid bootstrap repetitions or confidence level")
    ids = sorted(values_by_match)
    values = [float(values_by_match[match_id]) for match_id in ids]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Match-level values must be finite")
    rng = random.Random(seed)
    estimates = []
    for _ in range(repetitions):
        estimates.append(
            sum(values[rng.randrange(len(values))] for _ in range(len(values))) / len(values)
        )
    estimates.sort()
    tail = (1 - confidence) / 2
    low = estimates[min(len(estimates) - 1, int(tail * repetitions))]
    high = estimates[min(len(estimates) - 1, int((1 - tail) * repetitions))]
    return {
        "matches": len(values),
        "repetitions": repetitions,
        "seed": seed,
        "estimate": sum(values) / len(values),
        "ci_low": low,
        "ci_high": high,
    }
