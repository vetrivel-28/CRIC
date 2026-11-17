from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data"
DEFAULT_OUTPUT_DIR = ROOT / "phase2_outputs"

REQUIRED_COLUMNS = {
    "deliveries.csv": [
        "match_id",
        "innings_number",
        "over_number",
        "ball_in_over",
        "batter_id",
        "bowler_id",
        "runs_batter",
        "runs_extras",
        "runs_total",
        "extra_wides",
        "extra_noballs",
        "is_legal_delivery",
        "is_wicket",
        "match_phase",
    ],
    "wicket_events.csv": [
        "match_id",
        "innings_number",
        "over_number",
        "ball_in_over",
        "bowler_id",
        "is_bowler_credited",
    ],
    "bowler_career_performance_v1.csv": [
        "bowler_id",
        "bowler_name",
        "matches",
        "innings",
        "deliveries",
        "legal_balls",
        "runs_conceded",
        "wickets",
    ],
    "bowler_phase_performance_v1.csv": [
        "bowler_id",
        "bowler_name",
        "match_phase",
        "matches",
        "innings",
        "deliveries",
        "legal_balls",
        "runs_conceded",
        "wickets",
    ],
}

NUMERIC_COLUMNS = {
    "deliveries.csv": [
        "innings_number",
        "over_number",
        "ball_in_over",
        "runs_batter",
        "runs_extras",
        "runs_total",
        "extra_wides",
        "extra_noballs",
        "extra_byes",
        "extra_legbyes",
        "extra_penalty",
        "is_legal_delivery",
        "is_wicket",
    ],
    "wicket_events.csv": [
        "innings_number",
        "over_number",
        "ball_in_over",
        "is_bowler_credited",
    ],
}


def _find_first_csv(name: str, search_root: Path) -> Path | None:
    for path in sorted(search_root.rglob(name)):
        if path.is_file():
            return path
    return None


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _iter_csv_chunks(path: Path, chunksize: int = 100000):
    return pd.read_csv(path, low_memory=False, chunksize=chunksize)


def validate_file(path: Path, required_columns: Iterable[str], key_columns: Iterable[str] | None = None) -> dict:
    expected = list(required_columns)
    if not path.exists():
        return {
            "dataset": path.name,
            "status": "FAIL",
            "file": str(path),
            "missing_columns": expected,
            "rows": 0,
            "duplicate_key_rows": 0,
            "missing_identifier_rows": 0,
            "invalid_numeric_rows": 0,
            "issues": ["File not found"],
        }

    try:
        sample = pd.read_csv(path, nrows=5, low_memory=False)
    except Exception as exc:
        return {
            "dataset": path.name,
            "status": "FAIL",
            "file": str(path),
            "missing_columns": expected,
            "rows": 0,
            "duplicate_key_rows": 0,
            "missing_identifier_rows": 0,
            "invalid_numeric_rows": 0,
            "issues": [f"Could not read file: {exc}"],
        }

    columns = list(sample.columns)
    missing = [col for col in expected if col not in columns]
    if missing:
        return {
            "dataset": path.name,
            "status": "FAIL",
            "file": str(path),
            "missing_columns": missing,
            "rows": 0,
            "duplicate_key_rows": 0,
            "missing_identifier_rows": 0,
            "invalid_numeric_rows": 0,
            "issues": ["Missing required columns"],
        }

    total_rows = 0
    duplicate_key_rows = 0
    missing_identifier_rows = 0
    invalid_numeric_rows = 0
    zero_legal_ball_bowlers = 0
    legal_balls_by_bowler: dict[str, int] = {}

    numeric_fields = NUMERIC_COLUMNS.get(path.name, [])
    id_fields = [field for field in ("bowler_id", "batter_id", "player_out_id", "match_id") if field in sample.columns]
    key_fields = list(key_columns) if key_columns else []

    try:
        for chunk in _iter_csv_chunks(path):
            total_rows += len(chunk)
            if key_fields:
                duplicate_key_rows += int(chunk.duplicated(subset=key_fields).sum())
            for field in id_fields:
                missing_identifier_rows += int(chunk[field].isna().sum())
            for field in numeric_fields:
                if field in chunk.columns:
                    invalid_numeric_rows += int(
                        (pd.to_numeric(chunk[field], errors="coerce").isna() & chunk[field].notna()).sum()
                    )
            if path.name == "deliveries.csv":
                legal_flags = chunk["is_legal_delivery"].fillna(False).astype(bool)
                legal_totals = (
                    chunk.assign(_legal_flag=legal_flags)
                    .groupby("bowler_id", dropna=False)["_legal_flag"]
                    .sum()
                )
                for bowler_id, legal_count in legal_totals.items():
                    key = str(bowler_id)
                    legal_balls_by_bowler[key] = legal_balls_by_bowler.get(key, 0) + int(legal_count)
    except Exception as exc:
        return {
            "dataset": path.name,
            "status": "FAIL",
            "file": str(path),
            "missing_columns": [],
            "rows": total_rows,
            "duplicate_key_rows": duplicate_key_rows,
            "missing_identifier_rows": missing_identifier_rows,
            "invalid_numeric_rows": invalid_numeric_rows,
            "issues": [f"Chunk validation failed: {exc}"],
        }

    status = "PASS"
    issues: list[str] = []
    if path.name == "deliveries.csv":
        zero_legal_ball_bowlers = sum(count == 0 for count in legal_balls_by_bowler.values())
    if duplicate_key_rows > 0:
        issues.append(f"Duplicate key rows: {duplicate_key_rows}")
        status = "WARNING"
    if missing_identifier_rows > 0:
        issues.append(f"Missing identifiers: {missing_identifier_rows}")
        status = "WARNING"
    if invalid_numeric_rows > 0:
        issues.append(f"Invalid numeric values: {invalid_numeric_rows}")
        status = "WARNING"

    return {
        "dataset": path.name,
        "status": status,
        "file": str(path),
        "missing_columns": missing,
        "rows": total_rows,
        "duplicate_key_rows": duplicate_key_rows,
        "missing_identifier_rows": missing_identifier_rows,
        "invalid_numeric_rows": invalid_numeric_rows,
        "zero_legal_ball_bowlers": zero_legal_ball_bowlers,
        "issues": issues,
    }


def validate_cric_source_files(source_root: Path) -> list[dict]:
    results: list[dict] = []
    deliveries_path = _find_first_csv("deliveries.csv", source_root)
    wickets_path = _find_first_csv("wicket_events.csv", source_root)

    if deliveries_path is not None:
        results.append(validate_file(deliveries_path, REQUIRED_COLUMNS["deliveries.csv"], key_columns=["match_id", "innings_number", "over_number", "ball_in_over"]))
    if wickets_path is not None:
        results.append(validate_file(wickets_path, REQUIRED_COLUMNS["wicket_events.csv"], key_columns=["wicket_event_id"]))

    return results


def validate_derived_outputs(source_root: Path) -> list[dict]:
    career_path = _find_first_csv("bowler_career_performance_v1.csv", source_root)
    phase_path = _find_first_csv("bowler_phase_performance_v1.csv", source_root)
    results: list[dict] = []

    if career_path is not None:
        metrics = validate_file(career_path, REQUIRED_COLUMNS["bowler_career_performance_v1.csv"])
        results.append(metrics)
    if phase_path is not None:
        metrics = validate_file(phase_path, REQUIRED_COLUMNS["bowler_phase_performance_v1.csv"])
        results.append(metrics)

    return results


def write_validation_report(results: list[dict], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "validation_report.csv"
    df = pd.DataFrame(results)
    _atomic_write_text(report_path, df.to_csv(index=False))
    return report_path


def write_summary_json(results: list[dict], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "validation_summary.json"
    info = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds").replace("+00:00", "Z"),
        "checks": results,
        "pass_count": sum(1 for row in results if row.get("status") == "PASS"),
        "warning_count": sum(1 for row in results if row.get("status") == "WARNING"),
        "fail_count": sum(1 for row in results if row.get("status") == "FAIL"),
    }
    _atomic_write_text(path, json.dumps(info, indent=2, sort_keys=True))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the CRIC source and derived CSV datasets without mutating the source files.")
    parser.add_argument("--source-root", type=Path, default=DATA_ROOT, help="Directory that contains the CRIC CSVs")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for validation artifacts")
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    output_dir = args.output_dir.resolve()

    source_results = validate_cric_source_files(source_root)
    derived_results = validate_derived_outputs(source_root)
    report_path = write_validation_report(source_results + derived_results, output_dir)
    summary_path = write_summary_json(source_results + derived_results, output_dir)

    print(f"Validation report written to: {report_path}")
    print(f"Summary JSON written to: {summary_path}")
    for result in source_results + derived_results:
        print(f"{result['dataset']}: {result['status']} | rows={result.get('rows', 0)} | issues={result.get('issues', [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
