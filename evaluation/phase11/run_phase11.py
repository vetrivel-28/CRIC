from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.recommendation_engine import RecommendationEngine
from evaluation.phase10.protocol import load_phase9_baseline
from evaluation.phase11.collection import (
    record_actual_selection,
    record_correction,
    record_observation,
)
from evaluation.phase11.event_store import EventStore, EventStoreError
from evaluation.phase11.outcomes import finalize_fixed_horizon
from evaluation.phase11.reporting import generate_reports
from evaluation.phase11.schema import EventValidationError
from evaluation.phase11.shadow import run_shadow_decision

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORE_PATH = PROJECT_ROOT / "evaluation" / "phase11" / "store" / "default.sqlite3"
MAX_STDIN_BYTES = 1024 * 1024


def _read_stdin() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(raw) > MAX_STDIN_BYTES:
        raise EventValidationError("Input exceeds 1 MiB")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise EventValidationError("Input must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise EventValidationError("Input must be a JSON object")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise EventValidationError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _strict_fields(value: dict[str, Any], required: set[str], optional: set[str] = frozenset()) -> None:
    missing = required - value.keys()
    unexpected = value.keys() - required - optional
    if missing or unexpected:
        detail = []
        if missing:
            detail.append("missing fields: " + ", ".join(sorted(missing)))
        if unexpected:
            detail.append("unsupported fields: " + ", ".join(sorted(unexpected)))
        raise EventValidationError("; ".join(detail))


def _store() -> EventStore:
    return EventStore(PROJECT_ROOT)


def _unique_export_dir() -> Path:
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    destination = PROJECT_ROOT / "reports" / f"phase11_export_{identifier}"
    destination.mkdir(parents=False, exist_ok=False)
    return destination


def command_validate() -> dict[str, Any]:
    phase9 = load_phase9_baseline(PROJECT_ROOT / "reports" / "phase9_complete_06")
    engine = RecommendationEngine.from_data_root(PROJECT_ROOT / "data")
    if not engine.ready:
        raise RuntimeError("Recommendation engine did not become ready")
    return {
        "status": "valid",
        "engine": "CRIC.RecommendationEngine",
        "execution_mode": "local_python",
        "phase9_matches": phase9["total_unique_split_matches"],
        "formula_checks": phase9["formula_check_count"],
        "phase10_report": str(PROJECT_ROOT / "reports" / "phase10_20261012T115559Z"),
        "listener_started": False,
    }


def command_shadow(args: argparse.Namespace) -> dict[str, Any]:
    if not args.confirm_prospective:
        raise EventValidationError("Use --confirm-prospective only when the input is an explicitly configured real decision snapshot")
    value = _read_stdin()
    _strict_fields(
        value, {"decision_id", "request"},
        {"candidates_evidence", "context_provenance", "mode", "event_time_utc", "match_state", "outcome_horizon"},
    )
    if value.get("mode", "prospective_shadow") != "prospective_shadow":
        raise EventValidationError("Shadow CLI accepts prospective_shadow only; historical replay is not implemented")
    engine = RecommendationEngine.from_data_root(PROJECT_ROOT / "data")
    return run_shadow_decision(
        engine=engine,
        store=_store(),
        decision_id=value["decision_id"],
        request=value["request"],
        candidates_evidence=value.get("candidates_evidence"),
        context_provenance=value.get("context_provenance"),
        mode="prospective_shadow",
        event_time_utc=value.get("event_time_utc"),
        match_state=value.get("match_state"),
        outcome_horizon=value.get("outcome_horizon"),
    )


def command_selection(args: argparse.Namespace) -> dict[str, Any]:
    if not args.confirm_prospective:
        raise EventValidationError("Use --confirm-prospective when recording an explicitly observed selection")
    value = _read_stdin()
    _strict_fields(value, {"decision_id", "selected_bowler_id", "selection_source", "observed"},
                   {"selection_time_utc", "reason"})
    return record_actual_selection(
        store=_store(), decision_id=value["decision_id"], selected_bowler_id=value["selected_bowler_id"],
        selection_source=value["selection_source"], observed=value["observed"],
        selection_time_utc=value.get("selection_time_utc"), reason=value.get("reason"),
    )


def command_observation(args: argparse.Namespace, event_type: str) -> dict[str, Any]:
    if not args.confirm_prospective:
        raise EventValidationError("Use --confirm-prospective when ingesting explicitly observed source events")
    value = _read_stdin()
    _strict_fields(value, {"decision_id", "event_time_utc", "payload"})
    if not isinstance(value["payload"], dict):
        raise EventValidationError("payload must be an object")
    return record_observation(
        store=_store(), decision_id=value["decision_id"], event_type=event_type,
        payload=value["payload"], event_time_utc=value["event_time_utc"],
    )


def command_finalize(args: argparse.Namespace) -> dict[str, Any]:
    if not args.confirm_prospective:
        raise EventValidationError("Use --confirm-prospective only to finalize an explicitly complete observation horizon")
    value = _read_stdin()
    _strict_fields(value, {"decision_id", "observation_complete", "coverage_source"})
    if not isinstance(value["observation_complete"], bool):
        raise EventValidationError("observation_complete must be a boolean")
    return finalize_fixed_horizon(
        store=_store(), decision_id=value["decision_id"],
        observation_complete=value["observation_complete"], coverage_source=value["coverage_source"],
    )


def command_correction(args: argparse.Namespace) -> dict[str, Any]:
    if not args.confirm_prospective:
        raise EventValidationError("Use --confirm-prospective when appending a correction event")
    value = _read_stdin()
    _strict_fields(value, {"decision_id", "supersedes_event_id", "reason", "replacement_event"})
    return record_correction(
        store=_store(), decision_id=value["decision_id"],
        supersedes_event_id=value["supersedes_event_id"], reason=value["reason"],
        replacement_event=value["replacement_event"],
    )


def command_summary() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return {"event_count": 0, "decision_count": 0, "store_integrity": "empty", "message": "No event store exists; it was not created."}
    store = _store()
    events, integrity = store.events(), store.verify()
    from evaluation.phase11.reporting import _summary

    return _summary(events, integrity)


def command_export() -> dict[str, Any]:
    if not STORE_PATH.is_file():
        raise EventStoreError("No event store exists; nothing can be exported")
    store = _store()
    output = _unique_export_dir()
    export_info = store.export_json(output / "CRIC_Phase11_Events.json")
    backup = store.backup(output / "CRIC_Phase11_Events.sqlite3")
    integrity = store.verify()
    manifest = {
        "schema_version": 1,
        "event_count": export_info["event_count"],
        "events_json": {"file": "CRIC_Phase11_Events.json", "sha256": export_info["sha256"]},
        "sqlite_backup": {"file": backup.name, "sha256": _sha256_file(backup)},
        "event_store_integrity": integrity,
    }
    (output / "CRIC_Phase11_Export_Manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return {
        "output_dir": str(output),
        "event_export": export_info,
        "backup_file": backup.name,
        "manifest_file": "CRIC_Phase11_Export_Manifest.json",
        "integrity": integrity,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_report(args: argparse.Namespace) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = PROJECT_ROOT / "reports" / f"phase11_{timestamp}_{uuid.uuid4().hex[:6]}"
    result = generate_reports(
        project_root=PROJECT_ROOT,
        output_dir=destination,
        baseline_hashes=args.baseline_hashes,
        phase11_test_result=args.phase11_tests,
        regression_test_result=args.regression_tests,
        compile_result=args.compile_result,
    )
    return {
        "output_dir": str(result["output_dir"]),
        "pdf": str(result["output_dir"] / "CRIC_Phase11_Implementation_Report.pdf"),
        "summary": result["summary"],
        "source_hashes_unchanged": result["all_hashes_unchanged"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Opt-in local CRIC Phase 11 shadow logger and report utility")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="Validate local engine and Phase 9 baseline without starting a service")
    shadow = commands.add_parser("shadow", help="Record one explicitly configured prospective request from stdin")
    shadow.add_argument("--confirm-prospective", action="store_true")
    selection = commands.add_parser("selection", help="Append an explicitly observed actual selection")
    selection.add_argument("--confirm-prospective", action="store_true")
    delivery = commands.add_parser("observe-delivery", help="Append one source delivery record")
    delivery.add_argument("--confirm-prospective", action="store_true")
    wicket = commands.add_parser("observe-wicket", help="Append one source wicket record")
    wicket.add_argument("--confirm-prospective", action="store_true")
    finalization = commands.add_parser("finalize-outcome", help="Finalize only a predeclared fully observed horizon")
    finalization.add_argument("--confirm-prospective", action="store_true")
    correction = commands.add_parser("correct", help="Append a correction/supersession event")
    correction.add_argument("--confirm-prospective", action="store_true")
    commands.add_parser("summary", help="Print descriptive event coverage and integrity")
    commands.add_parser("export", help="Create a unique checksummed JSON export and SQLite backup")
    report = commands.add_parser("report", help="Create required non-Markdown reports in a new directory")
    report.add_argument("--baseline-hashes", type=Path)
    report.add_argument("--phase11-tests", default="not supplied")
    report.add_argument("--regression-tests", default="not supplied")
    report.add_argument("--compile-result", default="not supplied")
    args = parser.parse_args()
    actions = {
        "validate": lambda: command_validate(),
        "shadow": lambda: command_shadow(args),
        "selection": lambda: command_selection(args),
        "observe-delivery": lambda: command_observation(args, "observed_delivery"),
        "observe-wicket": lambda: command_observation(args, "observed_wicket"),
        "finalize-outcome": lambda: command_finalize(args),
        "correct": lambda: command_correction(args),
        "summary": command_summary,
        "export": command_export,
        "report": lambda: command_report(args),
    }
    try:
        result = actions[args.command]()
    except (EventValidationError, EventStoreError, ValueError, FileExistsError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
