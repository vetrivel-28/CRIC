from __future__ import annotations

import json
from pathlib import Path


def load_phase9_baseline(report_dir: Path) -> dict:
    required = (
        "CRIC_Phase9_Reproducibility.json",
        "CRIC_Phase9_Chronological_Splits.json",
        "CRIC_Phase9_Evaluation_Protocol.json",
        "CRIC_Phase9_Summary.txt",
        "CRIC_Phase9_Historical_Evaluation_Report.pdf",
        "CRIC_Phase9_Candidate_Eligibility.csv",
        "CRIC_Phase9_Feature_Provenance.csv",
        "CRIC_Phase9_Findings.csv",
        "CRIC_Phase9_Formula_Validation.csv",
    )
    missing = [name for name in required if not (report_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing Phase 9 baseline artifacts: {', '.join(missing)}")
    reproducibility = json.loads(
        (report_dir / "CRIC_Phase9_Reproducibility.json").read_text(encoding="utf-8")
    )
    splits = json.loads(
        (report_dir / "CRIC_Phase9_Chronological_Splits.json").read_text(encoding="utf-8")
    )
    ids_by_split = {
        name: part["match_ids"]
        for name, part in splits["splits"].items()
    }
    memberships = [set(ids) for ids in ids_by_split.values()]
    if any(memberships[i] & memberships[j] for i in range(len(memberships)) for j in range(i + 1, len(memberships))):
        raise ValueError("Phase 9 chronological split match IDs overlap")
    if len(set().union(*memberships)) != 4223:
        raise ValueError("Phase 9 split membership differs from the established 4,223-match baseline")
    expected = {"development": 2117, "validation": 1001, "final_holdout": 1105}
    observed = {name: len(ids) for name, ids in ids_by_split.items()}
    if observed != expected:
        raise ValueError(f"Phase 9 split sizes differ from baseline: {observed}")
    formula_rows = _csv_rows(report_dir / "CRIC_Phase9_Formula_Validation.csv")
    if len(formula_rows) != 6 or any(row.get("status") != "PASS" for row in formula_rows):
        raise ValueError("Phase 9 formula-validation baseline is not six of six passing")
    return {
        "reproducibility": reproducibility,
        "splits": splits,
        "formula_check_count": len(formula_rows),
        "match_ids_by_split": ids_by_split,
        "total_unique_split_matches": 4223,
    }


def _csv_rows(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def evaluation_feasibility() -> list[dict]:
    return [
        {
            "design": "Historical descriptive analysis",
            "current_status": "FEASIBLE_WITH_LIMITS",
            "supported_question": "What happened to the bowler actually used, over the observed deliveries?",
            "evidence": "Raw deliveries, innings, matches, and wicket events have joinable match/innings/delivery keys; legal-ball and charged-run fields are present.",
            "limitation": "Describes selected historical usage only; usage selection is non-random and does not represent unused candidates.",
            "permitted_claim": "Descriptive historical summaries only; no future-prediction or causal claim.",
        },
        {
            "design": "Retrospective ranking evaluation",
            "current_status": "BLOCKED",
            "supported_question": "Could CRIC rank the historical eligible alternatives at a recorded decision point?",
            "evidence": "No documented decision-time candidate list, availability, quota state, or past recommendation record.",
            "limitation": "Playing-XI semantics and outcome labels for unused alternatives are unsupported.",
            "permitted_claim": "None for ranking quality until candidate and label evidence is supplied.",
        },
        {
            "design": "Counterfactual evaluation",
            "current_status": "BLOCKED",
            "supported_question": "What would have happened if a different bowler had been selected?",
            "evidence": "Observed outcomes belong to actual delivery bowlers; no alternative-bowler outcomes or randomization/causal design.",
            "limitation": "Unobserved potential outcomes cannot be set to zero or inferred from the unused-player record.",
            "permitted_claim": "No counterfactual or causal claim.",
        },
        {
            "design": "Prospective shadow evaluation",
            "current_status": "FEASIBLE_AFTER_INSTRUMENTATION",
            "supported_question": "What recommendations would CRIC make on future decision snapshots without influencing selection?",
            "evidence": "Local loopback recommender exists, but no immutable event log of decision state, candidates, recommendation, and actual selection was found.",
            "limitation": "Shadow logging alone observes outcomes only for the selected bowler; ranking relevance needs a predeclared target and complete candidate snapshots.",
            "permitted_claim": "Prospective reliability/coverage and descriptive association, not recommendation effect.",
        },
        {
            "design": "Prospective intervention evaluation",
            "current_status": "NOT_READY",
            "supported_question": "Does using CRIC recommendations change outcomes?",
            "evidence": "No approved intervention, allocation protocol, governance, safety monitoring, or causal analysis plan.",
            "limitation": "Requires prospective design and operational oversight; observational outcome differences do not establish benefit.",
            "permitted_claim": "Only after a preregistered controlled design and governance review.",
        },
    ]


def phase10_protocol(baseline: dict) -> dict:
    return {
        "primary_status": "B — LIMITED DESCRIPTIVE EVALUATION ONLY",
        "historical_ranking_evaluation": "BLOCKED",
        "counterfactual_evaluation": "BLOCKED",
        "descriptive_analysis": "Permitted for outcomes actually observed for the historical bowler; do not treat them as labels for alternatives.",
        "final_holdout_ranking_metrics_computed": False,
        "metrics": {},
        "phase9_baseline": {
            "split_sizes": {
                name: len(ids)
                for name, ids in baseline["match_ids_by_split"].items()
            },
            "unique_matches": baseline["total_unique_split_matches"],
            "formula_checks": baseline["formula_check_count"],
            "phase9_tests": baseline["reproducibility"]["test_outcomes"]["dedicated_phase9"],
            "regression_tests": baseline["reproducibility"]["test_outcomes"]["final_full_suite"],
            "excluded_format_anomalies": baseline["reproducibility"]["evaluation_settings"]["excluded_match_ids"],
        },
        "split_policy": baseline["splits"]["date_policy"],
        "decision_time_rule": "Pre-decision features must use only records available before the decision; same-match prior deliveries require a timestamp/order and must not include the current or future delivery.",
        "candidate_rule": "Eligibility is unknown unless independently evidenced for team membership, decision-time availability, and permission to bowl; role is an additional required concept only where the target protocol requires it.",
        "outcome_rule": "A complete observed over may be summarized for its actual bowler only; incomplete horizons are unavailable, and unused candidates have no outcome labels.",
        "holdout_policy": "Do not compute final-holdout ranking metrics until candidate universe, decision time, target, and metrics are specified and frozen.",
        "causal_policy": "No causal benefit claims from retrospective or shadow observational comparisons.",
    }
