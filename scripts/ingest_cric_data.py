#!/usr/bin/env python3
"""Safe CRIC dataset discovery and ingestion metadata generator.

This tool validates local CSV files used by the CRIC project and captures the
metadata needed for data cataloging and relational ingestion. It does not overwrite source
files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
PROCESSED_ROOT = DATA_ROOT / "processed"
LOGS_ROOT = ROOT / "logs"
DEFAULT_MANIFEST = PROCESSED_ROOT / "ingestion_manifest.csv"
DEFAULT_LOG = LOGS_ROOT / "cric_ingestion.log"

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
    "bowler_batter_matchup_stats_v2.csv": [
        "bowler_id",
        "batter_id",
        "bowler_name",
        "batter_name",
        "balls",
        "runs_conceded_by_bowler",
        "wickets",
    ],
    "bowler_situation_stats_v2.csv": [
        "bowler_id",
        "bowler_name",
        "situation_type",
        "situation_value",
        "balls",
        "runs_conceded",
        "wickets",
    ],
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_csvs(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.csv")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in {"processed", "reports", "__pycache__"} for part in rel_parts):
            continue
        files.append(path)
    return files


def file_metadata(path: Path) -> dict:
    return {
        "file_name": path.name,
        "relative_path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "file_size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "modified_at_utc": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
    }


def validate_headers(path: Path) -> dict:
    required = REQUIRED_COLUMNS.get(path.name)
    if required is None:
        return {
            "status": "OK",
            "required_columns": [],
            "missing_columns": [],
            "header_preview": [],
        }

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return {
                "status": "EMPTY_FILE",
                "required_columns": required,
                "missing_columns": required,
                "header_preview": [],
            }

    lower_lookup = {value.strip().lower(): value for value in header}
    missing = [column for column in required if column.lower() not in lower_lookup]
    return {
        "status": "OK" if not missing else "MISSING_COLUMNS",
        "required_columns": required,
        "missing_columns": missing,
        "header_preview": header[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT, help="Directory containing the CRIC datasets")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="CSV manifest path for file metadata")
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    if not data_root.exists():
        raise SystemExit(f"Data root does not exist: {data_root}")

    files = discover_csvs(data_root)
    if not files:
        print(f"No CSV files found under {data_root}")
        return 1

    PROCESSED_ROOT.mkdir(parents=True, exist_ok=True)
    LOGS_ROOT.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for path in files:
        meta = file_metadata(path)
        validation = validate_headers(path)
        rows.append({
            **meta,
            "validation_status": validation["status"],
            "required_columns": ";".join(validation["required_columns"]),
            "missing_columns": ";".join(validation["missing_columns"]),
            "header_preview": ";".join(validation["header_preview"]),
            "recorded_at_utc": utc_now_iso(),
        })

    fieldnames = [
        "recorded_at_utc",
        "relative_path",
        "file_name",
        "file_size_bytes",
        "sha256",
        "modified_at_utc",
        "validation_status",
        "required_columns",
        "missing_columns",
        "header_preview",
    ]
    with args.manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    log_lines = [
        f"[{utc_now_iso()}] CRIC ingestion metadata generated for {len(files)} CSV files",
        f"Manifest: {args.manifest}",
    ]
    with DEFAULT_LOG.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(log_lines) + "\n")

    print(f"Discovered {len(files)} CSV file(s) under {data_root}")
    print(f"Manifest written to: {args.manifest}")
    for row in rows[:5]:
        print(json.dumps(row, sort_keys=True))
    if len(rows) > 5:
        print(f"... {len(rows) - 5} additional rows omitted from console output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
