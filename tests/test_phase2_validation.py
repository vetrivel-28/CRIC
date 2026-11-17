from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.validation.cric_validation import validate_file
from scripts.validation.phase2_pipeline import build_phase2_outputs


def test_missing_columns_are_reported(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"match_id": [1], "innings_number": [1]}).to_csv(path, index=False)
    result = validate_file(path, ["match_id", "innings_number", "bowler_id"])
    assert result["status"] == "FAIL"
    assert "bowler_id" in result["missing_columns"]


def test_duplicate_key_and_missing_identifier_are_flagged(tmp_path):
    path = tmp_path / "dup.csv"
    df = pd.DataFrame([
        {"match_id": "m1", "innings_number": 1, "over_number": 1, "ball_in_over": 1, "bowler_id": None},
        {"match_id": "m1", "innings_number": 1, "over_number": 1, "ball_in_over": 1, "bowler_id": "b1"},
    ])
    df.to_csv(path, index=False)
    result = validate_file(path, ["match_id", "innings_number", "over_number", "ball_in_over", "bowler_id"], key_columns=["match_id", "innings_number", "over_number", "ball_in_over"])
    assert result["duplicate_key_rows"] == 1
    assert result["missing_identifier_rows"] == 1


def test_zero_legal_ball_bowler_is_counted_across_delivery_chunks(tmp_path):
    path = tmp_path / "deliveries.csv"
    pd.DataFrame([
        {
            "match_id": "m1", "innings_number": 1, "over_number": 1,
            "ball_in_over": 1, "batter_id": "a", "bowler_id": "wide-only",
            "runs_batter": 0, "runs_extras": 1, "runs_total": 1,
            "extra_wides": 1, "extra_noballs": 0, "is_legal_delivery": False,
            "is_wicket": False, "match_phase": "Powerplay",
        },
        {
            "match_id": "m1", "innings_number": 1, "over_number": 1,
            "ball_in_over": 2, "batter_id": "a", "bowler_id": "legal",
            "runs_batter": 0, "runs_extras": 0, "runs_total": 0,
            "extra_wides": 0, "extra_noballs": 0, "is_legal_delivery": True,
            "is_wicket": False, "match_phase": "Powerplay",
        },
    ]).to_csv(path, index=False)
    result = validate_file(path, [
        "match_id", "innings_number", "over_number", "ball_in_over", "batter_id",
        "bowler_id", "runs_batter", "runs_extras", "runs_total", "extra_wides",
        "extra_noballs", "is_legal_delivery", "is_wicket", "match_phase",
    ])
    assert result["zero_legal_ball_bowlers"] == 1


def test_phase2_output_generation_creates_expected_files(tmp_path):
    source_root = Path("C:/CRIC/data").resolve()
    output_dir = tmp_path / "phase2_outputs"
    result = build_phase2_outputs(source_root, output_dir)
    files = result["files"]
    assert files["career_aggregates"].endswith("career_aggregates_phase2.csv")
    assert files["phase_aggregates"].endswith("phase_aggregates_phase2.csv")
    assert Path(files["recommendation_contract"]).exists()
    assert Path(files["execution_summary"]).exists()


def test_invalid_path_fails_gracefully(tmp_path):
    missing = tmp_path / "missing" / "deliveries.csv"
    result = validate_file(missing, ["match_id", "bowler_id"])
    assert result["status"] == "FAIL"
    assert "File not found" in result["issues"]


def test_zero_ball_record_is_preserved_in_legal_filter(tmp_path):
    path = tmp_path / "deliveries.csv"
    df = pd.DataFrame([
        {"match_id": "m1", "innings_number": 1, "over_number": 1, "ball_in_over": 1, "batter_id": "a", "bowler_id": "b", "runs_batter": 0, "runs_extras": 1, "runs_total": 1, "extra_wides": 1, "extra_noballs": 0, "is_legal_delivery": False, "is_wicket": False, "match_phase": "Powerplay"},
        {"match_id": "m1", "innings_number": 1, "over_number": 1, "ball_in_over": 2, "batter_id": "a", "bowler_id": "b", "runs_batter": 4, "runs_extras": 0, "runs_total": 4, "extra_wides": 0, "extra_noballs": 0, "is_legal_delivery": True, "is_wicket": False, "match_phase": "Powerplay"},
    ])
    df.to_csv(path, index=False)
    legal = df[df["is_legal_delivery"].fillna(False).astype(bool)]
    assert len(df) == 2
    assert len(legal) == 1
    assert bool(df.loc[0, "is_legal_delivery"]) is False


def test_rerun_produces_same_summary(tmp_path):
    source_root = Path("C:/CRIC/data").resolve()
    result_1 = build_phase2_outputs(source_root, tmp_path / "phase2a")
    result_2 = build_phase2_outputs(source_root, tmp_path / "phase2b")
    assert result_1["validation"][0]["rows"] == result_2["validation"][0]["rows"]
    assert result_1["validation"][0]["status"] == result_2["validation"][0]["status"]
    summary1 = json.loads(Path(result_1["files"]["execution_summary"]).read_text(encoding="utf-8"))
    summary2 = json.loads(Path(result_2["files"]["execution_summary"]).read_text(encoding="utf-8"))
    assert summary1["deliveries_rows"] == summary2["deliveries_rows"]
