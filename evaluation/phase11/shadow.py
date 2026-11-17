from __future__ import annotations

import copy
import hashlib
import inspect
import math
from pathlib import Path
from typing import Any

from backend.recommendation_engine import RecommendationEngine
from evaluation.phase11.event_store import EventStore, stable_event_id
from evaluation.phase11.schema import (
    CONTEXT_STATES,
    EVIDENCE_STATES,
    EventValidationError,
    canonical_json,
    validate_identifier,
)

RECOMMENDATION_FIELDS = {"batter_id", "phase", "situation", "context", "candidates"}
ELIGIBILITY_CONCEPTS = ("team_membership", "available_at_decision", "permitted_to_bowl")


def _bounded_string(value: Any, field: str, max_length: int = 512, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise EventValidationError(f"{field} must be a nonempty string of at most {max_length} characters")
    return value.strip()


def _evidence_record(value: Any, concept: str) -> dict[str, Any]:
    if value is None:
        value = {"status": "unknown"}
    if not isinstance(value, dict) or set(value) - {"status", "source", "evidence_time_utc", "reference"}:
        raise EventValidationError(f"{concept} evidence has an invalid structure")
    status = value.get("status", "unknown")
    if status not in EVIDENCE_STATES:
        raise EventValidationError(f"{concept} evidence status is invalid")
    source = _bounded_string(value.get("source"), f"{concept}.source", 128, optional=True)
    reference = _bounded_string(value.get("reference"), f"{concept}.reference", 256, optional=True)
    evidence_time = value.get("evidence_time_utc")
    if evidence_time is not None:
        from evaluation.phase11.schema import normalize_timestamp

        evidence_time = normalize_timestamp(evidence_time, f"{concept}.evidence_time_utc")
    if status in {"confirmed", "contradicted"} and not source:
        raise EventValidationError(f"{concept} {status} evidence requires a source")
    return {
        "status": status,
        "source": source,
        "evidence_time_utc": evidence_time,
        "reference": reference,
    }


def _candidate_rows(
    request: dict[str, Any], supplied: Any, match_state: dict[str, Any] | None,
    decision_time_utc: str | None,
) -> list[dict[str, Any]]:
    candidates = request.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > 30:
        raise EventValidationError("request.candidates must be an array of at most 30 candidates")
    if not isinstance(supplied, list) or len(supplied) > 30:
        raise EventValidationError("candidates_evidence must be an array of at most 30 records")
    by_id: dict[str, dict[str, Any]] = {}
    for item in supplied:
        if not isinstance(item, dict):
            raise EventValidationError("Each candidate evidence entry must be an object")
        allowed = {
            "candidate_player_id", "candidate_team", "evidence", "bowling_quota_state",
            "exclusion_reason", "sufficient_recommendation_data", "data_quality_warnings",
        }
        if set(item) - allowed:
            raise EventValidationError("Candidate evidence contains unsupported fields")
        candidate_id = validate_identifier(item.get("candidate_player_id"), "candidate_player_id").casefold()
        if candidate_id in by_id:
            raise EventValidationError("Candidate evidence contains duplicate IDs")
        by_id[candidate_id] = item

    request_ids: list[str] = []
    request_by_id: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            raise EventValidationError("Each recommendation candidate must be an object")
        if set(item) - {"bowler_id", "available", "overs_bowled", "overs_remaining"}:
            raise EventValidationError("Recommendation candidate contains unsupported fields")
        candidate_id = validate_identifier(item.get("bowler_id"), "bowler_id").casefold()
        if candidate_id in request_ids:
            raise EventValidationError("Request contains duplicate candidates")
        request_ids.append(candidate_id)
        request_by_id[candidate_id] = item
        available = item.get("available", True)
        if not isinstance(available, bool):
            raise EventValidationError("candidate.available must be a boolean")
        for key in ("overs_bowled", "overs_remaining"):
            value = item.get(key)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0
            ):
                raise EventValidationError(f"candidate.{key} must be finite and nonnegative")
    unexpected = set(by_id) - set(request_ids)
    if unexpected:
        raise EventValidationError("Evidence was supplied for a candidate absent from the request")

    result = []
    for candidate_id in request_ids:
        item = by_id.get(candidate_id, {})
        evidence_input = item.get("evidence", {})
        if not isinstance(evidence_input, dict) or set(evidence_input) - {
            *ELIGIBILITY_CONCEPTS, "bowling_role"
        }:
            raise EventValidationError("Candidate eligibility evidence contains unknown concepts")
        evidence = {
            concept: _evidence_record(evidence_input.get(concept), concept)
            for concept in (*ELIGIBILITY_CONCEPTS, "bowling_role")
        }
        for concept, item_evidence in evidence.items():
            if (
                item_evidence["status"] in {"confirmed", "contradicted"}
                and item_evidence["evidence_time_utc"] is not None
                and decision_time_utc is not None
                and item_evidence["evidence_time_utc"] > decision_time_utc
            ):
                raise EventValidationError(f"{concept} evidence was recorded after the decision time")
        request_candidate = request_by_id[candidate_id]
        if request_candidate.get("available") is False and evidence["available_at_decision"]["status"] == "confirmed":
            raise EventValidationError("candidate availability conflicts with sourced eligibility evidence")
        if request_candidate.get("overs_remaining") == 0 and evidence["permitted_to_bowl"]["status"] == "confirmed":
            raise EventValidationError("candidate quota conflicts with sourced bowling-rule evidence")
        states = [evidence[key]["status"] for key in ELIGIBILITY_CONCEPTS]
        evidence_is_time_supported = decision_time_utc is not None and all(
            evidence[key]["status"] not in {"confirmed", "contradicted"}
            or evidence[key]["evidence_time_utc"] is not None
            for key in ELIGIBILITY_CONCEPTS
        )
        candidate_team = _bounded_string(item.get("candidate_team"), "candidate_team", 128, optional=True)
        bowling_team = (match_state or {}).get("bowling_team_id")
        if evidence_is_time_supported and "contradicted" in states:
            eligibility = "confirmed_ineligible"
        elif (
            evidence_is_time_supported
            and
            all(state == "confirmed" for state in states)
            and candidate_team is not None
            and bowling_team is not None
            and candidate_team.casefold() == bowling_team.casefold()
        ):
            eligibility = "confirmed_eligible"
        else:
            eligibility = "unknown"
        if request_candidate.get("available") is False or request_candidate.get("overs_remaining") == 0:
            if eligibility == "confirmed_eligible":
                raise EventValidationError("Recommendation exclusion conflicts with confirmed candidate eligibility")
            eligibility = "unknown" if "contradicted" not in states else "confirmed_ineligible"
        warnings = item.get("data_quality_warnings", [])
        if not isinstance(warnings, list) or len(warnings) > 20 or any(
            not isinstance(warning, str) or len(warning) > 256 for warning in warnings
        ):
            raise EventValidationError("data_quality_warnings must contain at most 20 bounded strings")
        warnings = list(warnings)
        if not evidence_is_time_supported and any(state in {"confirmed", "contradicted"} for state in states):
            warnings.append("Eligibility evidence lacks decision-time timestamps; status remains unknown.")
        if all(state == "confirmed" for state in states) and eligibility == "unknown":
            warnings.append("Required evidence is complete but candidate team cannot be matched to a confirmed bowling team.")
        quota = item.get("bowling_quota_state")
        if quota is not None:
            if not isinstance(quota, dict) or len(canonical_json(quota)) > 2048:
                raise EventValidationError("bowling_quota_state must be a bounded object")
        exclusion = _bounded_string(item.get("exclusion_reason"), "exclusion_reason", 256, optional=True)
        sufficient = item.get("sufficient_recommendation_data")
        if sufficient is not None and not isinstance(sufficient, bool):
            raise EventValidationError("sufficient_recommendation_data must be boolean or unknown")
        engine_exclusion = (
            "unavailable" if request_candidate.get("available", True) is False else
            "no_overs_remaining" if request_candidate.get("overs_remaining") == 0 else None
        )
        exclusion = exclusion or engine_exclusion
        result.append(
            {
                "candidate_player_id": candidate_id,
                "candidate_team": candidate_team,
                "eligibility_status": eligibility,
                "evidence": evidence,
                "bowling_quota_state": quota,
                "exclusion_reason": exclusion,
                "sufficient_recommendation_data": sufficient,
                "data_quality_warnings": warnings,
            }
        )
    return result


def _validate_request_shape(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or set(request) - RECOMMENDATION_FIELDS:
        raise EventValidationError("request must be an object with only supported recommendation fields")
    encoded = canonical_json(request)
    if len(encoded.encode("utf-8")) > 256 * 1024:
        raise EventValidationError("recommendation request exceeds 256 KiB")
    if not isinstance(request.get("batter_id"), str) or not request["batter_id"].strip():
        raise EventValidationError("request.batter_id must be a nonempty string")
    if len(request["batter_id"]) > 128:
        raise EventValidationError("request.batter_id is too long")
    phase = request.get("phase")
    if phase is not None and (not isinstance(phase, str) or not phase.strip() or len(phase) > 64):
        raise EventValidationError("request.phase must be a bounded nonempty string when provided")
    situation = request.get("situation")
    if situation is not None and (
        not isinstance(situation, dict) or set(situation) != {"type", "value"}
        or any(not isinstance(v, str) or not v.strip() or len(v) > 128 for v in situation.values())
    ):
        raise EventValidationError("request.situation must contain bounded type and value strings")
    context = request.get("context")
    if context is not None and not isinstance(context, dict):
        raise EventValidationError("request.context must be an object")
    if context is not None:
        allowed_context = {"match_id", "innings_number", "batting_team", "bowling_team", "over"}
        if set(context) - allowed_context:
            raise EventValidationError("request.context contains unsupported fields")
        for key, item in context.items():
            if key in {"match_id", "batting_team", "bowling_team"}:
                _bounded_string(item, f"request.context.{key}", 128)
            elif isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) or item < 0:
                raise EventValidationError(f"request.context.{key} must be finite and nonnegative")
    return request


def _context_provenance(value: Any) -> dict[str, Any]:
    if value is None:
        return {"status": "not_recorded", "source": None, "confidence": None}
    if not isinstance(value, dict) or set(value) - {"status", "source", "confidence"}:
        raise EventValidationError("context_provenance has an invalid structure")
    status = value.get("status", "unknown")
    if status not in CONTEXT_STATES:
        raise EventValidationError("context_provenance.status is invalid")
    source = _bounded_string(value.get("source"), "context_provenance.source", 128, optional=True)
    if status in {"confirmed", "inferred"} and not source:
        raise EventValidationError("confirmed or inferred context provenance requires a source")
    confidence = value.get("confidence")
    if confidence is not None and (
        isinstance(confidence, bool) or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence) or not 0 <= confidence <= 1
    ):
        raise EventValidationError("context_provenance.confidence must be in [0, 1] or unknown")
    return {"status": status, "source": source, "confidence": confidence}


def run_shadow_decision(
    *,
    engine: RecommendationEngine,
    store: EventStore,
    decision_id: str,
    request: dict[str, Any],
    candidates_evidence: list[dict[str, Any]] | None = None,
    context_provenance: dict[str, Any] | None = None,
    mode: str = "prospective_shadow",
    event_time_utc: str | None = None,
    match_state: dict[str, Any] | None = None,
    outcome_horizon: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = _validate_request_shape(request)
    provenance = _context_provenance(context_provenance)
    if mode not in {"prospective_shadow", "synthetic_test"}:
        raise EventValidationError("This runner records prospective shadow or synthetic-test events only; historical replay is import-only and is not implemented")
    if match_state is not None:
        allowed_state = {
            "match_id", "innings_id", "competition", "format", "batting_team_id", "bowling_team_id",
            "current_over", "ball_index", "innings_score", "wickets", "target", "remaining_runs",
        }
        if not isinstance(match_state, dict) or set(match_state) - allowed_state or len(canonical_json(match_state)) > 8192:
            raise EventValidationError("match_state contains unsupported fields or exceeds its size limit")
        for key in ("match_id", "innings_id", "competition", "format", "batting_team_id", "bowling_team_id"):
            if key in match_state:
                _bounded_string(match_state[key], f"match_state.{key}", 128)
        for key in ("current_over", "ball_index", "innings_score", "wickets", "target", "remaining_runs"):
            if key in match_state:
                number = match_state[key]
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
                    raise EventValidationError(f"match_state.{key} must be a finite nonnegative number")
    from evaluation.phase11.schema import normalize_timestamp

    normalized_event_time = normalize_timestamp(event_time_utc, "event_time_utc", optional=True)
    match_state_fields = (
        "match_id", "innings_id", "competition", "format", "batting_team_id", "bowling_team_id",
        "current_over", "ball_index", "innings_score", "wickets", "target", "remaining_runs",
    )
    normalized_match_state = {key: (match_state or {}).get(key) for key in match_state_fields}
    candidates = _candidate_rows(
        request,
        [] if candidates_evidence is None else candidates_evidence,
        normalized_match_state,
        normalized_event_time,
    )
    if outcome_horizon is not None and (
        not isinstance(outcome_horizon, dict) or len(canonical_json(outcome_horizon)) > 2048
    ):
        raise EventValidationError("outcome_horizon must be a bounded object")
    if outcome_horizon is not None:
        required_horizon = {"match_id", "innings_number", "over_number", "expected_legal_deliveries", "definition_version"}
        if set(outcome_horizon) != required_horizon:
            raise EventValidationError("outcome_horizon must declare its match, innings, over, legal-ball count, and definition version")
        validate_identifier(outcome_horizon["match_id"], "outcome_horizon.match_id")
        _bounded_string(outcome_horizon["definition_version"], "outcome_horizon.definition_version", 64)
        for key in ("innings_number", "over_number", "expected_legal_deliveries"):
            value = outcome_horizon[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise EventValidationError(f"outcome_horizon.{key} must be a nonnegative integer")
    request_payload = {
        "mode": mode,
        "request": request,
        "context_provenance": provenance,
        "match_state": normalized_match_state,
        "outcome_horizon": outcome_horizon,
        "engine_identifier": "CRIC.RecommendationEngine",
    }
    store.append(
        event_type="decision_request",
        decision_id=decision_id,
        payload=request_payload,
        event_time_utc=normalized_event_time,
        event_id=stable_event_id(decision_id, "decision_request"),
    )
    store.append(
        event_type="candidate_snapshot",
        decision_id=decision_id,
        payload={"candidates": candidates},
        event_time_utc=normalized_event_time,
        event_id=stable_event_id(decision_id, "candidate_snapshot"),
    )
    try:
        result = engine.recommend(copy.deepcopy(request))
    except Exception as exc:
        safe_type = type(exc).__name__
        store.append(
            event_type="recommendation_error",
            decision_id=decision_id,
            payload={"error_type": safe_type, "message": "Recommendation generation failed"},
            event_time_utc=normalized_event_time,
            event_id=stable_event_id(decision_id, "recommendation_error"),
        )
        return {"status": "recommendation_failed", "error": {"type": safe_type, "message": "Recommendation generation failed"}}

    config = {
        "component_weights": dict(engine.config.component_weights),
        "metric_weights": {key: dict(value) for key, value in engine.config.metric_weights.items()},
        "reliability_prior_balls": engine.config.reliability_prior_balls,
        "very_small_sample_balls": engine.config.very_small_sample_balls,
        "limited_sample_balls": engine.config.limited_sample_balls,
    }
    source_path = Path(inspect.getfile(type(engine)))
    source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    config_digest = hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()
    store.append(
        event_type="recommendation_snapshot",
        decision_id=decision_id,
        payload={
            "engine": f"CRIC.RecommendationEngine:{source_digest}",
            "configuration_sha256": config_digest,
            "configuration": config,
            "result": result,
        },
        event_time_utc=normalized_event_time,
        event_id=stable_event_id(decision_id, "recommendation_snapshot"),
    )
    return {"status": "ok", "decision_id": decision_id, "result": result}
