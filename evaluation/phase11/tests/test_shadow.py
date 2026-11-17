from __future__ import annotations

import json

import pytest

from evaluation.phase11.event_store import EventStore
from evaluation.phase11.schema import EventValidationError
from evaluation.phase11.shadow import run_shadow_decision


def request():
    return {
        "batter_id": "bat1",
        "phase": "Death",
        "situation": {"type": "phase", "value": "death"},
        "context": {"match_id": "M-1", "innings_number": 1, "over": 18},
        "candidates": [{"bowler_id": "b1"}, {"bowler_id": "b2"}],
    }


def test_shadow_result_matches_unchanged_engine_and_unknown_candidates_stay_unknown(engine, tmp_path):
    original = engine.recommend(request())
    store = EventStore(tmp_path)
    result = run_shadow_decision(
        engine=engine, store=store, decision_id="decision-1", request=request(),
        mode="synthetic_test", event_time_utc="2026-10-12T10:00:00Z",
        candidates_evidence=[{
            "candidate_player_id": "b1",
            "candidate_team": "TEAM1",
            "evidence": {
                "team_membership": {"status": "confirmed", "source": "official-sheet", "evidence_time_utc": "2026-10-12T09:59:00Z"},
                "available_at_decision": {"status": "confirmed", "source": "operator-confirmed", "evidence_time_utc": "2026-10-12T09:59:00Z"},
                "permitted_to_bowl": {"status": "confirmed", "source": "quota-record", "evidence_time_utc": "2026-10-12T09:59:00Z"},
            },
        }],
        match_state={"bowling_team_id": "TEAM1"},
    )
    assert result["status"] == "ok"
    assert result["result"] == original
    candidates = next(row for row in store.events() if row["event_type"] == "candidate_snapshot")["payload"]["candidates"]
    assert candidates[0]["eligibility_status"] == "confirmed_eligible"
    assert candidates[1]["eligibility_status"] == "unknown"
    assert candidates[1]["evidence"]["available_at_decision"]["status"] == "unknown"
    assert store.verify()["integrity"] == "ok"


def test_recommendation_failure_is_logged_without_exception_details(engine, tmp_path, monkeypatch):
    def fail(_):
        raise RuntimeError(r"private C:\secrets\token.txt")

    monkeypatch.setattr(engine, "recommend", fail)
    store = EventStore(tmp_path)
    result = run_shadow_decision(engine=engine, store=store, decision_id="failed-1", request=request(), mode="synthetic_test")
    assert result == {
        "status": "recommendation_failed",
        "error": {"type": "RuntimeError", "message": "Recommendation generation failed"},
    }
    stored = json.dumps(store.events())
    assert "private" not in stored and "token.txt" not in stored
    assert "Traceback" not in stored


def test_request_validation_and_historical_replay_fail_closed(engine, tmp_path):
    store = EventStore(tmp_path)
    with pytest.raises(EventValidationError, match="historical replay"):
        run_shadow_decision(
            engine=engine, store=store, decision_id="replay-1",
            request=request(), mode="historical_replay",
        )
    assert store.events() == []
    with pytest.raises(EventValidationError, match="supported recommendation fields"):
        run_shadow_decision(
            engine=engine, store=store, decision_id="invalid-1",
            request={**request(), "filesystem_path": "C:\\private"},
        )
    with pytest.raises(EventValidationError, match="source"):
        run_shadow_decision(
            engine=engine, store=store, decision_id="invalid-2", request=request(),
            candidates_evidence=[{"candidate_player_id": "b1", "evidence": {
                "team_membership": {"status": "confirmed"},
            }}],
        )


def test_missing_optional_context_stays_unknown_and_empty_candidates_are_logged(engine, tmp_path):
    store = EventStore(tmp_path)
    empty = {"batter_id": "bat1", "candidates": []}
    result = run_shadow_decision(
        engine=engine, store=store, decision_id="empty-1", request=empty, mode="synthetic_test",
    )
    assert result["result"]["recommendations"] == []
    request_event = store.events()[0]
    assert request_event["event_time_utc"] is None
    assert request_event["payload"]["context_provenance"]["status"] == "not_recorded"
    assert request_event["payload"]["match_state"]["match_id"] is None


def test_candidate_conflict_and_duplicate_evidence_are_rejected(engine, tmp_path):
    store = EventStore(tmp_path)
    evidence = {"team_membership": {"status": "contradicted", "source": "official", "evidence_time_utc": "2026-10-12T09:59:00Z"},
                "available_at_decision": {"status": "unknown"},
                "permitted_to_bowl": {"status": "unknown"}}
    run_shadow_decision(
        engine=engine, store=store, decision_id="ineligible-1",
        request={"batter_id": "bat1", "candidates": [{"bowler_id": "b1"}]},
        candidates_evidence=[{"candidate_player_id": "b1", "evidence": evidence}],
        mode="synthetic_test", event_time_utc="2026-10-12T10:00:00Z",
    )
    candidate = store.events()[1]["payload"]["candidates"][0]
    assert candidate["eligibility_status"] == "confirmed_ineligible"
    with pytest.raises(EventValidationError, match="duplicate IDs"):
        run_shadow_decision(
            engine=engine, store=EventStore(tmp_path / "separate"), decision_id="duplicate-1",
            request={"batter_id": "bat1", "candidates": [{"bowler_id": "b1"}]},
            candidates_evidence=[
                {"candidate_player_id": "b1"},
                {"candidate_player_id": "b1"},
            ],
            mode="synthetic_test",
        )
