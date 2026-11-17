from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from evaluation.phase10.audit import (
    audit_roster,
    hash_tree,
    roster_anomaly_rows,
    sha256_file,
    source_inventory,
)
from evaluation.phase10.protocol import (
    evaluation_feasibility,
    load_phase9_baseline,
    phase10_protocol,
)
from evaluation.phase9.data_quality import DATASETS, find_unique


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
PHASE9_ROOT = PROJECT_ROOT / "reports" / "phase9_complete_06"


def _csv_read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _source_paths() -> dict[str, Path]:
    return {name: find_unique(DATA_ROOT, name) for name in DATASETS}


def _candidate_eligibility_rows(audit: dict) -> list[dict]:
    return [
        {
            "concept": "Relevant-team membership",
            "formal_definition": "The player is a member of the team fielding at the specified decision time.",
            "required_source_columns": "match_playing_xi.match_id,team,player_id; matches.team_1,team_2; authoritative team sheet",
            "current_status": "SUPPORTED_BUT_UNCERTAIN",
            "local_evidence": f"Roster rows join to match and player catalogs with {audit['wrong_team_rows']} team-name mismatches; roster semantics and provenance are not documented.",
            "leakage_or_bias": "Roster may describe a squad, starters, substitutes, or mixed records; membership alone does not establish availability.",
            "primary_evaluation_use": "No; require authoritative lineup semantics and row-level provenance.",
        },
        {
            "concept": "Available at decision time",
            "formal_definition": "The player was active and available immediately before the decision, including substitutions/withdrawals.",
            "required_source_columns": "Timestamped lineup/availability events, substitution and replacement events, decision timestamp",
            "current_status": "UNKNOWN",
            "local_evidence": "No availability, injury, withdrawal, replacement, or substitution timestamps were found in the roster table.",
            "leakage_or_bias": "Using later bowling participation leaks future selection and can exclude valid unused alternatives.",
            "primary_evaluation_use": "Required; no proxy is acceptable.",
        },
        {
            "concept": "Permitted to bowl under rules",
            "formal_definition": "The player had legal bowling quota and no rule-based restriction for the proposed next over.",
            "required_source_columns": "Format/ruleset, decision innings/over, balls-per-over, overs already bowled by candidate, quota/penalty state",
            "current_status": "UNKNOWN",
            "local_evidence": "Historical deliveries show who bowled, but the source contains no decision-time remaining-quota state; seven format/overs metadata anomalies are known.",
            "leakage_or_bias": "Inferring quota from eventual full-innings bowling history uses future events and can misstate availability.",
            "primary_evaluation_use": "Required; exclude unresolved decision points rather than impute.",
        },
        {
            "concept": "Bowling-role eligibility",
            "formal_definition": "The player meets a pre-specified role condition if the experiment requires a designated bowler.",
            "required_source_columns": "Dated authoritative role classification with source and validity interval; combined_data.bowls_flag is a local undated field.",
            "current_status": "SUPPORTED_BUT_UNCERTAIN",
            "local_evidence": f"Roster rows have role-flag counts {json.dumps(audit['bowls_flag_row_counts'], sort_keys=True)}; {audit['unique_roster_ids_with_missing_bowls_flag']} unique roster IDs have a blank flag.",
            "leakage_or_bias": "Role flags are not shown to be contemporaneous or authoritative; bowling participation cannot be used to label role.",
            "primary_evaluation_use": "Only if the role requirement is prespecified and authoritative dated role evidence is acquired.",
        },
        {
            "concept": "Historical actual bowling",
            "formal_definition": "A player appears as bowler_id on an observed delivery before or after the hypothetical decision.",
            "required_source_columns": "deliveries.match_id,innings_number,over_number,ball_in_over,bowler_id",
            "current_status": "VERIFIED_AS_OBSERVED_HISTORY_ONLY",
            "local_evidence": f"{audit['delivery_rows']} delivery rows and {audit['delivery_player_ids']} distinct batter/bowler IDs are present; each observed participant has a roster match-player record in this snapshot.",
            "leakage_or_bias": "Actual bowling is a post-selection outcome; it is not evidence that the player was available earlier.",
            "primary_evaluation_use": "Descriptive outcome attribution only; never as an eligibility proxy.",
        },
        {
            "concept": "Eligibility inferred from incomplete data",
            "formal_definition": "Any one or more required states remain unknown or are inferred from participation/absence.",
            "required_source_columns": "All time-specific membership, availability, rules, and role evidence above.",
            "current_status": "UNKNOWN_NOT_ADMITTED",
            "local_evidence": "No decision scenarios admitted; nonparticipation and later bowling do not resolve availability.",
            "leakage_or_bias": "Converting unknown to eligible or ineligible creates selection bias and false labels.",
            "primary_evaluation_use": "Neither; report as unresolved and do not score.",
        },
    ]


def _provenance_rows(audit: dict) -> list[dict]:
    return [
        {
            "area": "Merged source package origin",
            "status": "UNKNOWN",
            "evidence": "Timestamped extracted directory name and local ingestion manifest with relative paths, byte sizes, SHA-256, modified timestamps, and validation status.",
            "finding": "No source URL, archive checksum, upstream API/export log, or license is recorded in the inspected local metadata. The package filename does not establish origin.",
            "handling": "Preserve files and hashes; obtain original archive/source metadata and license.",
        },
        {
            "area": "match_playing_xi.csv meaning",
            "status": "UNKNOWN",
            "evidence": "Header is match_id, team, player_id, player_name; no row status, source URL, timestamp, role, starter/substitute, or availability field.",
            "finding": "Official announced XI versus squad versus another roster concept is not established.",
            "handling": "Do not use as the eligible candidate set until source owner semantics and row lineage are supplied.",
        },
        {
            "area": "Roster identifier joins",
            "status": "VERIFIED_LOCAL_JOIN_ONLY",
            "evidence": f"Unknown match rows={audit['unknown_match_rows']}; player catalog orphans={audit['unknown_player_rows']}; team name mismatches={audit['wrong_team_rows']}; delivery match-player keys absent from roster={audit['delivery_participant_match_keys_absent_from_roster']}; delivery match-player-team keys absent={audit['delivery_participant_team_keys_absent_from_roster']}.",
            "finding": "IDs and team strings are internally joinable, but the local catalogs are not independently established as authoritative.",
            "handling": "Retain the clean join check as a data-quality result, not proof of XI validity.",
        },
        {
            "area": "Roster duplicate",
            "status": "VERIFIED_ANOMALY",
            "evidence": json.dumps(audit["cross_team_assignments"], sort_keys=True),
            "finding": "One player ID is assigned to both teams in match 1229824; no same-team duplicate key was observed.",
            "handling": "Flag this match-player assignment; obtain corrected source row or provenance.",
        },
        {
            "area": "Bowling-role flag provenance",
            "status": "UNKNOWN",
            "evidence": f"Combined player catalog row counts by bowls_flag={json.dumps(audit['bowls_flag_row_counts'], sort_keys=True)}; missing role flag players={audit['unique_roster_ids_with_missing_bowls_flag']}.",
            "finding": "The flag is not tied to a historical validity interval or documented source lineage.",
            "handling": "Do not impute role from delivery participation or absence.",
        },
        {
            "area": "Derived aggregates",
            "status": "PARTIALLY_DOCUMENTED",
            "evidence": "Career/phase README files document raw inputs and formulas; Phase 2 manifests document file hashes and local output summaries; matchup validation documents 42 situation duplicate rows removed.",
            "finding": "Some formula lineage is documented, but not every aggregate generator and upstream source is present; aggregates are all-history and unsafe as point-in-time predictors.",
            "handling": "Use Phase 9 raw-only date-cutoff feature pathway for future research, not precomputed full-history aggregates.",
        },
        {
            "area": "Wicket event derivation",
            "status": "PARTIALLY_DOCUMENTED",
            "evidence": f"wicket_events.csv contains {audit['wicket_event_rows']} rows and {audit['bowler_credited_wickets']} credited flags; Phase 9 independently validated delivery-key joins and event-level treatment.",
            "finding": "The exact local generator/extraction provenance for the derived package is not established by a package-specific source URL or license.",
            "handling": "Keep event data read-only and obtain the derivation script/source archive for full lineage.",
        },
        {
            "area": "Phase and format definitions",
            "status": "PARTIALLY_DOCUMENTED",
            "evidence": "Phase labels are present on deliveries; seven T20-labeled records have overs=50 and actual observed max over 19.",
            "finding": "Phase-generation rules and resolution of format metadata conflicts remain unknown.",
            "handling": "Preserve supplied phase labels; exclude known format anomalies as Phase 9 did.",
        },
    ]


def _outcome_rows() -> list[dict]:
    return [
        {
            "target": "Observed complete-over charged runs",
            "unit": "One complete observed over; actual historical bowler only.",
            "decision_time_and_horizon": "A hypothetical over-start could be used only if prior-delivery cutoff and expected legal-ball horizon are specified independently.",
            "formula": "Sum runs_batter + extra_wides + extra_noballs over the observed delivery rows.",
            "extras_and_dismissals": "Byes, leg-byes, and penalty extras are excluded from bowler-charged runs. Wickets do not alter this runs formula.",
            "coverage_and_missingness": "Require one match/innings/over/bowler and exactly the predeclared expected legal deliveries; incomplete innings/target/abandonment horizons return unavailable, not zero.",
            "observed_for_all_candidates": "No; only the bowler recorded on deliveries has an observed label.",
            "permitted_use": "Descriptive historical outcome only; not a general ranking target and not causal.",
        },
        {
            "target": "Observed complete-over bowler-credited wickets",
            "unit": "One complete observed over; actual historical bowler only.",
            "decision_time_and_horizon": "Same observed-over horizon as above; wicket event must join to a delivery in the target.",
            "formula": "Count each wicket_events row with is_bowler_credited=true and bowler_id matching the actual delivery bowler; preserve multiple events per delivery.",
            "extras_and_dismissals": "Run-outs and other non-bowler-credited dismissals are excluded; multiple distinct wicket events are counted event by event.",
            "coverage_and_missingness": "Missing event joins, duplicate event IDs, unknown credit flags, or incomplete legal-ball horizons produce unavailable labels.",
            "observed_for_all_candidates": "No; unused alternatives have no observed wicket label.",
            "permitted_use": "Descriptive historical outcome only; not a general ranking target and not causal.",
        },
        {
            "target": "Fixed N future legal deliveries, runs and wickets",
            "unit": "A predeclared decision point and actual selected bowler across a fixed N-legal-delivery horizon.",
            "decision_time_and_horizon": "Needs an exact pre-delivery sequence index and an agreed policy for over changes, innings end, target completion, interruption, and bowler changes.",
            "formula": "Runs use the charged-runs convention above; wickets count credited event rows only.",
            "extras_and_dismissals": "Wides/no-balls contribute charged extras but not legal-ball count; byes/leg-byes/penalties excluded from bowler runs; non-credited dismissals excluded from bowler wickets.",
            "coverage_and_missingness": "Only complete horizons can be labelled; if innings ends or target is achieved early, label is unavailable unless a separate truncated-horizon target is preregistered.",
            "observed_for_all_candidates": "No; only the selected bowler's realized outcome is present.",
            "permitted_use": "Descriptive selected-bowler analysis after protocol definition; not unbiased ranking or causal evidence.",
        },
        {
            "target": "Combined runs-and-wickets utility",
            "unit": "A decision point and candidate.",
            "decision_time_and_horizon": "Would require an agreed horizon and scientifically justified utility weights before evaluation.",
            "formula": "Not specified; no utility weights are supported by current evidence.",
            "extras_and_dismissals": "Must follow separately defined runs and wicket conventions above.",
            "coverage_and_missingness": "Unavailable unless both targets and the complete observation window exist.",
            "observed_for_all_candidates": "No.",
            "permitted_use": "Unsupported; do not calculate.",
        },
        {
            "target": "Past-only descriptive phase or matchup features",
            "unit": "Bowler or bowler-batter context at a specified decision time.",
            "decision_time_and_horizon": "Feature cutoff must precede the decision; same-day history is excluded by Phase 9 baseline, and same-match as-of features require a precise delivery order.",
            "formula": "Use raw deliveries, matches, and event-level wicket data; preserve supplied phase labels and existing validated scoring formula only.",
            "extras_and_dismissals": "Phase 9 formula uses legal-ball flag; runs_batter+wides+no-balls; event-level credited wickets.",
            "coverage_and_missingness": "Zero denominators remain unavailable/null; do not substitute zero.",
            "observed_for_all_candidates": "Feature coverage may differ; outcomes remain selected-bowler only.",
            "permitted_use": "Descriptive features; predictors only after exact decision-time availability and a candidate protocol are established.",
        },
    ]


def _risk_rows(audit: dict) -> list[dict]:
    return [
        {"risk_id": "R10-01", "severity": "BLOCKER", "risk": "Roster semantics and decision-time availability are not established.", "evidence": f"match_playing_xi contains only four identity columns; {audit['rows_without_match_participation']} rows lack same-match delivery participation.", "mitigation": "Acquire source documentation and time-stamped announced lineup, substitutes, replacements, and availability."},
        {"risk_id": "R10-02", "severity": "BLOCKER", "risk": "Quota/rules eligibility cannot be reconstructed.", "evidence": "No quota state at the proposed decision point; seven T20/overs metadata anomalies.", "mitigation": "Acquire format ruleset and decision-time legal overs remaining/penalty state."},
        {"risk_id": "R10-03", "severity": "BLOCKER", "risk": "Outcomes for unused candidates are unobserved.", "evidence": "Raw deliveries identify the actual bowler only.", "mitigation": "Use prospective shadow logging for decisions; no retrospective imputation of alternative outcomes."},
        {"risk_id": "R10-04", "severity": "HIGH", "risk": "Potential post-decision leakage if eventual participation is used as eligibility.", "evidence": "Delivery participation is an outcome after selection, not a recorded availability event.", "mitigation": "Enforce explicit decision-time evidence states and strict as-of feature construction."},
        {"risk_id": "R10-05", "severity": "HIGH", "risk": "Source and license provenance incomplete.", "evidence": "Ingestion manifest has local hashes/timestamps but no source URL or license.", "mitigation": "Obtain original source packages, citations, license, extraction logs, and stable player/team ID dictionaries."},
        {"risk_id": "R10-06", "severity": "MEDIUM", "risk": "Cross-team roster conflict and variable roster sizes.", "evidence": "One cross-team duplicate; match roster rows 21-25 and team rows 10-13.", "mitigation": "Flag conflicts; no source-row deletion or automatic correction."},
        {"risk_id": "R10-07", "severity": "MEDIUM", "risk": "Role flags are incomplete and undated.", "evidence": f"{audit['rows_with_missing_bowls_flag']} roster rows and {audit['unique_roster_ids_with_missing_bowls_flag']} unique players have missing bowls_flag.", "mitigation": "Acquire dated role-source fields; do not derive role from observed bowling."},
    ]


def _additional_data_rows() -> list[dict]:
    return [
        {"priority": 1, "data_required": "Official source semantics and provenance for match_playing_xi.csv", "minimum_fields": "Source URL/archive ID, extraction timestamp, license, row meaning, team/player ID dictionary, official status", "unblocks": "Interpret roster membership and trace data lineage", "acceptance_check": "Source owner confirms whether rows mean announced XI, squad, replacements, substitutes, or other; reproduce joins."},
        {"priority": 2, "data_required": "Decision-time availability and lineup changes", "minimum_fields": "Match/innings/decision timestamp, team, player_id, available status, announced XI status, substitute/replacement/withdrawal event and effective time", "unblocks": "Candidate membership and availability at each simulated decision", "acceptance_check": "Independent source with complete timestamped events and auditable coverage."},
        {"priority": 3, "data_required": "Bowling rules and candidate quota state", "minimum_fields": "Format/ruleset/version, scheduled balls per over, quota, candidate overs already bowled, penalties/restrictions, innings state", "unblocks": "Whether a candidate was legally permitted to bowl", "acceptance_check": "Recompute remaining quota using only pre-decision events; validate seven metadata anomalies."},
        {"priority": 4, "data_required": "Decision log or prospective shadow decision snapshots", "minimum_fields": "Exact decision time/index, complete eligible candidates, batter/context, current state, CRIC version/input, full ranked output, actual selection", "unblocks": "Auditable decision unit and prospective shadow evaluation", "acceptance_check": "Immutable append-only logs, versioned schema, missingness monitoring, no post-decision fields."},
        {"priority": 5, "data_required": "Preregistered target and evaluation protocol", "minimum_fields": "Outcome horizon, extras/wicket rules, incomplete-horizon policy, primary descriptive or ranking question, minimum sample, split and metrics", "unblocks": "A frozen analysis protocol", "acceptance_check": "Review and freeze before inspecting holdout outputs; causal claims require separate design."},
        {"priority": 6, "data_required": "Authoritative player-role and identity history", "minimum_fields": "Stable player ID, dated role/source, name/ID crosswalk, validity period", "unblocks": "Role-specific candidate criteria and resolution of identity anomalies", "acceptance_check": "Documented source, no role inferred from whether the player bowled."},
    ]


def _phase9_hash_by_path(baseline: dict) -> dict[str, str]:
    return {
        item["path"]: item["sha256"]
        for item in baseline["reproducibility"]["sources"].values()
    }


def _compact_examples(raw_examples: str) -> str:
    try:
        value = json.loads(raw_examples)
    except (TypeError, json.JSONDecodeError):
        return raw_examples
    if isinstance(value, list):
        value = value[:3]
    elif isinstance(value, dict):
        value = {
            key: item[:3] if isinstance(item, list) else item
            for key, item in value.items()
        }
    return json.dumps(value, sort_keys=True)


def _write_pdf(path: Path, audit: dict, anomalies: list[dict], candidates: list[dict],
               outcomes: list[dict], feasibility: list[dict], risks: list[dict],
               extra_data: list[dict], phase10_tests: str, regression_tests: str) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="P10Title", parent=styles["Title"], alignment=TA_CENTER, leading=19))
    styles.add(ParagraphStyle(name="P10Body", parent=styles["BodyText"], fontSize=8.5, leading=11))
    styles.add(ParagraphStyle(name="P10Small", parent=styles["BodyText"], fontSize=7.1, leading=8.5))

    def para(value: object, style: str = "P10Small") -> Paragraph:
        text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return Paragraph(text, styles[style])

    story = [
        Paragraph("CRIC PHASE 10 - HISTORICAL DECISION EVALUATION AUDIT", styles["P10Title"]),
        para("Primary status: B - LIMITED DESCRIPTIVE EVALUATION ONLY", "Heading2"),
        para("Historical ranking and counterfactual evaluation remain blocked. The available raw data supports descriptive summaries of events for the bowler actually used, but it does not identify a complete eligible candidate set or outcomes for unused alternatives.", "P10Body"),
        Spacer(1, 8),
        para("Executive summary", "Heading2"),
        para(f"Phase 10 rechecked the Phase 9 baseline and investigated roster joins, participation, role flags, source lineage, observed outcome semantics, and five evaluation designs. All {audit['roster_rows']:,} roster rows join locally to known match/player catalogs, but internal joins do not prove official lineup semantics. No decision-time availability or quota state is present. No predictive metrics were calculated.", "P10Body"),
        para("Phase 9 baseline and Phase 10 scope", "Heading2"),
        Table([
            [para("Baseline item"), para("Verified value")],
            [para("Matches / dates"), para(f"{audit['match_count']:,} matches; dates per Phase 9 protocol")],
            [para("Deliveries / legal deliveries"), para(f"{audit['delivery_rows']:,} / {audit['legal_deliveries']:,}")],
            [para("Wicket events / bowler credited"), para(f"{audit['wicket_event_rows']:,} / {audit['bowler_credited_wickets']:,}")],
            [para("Roster rows / matches"), para(f"{audit['roster_rows']:,} / {audit['matches_with_roster']:,}")],
            [para("Phase 9 tests / regression"), para(f"32 passed; 68 passed, per Phase 9 reproducibility manifest")],
            [para("Phase 9 formula checks / splits"), para("6/6 passed; 2,117 / 1,001 / 1,105 matches, 4,223 total")],
        ], colWidths=[2.1*inch, 4.3*inch], style=TableStyle([
            ("BACKGROUND", (0,0),(-1,0),colors.HexColor("#214761")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.3,colors.grey),
            ("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#EEF3F6")]),
        ])),
        para("Dataset inventory and provenance", "Heading2"),
        para("The CSV inventory records path, byte size, SHA-256, header, row count, candidate key, relevant null counts, provenance state, source role/type, and known transformations. The ingestion manifest records local path, size, checksum, modified timestamp, and validation status. Source URL, upstream extraction log, archive checksum, and license for the merged roster source are not established. The local Phase 2 lineage note documents aggregate formulas but not the origin or semantics of the XI table.", "P10Body"),
        para("Roster anomaly counts and examples", "Heading2"),
        Table(
            [[para("Finding"), para("Count/distribution"), para("Assessment / handling")]]
            + [
                [
                    para(item["finding"]),
                    para(item["exact_distribution"] + " Examples: " + _compact_examples(item["examples"])),
                    para(item["assessment"] + " Handling: " + item["action"]),
                ]
                for item in anomalies
            ],
            colWidths=[1.45*inch, 1.65*inch, 3.3*inch],
            style=TableStyle([
                ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#214761")),
                ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.25,colors.grey),
                ("VALIGN",(0,0),(-1,-1),"TOP"),("FONTSIZE",(0,0),(-1,-1),7),
                ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F4F6F7")]),
            ]),
        ),
        Spacer(1, 5),
        para("Examples are preserved in CRIC_Phase10_Roster_Anomalies.csv. Match 1229824 contains player efcb778e assigned to both Guernsey and Isle of Man. No same-team duplicate was found. Roster rows without delivery participation are not treated as proof of absence or ineligibility.", "P10Body"),
        para("Candidate eligibility framework", "Heading2"),
        Table(
            [[para("Concept"), para("Status"), para("Required evidence / conclusion")]]
            + [[para(row["concept"]), para(row["current_status"]), para(row["local_evidence"] + " " + row["primary_evaluation_use"])] for row in candidates],
            colWidths=[1.45*inch, 1.25*inch, 3.7*inch],
            style=TableStyle([
                ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#214761")),
                ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.25,colors.grey),
                ("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#EEF3F6")]),
            ]),
        ),
        para("Outcome definitions and scoring semantics", "Heading2"),
        para("A complete observed over can be summarized for its recorded bowler only. Charged runs are runs_batter + extra_wides + extra_noballs on every delivery; byes, leg-byes, and penalty extras are excluded. Wickets count event-by-event only when is_bowler_credited is true and event bowler matches the delivery bowler. Incomplete legal-ball horizons are unavailable, not zero. These outcomes are selected-bowler descriptions, not labels for unused alternatives.", "P10Body"),
        Table(
            [[para("Target"), para("Permitted interpretation"), para("Coverage limitation")]]
            + [[para(row["target"]), para(row["permitted_use"]), para(row["coverage_and_missingness"])] for row in outcomes],
            colWidths=[1.6*inch, 2.2*inch, 2.6*inch],
            style=TableStyle([
                ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#214761")),
                ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.25,colors.grey),
                ("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F4F6F7")]),
            ]),
        ),
        para("Leakage and selection-bias assessment", "Heading2"),
        para("Phase 9's date-grouped 60/20/20 split is preserved as a protocol baseline; no final-holdout ranking run was performed. Phase 9 features use only earlier match dates and exclude same-day matches. For decision-level simulation within a match, the cutoff must instead be an exact pre-delivery index and may not include the current/future delivery. Eventual bowling participation is a post-selection variable, and outcomes for unused candidates are unobserved. Candidate-relative recommendation scores are not probabilities.", "P10Body"),
        para("Feasibility of the five evaluation designs", "Heading2"),
        Table(
            [[para("Design"), para("Status"), para("Evidence and claim limit")]]
            + [[para(row["design"]), para(row["current_status"]), para(row["evidence"] + " " + row["permitted_claim"])] for row in feasibility],
            colWidths=[1.45*inch, 1.45*inch, 3.5*inch],
            style=TableStyle([
                ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#214761")),
                ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.25,colors.grey),
                ("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#EEF3F6")]),
            ]),
        ),
        para("Automated tests, resolved and unresolved issues", "Heading2"),
        para(f"Phase 10 tests: {phase10_tests}. Existing regression suite: {regression_tests}. The isolated code audits source metadata and roster anomalies, represents evidence as confirmed/contradicted/unknown, summarizes only complete observed overs for the actual bowler, and fails closed when candidate or label prerequisites are missing. Resolved: local join/duplicate/participation counts and provenance gaps are quantified. Unresolved: authoritative roster meaning, decision-time availability, quota/rules state, source license, and all unused-candidate outcomes.", "P10Body"),
        para("Exact additional data needed", "Heading2"),
        Table(
            [[para("Priority"), para("Required evidence"), para("Purpose")]]
            + [[para(row["priority"]), para(row["data_required"]), para(row["unblocks"])] for row in extra_data],
            colWidths=[0.55*inch, 3.0*inch, 2.85*inch],
            style=TableStyle([
                ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#214761")),
                ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.25,colors.grey),
                ("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F4F6F7")]),
            ]),
        ),
        para("Reproducibility, limitations, and next steps", "Heading2"),
        para("Run from C:\\CRIC with python -m evaluation.phase10.run_phase10 after reviewing the code and confirming a new output directory will be created. The report directory is unique and never overwrites an earlier run. Check CRIC_Phase10_Reproducibility.json for Python/platform and script/source hashes, and CRIC_Phase10_Source_Hash_Check.csv for before/after source integrity. Status B permits descriptive history only; do not tune or calculate ranking metrics until the required candidate and decision logs are available.", "P10Body"),
    ]
    document = SimpleDocTemplate(
        str(path), pagesize=letter, rightMargin=0.45*inch, leftMargin=0.45*inch,
        topMargin=0.45*inch, bottomMargin=0.45*inch,
    )
    document.build(story)


def run_phase10(phase10_tests: str, regression_tests: str, compile_result: str) -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = PROJECT_ROOT / "reports" / f"phase10_{run_id}"
    suffix = 2
    while base.exists():
        base = PROJECT_ROOT / "reports" / f"phase10_{run_id}_{suffix:02d}"
        suffix += 1
    output = base
    output.mkdir(parents=False)

    baseline = load_phase9_baseline(PHASE9_ROOT)
    source_hashes_before = hash_tree(DATA_ROOT)
    paths = _source_paths()
    audit = audit_roster(paths)
    inventory = source_inventory(PROJECT_ROOT)
    anomalies = roster_anomaly_rows(audit)
    candidates = _candidate_eligibility_rows(audit)
    provenance = _provenance_rows(audit)
    outcomes = _outcome_rows()
    feasibility = evaluation_feasibility()
    risks = _risk_rows(audit)
    additional_data = _additional_data_rows()
    protocol = phase10_protocol(baseline)
    gate = {
        "eligible_candidate_universe_supported": False,
        "decision_time_features_supported": False,
        "labels_observed_for_all_candidates": False,
        "status": "BLOCKED",
        "blockers": [
            "decision-time eligible candidate universe is unsupported",
            "decision-time features for an intra-match selection are not established",
            "outcomes are not observed for every eligible candidate",
        ],
        "metrics": {},
    }
    protocol["evaluation_gate"] = gate
    protocol["five_designs"] = feasibility

    _write_csv(
        output / "CRIC_Phase10_Source_Inventory.csv",
        ["relative_path", "format", "byte_size", "sha256", "header", "row_count", "candidate_key",
         "relevant_null_counts", "provenance_status", "source_role", "source_type", "transformation_history"],
        inventory,
    )
    _write_csv(
        output / "CRIC_Phase10_Roster_Anomalies.csv",
        ["finding", "affected_rows", "affected_players", "affected_matches", "exact_distribution", "examples", "assessment", "action"],
        anomalies,
    )
    _write_csv(
        output / "CRIC_Phase10_Candidate_Eligibility_Audit.csv",
        ["concept", "formal_definition", "required_source_columns", "current_status", "local_evidence",
         "leakage_or_bias", "primary_evaluation_use"],
        candidates,
    )
    _write_csv(
        output / "CRIC_Phase10_Provenance_Findings.csv",
        ["area", "status", "evidence", "finding", "handling"],
        provenance,
    )
    _write_csv(
        output / "CRIC_Phase10_Outcome_Definitions.csv",
        ["target", "unit", "decision_time_and_horizon", "formula", "extras_and_dismissals",
         "coverage_and_missingness", "observed_for_all_candidates", "permitted_use"],
        outcomes,
    )
    _write_csv(
        output / "CRIC_Phase10_Evaluation_Feasibility.csv",
        ["design", "current_status", "supported_question", "evidence", "limitation", "permitted_claim"],
        feasibility,
    )
    _write_csv(
        output / "CRIC_Phase10_Risk_Register.csv",
        ["risk_id", "severity", "risk", "evidence", "mitigation"],
        risks,
    )
    _write_csv(
        output / "CRIC_Phase10_Required_Additional_Data.csv",
        ["priority", "data_required", "minimum_fields", "unblocks", "acceptance_check"],
        additional_data,
    )
    _write_json(output / "CRIC_Phase10_Chronological_Protocol.json", protocol)

    phase9_hashes = _phase9_hash_by_path(baseline)
    source_hashes_after = hash_tree(DATA_ROOT)
    hash_rows = []
    for relative_path in sorted(set(source_hashes_before) | set(source_hashes_after)):
        before = source_hashes_before.get(relative_path)
        after = source_hashes_after.get(relative_path)
        absolute_path = str(DATA_ROOT / Path(relative_path))
        phase9_hash = phase9_hashes.get(absolute_path, "")
        hash_rows.append({
            "relative_path": relative_path,
            "before_bytes": before["bytes"] if before else "",
            "after_bytes": after["bytes"] if after else "",
            "before_sha256": before["sha256"] if before else "",
            "after_sha256": after["sha256"] if after else "",
            "phase9_sha256": phase9_hash,
            "phase9_hash_comparison": (
                "NOT_RECORDED_IN_PHASE9"
                if not phase9_hash
                else "MATCH"
                if phase9_hash.casefold() == (before or {}).get("sha256", "").casefold()
                else "DIFFERS_FROM_PHASE9"
            ),
            "audit_integrity": "UNCHANGED" if before and after and before == after else "CHANGED_OR_MISSING",
        })
    _write_csv(
        output / "CRIC_Phase10_Source_Hash_Check.csv",
        ["relative_path", "before_bytes", "after_bytes", "before_sha256", "after_sha256",
         "phase9_sha256", "phase9_hash_comparison", "audit_integrity"],
        hash_rows,
    )

    test_results = (
        f"Phase 10: {phase10_tests}\n"
        f"Existing regression suite: {regression_tests}\n"
        f"Python compilation: {compile_result}\n"
        f"Source hash check: {'PASS' if all(row['audit_integrity'] == 'UNCHANGED' for row in hash_rows) else 'FAIL'} across {len(hash_rows)} files under data/.\n"
        "No predictive metrics were calculated; evaluation gate is BLOCKED.\n"
    )
    (output / "CRIC_Phase10_Test_Results.txt").write_text(test_results, encoding="utf-8")

    source_counts = {
        "matches": audit["match_count"],
        "deliveries": audit["delivery_rows"],
        "legal_deliveries": audit["legal_deliveries"],
        "wicket_events": audit["wicket_event_rows"],
        "bowler_credited_wickets": audit["bowler_credited_wickets"],
        "roster_rows": audit["roster_rows"],
        "roster_matches": audit["matches_with_roster"],
    }
    summary = f"""CRIC PHASE 10 - HISTORICAL DECISION EVALUATION AUDIT
Run ID: {output.name.removeprefix('phase10_')}
Project: C:\\CRIC

PRIMARY STATUS
B - LIMITED DESCRIPTIVE EVALUATION ONLY.

Historical ranking and counterfactual evaluation are blocked. The data can support descriptive summaries of observed deliveries and outcomes for the bowler actually used. It does not establish an eligible alternative-candidate set, availability at decision time, bowling quota state, or labels for unused bowlers. No predictive metrics, confidence intervals, or causal claims were calculated.

PHASE 9 BASELINE
Phase 9 outputs were inspected and independently loaded. Tests recorded: 32 Phase 9 tests passed; 68 existing regression tests passed. Six of six formula checks passed. Date-grouped splits were 2,117 development, 1,001 validation, and 1,105 final-holdout matches: 4,223 unique matches. Seven T20/50-over metadata anomalies were excluded. The Phase 9 report contains no predictive metrics.

PHASE 10 COUNTS
{json.dumps(source_counts, indent=2)}
Roster match row-count distribution: {json.dumps(audit['match_roster_row_counts'], sort_keys=True)}
Per-team roster row-count distribution: {json.dumps(audit['team_roster_size_counts'], sort_keys=True)}
Roster rows with no same-match batter/bowler delivery participation: {audit['rows_without_match_participation']}.
Unique roster IDs absent from all delivery records: {audit['unique_roster_ids_absent_from_all_deliveries']}.
Duplicate match/player extra rows: {audit['duplicate_match_player_extra_rows']}; cross-team assignments: {json.dumps(audit['cross_team_assignments'], sort_keys=True)}; same-team duplicates: {json.dumps(audit['same_team_duplicate_keys'], sort_keys=True)}.
Rows with missing bowls_flag: {audit['rows_with_missing_bowls_flag']}; unique roster IDs with missing role flag: {audit['unique_roster_ids_with_missing_bowls_flag']}.
Unknown match/player IDs and roster team mismatches: {audit['unknown_match_rows']}/{audit['unknown_player_rows']}/{audit['wrong_team_rows']}. Delivery participants without a same-match roster row: {audit['delivery_participant_match_keys_absent_from_roster']}; with no same-team roster key: {audit['delivery_participant_team_keys_absent_from_roster']}.

PROVENANCE
Local ingestion metadata provides local paths, file sizes, SHA-256 checksums, modified timestamps, and validation status. External origin, source URL, license, official status, and extraction lineage for match_playing_xi.csv are unknown/not established. The table only has match_id, team, player_id, player_name. Its clean joins do not establish announced-XI semantics.

ELIGIBILITY AND OUTCOMES
Team membership is supported by local rows but roster semantics remain uncertain. Decision-time availability and permission to bowl are unknown. Bowling-role flags are undated and missing for some rows. Historical actual bowling is an observed outcome, not evidence of prior eligibility. Descriptive over outcome semantics are documented in CSV; incomplete horizons are unavailable, never zero. Only actual bowler outcomes are observed.

EVALUATION FEASIBILITY
Historical descriptive analysis: feasible with selection limits.
Retrospective ranking: blocked.
Counterfactual evaluation: blocked.
Prospective shadow: feasible after decision-snapshot and recommendation logging.
Prospective intervention: not ready; requires a preregistered governed design.

TESTS
{phase10_tests}
{regression_tests}
No predictive ranking metrics were calculated.

NEXT REQUIRED DATA
Obtain official roster semantics/provenance and license; timestamped XI, availability, substitution/replacement events; format rules and decision-time quota state; immutable candidate/decision/recommendation/actual-selection logs; and a frozen, reviewed outcome protocol. Do not infer missing evidence from later bowling participation.

PRESERVATION
Source hashes under data/ were compared before and after this run. Source data, HDFS, infrastructure settings, production scoring/API/frontend, and Phase 2-9 code were not modified by Phase 10.
"""
    (output / "CRIC_Phase10_Summary.txt").write_text(summary, encoding="utf-8")

    _write_pdf(
        output / "CRIC_Phase10_Audit_Report.pdf",
        audit, anomalies, candidates, outcomes, feasibility, risks, additional_data,
        phase10_tests, regression_tests,
    )

    reproducibility = {
        "run_id": output.name.removeprefix("phase10_"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(PROJECT_ROOT),
        "python_version": sys.version,
        "platform": platform.platform(),
        "primary_status": "B — LIMITED DESCRIPTIVE EVALUATION ONLY",
        "historical_ranking_evaluation": "BLOCKED",
        "evaluation_gate": gate,
        "source_counts": source_counts,
        "phase9_baseline": protocol["phase9_baseline"],
        "source_hashes_unchanged": all(row["audit_integrity"] == "UNCHANGED" for row in hash_rows),
        "data_file_count_hashed_before_after": len(hash_rows),
        "phase10_test_result": phase10_tests,
        "regression_test_result": regression_tests,
        "phase10_script_sha256": {
            path.relative_to(PROJECT_ROOT).as_posix(): sha256_file(path)
            for path in sorted((PROJECT_ROOT / "evaluation" / "phase10").rglob("*.py"))
            if path.is_file()
        },
        "phase9_source_sha256": _phase9_hash_by_path(baseline),
        "artifacts": [],
        "limitations": [
            "Playing-XI source origin, license, official status, and semantic meaning are not established.",
            "Decision-time availability and bowling-quota state are absent.",
            "Outcomes are observed only for actual historical bowlers.",
            "No retrospective ranking, counterfactual, causal, or final-holdout metrics were calculated.",
        ],
    }
    reproducibility["artifacts"] = sorted(path.name for path in output.iterdir())
    _write_json(output / "CRIC_Phase10_Reproducibility.json", reproducibility)
    print(f"Phase 10 artifacts written to {output}")
    print(f"Primary status: {reproducibility['primary_status']}")
    print(f"Roster rows without participation={audit['rows_without_match_participation']}; missing role IDs={audit['unique_roster_ids_with_missing_bowls_flag']}; source hashes unchanged={reproducibility['source_hashes_unchanged']}")
    print("Ranking metrics: not calculated; evaluation gate BLOCKED")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase10-tests", required=True)
    parser.add_argument("--regression-tests", required=True)
    parser.add_argument("--compile-result", required=True)
    args = parser.parse_args()
    run_phase10(args.phase10_tests, args.regression_tests, args.compile_result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
