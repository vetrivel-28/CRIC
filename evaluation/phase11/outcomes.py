from __future__ import annotations

import hashlib
import json
from typing import Any

from evaluation.phase11.event_store import EventStore, stable_event_id
from evaluation.phase11.schema import EventValidationError


def derived_rates(charged_runs: float, legal_balls: int, credited_wickets: int) -> dict[str, float | None]:
    if legal_balls < 0 or charged_runs < 0 or credited_wickets < 0:
        raise EventValidationError("Outcome counts must be nonnegative")
    return {
        "economy": charged_runs * 6 / legal_balls if legal_balls else None,
        "strike_rate_balls_per_wicket": legal_balls / credited_wickets if credited_wickets else None,
        "wicket_rate_per_100_legal_balls": credited_wickets * 100 / legal_balls if legal_balls else None,
    }


def finalize_fixed_horizon(
    *,
    store: EventStore,
    decision_id: str,
    observation_complete: bool,
    coverage_source: str | None,
) -> dict[str, Any]:
    if not isinstance(observation_complete, bool):
        raise EventValidationError("observation_complete must be a boolean")
    if coverage_source is not None and (
        not isinstance(coverage_source, str) or not coverage_source.strip() or len(coverage_source) > 128
    ):
        raise EventValidationError("coverage_source must be a nonempty string of at most 128 characters or unknown")
    events = store.events(decision_id=decision_id)
    requests = [event for event in events if event["event_type"] == "decision_request"]
    selections = [event for event in events if event["event_type"] == "actual_selection"]
    if len(requests) != 1:
        raise EventValidationError("Outcome finalization requires exactly one logged decision request")
    decision = requests[0]["payload"]
    horizon = decision.get("outcome_horizon")
    if not isinstance(horizon, dict):
        raise EventValidationError("No fixed outcome horizon was recorded before the decision")
    required = {"match_id", "innings_number", "over_number", "expected_legal_deliveries", "definition_version"}
    if set(horizon) != required:
        raise EventValidationError("Predeclared outcome horizon is incomplete or unrecognized")
    if (
        not isinstance(horizon["match_id"], str) or not horizon["match_id"]
        or any(isinstance(horizon[key], bool) or not isinstance(horizon[key], int) or horizon[key] < 0
               for key in ("innings_number", "over_number"))
        or not isinstance(horizon["definition_version"], str) or not horizon["definition_version"]
    ):
        raise EventValidationError("Predeclared horizon identity or definition version is invalid")
    expected = horizon["expected_legal_deliveries"]
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise EventValidationError("Expected legal-delivery horizon must be a nonnegative integer")

    metrics: dict[str, Any] = {
        "delivery_rows": None,
        "legal_deliveries": None,
        "charged_runs": None,
        "bowler_credited_wickets": None,
        "rates": {"economy": None, "strike_rate_balls_per_wicket": None, "wicket_rate_per_100_legal_balls": None},
    }
    warnings: list[str] = []
    if len(selections) > 1:
        raise EventValidationError("Multiple actual selections require an explicit correction before outcome linking")
    selected_bowler_id = selections[0]["payload"]["selected_bowler_id"] if selections else None
    status = "unavailable"
    actual_bowler_id = None
    if not selections:
        warnings.append("No actual selection has been recorded; observed outcomes cannot be attributed to a selected bowler.")
    elif (
        requests[0]["event_time_utc"] is not None
        and selections[0]["event_time_utc"] is not None
        and selections[0]["event_time_utc"] <= requests[0]["event_time_utc"]
    ):
        warnings.append("Actual selection is not strictly later than the decision request.")
    elif not observation_complete or not coverage_source:
        status = "incomplete"
        warnings.append("Observation completeness and a nonempty coverage source are required for finalization.")
    else:
        selection_time = selections[0]["event_time_utc"]
        deliveries = [event["payload"] for event in events if event["event_type"] == "observed_delivery"]
        delivery_events = [event for event in events if event["event_type"] == "observed_delivery"]
        wickets = [event["payload"] for event in events if event["event_type"] == "observed_wicket"]
        match_id, innings, over = horizon["match_id"], horizon["innings_number"], horizon["over_number"]
        delivery_keys: set[tuple[Any, ...]] = set()
        selected_deliveries = []
        for delivery in deliveries:
            identity = (delivery["match_id"], delivery["innings_number"], delivery["over_number"])
            if identity != (match_id, innings, over):
                continue
            key = (*identity, delivery["ball_in_over"])
            if key in delivery_keys:
                warnings.append("Duplicate delivery key makes the outcome horizon ambiguous.")
                break
            delivery_keys.add(key)
            selected_deliveries.append(delivery)
        else:
            if selection_time is None or any(event["event_time_utc"] is None for event in delivery_events):
                status = "incomplete"
                warnings.append("Selection and observation timestamps are required to validate decision-time ordering.")
            elif any(event["event_time_utc"] <= selection_time for event in delivery_events):
                status = "unavailable"
                warnings.append("An observed delivery is not strictly later than the actual selection timestamp.")
            else:
                status = "complete"
            if status == "complete":
                legal_balls = sum(row["is_legal_delivery"] for row in selected_deliveries)
                if legal_balls != expected:
                    status = "incomplete"
                    warnings.append(f"Incomplete horizon: observed {legal_balls} legal deliveries; expected {expected}.")
                elif any(row["bowler_id"].casefold() != selected_bowler_id.casefold() for row in selected_deliveries):
                    status = "unavailable"
                    warnings.append("Observed deliveries do not all belong to the recorded selected bowler.")
                else:
                    delivery_key_set = delivery_keys
                    relevant_wickets = []
                    wicket_keys: set[str] = set()
                    invalid_wicket = False
                    delivery_times = {
                        (
                            row["match_id"], row["innings_number"], row["over_number"], row["ball_in_over"]
                        ): event["event_time_utc"]
                        for event in delivery_events
                        for row in [event["payload"]]
                    }
                    for event, wicket in zip(
                        [row for row in events if row["event_type"] == "observed_wicket"], wickets
                    ):
                        key = (wicket["match_id"], wicket["innings_number"], wicket["over_number"], wicket["ball_in_over"])
                        if key not in delivery_key_set:
                            if wicket["match_id"] == match_id and wicket["innings_number"] == innings and wicket["over_number"] == over:
                                invalid_wicket = True
                                warnings.append("Wicket event did not link to an observed delivery in the fixed horizon.")
                                break
                            continue
                        if event["event_time_utc"] is None or event["event_time_utc"] < selection_time:
                            invalid_wicket = True
                            warnings.append("A linked wicket lacks a valid post-selection event timestamp.")
                            break
                        delivery_time = delivery_times.get(key)
                        if delivery_time is None or event["event_time_utc"] < delivery_time:
                            invalid_wicket = True
                            warnings.append("A wicket event predates its linked delivery.")
                            break
                        delivery_bowler = next(
                            row["bowler_id"] for row in selected_deliveries
                            if (row["match_id"], row["innings_number"], row["over_number"], row["ball_in_over"]) == key
                        )
                        if wicket["bowler_id"].casefold() != delivery_bowler.casefold():
                            invalid_wicket = True
                            warnings.append("Wicket bowler does not match the linked delivery bowler.")
                            break
                        if wicket["source_record_id"] in wicket_keys:
                            invalid_wicket = True
                            warnings.append("Duplicate wicket source record makes the outcome ambiguous.")
                            break
                        wicket_keys.add(wicket["source_record_id"])
                        relevant_wickets.append(wicket)
                    if not invalid_wicket:
                        actual_bowler_id = selected_bowler_id
                        charged_runs = sum(
                            row["runs_batter"] + row["extra_wides"] + row["extra_noballs"]
                            for row in selected_deliveries
                        )
                        credited = sum(
                            wicket["is_bowler_credited"]
                            and wicket["bowler_id"].casefold() == selected_bowler_id.casefold()
                            for wicket in relevant_wickets
                        )
                        metrics = {
                            "delivery_rows": len(selected_deliveries),
                            "legal_deliveries": legal_balls,
                            "charged_runs": charged_runs,
                            "bowler_credited_wickets": credited,
                            "rates": derived_rates(charged_runs, legal_balls, credited),
                        }
                        status = "complete"
    payload = {
        "status": status,
        "horizon": {**horizon, "observation_complete": observation_complete, "coverage_source": coverage_source},
        "actual_bowler_id": actual_bowler_id,
        "metrics": metrics,
        "warnings": warnings,
    }
    finalization_key = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    event, created = store.append(
        event_type="outcome_finalized",
        decision_id=decision_id,
        payload=payload,
        event_id=stable_event_id(decision_id, "outcome_finalized", finalization_key),
    )
    return {"event": event, "created": created, "status": status}
