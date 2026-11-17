from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from evaluation.phase11 import SCHEMA_VERSION

EVENT_TYPES = {
    "decision_request",
    "candidate_snapshot",
    "recommendation_snapshot",
    "recommendation_error",
    "actual_selection",
    "observed_delivery",
    "observed_wicket",
    "outcome_finalized",
    "correction",
}
MODES = {"prospective_shadow", "historical_replay", "synthetic_test"}
EVIDENCE_STATES = {"confirmed", "contradicted", "unknown", "not_recorded"}
CONTEXT_STATES = {"confirmed", "inferred", "unknown", "not_recorded"}
SELECTION_SOURCES = {"manual_entry", "trusted_integration", "other"}
ELIGIBILITY_CONCEPTS = ("team_membership", "available_at_decision", "permitted_to_bowl")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MAX_JSON_BYTES = 1024 * 1024


class EventValidationError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def normalize_timestamp(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise EventValidationError(f"{field} must be an ISO-8601 UTC timestamp")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise EventValidationError(f"{field} must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EventValidationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_identifier(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise EventValidationError(f"{field} must be a 1-128 character stable identifier")
    return value


def canonical_json(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise EventValidationError("Event contains non-JSON or non-finite values") from exc
    if len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise EventValidationError("Event exceeds the 1 MiB limit")
    return text


def validate_payload(event_type: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise EventValidationError("Event payload must be an object")
    canonical_json(payload)
    required: dict[str, set[str]] = {
        "decision_request": {"mode", "request", "context_provenance"},
        "candidate_snapshot": {"candidates"},
        "recommendation_snapshot": {"engine", "configuration_sha256", "result"},
        "recommendation_error": {"error_type", "message"},
        "actual_selection": {"selected_bowler_id", "selection_source", "observed"},
        "observed_delivery": {"match_id", "innings_number", "over_number", "ball_in_over", "bowler_id", "runs_batter", "extra_wides", "extra_noballs", "extra_byes", "extra_legbyes", "is_legal_delivery", "source_record_id"},
        "observed_wicket": {"match_id", "innings_number", "over_number", "ball_in_over", "bowler_id", "is_bowler_credited", "dismissal_kind", "source_record_id"},
        "outcome_finalized": {"status", "horizon", "actual_bowler_id", "metrics", "warnings"},
        "correction": {"supersedes_event_id", "reason", "replacement_event"},
    }
    missing = required[event_type] - payload.keys()
    if missing:
        raise EventValidationError(f"{event_type} payload missing fields: {', '.join(sorted(missing))}")
    if event_type == "decision_request":
        if payload["mode"] not in MODES:
            raise EventValidationError("mode is not a supported collection mode")
        if not isinstance(payload["request"], dict):
            raise EventValidationError("request must be an object")
        if not isinstance(payload["context_provenance"], dict):
            raise EventValidationError("context_provenance must be an object")
        if payload["context_provenance"].get("status") not in CONTEXT_STATES:
            raise EventValidationError("context provenance status is invalid")
        if payload.get("match_state") is not None and not isinstance(payload["match_state"], dict):
            raise EventValidationError("match_state must be an object or unknown")
        if payload.get("outcome_horizon") is not None and not isinstance(payload["outcome_horizon"], dict):
            raise EventValidationError("outcome_horizon must be an object or unknown")
    elif event_type == "candidate_snapshot":
        if not isinstance(payload["candidates"], list) or len(payload["candidates"]) > 30:
            raise EventValidationError("candidates must be an array of at most 30 records")
        for candidate in payload["candidates"]:
            if not isinstance(candidate, dict):
                raise EventValidationError("Each candidate record must be an object")
            validate_identifier(candidate.get("candidate_player_id"), "candidate_player_id")
            if candidate.get("eligibility_status") not in {
                "confirmed_eligible", "confirmed_ineligible", "unknown"
            }:
                raise EventValidationError("Candidate eligibility status is invalid")
            evidence = candidate.get("evidence")
            if not isinstance(evidence, dict):
                raise EventValidationError("Candidate evidence must be an object")
            for concept, record in evidence.items():
                if concept not in {*ELIGIBILITY_CONCEPTS, "bowling_role"}:
                    raise EventValidationError("Candidate evidence concept is unrecognized")
                if not isinstance(record, dict) or record.get("status") not in EVIDENCE_STATES:
                    raise EventValidationError(f"{concept} evidence status is invalid")
                if record["status"] in {"confirmed", "contradicted"}:
                    if not isinstance(record.get("source"), str) or not record["source"].strip():
                        raise EventValidationError(f"{concept} sourced evidence requires a source")
                    if record.get("evidence_time_utc") is not None:
                        normalize_timestamp(record["evidence_time_utc"], f"{concept}.evidence_time_utc")
            if candidate["eligibility_status"] == "confirmed_eligible":
                if any(
                    evidence.get(concept, {}).get("status") != "confirmed"
                    or evidence.get(concept, {}).get("evidence_time_utc") is None
                    for concept in ELIGIBILITY_CONCEPTS
                ):
                    raise EventValidationError("Confirmed eligibility requires timestamped confirmation of all required evidence")
            if candidate["eligibility_status"] == "confirmed_ineligible":
                if not any(
                    evidence.get(concept, {}).get("status") == "contradicted"
                    and evidence.get(concept, {}).get("evidence_time_utc") is not None
                    for concept in ELIGIBILITY_CONCEPTS
                ):
                    raise EventValidationError("Confirmed ineligibility requires timestamped contradictory evidence")
    elif event_type == "recommendation_snapshot":
        if not isinstance(payload["engine"], str) or not payload["engine"]:
            raise EventValidationError("engine must be identified")
        if not re.fullmatch(r"[0-9a-f]{64}", payload["configuration_sha256"]):
            raise EventValidationError("configuration_sha256 must be a SHA-256 digest")
        if not isinstance(payload["result"], dict):
            raise EventValidationError("result must be an object")
        if len(canonical_json(payload["result"])) > 512 * 1024:
            raise EventValidationError("Recommendation result exceeds 512 KiB")
    elif event_type == "recommendation_error":
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", str(payload["error_type"])):
            raise EventValidationError("error_type must be a safe exception type name")
        if not isinstance(payload["message"], str) or len(payload["message"]) > 256:
            raise EventValidationError("error message must be bounded and sanitized")
    elif event_type == "actual_selection":
        validate_identifier(payload["selected_bowler_id"], "selected_bowler_id")
        if payload["selection_source"] not in SELECTION_SOURCES:
            raise EventValidationError("selection_source is invalid")
        if not isinstance(payload["observed"], bool):
            raise EventValidationError("observed must be a boolean")
        if payload.get("reason") is not None and (
            not isinstance(payload["reason"], str) or len(payload["reason"]) > 512
        ):
            raise EventValidationError("selection reason must be a string of at most 512 characters")
        if not isinstance(payload.get("warnings", []), list):
            raise EventValidationError("selection warnings must be an array")
    elif event_type in {"observed_delivery", "observed_wicket"}:
        for key in ("match_id", "bowler_id", "source_record_id"):
            validate_identifier(payload[key], key)
        for key in ("innings_number", "over_number", "ball_in_over"):
            if isinstance(payload[key], bool) or not isinstance(payload[key], int) or payload[key] < 0:
                raise EventValidationError(f"{key} must be a nonnegative integer")
        if event_type == "observed_delivery":
            for key in ("runs_batter", "extra_wides", "extra_noballs", "extra_byes", "extra_legbyes"):
                number = payload[key]
                if isinstance(number, bool) or not isinstance(number, (int, float)) or number < 0:
                    raise EventValidationError(f"{key} must be a nonnegative number")
            if not isinstance(payload["is_legal_delivery"], bool):
                raise EventValidationError("is_legal_delivery must be a boolean")
        else:
            if not isinstance(payload["is_bowler_credited"], bool):
                raise EventValidationError("is_bowler_credited must be a boolean")
            if not isinstance(payload["dismissal_kind"], str) or not payload["dismissal_kind"].strip() or len(payload["dismissal_kind"]) > 64:
                raise EventValidationError("dismissal_kind must be a bounded nonempty string")
    elif event_type == "outcome_finalized":
        if payload["status"] not in {"complete", "incomplete", "unavailable"}:
            raise EventValidationError("outcome status is invalid")
        if not isinstance(payload["horizon"], dict) or not isinstance(payload["metrics"], dict):
            raise EventValidationError("horizon and metrics must be objects")
        if not isinstance(payload["warnings"], list):
            raise EventValidationError("warnings must be an array")
        if any(not isinstance(warning, str) or len(warning) > 512 for warning in payload["warnings"]):
            raise EventValidationError("outcome warnings must be bounded strings")
    elif event_type == "correction":
        validate_identifier(payload["supersedes_event_id"], "supersedes_event_id")
        if not isinstance(payload["reason"], str) or not payload["reason"].strip() or len(payload["reason"]) > 512:
            raise EventValidationError("correction reason must be a nonempty string of at most 512 characters")
        if not isinstance(payload["replacement_event"], dict):
            raise EventValidationError("replacement_event must be an object")
    return payload


def make_event(
    *,
    event_type: str,
    decision_id: str,
    payload: Mapping[str, Any],
    event_time_utc: Any = None,
    event_id: str | None = None,
    logged_at_utc: str | None = None,
) -> dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise EventValidationError("event_type is unrecognized")
    identifier = validate_identifier(event_id or str(uuid.uuid4()), "event_id")
    decision = validate_identifier(decision_id, "decision_id")
    event_time = normalize_timestamp(event_time_utc, "event_time_utc", optional=True)
    logged = normalize_timestamp(logged_at_utc or utc_now(), "logged_at_utc")
    validated_payload = validate_payload(event_type, dict(payload))
    if event_type == "candidate_snapshot":
        for candidate in validated_payload["candidates"]:
            for evidence in candidate["evidence"].values():
                if evidence["status"] in {"confirmed", "contradicted"} and evidence.get("evidence_time_utc") is not None:
                    evidence_time = normalize_timestamp(evidence["evidence_time_utc"], "candidate evidence time")
                    if event_time is None:
                        if candidate["eligibility_status"] != "unknown":
                            raise EventValidationError("Decision-time eligibility requires a known decision event time")
                    elif evidence_time > event_time and candidate["eligibility_status"] != "unknown":
                        raise EventValidationError("Eligibility evidence postdates the decision event time")
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": identifier,
        "decision_id": decision,
        "event_type": event_type,
        "event_time_utc": event_time,
        "logged_at_utc": logged,
        "payload": validated_payload,
    }


def event_digest(event: Mapping[str, Any], previous_hash: str) -> str:
    body = {"event": dict(event), "previous_hash": previous_hash}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
