from __future__ import annotations

import csv
import hashlib
import json
import platform
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from evaluation.phase11.event_store import EventStore

PROTECTED = {
    "backend/recommendation_engine.py": "b0eda0186b18ee8f2fc7cae1162314d8af8a87c12ba3584ad8ba711241fc71a6",
    "backend/api.py": "f29298b2af96173ba30dffa08c2d66d41c989b52fb2da2079035f44009b98c02",
    "frontend/index.html": "56ec664891d3aa5e82d4d904f73ddfd412f6888b96cfd98fee5a91406e88c98c",
    "frontend/app.js": "6f41f705daf995fb65c66384a0909eb9f5f7b237aeba851d36859fb0a3354c2e",
    "frontend/styles.css": "d4eb53f3a462ed1f54d0eeed3a186b76ad3f7190fa3d37ad17c14e0c68130bc6",
}
EVENT_TYPES = (
    "decision_request", "candidate_snapshot", "recommendation_snapshot",
    "recommendation_error", "actual_selection", "observed_delivery",
    "observed_wicket", "outcome_finalized", "correction",
)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def _data_files(root: Path) -> list[dict[str, Any]]:
    data = root / "data"
    return [
        {"relative_path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": _hash(path)}
        for path in sorted(data.rglob("*")) if path.is_file()
    ]


def _phase10_data_hashes(root: Path) -> list[dict[str, Any]]:
    source = root / "reports" / "phase10_20261012T115559Z" / "CRIC_Phase10_Source_Hash_Check.csv"
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            {
                "relative_path": "data/" + row["relative_path"],
                "size": int(row["before_bytes"]),
                "sha256": row["before_sha256"].casefold(),
            }
            for row in csv.DictReader(handle)
            if not row["relative_path"].startswith("data/") and row["before_sha256"]
        ]
    if len(rows) != 42:
        raise ValueError(f"Phase 10 source hash artifact lists {len(rows)} data files, expected 42")
    return rows


def _summary(events: list[dict[str, Any]], integrity: dict[str, Any]) -> dict[str, Any]:
    modes = {
        event["decision_id"]: event["payload"]["mode"]
        for event in events if event["event_type"] == "decision_request"
    }
    prospective_ids = {key for key, value in modes.items() if value == "prospective_shadow"}
    real = [event for event in events if event["decision_id"] in prospective_ids]
    counts = Counter(event["event_type"] for event in real)
    candidate_rows = [
        row for event in real if event["event_type"] == "candidate_snapshot"
        for row in event["payload"]["candidates"]
    ]
    eligibility = Counter(row["eligibility_status"] for row in candidate_rows)
    selections = [event for event in real if event["event_type"] == "actual_selection"]
    outcome = Counter(event["payload"]["status"] for event in real if event["event_type"] == "outcome_finalized")
    event_time_order_issues = 0
    by_decision: dict[str, list[dict[str, Any]]] = {}
    for event in real:
        by_decision.setdefault(event["decision_id"], []).append(event)
    for group in by_decision.values():
        times = [row["event_time_utc"] for row in group if row["event_time_utc"] is not None]
        event_time_order_issues += sum(b < a for a, b in zip(times, times[1:]))
    return {
        "decision_count": counts["decision_request"],
        "event_count": len(real),
        "event_counts": {name: counts[name] for name in EVENT_TYPES},
        "recommendation_successes": counts["recommendation_snapshot"],
        "recommendation_failures": counts["recommendation_error"],
        "candidate_counts": {
            "total": sum(eligibility.values()),
            "confirmed_eligible": eligibility["confirmed_eligible"],
            "confirmed_ineligible": eligibility["confirmed_ineligible"],
            "unknown": eligibility["unknown"],
        },
        "selection_count": len(selections),
        "selection_capture_rate": len(selections) / counts["decision_request"] if counts["decision_request"] else None,
        "candidate_selection_overlap_count": sum(
            event["payload"].get("appeared_in_candidate_snapshot") is True for event in selections
        ),
        "recommendation_selection_overlap_count": sum(
            event["payload"].get("appeared_in_recommendations") is True for event in selections
        ),
        "outcome_counts": {key: outcome[key] for key in ("complete", "incomplete", "unavailable")},
        "missing_data_fields": _missing_fields(real),
        "duplicate_delivery_or_wicket_source_ids": _duplicate_observations(real),
        "out_of_order_event_times": event_time_order_issues,
        "store_integrity": integrity["integrity"],
        "store_issue_count": len(integrity["issues"]),
        "synthetic_event_count_excluded": sum(modes.get(event["decision_id"]) == "synthetic_test" for event in events),
        "historical_replay_event_count": sum(modes.get(event["decision_id"]) == "historical_replay" for event in events),
    }


def _missing_fields(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for event in events:
        if event["event_type"] != "decision_request":
            continue
        if event["event_time_utc"] is None:
            counts["event_time_utc"] += 1
        state = event["payload"].get("match_state") or {}
        for key in ("match_id", "innings_id", "competition", "format"):
            if not state.get(key):
                counts[key] += 1
    return dict(sorted(counts.items()))


def _duplicate_observations(events: list[dict[str, Any]]) -> int:
    delivery_rows = [event["payload"] for event in events if event["event_type"] == "observed_delivery"]
    wicket_rows = [event["payload"] for event in events if event["event_type"] == "observed_wicket"]
    delivery_keys = [
        (row["match_id"], row["innings_number"], row["over_number"], row["ball_in_over"])
        for row in delivery_rows
    ]
    delivery_ids = [row["source_record_id"] for row in delivery_rows]
    wicket_ids = [row["source_record_id"] for row in wicket_rows]
    return (
        len(delivery_keys) - len(set(delivery_keys))
        + len(delivery_ids) - len(set(delivery_ids))
        + len(wicket_ids) - len(set(wicket_ids))
    )


def _field_dictionary() -> list[dict[str, str]]:
    entries = [
        ("schema_version", "integer", "Required", "Envelope version; current value 1."),
        ("event_id", "UUID", "Required", "Stable event key; exact retries are idempotent."),
        ("decision_id", "string", "Required", "Stable decision correlation key."),
        ("event_type", "enum", "Required", "Versioned event family; unrecognized records are reported."),
        ("event_time_utc", "UTC timestamp/null", "Optional", "Original event time; never substituted when absent."),
        ("logged_at_utc", "UTC timestamp", "Required", "Local append time, distinct from event time."),
        ("payload.mode", "enum", "Decision", "prospective_shadow, historical_replay, synthetic_test."),
        ("payload.request", "object", "Decision", "Existing recommendation request contract only."),
        ("payload.context_provenance", "object", "Decision", "Context status, source, and optional confidence."),
        ("payload.candidates", "array", "Candidates", "Caller-provided candidate evidence snapshot."),
        ("payload.eligibility_status", "enum", "Candidate", "confirmed_eligible, confirmed_ineligible, or unknown."),
        ("payload.engine", "string", "Recommendation", "Engine source fingerprint; not a trained-model claim."),
        ("payload.configuration_sha256", "SHA-256", "Recommendation", "Recommendation scoring configuration fingerprint."),
        ("payload.selected_bowler_id", "string", "Selection", "Only explicitly observed or reported selection."),
        ("payload.source_record_id", "string", "Observation", "Source record key for duplicate detection."),
        ("payload.is_legal_delivery", "boolean", "Delivery", "Source-recorded legal-ball state."),
        ("payload.is_bowler_credited", "boolean", "Wicket", "Source-recorded bowler-credit status."),
        ("payload.status", "enum", "Outcome", "complete, incomplete, or unavailable; never a zero fallback."),
        ("payload.supersedes_event_id", "string", "Correction", "Prior immutable event explicitly superseded."),
    ]
    return [dict(zip(("field", "type", "applies_to", "definition"), row)) for row in entries]


def _validation_rules() -> list[dict[str, str]]:
    items = [
        ("Schema", "Require version 1 and report unknown versions; do not silently drop records."),
        ("Timestamps", "Store UTC event/logging times separately; unknown event time remains null."),
        ("Identifiers", "Bound identifiers; reject malformed IDs, duplicate candidate IDs, and invalid references."),
        ("Idempotency", "Same event ID/content is a no-op; changed content under the same ID is a conflict."),
        ("Append-only", "Database triggers reject update/delete; hash chain detects ordinary tampering."),
        ("Eligibility", "Only explicit sourced team, availability, and rule evidence can confirm eligibility; otherwise unknown."),
        ("Selection", "Record only observed/reported selection; absent candidate membership produces a warning."),
        ("Request", "Allow only existing request fields, bounded request size, and at most 30 candidates."),
        ("Errors", "Store safe exception type and generic text; never exception details or traceback."),
        ("Outcome horizon", "Require predeclared match/innings/over horizon and explicit observation coverage."),
        ("Runs", "Count batter runs and wides/no-balls; exclude byes and leg-byes from charged runs."),
        ("Wickets", "Count only source-linked bowler-credited wickets for the selected actual bowler."),
        ("Missing outcomes", "Incomplete/unavailable labels remain null, not zero; unselected candidates have no labels."),
        ("Zero denominators", "Zero legal balls yields null rates."),
        ("Replay", "Do not call the recommender to manufacture historical recommendation snapshots."),
        ("Synthetic", "Use temporary synthetic-test stores; exclude these events from prospective summaries."),
        ("Correction", "Append a provenance-bearing supersession event; never mutate prior events."),
        ("Export", "Sort deterministically, include checksums, and refuse destination overwrite."),
    ]
    return [
        {"rule_id": f"V{number:02d}", "area": area, "rule": rule}
        for number, (area, rule) in enumerate(items, 1)
    ]


def _pdf(path: Path, sections: list[tuple[str, str]]) -> None:
    styles = getSampleStyleSheet()
    title = ParagraphStyle("p11title", parent=styles["Title"], alignment=TA_CENTER, textColor=colors.HexColor("#123b57"), fontSize=17)
    heading = ParagraphStyle("p11heading", parent=styles["Heading2"], textColor=colors.HexColor("#123b57"), fontSize=11, leading=14, spaceBefore=8)
    body = ParagraphStyle("p11body", parent=styles["BodyText"], fontSize=9.5, leading=13, spaceAfter=5)
    story = [Paragraph("CRIC PHASE 11 IMPLEMENTATION REPORT", title), Spacer(1, 0.1 * inch)]
    for index, (name, text) in enumerate(sections):
        if index in {4, 8, 11}:
            story.append(PageBreak())
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        story.extend((Paragraph(name, heading), Paragraph(safe, body)))
    SimpleDocTemplate(
        str(path), pagesize=letter, rightMargin=0.55*inch, leftMargin=0.55*inch,
        topMargin=0.5*inch, bottomMargin=0.5*inch,
        title="CRIC Phase 11 Implementation Report",
    ).build(story)


def generate_reports(
    *,
    project_root: Path,
    output_dir: Path,
    baseline_hashes: Path | None,
    phase11_test_result: str,
    regression_test_result: str,
    compile_result: str,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    reports_root = (project_root / "reports").resolve()
    if reports_root not in output_dir.parents:
        raise ValueError("Report output must be a new child of the project reports directory")
    if output_dir.exists():
        raise FileExistsError("Report directory exists; refusing to overwrite")
    disk_free_before = shutil.disk_usage(project_root).free
    output_dir.mkdir(parents=True)

    if baseline_hashes is None:
        before = _phase10_data_hashes(project_root)
    else:
        before = json.loads(baseline_hashes.read_text(encoding="utf-8"))
        if not isinstance(before, list) or len(before) != 42:
            raise ValueError("Before-hash file must contain all 42 Phase 10-listed data files")
        if any(not row.get("relative_path", "").startswith("data/") for row in before):
            raise ValueError("Before-hash paths must remain under the project's data directory")
    before_map = {row["relative_path"]: row for row in before}
    current = _data_files(project_root)
    current_map = {row["relative_path"]: row for row in current}

    production_checks = []
    for relative, expected in PROTECTED.items():
        path = project_root / relative
        actual = _hash(path)
        production_checks.append({
            "relative_path": relative, "before_bytes": path.stat().st_size, "after_bytes": path.stat().st_size,
            "before_sha256": expected, "after_sha256": actual,
            "phase11_integrity": "UNCHANGED" if actual == expected else "BASELINE_MISMATCH",
        })
    source_rows = []
    for relative, initial in sorted(before_map.items()):
        last = current_map.get(relative)
        source_rows.append({
            "relative_path": relative, "before_bytes": initial["size"],
            "after_bytes": last["size"] if last else "",
            "before_sha256": initial["sha256"], "after_sha256": last["sha256"] if last else "",
            "phase11_integrity": "UNCHANGED" if last and last["size"] == initial["size"] and last["sha256"] == initial["sha256"] else "MISSING_OR_CHANGED",
        })
    source_rows.extend(production_checks)
    _csv(output_dir / "CRIC_Phase11_Source_Hash_Check.csv",
         ["relative_path", "before_bytes", "after_bytes", "before_sha256", "after_sha256", "phase11_integrity"],
         source_rows)

    store_path = project_root / "evaluation" / "phase11" / "store" / "default.sqlite3"
    if store_path.exists():
        store = EventStore(project_root)
        events, integrity = store.events(), store.verify()
    else:
        events = []
        integrity = {"integrity": "empty", "event_count": 0, "issues": [], "last_event_hash": "0" * 64}
    summary = _summary(events, integrity)
    run_id = output_dir.name[len("phase11_"):]
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    phase10_path = project_root / "reports" / "phase10_20261012T115559Z" / "CRIC_Phase10_Reproducibility.json"
    phase10 = json.loads(phase10_path.read_text(encoding="utf-8"))

    _json(output_dir / "CRIC_Phase11_Event_Schema.json", {
        "schema_version": 1,
        "store": "SQLite append-only event table with unique event IDs and SHA-256 hash chain",
        "envelope": {
            "schema_version": "integer", "event_id": "stable UUID", "decision_id": "stable identifier",
            "event_type": list(EVENT_TYPES), "event_time_utc": "UTC timestamp/null",
            "logged_at_utc": "UTC timestamp", "payload": "event-specific object",
        },
        "event_payloads": {
            "decision_request": ["mode", "request", "context_provenance", "match_state", "outcome_horizon"],
            "candidate_snapshot": ["candidates"],
            "recommendation_snapshot": ["engine", "configuration_sha256", "configuration", "result"],
            "recommendation_error": ["error_type", "message"],
            "actual_selection": ["selected_bowler_id", "selection_source", "observed", "reason", "appeared_in_candidate_snapshot", "warnings"],
            "observed_delivery": ["match_id", "innings_number", "over_number", "ball_in_over", "bowler_id", "runs_batter", "extra_wides", "extra_noballs", "extra_byes", "extra_legbyes", "is_legal_delivery", "source_record_id"],
            "observed_wicket": ["match_id", "innings_number", "over_number", "ball_in_over", "bowler_id", "is_bowler_credited", "dismissal_kind", "source_record_id"],
            "outcome_finalized": ["status", "horizon", "actual_bowler_id", "metrics", "warnings"],
            "correction": ["supersedes_event_id", "reason", "replacement_event"],
        },
        "eligibility": {
            "states": ["confirmed_eligible", "confirmed_ineligible", "unknown"],
            "required": ["team_membership", "available_at_decision", "permitted_to_bowl"],
            "evidence_states": ["confirmed", "contradicted", "unknown", "not_recorded"],
        },
        "modes": ["prospective_shadow", "historical_replay", "synthetic_test"],
        "limits": {"request_bytes": 262144, "event_bytes": 1048576, "candidates": 30},
        "historical_replay_policy": "Import-only; no retrospective recommendation is generated.",
    })
    fields = _field_dictionary()
    _csv(output_dir / "CRIC_Phase11_Field_Dictionary.csv",
         ["field", "type", "applies_to", "definition"], fields)
    rules = _validation_rules()
    _csv(output_dir / "CRIC_Phase11_Validation_Rules.csv", ["rule_id", "area", "rule"], rules)
    dq = [
        ("Prospective events", summary["decision_count"], "NO_REAL_EVENTS", "Report generation creates no observations."),
        ("Unknown candidate eligibility", summary["candidate_counts"]["unknown"], "EXPLICIT_UNKNOWN", "Never promote unknown to eligible."),
        ("Complete outcome labels", summary["outcome_counts"]["complete"], "NO_OUTCOMES", "Missing outcomes are not zeros."),
        ("Duplicate observed keys", summary["duplicate_delivery_or_wicket_source_ids"], "CHECKED", "Delivery keys and delivery/wicket source IDs are checked separately."),
        ("Event-store integrity issues", summary["store_issue_count"], summary["store_integrity"], "Investigate every detected integrity defect."),
        ("Roster provenance", 1, "UNRESOLVED", "Phase 10 could not establish official roster meaning or external source."),
        ("Unused-candidate outcomes", 0, "UNAVAILABLE", "Observed historical outcomes concern actual bowlers only."),
    ]
    _csv(output_dir / "CRIC_Phase11_Data_Quality_Findings.csv",
         ["finding", "count", "status", "handling"],
         [dict(zip(("finding", "count", "status", "handling"), row)) for row in dq])
    _csv(output_dir / "CRIC_Phase11_Event_Coverage.csv",
         ["event_type", "prospective_count", "synthetic_count_excluded", "historical_replay_count"],
         [{"event_type": event_type, "prospective_count": summary["event_counts"][event_type],
           "synthetic_count_excluded": summary["synthetic_event_count_excluded"] if event_type == "decision_request" else 0,
           "historical_replay_count": summary["historical_replay_event_count"] if event_type == "decision_request" else 0}
          for event_type in EVENT_TYPES])
    _csv(output_dir / "CRIC_Phase11_Outcome_Coverage.csv",
         ["status", "count", "interpretation"],
         [
             {"status": "complete", "count": summary["outcome_counts"]["complete"], "interpretation": "Complete descriptive outcome for selected bowler only."},
             {"status": "incomplete", "count": summary["outcome_counts"]["incomplete"], "interpretation": "Incomplete observation coverage; metrics unavailable."},
             {"status": "unavailable", "count": summary["outcome_counts"]["unavailable"], "interpretation": "No linked outcome; metrics unavailable."},
         ])
    risk_rows = [
        ("R01", "Candidate universe", "Availability, roster semantics, and quota evidence may be unknown.", "Require authoritative, timestamped evidence; unknown remains explicit."),
        ("R02", "Selection bias", "Observed outcomes belong to selected bowlers, not alternatives.", "Do not compute ranking or causal metrics."),
        ("R03", "Standalone integration", "Logger is not wired into the existing API or frontend.", "Use explicit, one-shot operator input; production stays unchanged."),
        ("R04", "Local integrity", "Hash-chain checks are not external signatures or a trusted ledger.", "Restrict access and retain unique backups/checksums."),
        ("R05", "No observations", "No real prospective decision has yet been logged.", "Collect only after explicit operator configuration."),
        ("R06", "Incomplete sources", "Event truth/completeness depends on supplied authoritative sources.", "Record source/time and audit late or missing records."),
    ]
    _csv(output_dir / "CRIC_Phase11_Risk_Register.csv",
         ["risk_id", "risk", "description", "mitigation"],
         [dict(zip(("risk_id", "risk", "description", "mitigation"), row)) for row in risk_rows])

    summary_text = f"""CRIC PHASE 11 - PROSPECTIVE SHADOW LOGGING
Run ID: {run_id}
Generated UTC: {generated}

IMPLEMENTATION STATUS
Standalone, opt-in, local-only shadow logger. Ready for data collection only; no service starts automatically and no recommendation affects an actual decision.
Real prospective decisions logged: {summary['decision_count']}
Real prospective events: {summary['event_count']}
Synthetic fixtures and historical replay records are not counted as prospective.

PHASE 10 MOTIVATION
Status: {phase10['primary_status']}
Historical ranking and counterfactual evaluation remain blocked. Roster meaning/source provenance, decision-time availability, and bowling quota evidence remain unresolved. Outcomes are observed only for actual bowlers.

EVENT STORE AND SAFEGUARDS
SQLite append-only event table; schema 1; stable IDs; idempotent retries; transaction boundaries; update/delete rejection; SHA-256 chain; deterministic export; overwrite refusal.
Store is created only by an explicit operator command under evaluation\\phase11\\store. Existing engine, API, frontend and scoring are unchanged. No listener, external service or distributed job.
Eligibility is confirmed only with sourced membership, decision-time availability and bowling-rule evidence. Missing evidence remains unknown.
Historical replay does not call the engine to fabricate past recommendation records.

DESCRIPTIVE COVERAGE
Recommendation successes/failures: {summary['recommendation_successes']}/{summary['recommendation_failures']}
Candidate states: {json.dumps(summary['candidate_counts'], sort_keys=True)}
Actual selection records: {summary['selection_count']}; capture rate: {summary['selection_capture_rate']}
Outcome states: {json.dumps(summary['outcome_counts'], sort_keys=True)}
Store integrity: {summary['store_integrity']}; issues: {summary['store_issue_count']}
These are operational coverage counts, not predictive or causal metrics.

TESTS
Phase 11: {phase11_test_result}
Existing regression suite: {regression_test_result}
Python compilation: {compile_result}

PRESERVATION
42 Phase 10-listed data files and five production files are hash-checked. No Markdown, source dataset, production file, or infrastructure setting was intentionally modified.

LIMITATIONS / NEXT STEP
No real prospective events have been logged. Candidate snapshots need authoritative timestamped evidence; outcome completeness needs source coverage. Selected-bowler outcomes are not labels for alternatives. Before ranking evaluation, collect decision-time candidate/availability/rule evidence, selection and source-linked outcomes, then freeze and independently review a leakage-safe protocol. No accuracy, ranking quality, causal lift, or recommendation effectiveness is claimed.
"""
    (output_dir / "CRIC_Phase11_Summary.txt").write_text(summary_text, encoding="utf-8")
    (output_dir / "CRIC_Phase11_Test_Results.txt").write_text(
        f"Phase 11 tests: {phase11_test_result}\nExisting full regression suite: {regression_test_result}\nPython compilation: {compile_result}\nSynthetic events were isolated in temporary test stores.\n",
        encoding="utf-8",
    )
    runbook = f"""CRIC PHASE 11 LOCAL RUNBOOK
Run from {project_root}; commands are one-shot and no background server starts.

Validate installation and Phase 9 baseline:
  python -m evaluation.phase11.run_phase11 validate

Only when an operator intentionally configures a prospective decision, pass one JSON object on stdin:
  Get-Content -Raw .\\decision-input.json | python -m evaluation.phase11.run_phase11 shadow --confirm-prospective
The object has decision_id, request, and optional candidates_evidence, context_provenance, event_time_utc, match_state, outcome_horizon. Request fields are exactly the existing API contract: batter_id, phase, situation, context, candidates. No file path is accepted as a write target; the store root is fixed beneath evaluation\\phase11\\store.
The recommendation is not transmitted or acted on. Exiting returns to the prompt; no process remains.

Record explicitly observed later events:
  Get-Content -Raw .\\selection-input.json | python -m evaluation.phase11.run_phase11 selection --confirm-prospective
  Get-Content -Raw .\\delivery-input.json | python -m evaluation.phase11.run_phase11 observe-delivery --confirm-prospective
  Get-Content -Raw .\\wicket-input.json | python -m evaluation.phase11.run_phase11 observe-wicket --confirm-prospective
  Get-Content -Raw .\\finalize-input.json | python -m evaluation.phase11.run_phase11 finalize-outcome --confirm-prospective

Inspect and export:
  python -m evaluation.phase11.run_phase11 summary
  python -m evaluation.phase11.run_phase11 export
Generate the required implementation reports in a unique new directory:
  python -m evaluation.phase11.run_phase11 report
Export and backup files go only into a new unique reports\\phase11_export_<id> directory and refuse overwrite.
Each export includes a checksum manifest and the final event-chain integrity state.

Tests use synthetic fixtures only in temporary stores:
  python -m pytest C:\\CRIC\\evaluation\\phase11\\tests -q
Do not request historical replay from the shadow runner. There is no UI/API listener, live-match integration, external communication, automatic selection, or trained model. Ctrl+C stops a command if needed.
"""
    (output_dir / "CRIC_Phase11_Operational_Runbook.txt").write_text(runbook, encoding="utf-8")
    reproducibility = {
        "run_id": run_id, "generated_at_utc": generated, "project_root": str(project_root),
        "python_version": sys.version, "platform": platform.platform(), "schema_version": 1,
        "event_store": "SQLite append-only with SHA-256 hash chain",
        "data_file_count": len(current), "data_bytes_hashed": sum(row["size"] for row in current),
        "data_hashes_unchanged": all(row["phase11_integrity"] == "UNCHANGED" for row in source_rows if row["relative_path"].startswith("data/")),
        "production_hashes_unchanged": all(row["phase11_integrity"] == "UNCHANGED" for row in production_checks),
        "phase10_status": phase10["primary_status"], "phase10_counts": phase10["source_counts"],
        "phase10_tests": phase10["phase10_test_result"], "phase10_regression_tests": phase10["regression_test_result"],
        "phase11_tests": phase11_test_result, "regression_tests": regression_test_result,
        "compile": compile_result, "event_summary": summary,
        "predictive_metrics_computed": False, "causal_claims_made": False,
        "disk_free_bytes_before_report_generation": disk_free_before,
    }
    _json(output_dir / "CRIC_Phase11_Reproducibility.json", reproducibility)
    _pdf(output_dir / "CRIC_Phase11_Implementation_Report.pdf", [
        ("Executive summary", "Isolated, opt-in prospective shadow logger. It records request context, candidate evidence, unchanged engine output or sanitized failure, later selection, raw observations and guarded fixed-horizon summaries. It does not affect decisions. It is ready for data collection only; no real prospective events have been logged."),
        ("Phase 10 findings and motivation", f"Phase 10 status: {phase10['primary_status']}. Roster meaning/provenance, availability and bowling quota at decision time remain unknown. Historical outcomes belong to the bowler used; ranking and counterfactual evaluations remain blocked."),
        ("Architecture and event flow", "Standalone Python package calls the existing engine in-process. Explicit request -> decision event -> caller-evidenced candidate snapshot -> recommendation snapshot or sanitized error -> later selection and observed outcomes. There is no service, frontend, or production API change."),
        ("Schema and provenance", "Schema version 1 records distinct event and logging UTC times, stable IDs and a chained SHA-256 integrity digest. Request structure follows the existing API; context and eligibility retain source/status/time. Unknown values remain unknown."),
        ("Eligibility handling", "Eligibility requires sourced team membership, decision-time availability and bowling-rule permission. Contradiction is recorded as ineligible; incomplete evidence stays unknown. A roster row or later bowling cannot prove availability."),
        ("Recommendation and selection logging", "The same engine response and scoring configuration fingerprint are stored. Failures store only exception type and generic text. Actual selections are recorded only when explicitly supplied, with a warning if outside the candidate snapshot; no output is sent to a team."),
        ("Outcome-linking semantics", "Raw deliveries/wickets remain separate. Finalization requires the predeclared horizon, explicit complete coverage and selection. Charged runs are batter runs plus wides/no-balls; byes/leg-byes are excluded; only credited wickets to the selected bowler count. Zero denominators yield null, incomplete outcomes are unavailable."),
        ("Security and preservation", "No listener or external service. Store location is constrained to the Phase 11 subtree, identifiers and payloads are validated, append-only triggers and hash verification are enabled, and exports refuse overwrite. Source/production hashes are reported."),
        ("Validation and tests", f"Phase 11: {phase11_test_result}; existing suite: {regression_test_result}; compilation: {compile_result}. See the CSV rule/test artifacts."),
        ("Data quality and coverage", f"Prospective decisions={summary['decision_count']}, candidates={summary['candidate_counts']['total']}, selections={summary['selection_count']}, complete outcomes={summary['outcome_counts']['complete']}. No events are fabricated by reporting."),
        ("Local runbook", "Run `python -m evaluation.phase11.run_phase11 validate`. When explicitly configured, use `shadow --confirm-prospective` with one JSON request on stdin. Inspect with `summary`; export to a unique folder with `export`. No process persists."),
        ("What Phase 11 does not prove", "No live-match integration, adoption, model accuracy, ranking quality, causal lift, or improved outcomes is established. This is not distributed processing or trained ML."),
        ("Future evaluation prerequisites", "Obtain authoritative timestamped lineup/availability/substitution evidence and format/quota rules; capture full decision/candidate/selection snapshots and source-linked outcomes; freeze a reviewed, leakage-safe target/horizon protocol and collect sufficient prospective evidence."),
    ])
    reproducibility["disk_free_bytes_after_report_generation"] = shutil.disk_usage(project_root).free
    reproducibility["disk_space_change_bytes"] = (
        reproducibility["disk_free_bytes_after_report_generation"] - disk_free_before
    )
    _json(output_dir / "CRIC_Phase11_Reproducibility.json", reproducibility)
    return {"output_dir": output_dir, "summary": summary, "all_hashes_unchanged": all(row["phase11_integrity"] == "UNCHANGED" for row in source_rows)}