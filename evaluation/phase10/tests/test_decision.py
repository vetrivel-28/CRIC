from evaluation.phase10.decision import (
    EligibilityState,
    EvidenceState,
    assess_candidate_evidence,
    summarize_observed_over,
)


def _delivery(ball, *, legal, batter_runs=0, wides="", no_balls="", byes="", legbyes="", over="4", innings="1", match="M1", bowler="b1"):
    return {
        "match_id": match,
        "innings_number": innings,
        "over_number": over,
        "ball_in_over": str(ball),
        "bowler_id": bowler,
        "is_legal_delivery": "true" if legal else "false",
        "runs_batter": str(batter_runs),
        "extra_wides": wides,
        "extra_noballs": no_balls,
        "extra_byes": byes,
        "extra_legbyes": legbyes,
    }


def _event(event_id, ball, credited, bowler="b1", match="M1", innings="1", over="4"):
    return {
        "wicket_event_id": event_id,
        "match_id": match,
        "innings_number": innings,
        "over_number": over,
        "ball_in_over": str(ball),
        "bowler_id": bowler,
        "is_bowler_credited": "true" if credited else "false",
    }


def test_unknown_availability_is_not_resolved_by_later_bowling():
    result = assess_candidate_evidence(
        {
            "team_membership": EvidenceState.CONFIRMED,
            "available_at_decision": EvidenceState.UNKNOWN,
            "permitted_to_bowl": EvidenceState.CONFIRMED,
            "actual_bowling_later": EvidenceState.CONFIRMED,
        },
        {"actual_bowling_later": "Delivery participation occurs after the decision."},
        role_required=False,
    )
    assert result.state is EligibilityState.UNRESOLVED
    assert "available_at_decision" in result.required_concepts
    assert "actual_bowling_later" not in result.required_concepts


def test_candidate_status_distinguishes_confirmed_unknown_and_contradicted():
    base = {
        "team_membership": "confirmed",
        "available_at_decision": "confirmed",
        "permitted_to_bowl": "confirmed",
    }
    assert assess_candidate_evidence(base, {}, role_required=False).state is EligibilityState.ELIGIBLE
    assert assess_candidate_evidence(
        {**base, "available_at_decision": "unknown"}, {}, role_required=False
    ).state is EligibilityState.UNRESOLVED
    assert assess_candidate_evidence(
        {**base, "permitted_to_bowl": "contradicted"}, {}, role_required=False
    ).state is EligibilityState.INELIGIBLE
    assert assess_candidate_evidence(base, {}, role_required=True).state is EligibilityState.UNRESOLVED


def test_observed_over_charges_wides_and_noballs_but_not_byes_and_counts_only_credited_wickets():
    deliveries = [
        _delivery(1, legal=False, wides="2", byes="1"),
        _delivery(2, legal=False, batter_runs=4, no_balls="1", legbyes="2"),
        _delivery(3, legal=True, byes="2", legbyes="1"),
        _delivery(4, legal=True),
    ]
    events = [
        _event("w1", 4, True),
        _event("w2", 4, False),
    ]
    outcome = summarize_observed_over(deliveries, events, expected_legal_deliveries=2)

    assert outcome.status == "available"
    assert outcome.actual_bowler_id == "b1"
    assert outcome.legal_deliveries == 2
    assert outcome.charged_runs == 7
    assert outcome.credited_wickets == 1
    assert "actual historical bowler" in outcome.reason


def test_incomplete_horizon_and_early_innings_end_are_unavailable_not_zero():
    outcome = summarize_observed_over(
        [_delivery(1, legal=True), _delivery(2, legal=False, wides="1")],
        [],
        expected_legal_deliveries=2,
    )
    assert outcome.status == "unavailable"
    assert "Incomplete horizon" in outcome.reason
    assert outcome.charged_runs is None
    assert outcome.credited_wickets is None
    assert summarize_observed_over([], [], 6).status == "unavailable"


def test_over_summary_rejects_match_innings_or_actual_bowler_boundary_leakage():
    assert summarize_observed_over(
        [_delivery(1, legal=True), _delivery(2, legal=True, innings="2")], [], 2
    ).status == "unavailable"
    assert summarize_observed_over(
        [_delivery(1, legal=True), _delivery(2, legal=True, bowler="b2")], [], 2
    ).status == "unavailable"
    assert summarize_observed_over(
        [_delivery(1, legal=True), _delivery(1, legal=True)], [], 2
    ).status == "unavailable"


def test_multiple_events_at_one_delivery_are_supported_but_duplicate_event_ids_are_unavailable():
    deliveries = [_delivery(1, legal=True)]
    multiple = summarize_observed_over(
        deliveries,
        [_event("w1", 1, True), _event("w2", 1, False)],
        expected_legal_deliveries=1,
    )
    assert multiple.status == "available"
    assert multiple.credited_wickets == 1
    duplicate = summarize_observed_over(
        deliveries,
        [_event("w1", 1, True), _event("w1", 1, True)],
        expected_legal_deliveries=1,
    )
    assert duplicate.status == "unavailable"
    assert "Duplicate wicket_event_id" in duplicate.reason
