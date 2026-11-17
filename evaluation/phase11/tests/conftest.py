from __future__ import annotations

import csv
from pathlib import Path

import pytest

from backend.recommendation_engine import DatasetPaths, RecommendationEngine


def _write(path: Path, headers: list[str], rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def engine(tmp_path: Path) -> RecommendationEngine:
    players = _write(
        tmp_path / "players.csv", ["player_id", "player_name"],
        [{"player_id": "bat1", "player_name": "Batter One"},
         {"player_id": "b1", "player_name": "Bowler One"},
         {"player_id": "b2", "player_name": "Bowler Two"}],
    )
    career_headers = [
        "bowler_id", "bowler_name", "legal_balls", "economy",
        "bowling_strike_rate_balls_per_wicket", "wicket_rate_per_100_legal_balls",
    ]
    career = _write(
        tmp_path / "career.csv", career_headers,
        [{"bowler_id": "b1", "bowler_name": "Bowler One", "legal_balls": 60, "economy": 5,
          "bowling_strike_rate_balls_per_wicket": 12, "wicket_rate_per_100_legal_balls": 8},
         {"bowler_id": "b2", "bowler_name": "Bowler Two", "legal_balls": 30, "economy": 7,
          "bowling_strike_rate_balls_per_wicket": 24, "wicket_rate_per_100_legal_balls": 4}],
    )
    phase = _write(
        tmp_path / "phase.csv", ["bowler_id", "bowler_name", "match_phase", *career_headers[2:]],
        [{"bowler_id": "b1", "bowler_name": "Bowler One", "match_phase": "Death", "legal_balls": 12,
          "economy": 4, "bowling_strike_rate_balls_per_wicket": 6, "wicket_rate_per_100_legal_balls": 10}],
    )
    matchup = _write(
        tmp_path / "matchup.csv", ["bowler_id", "batter_id", "balls", "runs_conceded_by_bowler", "wickets"],
        [{"bowler_id": "b1", "batter_id": "bat1", "balls": 6, "runs_conceded_by_bowler": 5, "wickets": 1}],
    )
    situation = _write(
        tmp_path / "situation.csv",
        ["bowler_id", "situation_type", "situation_value", "balls", "runs_conceded", "wickets"],
        [{"bowler_id": "b1", "situation_type": "phase", "situation_value": "death", "balls": 6, "runs_conceded": 4, "wickets": 1}],
    )
    return RecommendationEngine(DatasetPaths(players, career, phase, matchup, situation))
