from datetime import date

import pytest

from evaluation.phase9.candidate_eligibility import (
    assess_candidate,
    format_metadata_is_consistent,
)
from evaluation.phase9.historical_features import MatchInfo
from evaluation.phase9.metrics import (
    match_level_bootstrap_mean,
    mean_reciprocal_rank,
    paired_scenario_differences,
)
from evaluation.phase9.protocol import chronological_splits, evaluation_protocol


def test_candidate_is_admitted_only_with_authoritative_decision_state():
    common = {
        "match_exists": True,
        "team_matches_fixture": True,
        "player_exists": True,
        "declared_bowler": True,
        "duplicate_match_player": False,
        "available_at_decision": True,
        "legal_overs_remaining": 2,
        "roster_semantics_verified": True,
        "quota_rules_verified": True,
    }
    assert assess_candidate(**common).eligible
    assert not assess_candidate(**{**common, "available_at_decision": None}).eligible
    assert not assess_candidate(**{**common, "legal_overs_remaining": None}).eligible


def test_roster_duplicates_missing_ids_and_team_join_fail_closed():
    common = {
        "match_exists": True,
        "team_matches_fixture": True,
        "player_exists": True,
        "declared_bowler": True,
        "duplicate_match_player": False,
        "available_at_decision": True,
        "legal_overs_remaining": 2,
        "roster_semantics_verified": True,
        "quota_rules_verified": True,
    }
    duplicate = assess_candidate(**{**common, "duplicate_match_player": True})
    unknown_player = assess_candidate(**{**common, "player_exists": False})
    invalid_team = assess_candidate(**{**common, "team_matches_fixture": False})
    assert not duplicate.eligible and "duplicate_or_conflicting_roster_identity" in duplicate.reasons
    assert not unknown_player.eligible and "unknown_player" in unknown_player.reasons
    assert not invalid_team.eligible and "team_mismatch" in invalid_team.reasons


def test_unknown_bowling_role_and_zero_quota_are_excluded():
    base = {
        "match_exists": True,
        "team_matches_fixture": True,
        "player_exists": True,
        "declared_bowler": None,
        "duplicate_match_player": False,
        "available_at_decision": True,
        "legal_overs_remaining": 0,
        "roster_semantics_verified": True,
        "quota_rules_verified": True,
    }
    decision = assess_candidate(**base)
    assert not decision.eligible
    assert "bowling_role_unknown" in decision.reasons
    assert "no_legal_overs_remaining" in decision.reasons


def test_format_metadata_anomalies_are_explicit():
    assert format_metadata_is_consistent("T20", 20)
    assert format_metadata_is_consistent("ODI", 50)
    assert not format_metadata_is_consistent("T20", 50)
    assert not format_metadata_is_consistent("T20I", 50)


def test_ranking_metric_denominators_and_empty_target_behavior():
    assert mean_reciprocal_rank(["b", "a"], {"a"}) == 0.5
    assert mean_reciprocal_rank(["b", "a"], {"missing"}) == 0
    assert mean_reciprocal_rank([], set()) is None


def test_method_comparison_uses_only_matched_scenarios():
    differences = paired_scenario_differences(
        {"s1": 0.4, "s2": 0.7, "s3": 0.5},
        {"s1": 0.5, "s2": 0.6, "different": 0.99},
    )
    assert differences["s1"] == pytest.approx(0.1)
    assert differences["s2"] == pytest.approx(-0.1)
    assert set(differences) == {"s1", "s2"}


def test_match_level_bootstrap_is_reproducible_and_match_clustered():
    values = {"m1": 0.2, "m2": 0.8, "m3": 0.4}
    first = match_level_bootstrap_mean(values, repetitions=500, seed=17)
    second = match_level_bootstrap_mean(values, repetitions=500, seed=17)
    assert first == second
    assert first["matches"] == 3
    assert first["repetitions"] == 500
    assert first["ci_low"] <= first["estimate"] <= first["ci_high"]


def test_split_excludes_format_anomaly_ids_before_assignment():
    matches = {
        f"m{index}": MatchInfo(date(2020, 1, index), "T20I", "2020", "A", "B", "V", "T20", 20)
        for index in range(1, 11)
    }
    matches["anomaly"] = MatchInfo(date(2020, 1, 5), "T20I", "2020", "A", "B", "V", "T20", 50)
    splits = chronological_splits(matches, excluded_match_ids={"anomaly"})
    all_ids = {
        match_id
        for split in splits["splits"].values()
        for match_id in split["match_ids"]
    }
    assert "anomaly" not in all_ids
    assert len(all_ids) == 10


def test_protocol_does_not_compute_or_tune_final_holdout_metrics():
    matches = {
        f"m{index}": MatchInfo(date(2020, 1, index), "T20I", "2020", "A", "B", "V", "T20", 20)
        for index in range(1, 11)
    }
    splits = chronological_splits(matches)
    protocol = evaluation_protocol(splits, [])
    assert protocol["final_holdout_metrics_computed"] is False
    assert protocol["primary_metric"] is None
    assert protocol["status"] == "BLOCKED_BEFORE_PREDICTIVE_EVALUATION"
