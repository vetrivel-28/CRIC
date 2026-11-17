from __future__ import annotations

from typing import Any

from evaluation.phase11.event_store import EventStore, stable_event_id
from evaluation.phase11.schema import EventValidationError, validate_identifier


def record_actual_selection(
    *,
    store: EventStore,
    decision_id: str,
    selected_bowler_id: str,
    selection_source: str,
    observed: bool,
    selection_time_utc: str | None,
    reason: str | None = None,
) -> dict[str, Any]:
    validate_identifier(decision_id, "decision_id")
    selected_bowler_id = validate_identifier(selected_bowler_id, "selected_bowler_id").casefold()
    events = store.events(decision_id=decision_id)
    requests = [event for event in events if event["event_type"] == "decision_request"]
    if len(requests) != 1 or requests[0]["payload"]["mode"] not in {"prospective_shadow", "synthetic_test"}:
        raise EventValidationError("Selection can only be linked to a prospective or synthetic decision")
    existing_selections = [event for event in events if event["event_type"] == "actual_selection"]
    if existing_selections and existing_selections[0]["payload"]["selected_bowler_id"] != selected_bowler_id:
        raise EventValidationError("A changed selection requires an explicit correction/supersession event")
    candidate_events = [event for event in events if event["event_type"] == "candidate_snapshot"]
    candidate_ids = {
        row["candidate_player_id"]
        for row in candidate_events[0]["payload"]["candidates"]
    } if len(candidate_events) == 1 else set()
    recommendation_events = [event for event in events if event["event_type"] == "recommendation_snapshot"]
    recommendation_ids = {
        row["bowler_id"].casefold()
        for row in recommendation_events[0]["payload"]["result"].get("recommendations", [])
        if isinstance(row, dict) and isinstance(row.get("bowler_id"), str)
    } if len(recommendation_events) == 1 else set()
    warnings = []
    if selected_bowler_id not in candidate_ids:
        warnings.append("Selected bowler was not in the candidate snapshot.")
    if recommendation_events and selected_bowler_id not in recommendation_ids:
        warnings.append("Selected bowler was absent from the recorded recommendations.")
    if reason is not None and (not isinstance(reason, str) or len(reason) > 512):
        raise EventValidationError("Selection reason must be a string of at most 512 characters")
    payload = {
        "selected_bowler_id": selected_bowler_id,
        "selection_source": selection_source,
        "observed": observed,
        "reason": reason,
        "appeared_in_candidate_snapshot": selected_bowler_id in candidate_ids,
        "appeared_in_recommendations": selected_bowler_id in recommendation_ids,
        "warnings": warnings,
    }
    event, created = store.append(
        event_type="actual_selection",
        decision_id=decision_id,
        payload=payload,
        event_time_utc=selection_time_utc,
        event_id=stable_event_id(decision_id, "actual_selection", selected_bowler_id),
    )
    return {"event": event, "created": created, "warnings": warnings}


def record_observation(
    *,
    store: EventStore,
    decision_id: str,
    event_type: str,
    payload: dict[str, Any],
    event_time_utc: str | None,
) -> dict[str, Any]:
    if event_type not in {"observed_delivery", "observed_wicket"}:
        raise EventValidationError("Only observed delivery or wicket events may be ingested here")
    requests = [event for event in store.events(decision_id=decision_id) if event["event_type"] == "decision_request"]
    if len(requests) != 1 or requests[0]["payload"]["mode"] not in {"prospective_shadow", "synthetic_test"}:
        raise EventValidationError("Observations can only be linked to a prospective or synthetic decision")
    horizon = requests[0]["payload"].get("outcome_horizon")
    if horizon is not None:
        identity = (
            payload.get("match_id"), payload.get("innings_number"), payload.get("over_number")
        )
        expected = (horizon["match_id"], horizon["innings_number"], horizon["over_number"])
        if identity != expected:
            raise EventValidationError("Observed event does not match the predeclared decision horizon")
    source_id = validate_identifier(payload.get("source_record_id"), "source_record_id")
    event, created = store.append(
        event_type=event_type,
        decision_id=decision_id,
        payload=payload,
        event_time_utc=event_time_utc,
        event_id=stable_event_id(decision_id, event_type, source_id),
    )
    return {"event": event, "created": created}


def record_correction(
    *,
    store: EventStore,
    decision_id: str,
    supersedes_event_id: str,
    reason: str,
    replacement_event: dict[str, Any],
) -> dict[str, Any]:
    validate_identifier(supersedes_event_id, "supersedes_event_id")
    events = store.events(decision_id=decision_id)
    if not any(event["event_id"] == supersedes_event_id for event in events):
        raise EventValidationError("Correction must reference an existing event for this decision")
    if not isinstance(replacement_event, dict):
        raise EventValidationError("replacement_event must be an object")
    event, created = store.append(
        event_type="correction",
        decision_id=decision_id,
        payload={
            "supersedes_event_id": supersedes_event_id,
            "reason": reason,
            "replacement_event": replacement_event,
        },
        event_id=stable_event_id(decision_id, "correction", supersedes_event_id),
    )
    return {"event": event, "created": created}
