from __future__ import annotations

import csv
from pathlib import Path

import pytest

from evaluation.phase9.historical_features import (
    EvaluationDataError,
    build_historical_snapshot,
)


def _write(path: Path, headers: list[str], rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def source_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    matches = _write(
        tmp_path / "matches.csv",
        ["match_id", "date", "competition", "season", "team_1", "team_2", "venue", "match_type", "overs"],
        [
            {"match_id": "prior", "date": "2020-01-01", "competition": "T20I", "season": "2020", "team_1": "A", "team_2": "B", "venue": "V", "match_type": "T20", "overs": 20},
            {"match_id": "same-day", "date": "2020-01-02", "competition": "T20I", "season": "2020", "team_1": "A", "team_2": "C", "venue": "V", "match_type": "T20", "overs": 20},
            {"match_id": "evaluation", "date": "2020-01-02", "competition": "T20I", "season": "2020", "team_1": "A", "team_2": "D", "venue": "V", "match_type": "T20", "overs": 20},
            {"match_id": "future", "date": "2020-01-03", "competition": "IPL", "season": "2020", "team_1": "E", "team_2": "F", "venue": "W", "match_type": "T20", "overs": 20},
        ],
    )
    delivery_headers = [
        "match_id", "innings_number", "over_number", "ball_in_over", "batter_id",
        "bowler_id", "runs_batter", "runs_extras", "extra_wides", "extra_noballs",
        "extra_byes", "extra_legbyes", "extra_penalty",
        "is_legal_delivery", "match_phase", "batting_team",
    ]
    deliveries = _write(
        tmp_path / "deliveries.csv",
        delivery_headers,
        [
            {"match_id": "prior", "innings_number": "1", "over_number": "0", "ball_in_over": "1", "batter_id": "bat", "bowler_id": "bow", "runs_batter": "4", "runs_extras": "0", "extra_wides": "", "extra_noballs": "", "extra_byes": "", "extra_legbyes": "", "extra_penalty": "", "is_legal_delivery": "TRUE", "match_phase": "Powerplay", "batting_team": "A"},
            {"match_id": "prior", "innings_number": "1", "over_number": "0", "ball_in_over": "2", "batter_id": "bat", "bowler_id": "bow", "runs_batter": "0", "runs_extras": "1", "extra_wides": "1", "extra_noballs": "", "extra_byes": "", "extra_legbyes": "", "extra_penalty": "", "is_legal_delivery": "false", "match_phase": "Powerplay", "batting_team": "A"},
            {"match_id": "prior", "innings_number": "1", "over_number": "1", "ball_in_over": "1", "batter_id": "bat", "bowler_id": "bow", "runs_batter": "1", "runs_extras": "1", "extra_wides": "", "extra_noballs": "1", "extra_byes": "", "extra_legbyes": "", "extra_penalty": "", "is_legal_delivery": "False", "match_phase": "Middle", "batting_team": "A"},
            {"match_id": "prior", "innings_number": "1", "over_number": "1", "ball_in_over": "1", "batter_id": "other", "bowler_id": "wideonly", "runs_batter": "0", "runs_extras": "1", "extra_wides": "1", "extra_noballs": "", "extra_byes": "", "extra_legbyes": "", "extra_penalty": "", "is_legal_delivery": "False", "match_phase": "Middle", "batting_team": "A"},
            {"match_id": "same-day", "innings_number": "1", "over_number": "0", "ball_in_over": "1", "batter_id": "bat", "bowler_id": "bow", "runs_batter": "6", "runs_extras": "0", "extra_wides": "", "extra_noballs": "", "extra_byes": "", "extra_legbyes": "", "extra_penalty": "", "is_legal_delivery": "true", "match_phase": "Powerplay", "batting_team": "A"},
            {"match_id": "evaluation", "innings_number": "1", "over_number": "0", "ball_in_over": "1", "batter_id": "bat", "bowler_id": "bow", "runs_batter": "6", "runs_extras": "0", "extra_wides": "", "extra_noballs": "", "extra_byes": "", "extra_legbyes": "", "extra_penalty": "", "is_legal_delivery": "true", "match_phase": "Powerplay", "batting_team": "A"},
            {"match_id": "future", "innings_number": "1", "over_number": "0", "ball_in_over": "1", "batter_id": "bat", "bowler_id": "bow", "runs_batter": "6", "runs_extras": "0", "extra_wides": "", "extra_noballs": "", "extra_byes": "", "extra_legbyes": "", "extra_penalty": "", "is_legal_delivery": "true", "match_phase": "Powerplay", "batting_team": "E"},
        ],
    )
    wickets = _write(
        tmp_path / "wicket_events.csv",
        [
            "wicket_event_id", "match_id", "innings_number", "over_number",
            "ball_in_over", "player_out_id", "bowler_id", "is_bowler_credited",
        ],
        [
            {"wicket_event_id": "w1", "match_id": "prior", "innings_number": "1", "over_number": "0", "ball_in_over": "1", "player_out_id": "bat", "bowler_id": "bow", "is_bowler_credited": "TRUE"},
            {"wicket_event_id": "w2", "match_id": "prior", "innings_number": "1", "over_number": "0", "ball_in_over": "1", "player_out_id": "other", "bowler_id": "bow", "is_bowler_credited": "false"},
            {"wicket_event_id": "w3", "match_id": "prior", "innings_number": "1", "over_number": "0", "ball_in_over": "1", "player_out_id": "other2", "bowler_id": "bow", "is_bowler_credited": "True"},
            {"wicket_event_id": "w4", "match_id": "same-day", "innings_number": "1", "over_number": "0", "ball_in_over": "1", "player_out_id": "bat", "bowler_id": "bow", "is_bowler_credited": "True"},
        ],
    )
    return matches, deliveries, wickets


def test_cutoff_excludes_evaluation_same_day_and_future(source_paths):
    matches, deliveries, wickets = source_paths
    snapshot = build_historical_snapshot(
        matches, deliveries, wickets, "2020-01-02", "evaluation"
    )
    assert snapshot.history_match_ids == {"prior"}
    assert snapshot.prior_match_count == 1
    assert snapshot.prior_delivery_rows == 4
    assert snapshot.prior_legal_deliveries == 1
    assert snapshot.career["bow"].runs_conceded == 7
    snapshot.assert_leakage_free()


def test_bowler_runs_include_wides_and_ignore_nonbowler_charged_runs(source_paths):
    snapshot = build_historical_snapshot(*source_paths, "2020-01-02", "evaluation")
    stats = snapshot.career["bow"]
    assert stats.runs_conceded == 7
    assert stats.legal_balls == 1
    assert stats.metrics()["economy"] == 42


def test_multiple_events_preserve_credited_and_uncredited_dismissals(source_paths):
    snapshot = build_historical_snapshot(*source_paths, "2020-01-02", "evaluation")
    assert snapshot.career["bow"].credited_wickets == 2
    assert snapshot.prior_credited_wickets == 2
    assert snapshot.matchup[("bow", "bat")].credited_wickets == 1
    assert snapshot.matchup[("bow", "other2")].credited_wickets == 1
    assert ("bow", "other") not in snapshot.matchup


def test_phase_matchup_and_situation_are_built_from_prior_rows(source_paths):
    snapshot = build_historical_snapshot(*source_paths, "2020-01-02", "evaluation")
    assert snapshot.phase[("bow", "Powerplay")].legal_balls == 1
    assert snapshot.phase_matchup[("bow", "bat", "powerplay")].legal_balls == 1
    assert snapshot.situation[("bow", "competition", "t20i")].legal_balls == 1
    assert snapshot.situation[("bow", "exact_over", "0")].legal_balls == 1


def test_zero_legal_ball_rates_remain_unavailable(source_paths):
    snapshot = build_historical_snapshot(*source_paths, "2020-01-02", "evaluation")
    stats = snapshot.career["wideonly"]
    assert stats.legal_balls == 0
    assert stats.runs_conceded == 1
    assert stats.metrics() == {
        "economy": None,
        "strike_rate": None,
        "wicket_rate_per_100_legal_balls": None,
    }


def test_explicitly_excluded_match_is_not_added_to_history(source_paths):
    snapshot = build_historical_snapshot(
        *source_paths,
        "2020-01-02",
        "evaluation",
        excluded_match_ids={"prior"},
    )
    assert snapshot.prior_match_count == 0
    assert snapshot.prior_delivery_rows == 0


def test_aggregate_file_cannot_be_passed_as_delivery_source(source_paths, tmp_path):
    matches, _, wickets = source_paths
    aggregate = _write(
        tmp_path / "career_aggregate.csv",
        ["bowler_id", "legal_balls", "economy"],
        [{"bowler_id": "bow", "legal_balls": "100", "economy": "1"}],
    )
    with pytest.raises(EvaluationDataError, match="missing columns"):
        build_historical_snapshot(matches, aggregate, wickets, "2020-01-02", "evaluation")


def test_wicket_event_with_unknown_match_is_rejected(source_paths, tmp_path):
    matches, deliveries, _ = source_paths
    wickets = _write(
        tmp_path / "orphan.csv",
        ["match_id", "innings_number", "over_number", "ball_in_over", "player_out_id", "bowler_id", "is_bowler_credited"],
        [{"match_id": "missing", "innings_number": "1", "over_number": "0", "ball_in_over": "1", "player_out_id": "x", "bowler_id": "bow", "is_bowler_credited": "True"}],
    )
    with pytest.raises(EvaluationDataError, match="unknown match_id"):
        build_historical_snapshot(matches, deliveries, wickets, "2020-01-02", "evaluation")

def test_evaluation_match_must_match_cutoff_date(source_paths):
    with pytest.raises(EvaluationDataError, match="on the cutoff date"):
        build_historical_snapshot(*source_paths, "2020-01-03", "evaluation")


def test_event_bowler_mismatch_is_rejected(source_paths, tmp_path):
    matches, deliveries, _ = source_paths
    wickets = _write(
        tmp_path / "mismatch.csv",
        ["match_id", "innings_number", "over_number", "ball_in_over", "player_out_id", "bowler_id", "is_bowler_credited"],
        [{"match_id": "prior", "innings_number": "1", "over_number": "0", "ball_in_over": "1", "player_out_id": "bat", "bowler_id": "wrong", "is_bowler_credited": "True"}],
    )
    with pytest.raises(EvaluationDataError, match="does not match"):
        build_historical_snapshot(matches, deliveries, wickets, "2020-01-02", "evaluation")


def test_wicket_event_without_a_delivery_key_is_rejected(source_paths, tmp_path):
    matches, deliveries, _ = source_paths
    wickets = _write(
        tmp_path / "unjoined.csv",
        ["match_id", "innings_number", "over_number", "ball_in_over", "player_out_id", "bowler_id", "is_bowler_credited"],
        [{"match_id": "prior", "innings_number": "9", "over_number": "9", "ball_in_over": "9", "player_out_id": "x", "bowler_id": "bow", "is_bowler_credited": "False"}],
    )
    with pytest.raises(EvaluationDataError, match="no delivery"):
        build_historical_snapshot(matches, deliveries, wickets, "2020-01-02", "evaluation")


def test_inconsistent_extra_components_are_rejected(source_paths, tmp_path):
    matches, deliveries, wickets = source_paths
    rows = list(csv.DictReader(deliveries.open(encoding="utf-8-sig", newline="")))
    rows[1]["runs_extras"] = "2"
    bad_deliveries = _write(deliveries, list(rows[0]), rows)
    with pytest.raises(EvaluationDataError, match="runs_extras"):
        build_historical_snapshot(matches, bad_deliveries, wickets, "2020-01-02", "evaluation")
