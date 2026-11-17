from pathlib import Path
import csv

from evaluation.phase10.decision import fail_closed_evaluation
from evaluation.phase10.protocol import evaluation_feasibility, load_phase9_baseline, phase10_protocol
from evaluation.phase9.historical_features import build_historical_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_phase9_chronological_baseline_has_expected_nonoverlapping_membership():
    baseline = load_phase9_baseline(PROJECT_ROOT / "reports" / "phase9_complete_06")
    assert baseline["formula_check_count"] == 6
    assert baseline["total_unique_split_matches"] == 4223
    assert {
        name: len(ids) for name, ids in baseline["match_ids_by_split"].items()
    } == {"development": 2117, "validation": 1001, "final_holdout": 1105}
    protocol = phase10_protocol(baseline)
    assert protocol["final_holdout_ranking_metrics_computed"] is False
    assert protocol["metrics"] == {}


def test_all_five_designs_have_distinct_feasibility_and_claim_limits():
    rows = evaluation_feasibility()
    assert len(rows) == 5
    assert {row["design"] for row in rows} == {
        "Historical descriptive analysis",
        "Retrospective ranking evaluation",
        "Counterfactual evaluation",
        "Prospective shadow evaluation",
        "Prospective intervention evaluation",
    }
    assert all(row["permitted_claim"] for row in rows)


def test_evaluation_gate_fails_closed_and_never_emits_placeholder_metrics():
    result = fail_closed_evaluation(
        eligible_candidate_universe_supported=False,
        decision_time_features_supported=False,
        labels_observed_for_all_candidates=False,
    )
    assert result["status"] == "BLOCKED"
    assert len(result["blockers"]) == 3
    assert result["metrics"] == {}


def test_historical_features_exclude_same_day_evaluation_and_future_deliveries(tmp_path):
    def write(name, fields, rows):
        path = tmp_path / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    matches = write(
        "matches.csv",
        ["match_id", "date", "competition", "season", "team_1", "team_2", "venue", "match_type", "overs"],
        [
            {"match_id": "prior", "date": "2020-01-01", "competition": "C", "season": "S", "team_1": "A", "team_2": "B", "venue": "V", "match_type": "T20", "overs": "20"},
            {"match_id": "evaluation", "date": "2020-01-02", "competition": "C", "season": "S", "team_1": "A", "team_2": "B", "venue": "V", "match_type": "T20", "overs": "20"},
            {"match_id": "same-day", "date": "2020-01-02", "competition": "C", "season": "S", "team_1": "A", "team_2": "B", "venue": "V", "match_type": "T20", "overs": "20"},
            {"match_id": "future", "date": "2020-01-03", "competition": "C", "season": "S", "team_1": "A", "team_2": "B", "venue": "V", "match_type": "T20", "overs": "20"},
        ],
    )
    delivery_fields = [
        "match_id", "innings_number", "over_number", "ball_in_over", "batter_id", "bowler_id",
        "runs_batter", "extra_wides", "extra_noballs", "runs_extras", "extra_byes",
        "extra_legbyes", "extra_penalty", "is_legal_delivery", "match_phase", "batting_team",
    ]
    deliveries = write(
        "deliveries.csv",
        delivery_fields,
        [
            {"match_id": match_id, "innings_number": "1", "over_number": "0", "ball_in_over": "1",
             "batter_id": "bat", "bowler_id": "b", "runs_batter": str(runs), "extra_wides": "",
             "extra_noballs": "", "runs_extras": "0", "extra_byes": "", "extra_legbyes": "",
             "extra_penalty": "", "is_legal_delivery": "true", "match_phase": "Powerplay", "batting_team": "A"}
            for match_id, runs in [("prior", 1), ("evaluation", 99), ("same-day", 88), ("future", 77)]
        ],
    )
    wickets = write(
        "wicket_events.csv",
        ["match_id", "innings_number", "over_number", "ball_in_over", "player_out_id", "bowler_id", "is_bowler_credited"],
        [],
    )

    snapshot = build_historical_snapshot(matches, deliveries, wickets, "2020-01-02", "evaluation")
    assert snapshot.prior_delivery_rows == 1
    assert snapshot.history_match_ids == frozenset({"prior"})
    assert snapshot.career["b"].runs_conceded == 1
