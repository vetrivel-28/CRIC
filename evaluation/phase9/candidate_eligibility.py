from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reasons: tuple[str, ...]


def assess_candidate(
    *,
    match_exists: bool,
    team_matches_fixture: bool,
    player_exists: bool,
    declared_bowler: bool | None,
    duplicate_match_player: bool,
    available_at_decision: bool | None,
    legal_overs_remaining: float | None,
    roster_semantics_verified: bool,
    quota_rules_verified: bool,
) -> EligibilityDecision:
    reasons = []
    if not match_exists:
        reasons.append("unknown_match")
    if not team_matches_fixture:
        reasons.append("team_mismatch")
    if not player_exists:
        reasons.append("unknown_player")
    if declared_bowler is False:
        reasons.append("not_declared_bowler")
    elif declared_bowler is None:
        reasons.append("bowling_role_unknown")
    if duplicate_match_player:
        reasons.append("duplicate_or_conflicting_roster_identity")
    if available_at_decision is not True:
        reasons.append("decision_time_availability_unverified")
    if legal_overs_remaining is None:
        reasons.append("quota_state_unavailable")
    elif legal_overs_remaining <= 0:
        reasons.append("no_legal_overs_remaining")
    if not roster_semantics_verified:
        reasons.append("roster_semantics_unverified")
    if not quota_rules_verified:
        reasons.append("quota_rules_unverified")
    return EligibilityDecision(eligible=not reasons, reasons=tuple(reasons))


def format_metadata_is_consistent(match_type: str, scheduled_overs: int | None) -> bool:
    if match_type.strip().casefold() in {"t20", "t20i"}:
        return scheduled_overs == 20
    if match_type.strip().casefold() in {"odi", "one day international"}:
        return scheduled_overs == 50
    return scheduled_overs is not None and scheduled_overs > 0
