from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from backend.recommendation_engine import (
    DatasetPaths,
    DatasetError,
    InvalidRequest,
    RecommendationConfig,
    RecommendationEngine,
    UnknownIdentifier,
)


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def fixture_paths(tmp_path: Path) -> DatasetPaths:
    players = _write_csv(
        tmp_path / "players.csv",
        ["player_id", "player_name"],
        [
            {"player_id": "BAT1", "player_name": "Batter One"},
            {"player_id": "BAT2", "player_name": "Batter Two"},
            {"player_id": "A001", "player_name": "Bowler A"},
            {"player_id": "B001", "player_name": "Bowler B"},
            {"player_id": "C001", "player_name": "Bowler C"},
            {"player_id": "D001", "player_name": "Wide Only"},
        ],
    )
    metric_headers = [
        "bowler_id",
        "bowler_name",
        "legal_balls",
        "economy",
        "bowling_strike_rate_balls_per_wicket",
        "wicket_rate_per_100_legal_balls",
    ]
    career = _write_csv(
        tmp_path / "career.csv",
        metric_headers,
        [
            {"bowler_id": "A001", "bowler_name": "Bowler A", "legal_balls": 600, "economy": 4, "bowling_strike_rate_balls_per_wicket": 15, "wicket_rate_per_100_legal_balls": 6.67},
            {"bowler_id": "B001", "bowler_name": "Bowler B", "legal_balls": 300, "economy": 6, "bowling_strike_rate_balls_per_wicket": 20, "wicket_rate_per_100_legal_balls": 5},
            {"bowler_id": "C001", "bowler_name": "Bowler C", "legal_balls": 120, "economy": 8, "bowling_strike_rate_balls_per_wicket": 30, "wicket_rate_per_100_legal_balls": 3.33},
            {"bowler_id": "D001", "bowler_name": "Wide Only", "legal_balls": 0, "economy": 0, "bowling_strike_rate_balls_per_wicket": 0, "wicket_rate_per_100_legal_balls": 0},
        ],
    )
    phase = _write_csv(
        tmp_path / "phase.csv",
        ["bowler_id", "bowler_name", "match_phase", *metric_headers[2:]],
        [
            {"bowler_id": "A001", "bowler_name": "Bowler A", "match_phase": "Death", "legal_balls": 60, "economy": 5, "bowling_strike_rate_balls_per_wicket": 12, "wicket_rate_per_100_legal_balls": 8.33},
            {"bowler_id": "B001", "bowler_name": "Bowler B", "match_phase": "Death", "legal_balls": 30, "economy": 7, "bowling_strike_rate_balls_per_wicket": 30, "wicket_rate_per_100_legal_balls": 3.33},
            {"bowler_id": "C001", "bowler_name": "Bowler C", "match_phase": "Death", "legal_balls": 24, "economy": 9, "bowling_strike_rate_balls_per_wicket": "", "wicket_rate_per_100_legal_balls": 0},
            {"bowler_id": "D001", "bowler_name": "Wide Only", "match_phase": "Death", "legal_balls": 0, "economy": 0, "bowling_strike_rate_balls_per_wicket": 0, "wicket_rate_per_100_legal_balls": 0},
        ],
    )
    matchup = _write_csv(
        tmp_path / "matchup.csv",
        [
            "bowler_id", "batter_id", "balls", "runs_conceded_by_bowler", "wickets",
            "phase_balls_death", "phase_runs_conceded_death", "phase_wickets_death",
        ],
        [
            {"bowler_id": "A001", "batter_id": "BAT1", "balls": 10, "runs_conceded_by_bowler": 8, "wickets": 1, "phase_balls_death": 10, "phase_runs_conceded_death": 8, "phase_wickets_death": 1},
            {"bowler_id": "B001", "batter_id": "BAT1", "balls": 60, "runs_conceded_by_bowler": 70, "wickets": 2, "phase_balls_death": 30, "phase_runs_conceded_death": 40, "phase_wickets_death": 1},
            {"bowler_id": "D001", "batter_id": "BAT1", "balls": 0, "runs_conceded_by_bowler": 0, "wickets": 0, "phase_balls_death": 0, "phase_runs_conceded_death": 0, "phase_wickets_death": 0},
        ],
    )
    situation = _write_csv(
        tmp_path / "situation.csv",
        ["bowler_id", "situation_type", "situation_value", "balls", "runs_conceded", "wickets"],
        [
            {"bowler_id": "A001", "situation_type": "phase", "situation_value": "Death", "balls": 60, "runs_conceded": 50, "wickets": 6},
            {"bowler_id": "B001", "situation_type": "phase", "situation_value": "Death", "balls": 30, "runs_conceded": 45, "wickets": 1},
            {"bowler_id": "D001", "situation_type": "phase", "situation_value": "Death", "balls": 0, "runs_conceded": 0, "wickets": 1},
        ],
    )
    return DatasetPaths(players, career, phase, matchup, situation)


@pytest.fixture
def engine(fixture_paths: DatasetPaths) -> RecommendationEngine:
    return RecommendationEngine(fixture_paths)


def _request(*candidates: dict[str, object], **kwargs: object) -> dict[str, object]:
    return {"batter_id": "BAT1", "candidates": list(candidates), **kwargs}


def test_ranks_lower_economy_and_strike_rate_and_higher_wicket_rate(engine):
    response = engine.recommend(
        _request(
            {"bowler_id": "A001"},
            {"bowler_id": "B001"},
            {"bowler_id": "C001"},
            batter_id="BAT2",
        )
    )
    assert [item["bowler_id"] for item in response["recommendations"]] == ["a001", "b001", "c001"]
    assert response["execution_mode"] == "local_python"
    assert response["model_type"] == "deterministic_interpretable_baseline"
    assert response["recommendations"][0]["score"] > response["recommendations"][1]["score"]


def test_phase_matchup_and_situation_evidence_are_used(engine):
    response = engine.recommend(
        _request(
            {"bowler_id": "A001"},
            {"bowler_id": "B001"},
            phase="death",
            situation={"type": "phase", "value": "DEATH"},
        )
    )
    first = response["recommendations"][0]
    assert response["phase"] == "Death"
    assert response["situation"] == {"type": "phase", "value": "DEATH"}
    assert first["data_availability"]["performance"] == "phase"
    assert first["metrics"]["matchup"]["sample_balls"] == 10
    assert first["metrics"]["matchup"]["sample_assessment"] == "very_small_sample"
    assert first["metrics"]["situation"]["sample_balls"] == 60
    assert "matchup" in first["score_components"]
    assert "situation" in first["score_components"]
    for recommendation in response["recommendations"]:
        components = recommendation["score_components"]
        total_weight = sum(engine.config.component_weights[key] for key in components)
        expected_score = sum(
            value * engine.config.component_weights[key] / total_weight
            for key, value in components.items()
        )
        assert recommendation["score"] == pytest.approx(expected_score, abs=0.02)
        assert len(recommendation["evidence"]) == len(components)
        for source, component_score in components.items():
            effective_weight = engine.config.component_weights[source] / total_weight * 100
            assert (
                f"{source.capitalize()} component score: {component_score:.1f}/100 "
                f"after metric sample adjustment; effective weight {effective_weight:.1f}% "
                "of this candidate's overall score."
                in recommendation["evidence"]
            )


def test_known_batter_without_matchup_gets_explicit_missing_evidence(engine):
    response = engine.recommend(_request({"bowler_id": "A001"}, batter_id="BAT2"))
    recommendation = response["recommendations"][0]
    assert recommendation["data_availability"]["matchup"] == "no_matchup_evidence"
    assert any("No historical matchup evidence" in warning for warning in recommendation["warnings"])
    assert "matchup" not in recommendation["metrics"]
    assert set(recommendation["score_components"]) == {"performance"}
    assert len(recommendation["evidence"]) == 1
    assert recommendation["evidence"][0].startswith("Performance component score:")


def test_missing_phase_record_uses_career_evidence_and_labels_the_fallback(engine):
    del engine.phase[("a001", "death")]
    recommendation = engine.recommend(
        _request({"bowler_id": "A001"}, batter_id="BAT2", phase="Death")
    )["recommendations"][0]
    assert recommendation["data_availability"]["performance"] == "career"
    assert recommendation["metrics"]["performance"]["sample_balls"] == 600
    assert recommendation["metrics"]["performance"]["economy"] == 4
    assert set(recommendation["score_components"]) == {"performance"}


def test_requested_phase_does_not_fall_back_to_all_phase_matchup(fixture_paths):
    config = RecommendationConfig(
        component_weights={"performance": 0.0, "matchup": 1.0, "situation": 0.0}
    )
    recommender = RecommendationEngine(fixture_paths, config)
    matchup = recommender.matchups[("a001", "bat1")]
    assert matchup.balls == 10
    matchup.phase_totals["death"] = (0, 0, 0)

    phase_result = recommender.recommend(
        _request({"bowler_id": "A001"}, phase="Death")
    )["recommendations"][0]
    assert "matchup" not in phase_result["metrics"]
    assert phase_result["data_availability"]["matchup"] == "no_matchup_evidence"
    assert phase_result["score"] is None
    assert any("in the requested phase" in warning for warning in phase_result["warnings"])

    all_phase_result = recommender.recommend(
        _request({"bowler_id": "A001"})
    )["recommendations"][0]
    assert all_phase_result["metrics"]["matchup"]["sample_balls"] == 10
    assert all_phase_result["score"] == 50.0


def test_small_matchup_sample_is_warned_and_does_not_dominate(engine):
    response = engine.recommend(_request({"bowler_id": "A001"}, {"bowler_id": "B001"}))
    a = next(item for item in response["recommendations"] if item["bowler_id"] == "a001")
    assert any("matchup: very_small_sample" in warning for warning in a["warnings"])
    assert a["sample_reliability"] is not None


def test_sample_assessment_matches_configured_warning_boundaries(engine):
    assert engine._sample_assessment(0) == "no_legal_balls"
    assert engine._sample_assessment(11.99) == "very_small_sample"
    assert engine._sample_assessment(12) == "limited_sample"
    assert engine._sample_assessment(29.99) == "limited_sample"
    assert engine._sample_assessment(30) == "broader_sample"


def test_candidate_set_and_exclusion_recalibrate_relative_scores(fixture_paths):
    config = RecommendationConfig(
        component_weights={"performance": 1.0, "matchup": 0.0, "situation": 0.0}
    )
    recommender = RecommendationEngine(fixture_paths, config)
    batter_only = {"batter_id": "BAT2"}
    with_comparison = recommender.recommend(
        _request({"bowler_id": "A001"}, {"bowler_id": "B001"}, **batter_only)
    )
    b_with_a = next(item for item in with_comparison["recommendations"] if item["bowler_id"] == "b001")
    assert b_with_a["score"] == pytest.approx(4.55)
    assert b_with_a["score_scale"] == "0_to_100_candidate_relative"
    assert b_with_a["score_components"]["performance"] == pytest.approx(b_with_a["score"])
    assert (
        "Performance component score: 4.5/100 after metric sample adjustment; "
        "effective weight 100.0% of this candidate's overall score."
        in b_with_a["evidence"]
    )

    with_a_excluded = recommender.recommend(
        _request(
            {"bowler_id": "A001", "overs_remaining": 0},
            {"bowler_id": "B001"},
            **batter_only,
        )
    )
    assert with_a_excluded["excluded"] == [{"bowler_id": "a001", "reason": "no_overs_remaining"}]
    b_alone = with_a_excluded["recommendations"][0]
    assert b_alone["bowler_id"] == "b001"
    assert b_alone["score"] == 50.0
    assert b_alone["metrics"]["performance"]["economy"] == b_with_a["metrics"]["performance"]["economy"]
    assert b_alone["metrics"]["performance"]["sample_balls"] == b_with_a["metrics"]["performance"]["sample_balls"]


def test_equal_scores_have_stable_identifier_tie_breaking(engine):
    shared_values = {"economy": 6.0, "strike_rate": 20.0, "wicket_rate": 5.0}
    engine.career["a001"].values = dict(shared_values)
    engine.career["b001"].values = dict(shared_values)
    engine.career["a001"].balls = engine.career["b001"].balls = 300
    forward = engine.recommend(_request({"bowler_id": "B001"}, {"bowler_id": "A001"}, batter_id="BAT2"))
    reverse = engine.recommend(_request({"bowler_id": "A001"}, {"bowler_id": "B001"}, batter_id="BAT2"))
    assert [item["bowler_id"] for item in forward["recommendations"]] == ["a001", "b001"]
    assert forward == reverse


@pytest.mark.parametrize(
    ("metric", "a_value", "b_value", "expected_best"),
    [
        ("economy", 4.0, 6.0, "a001"),
        ("strike_rate", 15.0, 25.0, "a001"),
        ("wicket_rate", 6.0, 4.0, "a001"),
    ],
)
def test_metric_direction_when_other_metrics_are_equal(
    fixture_paths, metric, a_value, b_value, expected_best
):
    config = RecommendationConfig(
        component_weights={"performance": 1.0, "matchup": 0.0, "situation": 0.0}
    )
    recommender = RecommendationEngine(fixture_paths, config)
    keys = {"economy": "economy", "strike_rate": "strike_rate", "wicket_rate": "wicket_rate"}
    values_a = {"economy": 6.0, "strike_rate": 20.0, "wicket_rate": 5.0}
    values_b = dict(values_a)
    values_a[keys[metric]] = a_value
    values_b[keys[metric]] = b_value
    recommender.career["a001"].values = values_a
    recommender.career["b001"].values = values_b
    recommender.career["a001"].balls = 300
    recommender.career["b001"].balls = 300

    result = recommender.recommend(
        _request({"bowler_id": "A001"}, {"bowler_id": "B001"}, batter_id="BAT2")
    )
    assert result["recommendations"][0]["bowler_id"] == expected_best
    assert set(result["recommendations"][0]["score_components"]) == {"performance"}


def test_small_samples_shrink_candidate_relative_utility_toward_neutral(fixture_paths):
    config = RecommendationConfig(
        component_weights={"performance": 0.0, "matchup": 1.0, "situation": 0.0},
        metric_weights={
            "performance": {"economy": 0.45, "strike_rate": 0.25, "wicket_rate": 0.30},
            "matchup": {"economy": 1.0, "strike_rate": 0.0, "wicket_rate": 0.0},
            "situation": {"economy": 0.50, "wicket_rate": 0.50},
        },
    )
    recommender = RecommendationEngine(fixture_paths, config)
    recommender.matchups[("a001", "bat1")].balls = 2
    recommender.matchups[("a001", "bat1")].values = {
        "economy": 1.0,
        "strike_rate": None,
        "wicket_rate": 1.0,
    }
    recommender.matchups[("b001", "bat1")].balls = 300
    recommender.matchups[("b001", "bat1")].values = {
        "economy": 10.0,
        "strike_rate": None,
        "wicket_rate": 1.0,
    }
    result = recommender.recommend(_request({"bowler_id": "A001"}, {"bowler_id": "B001"}))
    scores = {item["bowler_id"]: item["score"] for item in result["recommendations"]}
    assert scores["a001"] == pytest.approx(53.12)
    assert scores["b001"] == pytest.approx(4.55)


def test_zero_legal_ball_and_null_rate_remain_unavailable(engine):
    response = engine.recommend(_request({"bowler_id": "D001"}, batter_id="BAT2"))
    recommendation = response["recommendations"][0]
    assert recommendation["metrics"]["performance"]["economy"] is None
    assert recommendation["metrics"]["performance"]["bowling_strike_rate_balls_per_wicket"] is None
    assert recommendation["metrics"]["performance"]["wicket_rate_per_100_legal_balls"] is None
    assert recommendation["metrics"]["performance"]["sample_assessment"] == "no_legal_balls"
    assert recommendation["score"] is None
    assert any("score is unavailable" in warning for warning in recommendation["warnings"])

    phase_response = engine.recommend(
        _request(
            {"bowler_id": "D001"},
            batter_id="BAT2",
            phase="Death",
            situation={"type": "phase", "value": "Death"},
        )
    )
    phase_performance = phase_response["recommendations"][0]["metrics"]["performance"]
    assert phase_performance["economy"] is None
    assert phase_performance["bowling_strike_rate_balls_per_wicket"] is None
    assert phase_performance["wicket_rate_per_100_legal_balls"] is None
    assert phase_performance["sample_assessment"] == "no_legal_balls"
    situation_metrics = phase_response["recommendations"][0]["metrics"]["situation"]
    assert situation_metrics["sample_balls"] == 0
    assert situation_metrics["economy"] is None
    assert situation_metrics["bowling_strike_rate_balls_per_wicket"] is None
    assert situation_metrics["wicket_rate_per_100_legal_balls"] is None
    assert RecommendationEngine._derived_values(0, 0, 1) == {
        "economy": None,
        "strike_rate": None,
        "wicket_rate": None,
    }


def test_unknown_situation_is_unavailable_and_not_scored(engine):
    recommendation = engine.recommend(
        _request(
            {"bowler_id": "A001"},
            situation={"type": "unsupported", "value": "not-a-historical-value"},
        )
    )["recommendations"][0]
    assert recommendation["data_availability"]["situation"] == "no_situation_evidence"
    assert "situation" not in recommendation["metrics"]
    assert "situation" not in recommendation["score_components"]
    assert all("Situation component score" not in line for line in recommendation["evidence"])
    assert any(
        "No historical evidence for the requested situation" in warning
        for warning in recommendation["warnings"]
    )


def test_unknown_identifiers_are_rejected(engine):
    with pytest.raises(UnknownIdentifier, match="Unknown batter_id"):
        engine.recommend(_request({"bowler_id": "A001"}, batter_id="NO-SUCH-BATTER"))
    with pytest.raises(UnknownIdentifier, match="Unknown bowler_id"):
        engine.recommend(_request({"bowler_id": "NO-SUCH-BOWLER"}))


def test_ineligible_bowlers_are_excluded_with_reason(engine):
    response = engine.recommend(
        _request(
            {"bowler_id": "A001", "available": False},
            {"bowler_id": "B001", "overs_remaining": 0},
            {"bowler_id": "C001", "overs_bowled": 2, "overs_remaining": 1},
        )
    )
    assert [item["bowler_id"] for item in response["recommendations"]] == ["c001"]
    assert response["excluded"] == [
        {"bowler_id": "a001", "reason": "unavailable"},
        {"bowler_id": "b001", "reason": "no_overs_remaining"},
    ]


def test_empty_and_all_excluded_candidates_return_empty_recommendations(engine):
    assert engine.recommend(_request())["recommendations"] == []
    response = engine.recommend(_request({"bowler_id": "A001", "available": False}))
    assert response["recommendations"] == []
    assert response["excluded"][0]["reason"] == "unavailable"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"batter_id": "BAT1"},
        {"batter_id": "BAT1", "candidates": "A001"},
        {"batter_id": "BAT1", "candidates": [{"bowler_id": "A001", "available": "yes"}]},
        {"batter_id": "BAT1", "candidates": [{"bowler_id": "A001", "overs_remaining": -1}]},
        {"batter_id": "BAT1", "phase": "Not a phase", "candidates": []},
        {"batter_id": "BAT1", "candidates": [{"bowler_id": "A001"}, {"bowler_id": "a001"}]},
        {"batter_id": "BAT1", "candidates": [], "extra": True},
    ],
)
def test_malformed_requests_are_rejected(engine, payload):
    with pytest.raises(InvalidRequest):
        engine.recommend(payload)


@pytest.mark.parametrize(
    "overs_remaining",
    [None, "1", True, float("nan"), float("inf"), -0.1],
)
def test_candidate_overs_must_be_finite_nonnegative_numbers(engine, overs_remaining):
    with pytest.raises(InvalidRequest):
        engine.recommend(
            _request({"bowler_id": "A001", "overs_remaining": overs_remaining})
        )


@pytest.mark.parametrize(
    "context",
    [
        {"over": -1},
        {"innings_number": True},
        {"over": float("nan")},
        {"innings_number": float("inf")},
    ],
)
def test_context_numeric_fields_reject_invalid_values(engine, context):
    with pytest.raises(InvalidRequest):
        engine.recommend(_request({"bowler_id": "A001"}, context=context))


def test_repeated_requests_are_deterministic_and_do_not_mutate_sources(fixture_paths):
    paths = [
        fixture_paths.players,
        fixture_paths.career,
        fixture_paths.phase,
        fixture_paths.matchup,
        fixture_paths.situation,
    ]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    recommender = RecommendationEngine(fixture_paths)
    request = _request({"bowler_id": "B001"}, {"bowler_id": "A001"}, phase="Death")
    assert recommender.recommend(request) == recommender.recommend(request)
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert before == after


def test_configurable_weights_are_validated():
    config = RecommendationConfig(
        component_weights={"performance": 0.8, "matchup": 0.2, "situation": 0.0}
    )
    assert config.component_weights["performance"] == 0.8
    with pytest.raises(ValueError, match="positive"):
        RecommendationConfig(
            component_weights={"performance": 0.0, "matchup": 0.0, "situation": 0.0}
        )


def test_duplicate_player_identifier_is_rejected(fixture_paths):
    with fixture_paths.players.open("a", encoding="utf-8", newline="") as output:
        output.write("BAT1,Duplicate Batter\n")
    with pytest.raises(DatasetError, match="duplicate player ID"):
        RecommendationEngine(fixture_paths)


def test_dataset_discovery_loads_actual_project_sources():
    root = Path("C:/CRIC/data")
    actual = DatasetPaths.discover(root)
    assert actual.players.name == "players.csv"
    assert RecommendationEngine(actual).ready


def test_relative_data_root_resolves_from_project_working_directory():
    paths = DatasetPaths.discover(Path("data"))
    assert RecommendationEngine(paths).ready
    assert all(not path.is_absolute() for path in vars(paths).values())


def test_verified_delivery_and_wicket_baselines_remain_distinct():
    data_root = Path("C:/CRIC/data")
    delivery_path = next(data_root.rglob("deliveries.csv"))
    wicket_path = next(data_root.rglob("wicket_events.csv"))
    delivery_rows = legal_balls = wicket_rows = credited_wickets = 0
    with delivery_path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            delivery_rows += 1
            legal_balls += row["is_legal_delivery"].strip().casefold() == "true"
    with wicket_path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            wicket_rows += 1
            credited_wickets += row["is_bowler_credited"].strip().casefold() == "true"
    assert delivery_rows == 966_985
    assert legal_balls == 925_882
    assert wicket_rows == 53_294
    assert credited_wickets == 48_983
