from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Literal

from evaluation.phase9.historical_features import FeatureSnapshot


Mode = Literal["cric", "career_only", "phase_only"]
COMPONENT_WEIGHTS = {"performance": 0.60, "matchup": 0.30, "situation": 0.10}
METRIC_WEIGHTS = {
    "performance": {"economy": 0.45, "strike_rate": 0.25, "wicket_rate_per_100_legal_balls": 0.30},
    "matchup": {"economy": 0.35, "strike_rate": 0.25, "wicket_rate_per_100_legal_balls": 0.40},
    "situation": {"economy": 0.50, "wicket_rate_per_100_legal_balls": 0.50},
}
METRIC_DIRECTIONS = {
    "economy": "lower",
    "strike_rate": "lower",
    "wicket_rate_per_100_legal_balls": "higher",
}
RELIABILITY_PRIOR_BALLS = 30.0


def _component_features(
    snapshot: FeatureSnapshot,
    bowler_id: str,
    batter_id: str,
    phase: str | None,
    situation: tuple[str, str] | None,
    mode: Mode,
):
    phase_key = phase.casefold() if phase else None
    if mode == "career_only":
        performance = snapshot.career.get(bowler_id)
        matchup = None
        situation_stats = None
    elif mode == "phase_only":
        performance = snapshot.phase.get((bowler_id, phase_key)) if phase_key else None
        matchup = None
        situation_stats = None
    else:
        performance = snapshot.phase.get((bowler_id, phase_key)) if phase_key else None
        if performance is None:
            performance = snapshot.career.get(bowler_id)
        if phase_key:
            matchup = snapshot.phase_matchup.get((bowler_id, batter_id, phase_key))
        else:
            matchup = snapshot.matchup.get((bowler_id, batter_id))
        situation_stats = None
        if situation:
            situation_stats = snapshot.situation.get(
                (bowler_id, situation[0].casefold(), situation[1].casefold())
            )
    return {
        "performance": performance,
        "matchup": matchup,
        "situation": situation_stats,
    }


def score_candidate_set(
    snapshot: FeatureSnapshot,
    candidate_ids: Iterable[str],
    batter_id: str,
    phase: str | None,
    situation: tuple[str, str] | None = None,
    mode: Mode = "cric",
) -> list[dict]:
    """Score a prevalidated candidate set using only snapshot features."""
    snapshot.assert_leakage_free()
    if mode not in {"cric", "career_only", "phase_only"}:
        raise ValueError("Unsupported scoring mode")
    candidates = [value.strip().casefold() for value in candidate_ids]
    if any(not value for value in candidates) or len(candidates) != len(set(candidates)):
        raise ValueError("Candidate IDs must be nonempty and unique")
    if len(candidates) > 30:
        raise ValueError("At most 30 candidate bowlers are supported")

    features = {
        candidate: _component_features(
            snapshot, candidate, batter_id.strip().casefold(), phase, situation, mode
        )
        for candidate in candidates
    }
    metric_weights = (
        METRIC_WEIGHTS
        if mode == "cric"
        else {"performance": METRIC_WEIGHTS["performance"]}
    )
    source_weights = (
        {"performance": COMPONENT_WEIGHTS["performance"]}
        if mode in {"career_only", "phase_only"}
        else COMPONENT_WEIGHTS
    )
    utilities: dict[str, dict[str, float]] = {candidate: {} for candidate in candidates}
    samples: dict[str, dict[str, float]] = {candidate: {} for candidate in candidates}

    for source, metrics in metric_weights.items():
        for metric, metric_weight in metrics.items():
            observations = {}
            for candidate, candidate_features in features.items():
                evidence = candidate_features[source]
                if evidence is None:
                    continue
                value = evidence.metrics()[metric]
                if value is None or evidence.legal_balls <= 0:
                    continue
                observations[candidate] = (value, evidence.legal_balls)
            if not observations or metric_weight <= 0:
                continue
            values = [value for value, _ in observations.values()]
            minimum, maximum = min(values), max(values)
            for candidate, (value, legal_balls) in observations.items():
                if minimum == maximum:
                    normalized = 0.5
                elif METRIC_DIRECTIONS[metric] == "lower":
                    normalized = (maximum - value) / (maximum - minimum)
                else:
                    normalized = (value - minimum) / (maximum - minimum)
                reliability = legal_balls / (legal_balls + RELIABILITY_PRIOR_BALLS)
                utilities[candidate][f"{source}.{metric}"] = (
                    0.5 + reliability * (normalized - 0.5)
                )
                samples[candidate][source] = legal_balls

    results = []
    for candidate in candidates:
        component_scores = {}
        for source, metrics in metric_weights.items():
            available = {
                metric: metrics[metric]
                for metric in metrics
                if f"{source}.{metric}" in utilities[candidate]
            }
            if not available:
                continue
            weight_total = sum(available.values())
            component_scores[source] = sum(
                utilities[candidate][f"{source}.{metric}"] * weight / weight_total
                for metric, weight in available.items()
            )
        available_sources = {
            source: source_weights[source]
            for source in component_scores
            if source_weights[source] > 0
        }
        score = None
        effective_weights = {}
        if available_sources:
            total_weight = sum(available_sources.values())
            effective_weights = {
                source: weight / total_weight for source, weight in available_sources.items()
            }
            score = sum(
                component_scores[source] * effective_weights[source]
                for source in available_sources
            )
        results.append(
            {
                "bowler_id": candidate,
                "score": round(score * 100, 2) if score is not None else None,
                "_sort_score": score,
                "components": {
                    name: round(value * 100, 2) for name, value in component_scores.items()
                },
                "effective_weights": effective_weights,
                "sample_balls": samples[candidate],
            }
        )
    results.sort(
        key=lambda row: (
            row["_sort_score"] is None,
            -(row["_sort_score"] or 0.0),
            row["bowler_id"],
        )
    )
    for rank, result in enumerate(results, start=1):
        result["rank"] = rank
        del result["_sort_score"]
    return results


def assert_valid_score(value: float | None) -> None:
    if value is not None and (not math.isfinite(value) or value < 0 or value > 100):
        raise ValueError("Candidate-relative scores must be finite and between 0 and 100")
