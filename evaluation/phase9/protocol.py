from __future__ import annotations

from evaluation.phase9.historical_features import MatchInfo


def chronological_splits(
    matches: dict[str, MatchInfo],
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    excluded_match_ids: set[str] | None = None,
) -> dict:
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("Split fractions must be between zero and one")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("A nonempty final holdout fraction is required")
    excluded = excluded_match_ids or set()
    included = {mid: item for mid, item in matches.items() if mid not in excluded}
    dates = sorted({item.match_date for item in included.values()})
    if len(dates) < 3:
        raise ValueError("At least three distinct dates are required")
    train_end_index = max(1, int(len(dates) * train_fraction))
    validation_end_index = max(train_end_index + 1, int(len(dates) * (train_fraction + validation_fraction)))
    validation_end_index = min(validation_end_index, len(dates) - 1)
    train_dates = set(dates[:train_end_index])
    validation_dates = set(dates[train_end_index:validation_end_index])
    test_dates = set(dates[validation_end_index:])
    match_splits = {
        "development": sorted(mid for mid, info in included.items() if info.match_date in train_dates),
        "validation": sorted(mid for mid, info in included.items() if info.match_date in validation_dates),
        "final_holdout": sorted(mid for mid, info in included.items() if info.match_date in test_dates),
    }
    return {
        "date_policy": "All matches on a date remain in one split; features use only dates strictly earlier than the decision date.",
        "fractions_by_unique_date": {
            "development": train_fraction,
            "validation": validation_fraction,
            "final_holdout": 1 - train_fraction - validation_fraction,
        },
        "splits": {
            name: {
                "start_date": min(matches[mid].match_date for mid in ids).isoformat(),
                "end_date": max(matches[mid].match_date for mid in ids).isoformat(),
                "unique_dates": len({matches[mid].match_date for mid in ids}),
                "match_count": len(ids),
                "match_ids": ids,
            }
            for name, ids in match_splits.items()
        },
    }


def evaluation_protocol(splits: dict, overs_anomaly_ids: list[str]) -> dict:
    return {
        "status": "BLOCKED_BEFORE_PREDICTIVE_EVALUATION",
        "decision_unit": "Hypothetical bowler selection at the start of a planned over; not evaluated.",
        "primary_target": None,
        "primary_metric": None,
        "target_status": "Not locked: historical outcomes are observed only for bowlers actually used, so the counterfactual outcomes for eligible alternatives are absent.",
        "candidate_eligibility": {
            "status": "unresolved",
            "required_evidence": [
                "Confirmed semantics of match_playing_xi.csv (starting XI versus squad/substitute/replacement roster)",
                "Decision-time player availability",
                "Format-specific quota state and legality of the next over",
            ],
            "prohibited_proxy": "Do not use eventual bowling in the target innings as evidence of earlier eligibility.",
        },
        "historical_cutoff": "history_match_date < evaluation_match_date; exclude every same-day match",
        "split_method": "Chronological split by unique match date, 60% development / 20% validation / 20% final holdout; no random ball-level split.",
        "splits": splits["splits"],
        "format_anomaly_match_ids_excluded_from_future_evaluation": sorted(overs_anomaly_ids),
        "intended_methods": ["current CRIC fixed-weight scorer", "career-only historical baseline", "phase-only historical baseline"],
        "formula_version": {
            "component_weights": {"performance": 0.60, "matchup": 0.30, "situation": 0.10},
            "metric_weights": {
                "performance": {"economy": 0.45, "strike_rate": 0.25, "wicket_rate": 0.30},
                "matchup": {"economy": 0.35, "strike_rate": 0.25, "wicket_rate": 0.40},
                "situation": {"economy": 0.50, "wicket_rate": 0.50},
            },
            "sample_shrinkage": "n_legal_balls / (n_legal_balls + 30)",
            "normalization": "Candidate-relative per metric among candidates with defined prior-only evidence; lower economy/strike-rate is better, higher wicket rate is better.",
        },
        "final_holdout_metrics_computed": False,
        "reason_no_metrics": "The roster does not establish decision-time availability and the observed delivery outcomes do not provide counterfactual outcomes for all candidates.",
        "uncertainty": "No confidence intervals computed because there are no valid matched candidate-outcome scenarios.",
        "random_seed": 20261012,
    }
