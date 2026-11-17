from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validation.cric_validation import DATA_ROOT, DEFAULT_OUTPUT_DIR, _atomic_write_text, _find_first_csv, validate_cric_source_files


def build_phase2_outputs(source_root: Path, output_dir: Path) -> dict:
    source_root = source_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    deliveries_path = _find_first_csv("deliveries.csv", source_root)
    wickets_path = _find_first_csv("wicket_events.csv", source_root)

    if deliveries_path is None or wickets_path is None:
        raise FileNotFoundError("Deliveries and wicket source files are required for phase 2 output generation.")

    deliveries_rows = 0
    legal_rows = 0
    legal_parts: list[pd.DataFrame] = []
    try:
        delivery_reader = pd.read_csv(
            deliveries_path,
            chunksize=250000,
            engine="python",
            on_bad_lines="skip",
        )
        for chunk in delivery_reader:
            deliveries_rows += len(chunk)
            legal_chunk = chunk[chunk["is_legal_delivery"].fillna(False).astype(bool)].copy()
            legal_rows += len(legal_chunk)
            if not legal_chunk.empty:
                legal_chunk["runs_conceded"] = (
                    legal_chunk["runs_batter"].fillna(0)
                    + legal_chunk["extra_wides"].fillna(0)
                    + legal_chunk["extra_noballs"].fillna(0)
                )
                legal_chunk["dot_ball_flag"] = (legal_chunk["runs_total"].fillna(0) == 0)
                legal_parts.append(legal_chunk)
    except ValueError as exc:
        raise ValueError(f"Unable to parse deliveries dataset: {deliveries_path}") from exc
    legal = pd.concat(legal_parts, ignore_index=True) if legal_parts else pd.DataFrame()
    wickets = pd.read_csv(wickets_path, engine="python", on_bad_lines="skip")

    career_path = _find_first_csv("bowler_career_performance_v1.csv", source_root)
    phase_path = _find_first_csv("bowler_phase_performance_v1.csv", source_root)

    if career_path is not None:
        career = pd.read_csv(career_path, low_memory=False)
    else:
        if legal.empty:
            career = pd.DataFrame(
                columns=[
                    "bowler_id",
                    "bowler_name",
                    "matches",
                    "innings",
                    "deliveries",
                    "legal_balls",
                    "runs_conceded",
                    "wickets",
                    "dot_balls",
                    "fours",
                    "sixes",
                    "economy",
                    "bowling_average",
                    "bowling_strike_rate_balls_per_wicket",
                    "wicket_rate_per_100_legal_balls",
                    "dot_ball_pct",
                    "boundary_pct_of_legal_balls",
                    "sample_size_flag",
                    "small_sample_flag",
                ]
            )
        else:
            career = (
                legal.groupby("bowler_id", dropna=False)
                .agg(
                    bowler_name=("bowler_name", "first"),
                    matches=("match_id", "nunique"),
                    innings=("innings_number", "nunique"),
                    deliveries=("match_id", "count"),
                    legal_balls=("is_legal_delivery", "sum"),
                    runs_conceded=("runs_conceded", "sum"),
                    wickets=("is_wicket", "sum"),
                    dot_balls=("dot_ball_flag", "sum"),
                    fours=("runs_batter", lambda s: int((s == 4).sum())),
                    sixes=("runs_batter", lambda s: int((s == 6).sum())),
                )
                .reset_index()
            )
            career["economy"] = career["runs_conceded"] / (career["legal_balls"] / 6)
            career["bowling_average"] = career["runs_conceded"] / career["wickets"].replace(0, pd.NA)
            career["bowling_strike_rate_balls_per_wicket"] = career["legal_balls"] / career["wickets"].replace(0, pd.NA)
            career["wicket_rate_per_100_legal_balls"] = (career["wickets"] / career["legal_balls"]) * 100
            career["dot_ball_pct"] = (career["dot_balls"] / career["legal_balls"]) * 100
            career["boundary_pct_of_legal_balls"] = ((career["fours"] + career["sixes"]) / career["legal_balls"]) * 100
            career["sample_size_flag"] = pd.Series(
                ["very_small_sample" if balls < 60 else "small_sample" if balls < 180 else "adequate_for_basic_summary" for balls in career["legal_balls"]],
                index=career.index,
            )
            career["small_sample_flag"] = career["legal_balls"] < 180

    if phase_path is not None:
        phase = pd.read_csv(phase_path, low_memory=False)
    else:
        if legal.empty:
            phase = pd.DataFrame(
                columns=[
                    "bowler_id",
                    "match_phase",
                    "bowler_name",
                    "matches",
                    "innings",
                    "deliveries",
                    "legal_balls",
                    "runs_conceded",
                    "wickets",
                    "dot_balls",
                    "fours",
                    "sixes",
                    "economy",
                    "bowling_average",
                    "bowling_strike_rate_balls_per_wicket",
                    "wicket_rate_per_100_legal_balls",
                    "dot_ball_pct",
                    "boundary_pct_of_legal_balls",
                    "sample_size_flag",
                    "small_sample_flag",
                ]
            )
        else:
            phase = (
                legal.groupby(["bowler_id", "match_phase"], dropna=False)
                .agg(
                    bowler_name=("bowler_name", "first"),
                    matches=("match_id", "nunique"),
                    innings=("innings_number", "nunique"),
                    deliveries=("match_id", "count"),
                    legal_balls=("is_legal_delivery", "sum"),
                    runs_conceded=("runs_conceded", "sum"),
                    wickets=("is_wicket", "sum"),
                    dot_balls=("dot_ball_flag", "sum"),
                    fours=("runs_batter", lambda s: int((s == 4).sum())),
                    sixes=("runs_batter", lambda s: int((s == 6).sum())),
                )
                .reset_index()
            )
            phase["economy"] = phase["runs_conceded"] / (phase["legal_balls"] / 6)
            phase["bowling_average"] = phase["runs_conceded"] / phase["wickets"].replace(0, pd.NA)
            phase["bowling_strike_rate_balls_per_wicket"] = phase["legal_balls"] / phase["wickets"].replace(0, pd.NA)
            phase["wicket_rate_per_100_legal_balls"] = (phase["wickets"] / phase["legal_balls"]) * 100
            phase["dot_ball_pct"] = (phase["dot_balls"] / phase["legal_balls"]) * 100
            phase["boundary_pct_of_legal_balls"] = ((phase["fours"] + phase["sixes"]) / phase["legal_balls"]) * 100
            phase["sample_size_flag"] = pd.Series(
                ["very_small_sample" if balls < 60 else "small_sample" if balls < 180 else "adequate_for_basic_summary" for balls in phase["legal_balls"]],
                index=phase.index,
            )
            phase["small_sample_flag"] = phase["legal_balls"] < 180

    credited = wickets[wickets["is_bowler_credited"].fillna(False).astype(bool)].copy()
    wicket_summary = credited.groupby("bowler_id", dropna=False).agg(bowler_name=("bowler_name", "first"), credited_wickets=("match_id", "count")).reset_index()

    processed = output_dir / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    career_path_out = processed / "career_aggregates_phase2.csv"
    phase_path_out = processed / "phase_aggregates_phase2.csv"
    wickets_path_out = processed / "credited_wickets_phase2.csv"
    contract_path = output_dir / "recommendation_contract.csv"
    validation_path = output_dir / "validation_report.csv"
    summary_path = output_dir / "execution_summary.json"

    career.to_csv(career_path_out, index=False)
    phase.to_csv(phase_path_out, index=False)
    wicket_summary.to_csv(wickets_path_out, index=False)

    contract = pd.DataFrame([
        {"field": "bowler_id", "dtype": "string", "required": True, "source": "deliveries.csv + wicket_events.csv", "notes": "Primary match key"},
        {"field": "batter_id", "dtype": "string", "required": True, "source": "deliveries.csv", "notes": "Needed to match a batter against bowlers"},
        {"field": "bowler_name", "dtype": "string", "required": False, "source": "deliveries.csv + wicket_events.csv", "notes": "Readable label for output"},
        {"field": "batter_name", "dtype": "string", "required": False, "source": "deliveries.csv", "notes": "Readable label only"},
        {"field": "balls", "dtype": "int64", "required": True, "source": "matchup aggregate", "notes": "Legal balls or total match-up deliveries"},
        {"field": "runs_conceded_by_bowler", "dtype": "float64", "required": True, "source": "matchup aggregate", "notes": "Runs conceded by the bowler in the matchup"},
        {"field": "wickets", "dtype": "int64", "required": True, "source": "matchup aggregate", "notes": "Credited wickets in the matchup sample"},
        {"field": "match_phase", "dtype": "string", "required": False, "source": "deliveries.csv", "notes": "Optional phase label for phase-level recommendations"},
    ])
    contract.to_csv(contract_path, index=False)

    validation_results = validate_cric_source_files(source_root)
    validation_df = pd.DataFrame(validation_results)
    validation_df.to_csv(validation_path, index=False)
    legal_rows = int(legal_rows)
    summary = {
        "status": "OK",
        "source_root": str(source_root),
        "output_dir": str(output_dir),
        "deliveries_rows": deliveries_rows,
        "legal_delivery_rows": legal_rows,
        "credited_wickets": int(credited.shape[0]),
        "career_rows": len(career),
        "phase_rows": len(phase),
        "validation_results": validation_results,
        "files_written": [
            str(career_path_out),
            str(phase_path_out),
            str(wickets_path_out),
            str(contract_path),
            str(validation_path),
        ],
    }
    _atomic_write_text(summary_path, json.dumps(summary, indent=2, sort_keys=True))

    return {
        "files": {
            "career_aggregates": str(career_path_out),
            "phase_aggregates": str(phase_path_out),
            "credited_wickets": str(wickets_path_out),
            "recommendation_contract": str(contract_path),
            "validation_report": str(validation_path),
            "execution_summary": str(summary_path),
        },
        "validation": validation_results,
        "recommendation_contract": contract.to_dict(orient="records"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Phase 2 CRIC analytics outputs in a dedicated output directory.")
    parser.add_argument("--source-root", type=Path, default=DATA_ROOT, help="Directory that contains the CRIC source CSV files")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for processed Phase 2 outputs")
    args = parser.parse_args()

    result = build_phase2_outputs(args.source_root, args.output_dir)
    print(json.dumps({
        "status": "OK",
        "default_files": result["files"],
        "validation": result["validation"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
