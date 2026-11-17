from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


class EvidenceState(str, Enum):
    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


class EligibilityState(str, Enum):
    ELIGIBLE = "confirmed_eligible"
    INELIGIBLE = "confirmed_ineligible"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class EligibilityEvidence:
    state: EligibilityState
    required_concepts: tuple[str, ...]
    evidence: Mapping[str, EvidenceState]
    explanations: Mapping[str, str]


@dataclass(frozen=True)
class ObservedOverOutcome:
    status: str
    reason: str
    actual_bowler_id: str | None = None
    delivery_rows: int | None = None
    legal_deliveries: int | None = None
    charged_runs: float | None = None
    credited_wickets: int | None = None


REQUIRED_ELIGIBILITY_EVIDENCE = (
    "team_membership",
    "available_at_decision",
    "permitted_to_bowl",
)


def assess_candidate_evidence(
    evidence: Mapping[str, EvidenceState | str],
    explanations: Mapping[str, str],
    *,
    role_required: bool,
) -> EligibilityEvidence:
    required = REQUIRED_ELIGIBILITY_EVIDENCE + (("bowling_role",) if role_required else ())
    normalized: dict[str, EvidenceState] = {}
    for concept, value in evidence.items():
        try:
            normalized[concept] = value if isinstance(value, EvidenceState) else EvidenceState(value)
        except ValueError as exc:
            raise ValueError(f"Unknown evidence state for {concept}") from exc

    required_states = [normalized.get(concept, EvidenceState.UNKNOWN) for concept in required]
    if EvidenceState.CONTRADICTED in required_states:
        state = EligibilityState.INELIGIBLE
    elif all(value is EvidenceState.CONFIRMED for value in required_states):
        state = EligibilityState.ELIGIBLE
    else:
        state = EligibilityState.UNRESOLVED
    return EligibilityEvidence(
        state=state,
        required_concepts=required,
        evidence=normalized,
        explanations=dict(explanations),
    )


def _unavailable(reason: str) -> ObservedOverOutcome:
    return ObservedOverOutcome(status="unavailable", reason=reason)


def summarize_observed_over(
    deliveries: Iterable[Mapping[str, str]],
    wicket_events: Iterable[Mapping[str, str]],
    expected_legal_deliveries: int,
) -> ObservedOverOutcome:
    """Summarize a complete observed over for its actual bowler only."""
    rows = list(deliveries)
    events = list(wicket_events)
    if expected_legal_deliveries <= 0:
        raise ValueError("expected_legal_deliveries must be positive")
    if not rows:
        return _unavailable("No observed deliveries; the outcome label is missing.")

    def field(row: Mapping[str, str], name: str) -> str:
        value = row.get(name)
        if value is None or not str(value).strip():
            raise KeyError(name)
        return str(value).strip()

    try:
        first = rows[0]
        identity = tuple(field(first, name) for name in ("match_id", "innings_number", "over_number", "bowler_id"))
        delivery_keys = []
        legal_count = 0
        charged_runs = 0.0
        for row in rows:
            if tuple(field(row, name) for name in ("match_id", "innings_number", "over_number", "bowler_id")) != identity:
                return _unavailable("Delivery sequence crosses a match, innings, over, or actual bowler boundary.")
            key = tuple(field(row, name) for name in ("match_id", "innings_number", "over_number", "ball_in_over"))
            if key in delivery_keys:
                return _unavailable("Duplicate delivery key makes the observed horizon ambiguous.")
            delivery_keys.append(key)
            legal_value = field(row, "is_legal_delivery").casefold()
            if legal_value not in {"true", "false", "1", "0"}:
                return _unavailable("A delivery has an unknown legal-ball status.")
            legal_count += legal_value in {"true", "1"}
            runs_batter = float(field(row, "runs_batter"))
            wides = float(row.get("extra_wides") or 0)
            no_balls = float(row.get("extra_noballs") or 0)
            if not all(math.isfinite(value) for value in (runs_batter, wides, no_balls)):
                return _unavailable("Runs contain a non-finite value.")
            charged_runs += runs_batter + wides + no_balls
        if legal_count != expected_legal_deliveries:
            return _unavailable(
                f"Incomplete horizon: observed {legal_count} legal deliveries; expected {expected_legal_deliveries}."
            )

        key_set = set(delivery_keys)
        credited = 0
        event_ids: set[str] = set()
        for event in events:
            event_key = tuple(field(event, name) for name in ("match_id", "innings_number", "over_number", "ball_in_over"))
            if event_key not in key_set:
                return _unavailable("A wicket event does not join to a delivery in the target horizon.")
            event_id = field(event, "wicket_event_id")
            if event_id in event_ids:
                return _unavailable("Duplicate wicket_event_id makes the wicket label ambiguous.")
            event_ids.add(event_id)
            credited_value = field(event, "is_bowler_credited").casefold()
            if credited_value not in {"true", "false", "1", "0"}:
                return _unavailable("A wicket event has unknown bowler-credit status.")
            if credited_value in {"true", "1"} and field(event, "bowler_id") == identity[3]:
                credited += 1
    except (KeyError, TypeError, ValueError, OverflowError):
        return _unavailable("Required delivery or wicket-event fields are missing or invalid.")

    return ObservedOverOutcome(
        status="available",
        reason="Descriptive outcome for the actual historical bowler; not a label for unused candidates.",
        actual_bowler_id=identity[3],
        delivery_rows=len(rows),
        legal_deliveries=legal_count,
        charged_runs=charged_runs,
        credited_wickets=credited,
    )


def fail_closed_evaluation(
    *,
    eligible_candidate_universe_supported: bool,
    decision_time_features_supported: bool,
    labels_observed_for_all_candidates: bool,
) -> dict:
    blockers = []
    if not eligible_candidate_universe_supported:
        blockers.append("decision-time eligible candidate universe is unsupported")
    if not decision_time_features_supported:
        blockers.append("decision-time features are unsupported")
    if not labels_observed_for_all_candidates:
        blockers.append("outcomes are not observed for every eligible candidate")
    if blockers:
        return {
            "status": "BLOCKED",
            "blockers": blockers,
            "metrics": {},
        }
    return {
        "status": "PREREQUISITES_SUPPORTED_NOT_RUN",
        "blockers": [],
        "metrics": {},
    }
