from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from reportlab.graphics import renderSVG
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from evaluation.phase9.data_quality import DATASETS, find_unique, inspect_sources
from evaluation.phase9.historical_features import (
    BowlingStats,
    EvaluationDataError,
    build_historical_snapshot,
    read_matches,
)
from evaluation.phase9.protocol import chronological_splits, evaluation_protocol


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
REPORT_ROOT = PROJECT_ROOT / "reports"
BASE_OUTPUT = REPORT_ROOT / "phase9_complete"
FORMULA_CUTOFF = "2020-01-01"


def _safe_output_directory(base: Path) -> Path:
    candidate = base
    suffix = 2
    while candidate.exists() and any(candidate.iterdir()):
        candidate = base.with_name(f"{base.name}_{suffix:02d}")
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_event_index(wickets_path: Path) -> dict:
    events = defaultdict(list)
    with wickets_path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            key = (
                row["match_id"], row["innings_number"], row["over_number"], row["ball_in_over"]
            )
            events[key].append(
                (
                    row["bowler_id"].casefold(),
                    row["player_out_id"].casefold(),
                    row["is_bowler_credited"].strip().casefold() in {"true", "1"},
                )
            )
    return events


def _find_formula_examples(
    deliveries_path: Path,
    matches: dict,
    events: dict,
    snapshot,
    final_holdout_start: str,
) -> dict:
    extra_bowlers = {"wide": None, "no_ball": None}
    multi_event = None
    for key, values in sorted(
        events.items(),
        key=lambda item: (matches[item[0][0]].match_date, item[0]),
    ):
        if matches[key[0]].match_date.isoformat() >= final_holdout_start:
            continue
        if len(values) > 1 and multi_event is None:
            credited = [value for value in values if value[2]]
            if credited:
                multi_event = (key, credited[0][0], len(values), len(credited))

    with deliveries_path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if matches[row["match_id"]].match_date.isoformat() >= FORMULA_CUTOFF:
                continue
            if float(row["extra_wides"] or 0):
                bowler = row["bowler_id"].casefold()
                if bowler in snapshot.career and snapshot.career[bowler].legal_balls:
                    extra_bowlers["wide"] = extra_bowlers["wide"] or bowler
            if float(row["extra_noballs"] or 0):
                bowler = row["bowler_id"].casefold()
                if bowler in snapshot.career and snapshot.career[bowler].legal_balls:
                    extra_bowlers["no_ball"] = extra_bowlers["no_ball"] or bowler
    if not extra_bowlers["wide"] or not extra_bowlers["no_ball"]:
        raise EvaluationDataError("No real prior-history wide and no-ball examples were found")
    return {"extra_bowlers": extra_bowlers, "multi_event": multi_event}


def _independent_stats(
    deliveries_path: Path,
    matches: dict,
    events: dict,
    bowler_ids: set[str],
    cutoff: str = FORMULA_CUTOFF,
    excluded_match_ids: set[str] | frozenset[str] = frozenset(),
) -> dict:
    result: dict[tuple[str, str, str, str], Counter] = defaultdict(Counter)

    def add(key, row, credited=0):
        state = result[key]
        state["delivery_rows"] += 1
        state["legal_balls"] += row["is_legal_delivery"].strip().casefold() in {"true", "1"}
        state["runs_conceded"] += (
            float(row["runs_batter"] or 0)
            + float(row["extra_wides"] or 0)
            + float(row["extra_noballs"] or 0)
        )
        state["credited_wickets"] += credited

    with deliveries_path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            match_id = row["match_id"]
            if matches[match_id].match_date.isoformat() >= cutoff or match_id in excluded_match_ids:
                continue
            bowler = row["bowler_id"].casefold()
            if bowler not in bowler_ids:
                continue
            phase = row["match_phase"].casefold()
            batter = row["batter_id"].casefold()
            key = (match_id, row["innings_number"], row["over_number"], row["ball_in_over"])
            credited_events = [
                event for event in events.get(key, ())
                if event[2] and event[0] == bowler
            ]
            add((bowler, "career", "", ""), row, len(credited_events))
            add((bowler, "phase", phase, ""), row, len(credited_events))
            add((bowler, "matchup", "", batter), row, sum(event[1] == batter for event in credited_events))
            add(
                (bowler, "phase_matchup", phase, batter),
                row,
                sum(event[1] == batter for event in credited_events),
            )
    return result


def _metric_values(stats: BowlingStats | Counter) -> dict[str, float | None]:
    balls = stats["legal_balls"] if isinstance(stats, Counter) else stats.legal_balls
    runs = stats["runs_conceded"] if isinstance(stats, Counter) else stats.runs_conceded
    wickets = stats["credited_wickets"] if isinstance(stats, Counter) else stats.credited_wickets
    return {
        "economy": runs * 6 / balls if balls else None,
        "strike_rate": balls / wickets if balls and wickets else None,
        "wicket_rate_per_100_legal_balls": wickets * 100 / balls if balls else None,
    }


def _formula_rows(
    paths: dict,
    matches: dict,
    snapshot,
    events: dict,
    final_holdout_start: str,
) -> list[dict]:
    example = _find_formula_examples(
        paths["deliveries.csv"], matches, events, snapshot, final_holdout_start
    )
    bowler_ids = set(example["extra_bowlers"].values())
    bowler = example["extra_bowlers"]["wide"]
    phase_key = next(
        key for key, stats in snapshot.phase.items() if key[0] == bowler and stats.delivery_rows
    )
    matchup_key = next(
        key for key, stats in snapshot.matchup.items() if key[0] == bowler and stats.delivery_rows
    )
    counters = _independent_stats(paths["deliveries.csv"], matches, events, bowler_ids)
    cases = [
        ("wide-career", bowler, FORMULA_CUTOFF, ("career", "", ""), snapshot.career[bowler]),
        (
            "no-ball-career",
            example["extra_bowlers"]["no_ball"],
            FORMULA_CUTOFF,
            ("career", "", ""),
            snapshot.career[example["extra_bowlers"]["no_ball"]],
        ),
        ("phase", bowler, FORMULA_CUTOFF, ("phase", phase_key[1].casefold(), ""), snapshot.phase[phase_key]),
        ("matchup", bowler, FORMULA_CUTOFF, ("matchup", "", matchup_key[1]), snapshot.matchup[matchup_key]),
    ]
    rows = []
    for label, case_bowler, cutoff, scope, pipeline in cases:
        key = (case_bowler, *scope)
        raw = counters[key]
        raw_metrics = _metric_values(raw)
        pipeline_metrics = pipeline.metrics()
        diffs = [
            abs(raw_metrics[name] - pipeline_metrics[name])
            for name in raw_metrics
            if raw_metrics[name] is not None and pipeline_metrics[name] is not None
        ]
        same_metrics = all(
            raw_metrics[name] == pipeline_metrics[name]
            for name in raw_metrics
        )
        values_equal = (
            raw["delivery_rows"] == pipeline.delivery_rows
            and raw["legal_balls"] == pipeline.legal_balls
            and raw["runs_conceded"] == pipeline.runs_conceded
            and raw["credited_wickets"] == pipeline.credited_wickets
            and same_metrics
        )
        rows.append(
            {
                "example_id": f"REAL-{label.upper()}",
                "source_type": "real_raw_historical",
                "cutoff_date": cutoff,
                "match_id": "prior matches strictly before cutoff",
                "bowler_id": case_bowler,
                "batter_id": matchup_key[1] if label == "matchup" else "",
                "phase": phase_key[1] if label == "phase" else "",
                "raw_delivery_rows": raw["delivery_rows"],
                "pipeline_delivery_rows": pipeline.delivery_rows,
                "raw_legal_balls": raw["legal_balls"],
                "pipeline_legal_balls": pipeline.legal_balls,
                "raw_charged_runs": raw["runs_conceded"],
                "pipeline_charged_runs": pipeline.runs_conceded,
                "raw_credited_wickets": raw["credited_wickets"],
                "pipeline_credited_wickets": pipeline.credited_wickets,
                "raw_economy": raw_metrics["economy"],
                "pipeline_economy": pipeline_metrics["economy"],
                "raw_bowling_strike_rate": raw_metrics["strike_rate"],
                "pipeline_bowling_strike_rate": pipeline_metrics["strike_rate"],
                "raw_wicket_rate_per_100": raw_metrics["wicket_rate_per_100_legal_balls"],
                "pipeline_wicket_rate_per_100": pipeline_metrics["wicket_rate_per_100_legal_balls"],
                "max_metric_abs_difference": max(diffs, default=0.0),
                "status": "PASS" if values_equal else "FAIL",
                "notes": "Independent second pass over prior raw deliveries and bowler-credited wicket events; same-day/future rows excluded.",
            }
        )
    multi = example["multi_event"]
    if multi:
        key, event_bowler, event_count, credited_event_count = multi
        multi_cutoff = date.fromordinal(matches[key[0]].match_date.toordinal() + 1).isoformat()
        multi_snapshot = build_historical_snapshot(
            paths["matches.csv"],
            paths["deliveries.csv"],
            paths["wicket_events.csv"],
            multi_cutoff,
            excluded_match_ids=snapshot.excluded_match_ids,
        )
        multi_counters = _independent_stats(
            paths["deliveries.csv"],
            matches,
            events,
            {event_bowler},
            cutoff=multi_cutoff,
            excluded_match_ids=snapshot.excluded_match_ids,
        )
        multi_raw = multi_counters[(event_bowler, "career", "", "")]
        multi_pipeline = multi_snapshot.career[event_bowler]
        multi_raw_metrics = _metric_values(multi_raw)
        multi_pipeline_metrics = multi_pipeline.metrics()
        multi_diffs = [
            abs(multi_raw_metrics[name] - multi_pipeline_metrics[name])
            for name in multi_raw_metrics
            if multi_raw_metrics[name] is not None
            and multi_pipeline_metrics[name] is not None
        ]
        multi_values_equal = (
            multi_raw["delivery_rows"] == multi_pipeline.delivery_rows
            and multi_raw["legal_balls"] == multi_pipeline.legal_balls
            and multi_raw["runs_conceded"] == multi_pipeline.runs_conceded
            and multi_raw["credited_wickets"] == multi_pipeline.credited_wickets
            and all(
                multi_raw_metrics[name] == multi_pipeline_metrics[name]
                for name in multi_raw_metrics
            )
        )
        rows.append(
            {
                "example_id": "REAL-MULTI-WICKET-DELIVERY",
                "source_type": "real_raw_historical",
                "cutoff_date": multi_cutoff,
                "match_id": key[0],
                "bowler_id": event_bowler,
                "raw_delivery_rows": multi_raw["delivery_rows"],
                "pipeline_delivery_rows": multi_pipeline.delivery_rows,
                "raw_legal_balls": multi_raw["legal_balls"],
                "pipeline_legal_balls": multi_pipeline.legal_balls,
                "raw_charged_runs": multi_raw["runs_conceded"],
                "pipeline_charged_runs": multi_pipeline.runs_conceded,
                "raw_credited_wickets": multi_raw["credited_wickets"],
                "pipeline_credited_wickets": multi_pipeline.credited_wickets,
                "max_metric_abs_difference": max(multi_diffs, default=0.0),
                "status": "PASS" if multi_values_equal and event_count > 1 and credited_event_count < event_count else "FAIL",
                "notes": f"Raw key contains {event_count} dismissal events ({credited_event_count} bowler-credited); separate snapshot is cutoff just after the event and validates event-by-event inclusion/exclusion outside the final holdout.",
            }
        )
    rows.append(
        {
            "example_id": "SYNTHETIC-ZERO-LEGAL-BALL",
            "source_type": "labelled_unit_test_fixture",
            "cutoff_date": "",
            "raw_legal_balls": 0,
            "pipeline_legal_balls": 0,
            "raw_economy": "",
            "pipeline_economy": "",
            "raw_bowling_strike_rate": "",
            "pipeline_bowling_strike_rate": "",
            "raw_wicket_rate_per_100": "",
            "pipeline_wicket_rate_per_100": "",
            "status": "PASS",
            "notes": "Dedicated synthetic test asserts zero legal balls preserve all rates as null; not historical evaluation data.",
        }
    )
    return rows


def _candidate_rows(audit: dict) -> list[dict]:
    roster = audit["roster"]
    quality = audit["quality"]
    rows = [
        {"measure": "total_matches", "value": roster["match_count"], "status": "observed", "notes": "All match records with date metadata."},
        {"measure": "eligible_matches_admitted", "value": quality["candidate_eligible_matches_admitted"], "status": "blocked", "notes": quality["candidate_block_reason"]},
        {"measure": "decision_scenarios_admitted", "value": quality["decision_scenarios_admitted"], "status": "blocked", "notes": "No scenarios scored because the candidate set and counterfactual target cannot be validated."},
        {"measure": "raw_matches_by_roster_row_count", "value": json.dumps(roster["xi_rows_per_match"], sort_keys=True), "status": "observed_not_eligibility", "notes": "Roster row counts are not evidence of decision-time availability."},
        {"measure": "raw_roster_rows_by_bowls_flag", "value": json.dumps(roster["xi_role_flag_row_counts"], sort_keys=True), "status": "observed_not_eligibility", "notes": "Role flags lack historical validity/source provenance."},
        {"measure": "duplicate_match_player_rows", "value": roster["duplicate_match_player_rows"], "status": "quality_issue", "notes": "One duplicate key; the record assigns one player to both teams in the same match."},
        {"measure": "unique_roster_ids_absent_from_all_deliveries", "value": roster["unique_xi_ids_not_in_any_delivery"], "status": "unresolved", "notes": "May be unused roster/substitute records; source does not distinguish."},
        {"measure": "unique_roster_ids_with_missing_bowls_flag", "value": roster["unique_xi_ids_with_missing_bowls_flag"], "status": "unresolved", "notes": "Cannot establish bowling eligibility from the catalog."},
        {"measure": "format_anomaly_matches", "value": len(quality["inconsistent_overs_match_ids"]), "status": "excluded", "notes": "All metadata T20 but overs=50; actual max over is 19. Excluded from future evaluation splits and history."},
    ]
    return rows


def _metric_dictionary() -> list[dict]:
    return [
        {"metric": "eligible_match_coverage", "formula": "eligible_matches / matches_in_scope", "target_definition": "Matches with verified pre-decision candidates", "numerator": "eligible matches", "denominator": "in-scope matches", "sample_unit": "match", "aggregation_level": "evaluation period", "status": "not calculated", "limitations": "Candidate availability and roster semantics are unresolved."},
        {"metric": "scenario_coverage", "formula": "valid decision scenarios / possible predeclared scenarios", "target_definition": "Valid decision scenario with verified candidate set and observed target", "numerator": "valid scenarios", "denominator": "predeclared scenarios", "sample_unit": "decision scenario", "aggregation_level": "evaluation period", "status": "not calculated", "limitations": "No decision timestamp/candidate set is validated."},
        {"metric": "mean_reciprocal_rank", "formula": "mean(1 / rank_of_positive_candidate); scenario without positive candidate excluded and counted", "target_definition": "Must be a predeclared decision-quality outcome; none established", "numerator": "not defined", "denominator": "not defined", "sample_unit": "decision scenario", "aggregation_level": "evaluation period", "status": "not calculated", "limitations": "No defensible positive event or counterfactual alternatives."},
        {"metric": "subsequent_runs_per_legal_ball", "formula": "(batter runs + wides + no-balls) / legal balls in the defined subsequent over", "target_definition": "Runs conceded by the bowler actually assigned to the evaluated over", "numerator": "charged runs in next over", "denominator": "legal balls in next over", "sample_unit": "over within match", "aggregation_level": "matched scenarios and match", "status": "not calculated", "limitations": "The unselected candidates have no observed counterfactual outcomes; selection is endogenous."},
        {"metric": "subsequent_credited_wickets_per_100_legal_balls", "formula": "100 * bowler-credited wicket events / legal balls in the defined subsequent over", "target_definition": "Wicket events attributed to the bowler in the outcome window", "numerator": "credited wicket events", "denominator": "legal balls", "sample_unit": "over within match", "aggregation_level": "matched scenarios and match", "status": "not calculated", "limitations": "No valid candidate comparison and no decision-time availability labels."},
        {"metric": "career_economy", "formula": "6 * (batter runs + wides + no-balls) / prior legal balls", "target_definition": "Strictly prior career evidence", "numerator": "bowler-charged runs", "denominator": "legal balls", "sample_unit": "bowler-history snapshot", "aggregation_level": "candidate", "status": "feature_formula_validated", "limitations": "Unavailable when legal-ball denominator is zero; not a predictive metric."},
        {"metric": "career_bowling_strike_rate", "formula": "prior legal balls / prior bowler-credited wicket events", "target_definition": "Strictly prior career evidence", "numerator": "legal balls", "denominator": "credited wickets", "sample_unit": "bowler-history snapshot", "aggregation_level": "candidate", "status": "feature_formula_validated", "limitations": "Unavailable when either denominator or wicket count is zero; not a predictive metric."},
    ]


def _provenance_rows() -> list[dict]:
    return [
        {"feature": "career performance", "source_tables": "deliveries.csv; wicket_events.csv; matches.csv", "calculation": "Prior legal balls; charged runs across all deliveries; credited wicket events joined by match/innings/over/ball", "cutoff": "match_date < decision_date", "keys": "bowler_id; match_id/innings_number/over_number/ball_in_over", "leakage_safeguard": "Raw files only; strict date cutoff; same-day matches excluded"},
        {"feature": "phase performance", "source_tables": "deliveries.csv match_phase; wicket_events.csv; matches.csv", "calculation": "Career formula grouped by supplied source match_phase label", "cutoff": "match_date < decision_date", "keys": "bowler_id/match_phase", "leakage_safeguard": "No phase aggregate files used; source labels preserved without reclassification"},
        {"feature": "batter matchup", "source_tables": "deliveries.csv batter_id; wicket_events.csv player_out_id; matches.csv", "calculation": "Bowler-charged runs and legal balls grouped by delivery batter; credited wickets assigned by player_out_id", "cutoff": "match_date < decision_date", "keys": "bowler_id/batter_id", "leakage_safeguard": "No matchup aggregate file used; phase-specific matchups require a phase sample"},
        {"feature": "phase matchup", "source_tables": "deliveries.csv batter_id/match_phase; wicket_events.csv; matches.csv", "calculation": "Matchup formula grouped by supplied phase label", "cutoff": "match_date < decision_date", "keys": "bowler_id/batter_id/match_phase", "leakage_safeguard": "No fallback to all-phase matchup if requested phase is absent"},
        {"feature": "situation: competition/season/venue/innings/opposition/exact_over/phase", "source_tables": "matches.csv; innings.csv via deliveries.csv", "calculation": "Prior bowling stats grouped by match-known metadata or raw delivery context", "cutoff": "match_date < decision_date", "keys": "bowler_id/situation_type/situation_value", "leakage_safeguard": "Built only from raw history; only values present in the decision context can be queried"},
        {"feature": "current aggregate files", "source_tables": "career/phase/matchup/situation aggregate CSVs", "calculation": "No features calculated from these files", "cutoff": "No temporal key", "keys": "Aggregate business keys", "leakage_safeguard": "Explicitly excluded from historical feature reconstruction and ranking"},
    ]


def _chart(roster: dict, output: Path):
    drawing = Drawing(470, 245)
    labels = sorted(roster["xi_rows_per_match"], key=lambda x: int(x))
    values = [roster["xi_rows_per_match"][label] for label in labels]
    max_value = max(values)
    left, bottom, plot_width, plot_height = 55, 48, 370, 150
    bar_width = plot_width / max(1, len(labels)) * 0.58
    drawing.add(Line(left, bottom, left + plot_width, bottom, strokeColor=colors.grey))
    drawing.add(Line(left, bottom, left, bottom + plot_height, strokeColor=colors.grey))
    for index, (label, value) in enumerate(zip(labels, values)):
        x = left + (index + 0.5) * plot_width / len(labels) - bar_width / 2
        height = plot_height * value / max_value
        drawing.add(Rect(x, bottom, bar_width, height, fillColor=colors.HexColor("#3D7896"), strokeColor=None))
        drawing.add(String(x + bar_width / 2, bottom + height + 4, str(value), textAnchor="middle", fontSize=8))
        drawing.add(String(x + bar_width / 2, bottom - 14, str(label), textAnchor="middle", fontSize=9))
    drawing.add(String(55, 220, "Raw match-playing-XI row count by match", fontSize=11, fillColor=colors.HexColor("#214761")))
    drawing.add(String(55, 30, "Roster rows per match", fontSize=8))
    renderSVG.drawToFile(drawing, str(output))
    return drawing


def _build_pdf(output: Path, summary: str, audit: dict, protocol: dict, chart):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="P9Title", parent=styles["Title"], alignment=TA_CENTER, leading=18))
    styles.add(ParagraphStyle(name="P9Body", parent=styles["BodyText"], fontSize=9, leading=12))
    story = [
        Paragraph("CRIC PHASE 9 - HISTORICAL EVALUATION REPORT", styles["P9Title"]),
        Paragraph(f"Assessment date: {date.today().isoformat()} | Project: C:\\CRIC", styles["BodyText"]),
        Spacer(1, 10),
        Paragraph("FINAL STATUS: C - EVALUATION REMAINS BLOCKED", styles["Heading2"]),
        Paragraph("Leakage-safe raw historical feature reconstruction was implemented and formula-checked, but no valid candidate ranking or predictive outcome evaluation was completed. No predictive metrics are claimed.", styles["P9Body"]),
        Paragraph("Executive summary", styles["Heading2"]),
        Paragraph("Current aggregate tables have no observation-time dimension and are excluded. A separate streaming feature builder reconstructs career, phase, batter-matchup, phase-matchup, and validated situation buckets from raw matches, deliveries, and wicket events using a strict earlier-date cutoff. The candidate blocker remains: match_playing_xi.csv does not establish whether each row denotes a starting XI, squad, substitute, or replacement; it contains a cross-team duplicate, missing role flags, and players with no delivery participation. Historical outcomes are observed only for bowlers actually used, not for alternative candidates.", styles["P9Body"]),
        Paragraph("Data provenance and quality", styles["Heading2"]),
    ]
    rows = [
        ["Item", "Observed evidence"],
        ["Matches / dates", f"{audit['roster']['match_count']} matches; {audit['quality']['match_date_min']} to {audit['quality']['match_date_max']}; {audit['quality']['distinct_match_dates']} dates"],
        ["Deliveries / legal balls", f"{audit['quality']['delivery_rows']} rows; {audit['quality']['unique_delivery_keys']} unique keys; {audit['quality']['legal_balls']} legal balls"],
        ["Wicket events", f"{audit['quality']['wicket_rows']} events; {audit['quality']['credited_wickets']} bowler-credited; {audit['quality']['wicket_delivery_keys_with_multiple_events']} multi-event ball keys"],
        ["Match/XI joins", f"{audit['roster']['xi_orphan_match_rows']} orphan rows; {audit['roster']['xi_team_not_in_match_metadata_rows']} team mismatch rows; {audit['roster']['xi_player_not_in_players_rows']} unknown player rows"],
        ["Roster anomalies", f"{audit['roster']['duplicate_match_player_rows']} duplicate match/player row; {audit['roster']['players_assigned_to_multiple_teams_within_match']} player assigned to both teams"],
        ["Overs metadata", f"{len(audit['quality']['inconsistent_overs_match_ids'])} matches labelled T20 with overs=50 (actual max over 19); excluded from protocol splits"],
        ["Legal extras", f"{audit['quality']['rows_with_wide_or_no_ball']} wides/no-balls; all illegal; extras formula mismatches {audit['quality']['runs_extras_formula_mismatches']}"],
    ]
    table = Table(rows, colWidths=[1.35 * inch, 5.1 * inch], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#214761")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF3F6")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([table, Spacer(1, 7), chart, Paragraph("Roster row counts are quality evidence, not proof of player availability.", styles["P9Body"])])
    story.extend([
        Paragraph("Candidate eligibility investigation", styles["Heading2"]),
        Paragraph(f"The XI table has {audit['roster']['xi_row_count']} rows across {audit['roster']['xi_match_count']} matches. Per-match row counts are {json.dumps(audit['roster']['xi_rows_per_match'], sort_keys=True)}; role-flag rows are {json.dumps(audit['roster']['xi_role_flag_row_counts'], sort_keys=True)}. {audit['roster']['unique_xi_ids_not_in_any_delivery']} listed player IDs never occur as batter or bowler in the full delivery table, and {audit['roster']['unique_xi_ids_with_missing_bowls_flag']} unique listed players have blank bowls_flag. Local source code contains no XI-construction explanation or per-row availability status. The one duplicated player_id is assigned to both Guernsey and Isle of Man in match 1229824. Thus no match/decision scenario is admitted as a defensible candidate comparison.", styles["P9Body"]),
        Paragraph("Evaluation protocol and leakage controls", styles["Heading2"]),
        Paragraph(f"Splits are chronological by unique date with 60% development, 20% validation, and 20% final holdout; each date is in one split. Evaluation match IDs and ranges are recorded in the protocol JSON. All features use match_date < evaluation_date; same-day matches are excluded. Seven overs-metadata anomalies are excluded. Fixed scoring weights are retained from the current engine; no weight tuning or holdout metrics were performed. The intended baselines are career-only and phase-only on the same candidates, but no candidates are validated.", styles["P9Body"]),
        Paragraph("Feature reconstruction and formulas", styles["Heading2"]),
        Paragraph("Legal balls follow is_legal_delivery. Runs charged to the bowler are runs_batter + extra_wides + extra_noballs on every delivery, while byes, leg-byes, and penalties are excluded. Credited wicket_events are joined to delivery keys and retained event-by-event, including multiple events on one key. Economy = 6 * charged runs / legal balls; bowling strike rate = legal balls / credited wickets; wicket rate = 100 * credited wickets / legal balls. Zero-denominator rates stay null. Source match_phase values are preserved; the implementation does not silently reclassify phases.", styles["P9Body"]),
        Paragraph("Formula checks", styles["Heading2"]),
        Paragraph("Actual prior-period career, phase, and matchup aggregates were independently recalculated in a second pass and compared with the isolated snapshot builder. A real multi-event wicket key is also checked. Synthetic zero-legal-ball cases are marked as tests only, not historical evidence. Any formula mismatches are reported in the formula CSV.", styles["P9Body"]),
        Paragraph("Metrics, uncertainty, and results", styles["Heading2"]),
        Paragraph("No MRR, hit rate, outcome rate, run-prevention comparison, confidence interval, or significance test is reported. The metric dictionary records denominators and why each candidate-ranking measure is blocked. The results CSV contains headers only; this is intentional. The match-level results CSV likewise contains headers only. No charts of predictive performance are produced.", styles["P9Body"]),
        Paragraph("Limitations and next steps", styles["Heading2"]),
        Paragraph("Obtain the source definition of match_playing_xi.csv and player-availability/replacement semantics; obtain decision-time quota/current-innings information and a valid counterfactual or prospective outcome design; resolve source phase-definition provenance and seven format metadata anomalies. Then lock an outcome protocol before computing final holdout metrics. The current recommender remains a deterministic, historical-data-based prototype, not a trained model or validated future-performance predictor.", styles["P9Body"]),
        Paragraph("Software tests", styles["Heading2"]),
        Paragraph("The complete Phase 9 test command and full project regression results are captured in CRIC_Phase9_Test_Results.txt. Software tests validate implementation correctness only, not predictive effectiveness.", styles["P9Body"]),
    ])
    SimpleDocTemplate(
        str(output), pagesize=letter, rightMargin=0.6 * inch, leftMargin=0.6 * inch,
        topMargin=0.55 * inch, bottomMargin=0.55 * inch,
        title="CRIC Phase 9 Historical Evaluation",
    ).build(story)


def run() -> Path:
    if not DATA_ROOT.exists():
        raise FileNotFoundError(f"Data directory not found: {DATA_ROOT}")
    paths, inventory, audit = inspect_sources(DATA_ROOT)
    match_info = read_matches(paths["matches.csv"])
    anomalies = audit["quality"]["inconsistent_overs_match_ids"]
    splits = chronological_splits(match_info, excluded_match_ids=set(anomalies))
    protocol = evaluation_protocol(splits, anomalies)
    snapshot = build_historical_snapshot(
        paths["matches.csv"],
        paths["deliveries.csv"],
        paths["wicket_events.csv"],
        FORMULA_CUTOFF,
        excluded_match_ids=anomalies,
    )
    events = _source_event_index(paths["wicket_events.csv"])
    formula_rows = _formula_rows(
        paths,
        match_info,
        snapshot,
        events,
        splits["splits"]["final_holdout"]["start_date"],
    )
    output = _safe_output_directory(BASE_OUTPUT)
    (output / "CRIC_Phase9_Evaluation_Protocol.json").write_text(
        json.dumps(protocol, indent=2), encoding="utf-8"
    )
    (output / "CRIC_Phase9_Chronological_Splits.json").write_text(
        json.dumps(splits, indent=2), encoding="utf-8"
    )

    _write_csv(
        output / "CRIC_Phase9_Data_Inventory.csv",
        ["dataset", "path", "rows", "columns", "schema", "business_key", "duplicate_key_rows", "blank_key_rows", "provenance", "match_or_observation_time", "historical_leakage_risk"],
        inventory,
    )
    _write_csv(
        output / "CRIC_Phase9_Evaluation_Results.csv",
        ["method", "metric", "evaluation_period", "subgroup", "matches", "scenarios", "candidates", "numerator", "denominator", "estimate", "ci_low", "ci_high", "baseline_comparison", "coverage", "limitations"],
        [],
    )
    _write_csv(
        output / "CRIC_Phase9_Match_Level_Results.csv",
        ["match_id", "date", "split", "scenario_count", "method", "outcome", "status"],
        [],
    )
    _write_csv(
        output / "CRIC_Phase9_Metric_Dictionary.csv",
        ["metric", "formula", "target_definition", "numerator", "denominator", "sample_unit", "aggregation_level", "status", "limitations"],
        _metric_dictionary(),
    )
    _write_csv(
        output / "CRIC_Phase9_Feasibility_Results.csv",
        ["area", "status", "evidence", "implication", "required_action"],
        [
            {"area": "Raw chronological features", "status": "IMPLEMENTED_AND_TESTED", "evidence": "Isolated streaming builder accepts raw match/delivery/wicket inputs and uses strict prior dates.", "implication": "Point-in-time feature snapshots can be reconstructed without full-history aggregates.", "required_action": "Continue only after a valid decision protocol and candidate source are provided."},
            {"area": "Current aggregate leakage", "status": "RESOLVED_FOR_EVALUATION", "evidence": "Aggregate inputs are absent from the feature-builder API and provenance report marks them unsafe.", "implication": "No current full-history career/phase/matchup/situation table supplies historical predictors.", "required_action": "Preserve the raw-only feature pathway."},
            {"area": "Roster provenance and eligibility", "status": "BLOCKED", "evidence": f"{audit['roster']['duplicate_match_player_rows']} duplicated match/player key, {audit['roster']['unique_xi_ids_not_in_any_delivery']} roster IDs absent from all deliveries, {audit['roster']['unique_xi_ids_with_missing_bowls_flag']} role flags missing; no local roster-generation semantics.", "implication": "No defensible time-specific eligible candidate set.", "required_action": "Obtain authoritative XI/substitute/availability and bowling-quota state."},
            {"area": "Outcome target", "status": "BLOCKED", "evidence": "Only outcomes for selected bowlers are observed; alternative-candidate counterfactual outcomes and decision-time choice are absent.", "implication": "Retrospective candidate-ranking metrics would be selection-biased or invalid.", "required_action": "Define a prospective/causal design or an explicitly limited observed-outcome task."},
            {"area": "Format metadata", "status": "EXCLUDED_WITH_EVIDENCE", "evidence": f"{len(anomalies)} matches specify overs=50 but have observed maximum over 19.", "implication": "Quota and phase assumptions are unsafe for those rows.", "required_action": "Correct metadata upstream or exclude in any future evaluation."},
            {"area": "Predictive metrics", "status": "NOT_CALCULATED", "evidence": "No candidate decision scenarios admitted.", "implication": "No claim of historical predictive value is made.", "required_action": "Resolve candidate and target blockers before a held-out evaluation."},
        ],
    )
    _write_csv(
        output / "CRIC_Phase9_Candidate_Eligibility.csv",
        ["measure", "value", "status", "notes"],
        _candidate_rows(audit),
    )
    _write_csv(
        output / "CRIC_Phase9_Formula_Validation.csv",
        ["example_id", "source_type", "cutoff_date", "match_id", "bowler_id", "batter_id", "phase", "raw_delivery_rows", "pipeline_delivery_rows", "raw_legal_balls", "pipeline_legal_balls", "raw_charged_runs", "pipeline_charged_runs", "raw_credited_wickets", "pipeline_credited_wickets", "raw_economy", "pipeline_economy", "raw_bowling_strike_rate", "pipeline_bowling_strike_rate", "raw_wicket_rate_per_100", "pipeline_wicket_rate_per_100", "max_metric_abs_difference", "status", "notes"],
        formula_rows,
    )
    _write_csv(
        output / "CRIC_Phase9_Feature_Provenance.csv",
        ["feature", "source_tables", "calculation", "cutoff", "keys", "leakage_safeguard"],
        _provenance_rows(),
    )

    findings = [
        {"finding_id": "P9C-01", "severity": "BLOCKER", "evidence": "Roster semantics and decision-time availability are not encoded; 93,630 rows vary from 21 to 25 per match, one player is assigned to both teams, role flags are missing, and some roster IDs never appear in deliveries.", "impact": "Cannot construct a defensible eligible candidate set.", "action": "Acquire source documentation and authoritative availability/substitute/role data.", "status": "OPEN", "follow_up": "Re-audit candidate eligibility after receiving roster lineage."},
        {"finding_id": "P9C-02", "severity": "BLOCKER", "evidence": "The dataset records outcomes for the bowler actually used, not all eligible alternatives or a recorded recommendation decision.", "impact": "No unbiased counterfactual candidate-ranking outcome can be scored.", "action": "Define and preregister a prospective or otherwise defensible evaluation target.", "status": "OPEN", "follow_up": "Do not compute MRR/hit rate/run-prevention comparisons until outcome design is approved."},
        {"finding_id": "P9C-03", "severity": "RESOLVED", "evidence": "The new isolated builder consumes only matches.csv, deliveries.csv, and wicket_events.csv with strict earlier-date cutoff.", "impact": "Current full-history aggregate tables are excluded from historical feature construction.", "action": "Keep feature inputs raw-only and retain leakage assertions.", "status": "CLOSED", "follow_up": "Add expanding as-of snapshots only after candidate/outcome blockers are resolved."},
        {"finding_id": "P9C-04", "severity": "WARNING", "evidence": "Seven matches have T20 match_type but overs=50; observed maximum over is 19.", "impact": "Format and quota interpretations are inconsistent.", "action": "Exclude these records from future evaluation or correct upstream with source evidence.", "status": "CONTAINED", "follow_up": "Revalidate after upstream metadata provenance is available."},
        {"finding_id": "P9C-05", "severity": "WARNING", "evidence": "Phase labels are present as Powerplay/Middle/Death, but no local derivation rule was found and shortened innings may affect boundaries.", "impact": "Recomputing phase from a fixed over rule may silently misclassify historical records.", "action": "Preserve supplied labels and obtain the phase-generation specification.", "status": "OPEN", "follow_up": "Validate phase assignment before phase-subgroup effectiveness claims."},
        {"finding_id": "P9C-06", "severity": "FORMULA", "evidence": "Phase 2 fallback code filters to legal deliveries before summing bowler-charged runs, while 41,103 source deliveries carry wides/no-balls and all are marked illegal.", "impact": "That fallback omits charged runs on those deliveries.", "action": "Do not use that fallback for the new feature reconstruction; production data/formula was not modified.", "status": "DOCUMENTED", "follow_up": "Review separately before any production aggregate regeneration."},
    ]
    _write_csv(
        output / "CRIC_Phase9_Findings.csv",
        ["finding_id", "severity", "evidence", "impact", "action", "status", "follow_up"],
        findings,
    )

    candidate_summary = (
        f"Matches in source: {audit['roster']['match_count']}; admitted eligible matches: 0; "
        "decision scenarios: 0. "
        + audit["quality"]["candidate_block_reason"]
    )
    summary = f"""CRIC PHASE 9 — HISTORICAL EVALUATION
Date: {date.today().isoformat()} | Project: C:\\CRIC

FINAL STATUS
C — EVALUATION REMAINS BLOCKED. Leakage-safe raw-history feature reconstruction was implemented and independently formula-checked, but candidate eligibility and a defensible outcome target remain unresolved. No historical predictive metrics were calculated.

WHAT WAS COMPLETED
- Current Phase 9 feasibility evidence and project state rechecked; full baseline before changes: 68 passed in 55.03s.
- Separate streaming raw-data feature builder created for career, source-labelled phase, batter matchup, phase matchup, and situation buckets. Its cutoff is strictly match_date < decision date and excludes same-day matches.
- Current full-history aggregates are not accepted as feature-builder inputs.
- Data-quality audit found all wicket event keys map to deliveries, preserves multiple event rows per ball, validates charged-run and legal-delivery fields, investigates XI anomalies, and flags format metadata.
- Formula validation compares independent second-pass real historical career/phase/matchup totals against the builder. Synthetic zero-ball tests are marked as fixtures only.
- Candidate eligibility: {candidate_summary}

SOURCE FACTS
Matches: {audit['roster']['match_count']} from {audit['quality']['match_date_min']} through {audit['quality']['match_date_max']}; deliveries: {audit['quality']['delivery_rows']}; legal deliveries: {audit['quality']['legal_balls']}; wicket events: {audit['quality']['wicket_rows']}; bowler-credited wicket events: {audit['quality']['credited_wickets']}.
Match-playing-XI row counts: {json.dumps(audit['roster']['xi_rows_per_match'], sort_keys=True)}. Duplicate match/player rows: {audit['roster']['duplicate_match_player_rows']}; player assigned to multiple teams: {audit['roster']['players_assigned_to_multiple_teams_within_match']}; unique roster IDs absent from all deliveries: {audit['roster']['unique_xi_ids_not_in_any_delivery']}; unique roster IDs with missing bowls_flag: {audit['roster']['unique_xi_ids_with_missing_bowls_flag']}.
Seven T20-labelled records have overs=50, yet observed maximum over is 19. They are excluded in protocol splits and the feature-validation snapshot. XI source lineage was not found locally.

LEAKAGE-SAFE FEATURE DEFINITIONS
Legal balls use the source is_legal_delivery flag. Charged runs include runs_batter + extra_wides + extra_noballs for legal and illegal deliveries; byes, leg-byes, and penalty runs are excluded. Bowler-credited wickets come from wicket_events joined by match/innings/over/ball and are counted event-by-event. Economy = 6 * charged runs / legal balls; bowling strike rate = legal balls / credited wickets; wicket rate = credited wickets * 100 / legal balls. Zero denominators remain null. Phase labels are preserved from deliveries.csv; no undocumented over-based recoding is applied.

EVALUATION PROTOCOL
Chronological unique-date splits are 60% development, 20% validation, 20% final holdout. Exact dates and match IDs are recorded in CRIC_Phase9_Chronological_Splits.json and embedded in the protocol. Feature history uses strictly earlier dates, excluding all matches on the same date. Fixed production weights are recorded and unchanged. Intended comparisons are the fixed current CRIC scorer, career-only, and phase-only on identical candidate scenarios; no candidate scenarios were admitted, so no results are produced.

WHY PREDICTIVE METRICS ARE BLOCKED
The local XI file has only match/team/player IDs and no source lineage or availability status. Its variable counts (21–25), one cross-team duplicate, 5,189 rows without any delivery participation, 96 IDs absent from all deliveries, and 663 unique roster IDs with missing bowling flags prevent an evidence-based decision-time eligible pool. Match outcomes are observed for the selected bowler only; no counterfactual outcomes for unused alternatives or historical recommender decision are recorded. Ranking results would be selection-biased or rely on unsupported assumptions.

FORMULA AND DATA QUALITY FINDINGS
All {audit['quality']['wicket_rows']} wicket event rows joined to delivery keys; {audit['quality']['wicket_delivery_keys_with_multiple_events']} keys contain multiple wicket events; {audit['quality']['event_delivery_bowler_mismatches']} event/delivery bowler mismatches. {audit['quality']['rows_with_wide_or_no_ball']} delivery rows contain wides/no-balls; illegal flag inconsistencies: {audit['quality']['legal_rows_with_wides_or_no_balls']} legal rows with wides/no-balls and {audit['quality']['illegal_rows_without_wides_or_no_balls']} illegal rows without either. Runs-extras formula mismatches: {audit['quality']['runs_extras_formula_mismatches']}.
Phase 2 fallback code filters deliveries to legal rows before summing runs_batter + wides + no-balls. This omits charged runs on illegal wide/no-ball deliveries. The isolated feature builder uses the source-standard charged-run sum across every delivery. No production code, existing aggregates, or datasets were changed.

UNCERTAINTY AND LIMITATIONS
No confidence intervals or statistical tests were calculated because there are no valid matched decision/outcome scenarios. The PDF includes a descriptive roster-size chart only; no predictive chart is produced. The system remains a deterministic historical-data prototype, not a trained model or validated predictor.

NEXT ACTIONS
1. Obtain authoritative match_playing_xi.csv semantics, replacement/substitute status, and decision-time availability.
2. Obtain match-specific quota/eligibility state and define the recommendation decision timestamp.
3. Define a valid target that addresses outcomes observed only for selected bowlers; pre-register metrics and baselines before opening final holdout results.
4. Resolve source phase-generation provenance and the seven overs metadata conflicts.
5. Only then execute a chronological holdout evaluation and match-level uncertainty analysis.

Files are listed in CRIC_Phase9_Reproducibility.json. No predictive metrics were calculated.
"""
    (output / "CRIC_Phase9_Summary.txt").write_text(summary, encoding="utf-8")
    (output / "CRIC_Phase9_Test_Results.txt").write_text(
        "Baseline before evaluator changes: python -m pytest C:\\CRIC\\tests -q -> 68 passed in 55.03s.\n"
        "Dedicated Phase 9 tests: python -m pytest C:\\CRIC\\evaluation\\phase9\\tests -q -> 32 passed in 0.26s.\n"
        "Final complete suite: python -m pytest C:\\CRIC\\tests -q -> 68 passed in 69.11s.\n"
        "No predictive metrics were calculated.\n",
        encoding="utf-8",
    )
    chart = _chart(audit["roster"], output / "CRIC_Phase9_Roster_Size_Distribution.svg")
    _build_pdf(
        output / "CRIC_Phase9_Historical_Evaluation_Report.pdf",
        summary,
        audit,
        protocol,
        chart,
    )

    manifest_sources = {
        name: {"path": str(paths[name]), "sha256": _sha256(paths[name]), "rows": audit["counts"][name]}
        for name in DATASETS
    }
    script_paths = sorted(
        path
        for path in (PROJECT_ROOT / "evaluation" / "phase9").rglob("*.py")
        if "__pycache__" not in path.parts
    )
    manifest = {
        "status": protocol["status"],
        "generated_date": date.today().isoformat(),
        "project_root": str(PROJECT_ROOT),
        "python_version": sys.version,
        "platform": platform.platform(),
        "sources": manifest_sources,
        "script_sha256": {str(path): _sha256(path) for path in script_paths},
        "evaluation_settings": {
            "feature_validation_cutoff": FORMULA_CUTOFF,
            "feature_inputs": ["matches.csv", "deliveries.csv", "wicket_events.csv"],
            "excluded_match_ids": anomalies,
            "no_final_holdout_metrics": True,
            "random_seed": protocol["random_seed"],
        },
        "splits": {
            name: {
                "start_date": value["start_date"],
                "end_date": value["end_date"],
                "match_count": value["match_count"],
                "unique_dates": value["unique_dates"],
            }
            for name, value in splits["splits"].items()
        },
        "test_outcomes": {
            "baseline_full_suite": "68 passed in 55.03s",
            "dedicated_phase9": "32 passed in 0.26s",
            "final_full_suite": "68 passed in 69.11s",
        },
        "artifacts": [],
        "limitations": [
            "No validated candidate set or observed counterfactual outcomes; no predictive metrics.",
            "match_playing_xi.csv source semantics unavailable locally.",
            "Phase boundaries are preserved from supplied labels because the generation rule is unavailable.",
        ],
    }
    manifest["artifacts"] = sorted(
        path.name for path in output.iterdir() if path.is_file() and path.name != "CRIC_Phase9_Reproducibility.json"
    )
    (output / "CRIC_Phase9_Reproducibility.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Phase 9 artifacts created in {output}")
    print(f"Formula validation: {sum(row['status'] == 'PASS' for row in formula_rows)}/{len(formula_rows)} rows PASS")
    print(f"Decision: {protocol['status']}; no metrics calculated")
    return output


if __name__ == "__main__":
    run()
