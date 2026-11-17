from __future__ import annotations

from datetime import date

import pytest

from evaluation.phase9.historical_features import BowlingStats, FeatureSnapshot, MatchInfo, assert_split_isolation
from evaluation.phase9.protocol import chronological_splits
from evaluation.phase9.scoring import score_candidate_set


def _stats(balls: int, runs: float, wickets: int = 0) -> BowlingStats:
    return BowlingStats(delivery_rows=balls, legal_balls=balls, runs_conceded=runs, credited_wickets=wickets)


def _snapshot() -> FeatureSnapshot:
    return FeatureSnapshot(
        cutoff_date=date(2021, 1, 1),
        evaluation_match_id=None,
        history_match_ids=frozenset(),
        history_match_dates={},
        excluded_match_ids=frozenset(),
        prior_delivery_rows=0,
        prior_legal_deliveries=0,
        prior_credited_wickets=0,
        career={"a": _stats(30, 20), "b": _stats(30, 40)},
        phase={("a", "death"): _stats(30, 20)},
        matchup={("a", "bat"): _stats(12, 9, 1)},
        phase_matchup={("a", "bat", "death"): _stats(6, 3, 1)},
        situation={("a", "phase", "death"): _stats(12, 9, 1)},
    )


def test_candidate_relative_normalization_and_sample_shrinkage():
    rows = score_candidate_set(_snapshot(), ["a", "b"], "bat", None, mode="career_only")
    assert [row["bowler_id"] for row in rows] == ["a", "b"]
    assert rows[0]["score"] == 65.0
    assert rows[1]["score"] == 35.0


def test_unrounded_scores_determine_rank_before_display_rounding():
    snapshot = _snapshot()
    balls = 100000
    snapshot.career = {
        "a": _stats(balls, 4.00001 * balls / 6),
        "m": _stats(balls, 6 * balls / 6),
        "z": _stats(balls, 4.0 * balls / 6),
    }
    rows = score_candidate_set(snapshot, ["a", "m", "z"], "bat", None, mode="career_only")
    ordered = {row["bowler_id"]: row for row in rows}
    assert ordered["a"]["score"] == ordered["z"]["score"]
    assert rows[0]["bowler_id"] == "z"


def test_equal_evidence_scores_are_neutral_and_ties_are_stable():
    snapshot = _snapshot()
    snapshot.career["b"] = _stats(30, 20)
    rows = score_candidate_set(snapshot, ["b", "a"], "bat", None, mode="career_only")
    assert [row["bowler_id"] for row in rows] == ["a", "b"]
    assert [row["score"] for row in rows] == [50.0, 50.0]


def test_full_mode_phase_specific_matchup_has_no_all_phase_fallback():
    rows = score_candidate_set(_snapshot(), ["a", "b"], "bat", "Death", mode="cric")
    by_id = {row["bowler_id"]: row for row in rows}
    assert by_id["a"]["sample_balls"]["matchup"] == 6
    assert "matchup" not in by_id["b"]["sample_balls"]


def test_career_only_and_phase_only_use_distinct_historical_features():
    snapshot = _snapshot()
    career = score_candidate_set(snapshot, ["a", "b"], "bat", "Death", mode="career_only")
    phase = score_candidate_set(snapshot, ["a", "b"], "bat", "Death", mode="phase_only")
    assert all("performance" in row["sample_balls"] for row in career)
    assert phase[0]["bowler_id"] == "a"
    assert phase[1]["score"] is None


def test_missing_components_renormalize_to_available_performance():
    rows = score_candidate_set(_snapshot(), ["a", "b"], "other", None, mode="cric")
    by_id = {row["bowler_id"]: row for row in rows}
    assert by_id["a"]["effective_weights"] == {"performance": 1.0}


def test_empty_candidate_set_returns_no_recommendations():
    assert score_candidate_set(_snapshot(), [], "bat", None) == []


def test_duplicate_candidate_ids_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        score_candidate_set(_snapshot(), ["a", "A"], "bat", None)


def test_candidate_limit_matches_production_limit():
    with pytest.raises(ValueError, match="30"):
        score_candidate_set(_snapshot(), [f"b{i}" for i in range(31)], "bat", None)


def test_chronological_split_groups_same_date_and_is_reproducible():
    matches = {
        f"m{i}": MatchInfo(date(2020, 1, i), "T20I", "2020", "A", "B", "V", "T20", 20)
        for i in range(1, 11)
    }
    matches["same-day-extra"] = MatchInfo(date(2020, 1, 2), "IPL", "2020", "C", "D", "W", "T20", 20)
    first = chronological_splits(matches)
    second = chronological_splits(matches)
    assert first == second
    assert first["splits"]["development"]["match_ids"].count("same-day-extra") == 1
    dev_dates = {matches[mid].match_date for mid in first["splits"]["development"]["match_ids"]}
    val_dates = {matches[mid].match_date for mid in first["splits"]["validation"]["match_ids"]}
    assert not dev_dates & val_dates
    assert max(dev_dates) < min(val_dates)


def test_split_isolation_rejects_same_date_across_splits():
    dates = {"dev": date(2020, 1, 1), "val": date(2020, 1, 1), "test": date(2020, 1, 2)}
    with pytest.raises(ValueError, match="strictly date ordered"):
        assert_split_isolation(["dev"], ["val"], ["test"], dates)
