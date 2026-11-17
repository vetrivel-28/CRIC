from __future__ import annotations

import pytest

from evaluation.phase11.collection import record_actual_selection, record_correction, record_observation
from evaluation.phase11.event_store import EventStore
from evaluation.phase11.outcomes import derived_rates, finalize_fixed_horizon
from evaluation.phase11.schema import EventValidationError
from evaluation.phase11.shadow import run_shadow_decision

T0 = "2026-10-12T10:00:00Z"
T1 = "2026-10-12T10:02:00Z"
HORIZON = {
    "match_id": "M-1", "innings_number": 1, "over_number": 18,
    "expected_legal_deliveries": 2, "definition_version": "one-over-v1",
}


def _start(engine, tmp_path, *, select=True):
    store = EventStore(tmp_path)
    run_shadow_decision(
        engine=engine, store=store, decision_id="outcome-1",
        request={"batter_id": "bat1", "candidates": [{"bowler_id": "b1"}]},
        outcome_horizon=HORIZON, event_time_utc=T0,
        mode="synthetic_test",
    )
    if select:
        record_actual_selection(
            store=store, decision_id="outcome-1", selected_bowler_id="b1",
            selection_source="manual_entry", observed=True, selection_time_utc="2026-10-12T10:01:00Z",
        )
    return store


def _delivery(ball, *, legal=True, batter=0, wides=0, noballs=0, byes=0, legbyes=0, bowler="b1", source=None):
    return {
        "match_id": "M-1", "innings_number": 1, "over_number": 18, "ball_in_over": ball,
        "bowler_id": bowler, "runs_batter": batter, "extra_wides": wides,
        "extra_noballs": noballs, "extra_byes": byes, "extra_legbyes": legbyes,
        "is_legal_delivery": legal, "source_record_id": source or f"delivery-{ball}",
    }


def _wicket(*, ball=2, credited=True, bowler="b1", source="wicket-1"):
    return {
        "match_id": "M-1", "innings_number": 1, "over_number": 18, "ball_in_over": ball,
        "bowler_id": bowler, "is_bowler_credited": credited, "dismissal_kind": "bowled",
        "source_record_id": source,
    }


def test_complete_horizon_charges_correct_runs_and_only_credited_wickets(engine, tmp_path):
    store = _start(engine, tmp_path)
    record_observation(store=store, decision_id="outcome-1", event_type="observed_delivery",
                       payload=_delivery(1, legal=False, batter=4, wides=2, byes=7), event_time_utc=T1)
    record_observation(store=store, decision_id="outcome-1", event_type="observed_delivery",
                       payload=_delivery(2, legal=True, noballs=1, legbyes=5), event_time_utc=T1)
    record_observation(store=store, decision_id="outcome-1", event_type="observed_delivery",
                       payload=_delivery(3, legal=True), event_time_utc=T1)
    record_observation(store=store, decision_id="outcome-1", event_type="observed_wicket",
                       payload=_wicket(credited=True), event_time_utc=T1)
    record_observation(store=store, decision_id="outcome-1", event_type="observed_wicket",
                       payload=_wicket(credited=False, source="wicket-2"), event_time_utc=T1)
    result = finalize_fixed_horizon(
        store=store, decision_id="outcome-1", observation_complete=True, coverage_source="scorer-feed-v1",
    )
    outcome = result["event"]["payload"]
    assert outcome["status"] == "complete"
    assert outcome["metrics"]["charged_runs"] == 7
    assert outcome["metrics"]["legal_deliveries"] == 2
    assert outcome["metrics"]["bowler_credited_wickets"] == 1
    assert outcome["metrics"]["rates"]["economy"] == 21


def test_bowler_identifiers_are_casefolded_consistently_for_outcome_linkage(engine, tmp_path):
    store = _start(engine, tmp_path)
    record_observation(
        store=store, decision_id="outcome-1", event_type="observed_delivery",
        payload=_delivery(1, legal=True, bowler="B1"), event_time_utc=T1,
    )
    record_observation(
        store=store, decision_id="outcome-1", event_type="observed_delivery",
        payload=_delivery(2, legal=True, bowler="B1"), event_time_utc=T1,
    )
    record_observation(
        store=store, decision_id="outcome-1", event_type="observed_wicket",
        payload=_wicket(ball=2, bowler="b1"), event_time_utc=T1,
    )

    result = finalize_fixed_horizon(
        store=store, decision_id="outcome-1", observation_complete=True,
        coverage_source="synthetic-source",
    )

    assert result["status"] == "complete"
    assert result["event"]["payload"]["actual_bowler_id"] == "b1"
    assert result["event"]["payload"]["metrics"]["bowler_credited_wickets"] == 1


def test_incomplete_horizon_and_unselected_bowler_never_become_zero(engine, tmp_path):
    store = _start(engine, tmp_path)
    record_observation(store=store, decision_id="outcome-1", event_type="observed_delivery",
                       payload=_delivery(1, legal=True), event_time_utc=T1)
    incomplete = finalize_fixed_horizon(
        store=store, decision_id="outcome-1", observation_complete=True, coverage_source="scorecard",
    )
    assert incomplete["status"] == "incomplete"
    assert incomplete["event"]["payload"]["metrics"]["charged_runs"] is None

    other = _start(engine, tmp_path / "unselected", select=False)
    unavailable = finalize_fixed_horizon(
        store=other, decision_id="outcome-1", observation_complete=True, coverage_source="scorecard",
    )
    assert unavailable["status"] == "unavailable"
    assert unavailable["event"]["payload"]["metrics"]["bowler_credited_wickets"] is None


def test_explicit_incomplete_coverage_is_not_finalized_and_zero_rates_are_null(engine, tmp_path):
    store = _start(engine, tmp_path)
    result = finalize_fixed_horizon(
        store=store, decision_id="outcome-1", observation_complete=False, coverage_source=None,
    )
    assert result["status"] == "incomplete"
    assert derived_rates(0, 0, 0) == {
        "economy": None, "strike_rate_balls_per_wicket": None,
        "wicket_rate_per_100_legal_balls": None,
    }


def test_predeclared_zero_ball_horizon_is_complete_with_null_rates(engine, tmp_path):
    store = EventStore(tmp_path)
    run_shadow_decision(
        engine=engine, store=store, decision_id="zero-ball",
        request={"batter_id": "bat1", "candidates": [{"bowler_id": "b1"}]},
        outcome_horizon={**HORIZON, "expected_legal_deliveries": 0}, event_time_utc=T0,
        mode="synthetic_test",
    )
    record_actual_selection(
        store=store, decision_id="zero-ball", selected_bowler_id="b1",
        selection_source="manual_entry", observed=True, selection_time_utc="2026-10-12T10:01:00Z",
    )
    outcome = finalize_fixed_horizon(
        store=store, decision_id="zero-ball", observation_complete=True, coverage_source="source-v1",
    )
    metrics = outcome["event"]["payload"]["metrics"]
    assert outcome["status"] == "complete"
    assert metrics["legal_deliveries"] == 0
    assert metrics["charged_runs"] == 0
    assert metrics["rates"] == {
        "economy": None, "strike_rate_balls_per_wicket": None,
        "wicket_rate_per_100_legal_balls": None,
    }


def test_selection_not_after_decision_cannot_receive_outcome(engine, tmp_path):
    store = EventStore(tmp_path)
    run_shadow_decision(
        engine=engine, store=store, decision_id="out-of-order-selection",
        request={"batter_id": "bat1", "candidates": [{"bowler_id": "b1"}]},
        outcome_horizon=HORIZON, event_time_utc=T0, mode="synthetic_test",
    )
    record_actual_selection(
        store=store, decision_id="out-of-order-selection", selected_bowler_id="b1",
        selection_source="manual_entry", observed=True, selection_time_utc=T0,
    )
    result = finalize_fixed_horizon(
        store=store, decision_id="out-of-order-selection",
        observation_complete=True, coverage_source="source-v1",
    )
    assert result["status"] == "unavailable"
    assert result["event"]["payload"]["metrics"]["charged_runs"] is None
    assert "not strictly later" in result["event"]["payload"]["warnings"][0]


def test_duplicate_delivery_key_keeps_outcome_unavailable(engine, tmp_path):
    store = _start(engine, tmp_path)
    record_observation(store=store, decision_id="outcome-1", event_type="observed_delivery",
                       payload=_delivery(1, legal=True, source="delivery-a"), event_time_utc=T1)
    record_observation(store=store, decision_id="outcome-1", event_type="observed_delivery",
                       payload=_delivery(1, legal=True, source="delivery-b"), event_time_utc=T1)
    result = finalize_fixed_horizon(
        store=store, decision_id="outcome-1", observation_complete=True, coverage_source="source-v1",
    )
    assert result["status"] == "unavailable"
    assert result["event"]["payload"]["metrics"]["charged_runs"] is None
    assert any("Duplicate delivery key" in warning for warning in result["event"]["payload"]["warnings"])


def test_selection_outside_candidate_is_retained_with_warning(engine, tmp_path):
    store = _start(engine, tmp_path, select=False)
    result = record_actual_selection(
        store=store, decision_id="outcome-1", selected_bowler_id="b2",
        selection_source="manual_entry", observed=False, selection_time_utc=T0,
    )
    assert result["created"] is True
    assert "not in the candidate snapshot" in result["warnings"][0]


def test_selection_overlap_uses_recommendation_snapshot_not_candidate_presence(engine, tmp_path):
    store = _start(engine, tmp_path, select=False)
    result = record_actual_selection(
        store=store, decision_id="outcome-1", selected_bowler_id="b2",
        selection_source="manual_entry", observed=True, selection_time_utc=T0,
    )
    assert result["event"]["payload"]["appeared_in_candidate_snapshot"] is False
    assert result["event"]["payload"]["appeared_in_recommendations"] is False
    assert any("absent from the recorded recommendations" in warning for warning in result["warnings"])


def test_correction_appends_without_mutating_superseded_event(engine, tmp_path):
    store = _start(engine, tmp_path)
    original = store.events()[0]
    correction = record_correction(
        store=store, decision_id="outcome-1", supersedes_event_id=original["event_id"],
        reason="source timestamp corrected", replacement_event={"event_time_utc": T0},
    )
    assert correction["created"] is True
    events = store.events()
    assert len(events) == 5
    assert events[0] == original
    assert events[-1]["event_type"] == "correction"


def test_missing_decision_and_unlinked_wicket_are_rejected(engine, tmp_path):
    store = EventStore(tmp_path)
    with pytest.raises(EventValidationError, match="exactly one"):
        finalize_fixed_horizon(
            store=store, decision_id="missing", observation_complete=True, coverage_source="source",
        )
