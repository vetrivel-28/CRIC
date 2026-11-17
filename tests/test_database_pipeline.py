"""
Tests for CRIC PostgreSQL Configuration, Ingestion, and Schema Pipelines.
"""

import os
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import pytest

from backend.database.connection import DatabaseConfig, DatabaseConnection, get_config_from_env
from backend.database.repository import CricketRepository
from backend.postgres_dashboard_data import PostgresDashboardData
from backend.recommendation_engine import RecommendationEngine
from config.config_loader import load_db_config
from scripts.ingestion.load_postgres import (
    compute_sha256,
    generate_deterministic_wicket_id,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _RecordingCursor:
    description = [("bowler_id",)]

    def __init__(self):
        self.query = ""
        self.params = ()

    def execute(self, query, params=()):
        self.query = query
        self.params = params

    def fetchall(self):
        return []


class _RecordingDatabase:
    def __init__(self):
        self.recording_cursor = _RecordingCursor()

    @contextmanager
    def cursor(self, *, read_only=False):
        yield self.recording_cursor


def test_config_loader_reads_defaults_and_env():
    # Test defaults
    cfg = load_db_config()
    assert "host" in cfg
    assert "port" in cfg
    assert "dbname" in cfg

    # Test environment variable overrides
    os.environ["CRIC_DB_HOST"] = "test-host"
    os.environ["CRIC_DB_PORT"] = "5433"
    os.environ["CRIC_DB_NAME"] = "test_analytics"
    try:
        cfg2 = load_db_config()
        assert cfg2["host"] == "test-host"
        assert cfg2["port"] == 5433
        assert cfg2["dbname"] == "test_analytics"
    finally:
        del os.environ["CRIC_DB_HOST"]
        del os.environ["CRIC_DB_PORT"]
        del os.environ["CRIC_DB_NAME"]


def test_database_connection_uses_documented_ini_configuration(monkeypatch):
    from backend.database import connection

    for name in (
        "CRIC_DB_HOST", "CRIC_DB_PORT", "CRIC_DB_NAME", "CRIC_DB_USER",
        "CRIC_DB_PASSWORD", "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        connection,
        "load_db_config",
        lambda: {
            "host": "db-host",
            "port": 5544,
            "dbname": "cric_test",
            "user": "cric_user",
            "password": "fixture-password",
            "sslmode": "prefer",
        },
    )

    config = get_config_from_env()

    assert (config.host, config.port, config.database, config.user) == (
        "db-host", 5544, "cric_test", "cric_user",
    )
    assert config.password == "fixture-password"


def test_deterministic_wicket_id_uniqueness_and_reproducibility():
    id1 = generate_deterministic_wicket_id("2023-01-01_M1", 1, 19, 5, "p_123")
    id2 = generate_deterministic_wicket_id("2023-01-01_M1", 1, 19, 5, "p_123")
    id3 = generate_deterministic_wicket_id("2023-01-01_M1", 1, 19, 5, "p_456")

    # Positive 63-bit integer
    assert id1 > 0
    assert id1 <= 0x7FFFFFFFFFFFFFFF
    # Reproducible across calls
    assert id1 == id2
    # Distinct for different players on the same ball
    assert id1 != id3


def test_sql_migration_files_exist_and_are_non_empty():
    migration_file = PROJECT_ROOT / "database" / "migrations" / "001_initial_schema.sql"
    assert migration_file.exists()
    assert migration_file.stat().st_size > 500

    seeds_file = PROJECT_ROOT / "database" / "seeds" / "01_seed_dimensions.sql"
    assert seeds_file.exists()
    assert seeds_file.stat().st_size > 200

    content = migration_file.read_text(encoding="utf-8")
    assert "CREATE SCHEMA IF NOT EXISTS cricket_raw;" in content
    assert "CREATE SCHEMA IF NOT EXISTS cricket_dim;" in content
    assert "CREATE SCHEMA IF NOT EXISTS cricket_fact;" in content
    assert "CREATE SCHEMA IF NOT EXISTS cricket_analytics;" in content
    assert "fact_delivery" in content
    assert "fact_wicket" in content
    assert "v_bowler_career_performance" in content


def test_database_connection_ping_handles_offline_gracefully():
    # When PostgreSQL is stopped, ping() must return False without crashing
    db = DatabaseConnection(DatabaseConfig(host="127.0.0.1", port=59999, database="dummy"))
    assert db.ping() is False


def test_compute_sha256_matches_known_data():
    players_csv = PROJECT_ROOT / "data" / "raw" / "players.csv"
    assert players_csv.exists()
    sha = compute_sha256(players_csv)
    assert len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha)


def test_repository_queries_match_all_seven_analytics_view_contracts():
    db = _RecordingDatabase()
    repository = CricketRepository(db)
    view_queries = (
        (repository.get_bowler_career_performance, "v_bowler_career_performance"),
        (repository.get_bowler_phase_performance, "v_bowler_phase_performance"),
        (repository.get_bowler_batter_matchups, "v_bowler_batter_matchups"),
        (repository.get_bowler_situation_performance, "v_bowler_situation_performance"),
        (repository.get_wicket_profiles, "v_wicket_profiles"),
        (repository.get_season_bowling_performance, "v_season_bowling_performance"),
        (repository.get_batter_career_performance, "v_batter_career_performance"),
    )

    for query_method, view_name in view_queries:
        assert query_method() == []
        assert f"cricket_analytics.{view_name}" in db.recording_cursor.query


def test_repository_matchups_include_phase_splits_from_staged_aggregate():
    db = _RecordingDatabase()
    repository = CricketRepository(db)

    assert repository.get_bowler_batter_matchups() == []
    assert "cricket_analytics.v_bowler_batter_matchups" in db.recording_cursor.query
    assert "cricket_raw.raw_matchups" in db.recording_cursor.query
    assert "phase_runs_conceded_powerplay" in db.recording_cursor.query
    assert "HAVING COUNT(*) = 1" in db.recording_cursor.query


def test_recommendation_engine_can_load_postgres_records_without_changing_scores():
    class RepositoryStub:
        def get_players(self):
            return [
                {"player_id": "bowler-1", "player_name": "Bowler One"},
                {"player_id": "batter-1", "player_name": "Batter One"},
            ]

        def get_bowler_career_performance(self):
            return [{
                "bowler_id": "bowler-1",
                "bowler_name": "Bowler One",
                "legal_balls": 60,
                "runs_conceded": 45,
                "wickets": 3,
                "economy": 4.5,
                "bowling_strike_rate_balls_per_wicket": 20,
                "wicket_rate_per_100_legal_balls": 5,
                "dot_balls": 20,
                "dot_ball_pct": 33.33,
            }]

        def get_bowler_phase_performance(self):
            return [{
                "bowler_id": "bowler-1",
                "bowler_name": "Bowler One",
                "match_phase": "Powerplay",
                "legal_balls": 30,
                "runs_conceded": 20,
                "wickets": 2,
                "economy": 4,
                "bowling_strike_rate_balls_per_wicket": 15,
                "wicket_rate_per_100_legal_balls": 6.67,
                "dot_balls": 10,
                "dot_ball_pct": 33.33,
            }]

        def get_bowler_batter_matchups(self):
            return [{
                "bowler_id": "bowler-1",
                "batter_id": "batter-1",
                "balls": 20,
                "runs_conceded_by_bowler": 18,
                "wickets": 1,
                "dot_balls": 7,
                "phase_balls_powerplay": 8,
                "phase_runs_conceded_powerplay": 4,
                "phase_wickets_powerplay": 1,
                "phase_dots_powerplay": 3,
            }]

        def get_bowler_situation_performance(self):
            return [{
                "bowler_id": "bowler-1",
                "situation_type": "required run rate",
                "situation_value": "7-9",
                "balls": 30,
                "runs_conceded": 20,
                "wickets": 2,
                "dot_balls": 10,
                "economy": 4,
                "strike_rate_balls_per_wicket": 15,
                "wicket_rate_per_100_legal_balls": 6.67,
                "dot_ball_pct": 33.33,
            }]

    engine = RecommendationEngine.from_repository(RepositoryStub())

    assert engine.ready
    assert engine.matchups[("bowler-1", "batter-1")].phase_totals["powerplay"] == (8, 4, 1)
    assert engine.matchups[("bowler-1", "batter-1")].phase_dot_balls["powerplay"] == 3


def test_postgres_matchup_projection_uses_phase_source_metrics():
    dashboard = PostgresDashboardData.__new__(PostgresDashboardData)
    row = dashboard._matchup_row(
        {
            "bowler_id": "bowler-1",
            "bowler_name": "Bowler One",
            "batter_id": "batter-1",
            "batter_name": "Batter One",
            "phase_balls_powerplay": 8,
            "phase_runs_conceded_powerplay": 4,
            "phase_wickets_powerplay": 1,
            "phase_runs_scored_powerplay": 6,
        },
        "powerplay",
    )

    assert row["legal_balls"] == 8
    assert row["runs_conceded"] == 4
    assert row["wickets"] == 1
    assert row["batter_runs"] == 6
    assert row["batter_strike_rate"] == 75
    assert row["economy"] == 3
    assert row["bowling_strike_rate"] == 8


def test_repository_values_are_json_serializable():
    assert CricketRepository._json_value(Decimal("7.50")) == 7.5
    assert CricketRepository._json_value(Decimal("12")) == 12
    assert CricketRepository._json_value(date(2024, 1, 2)) == "2024-01-02"


def test_postgres_dashboard_projects_real_analytics_contracts():
    class RepositoryStub:
        def get_players(self):
            return [
                {"player_id": "bowler-1", "player_name": "Bowler One"},
                {"player_id": "batter-1", "player_name": "Batter One"},
            ]

        def get_bowler_career_performance(self):
            return [{
                "bowler_id": "bowler-1", "bowler_name": "Bowler One",
                "legal_balls": 60, "runs_conceded": 45, "wickets": 3,
                "economy": 4.5, "bowling_average": 15,
                "bowling_strike_rate_balls_per_wicket": 20,
                "wicket_rate_per_100_legal_balls": 5, "dot_balls": 20,
                "dot_ball_pct": 33.33, "sample_size_flag": "broader",
            }]

        def get_bowler_phase_performance(self):
            return [{
                "bowler_id": "bowler-1", "bowler_name": "Bowler One",
                "match_phase": "Powerplay", "legal_balls": 30,
                "runs_conceded": 20, "wickets": 2, "economy": 4,
                "bowling_average": 10, "bowling_strike_rate_balls_per_wicket": 15,
                "wicket_rate_per_100_legal_balls": 6.67, "dot_balls": 10,
                "dot_ball_pct": 33.33,
            }]

        def get_bowler_batter_matchups(self):
            return [{
                "bowler_id": "bowler-1", "bowler_name": "Bowler One",
                "batter_id": "batter-1", "batter_name": "Batter One",
                "balls": 20, "runs_scored_by_batter": 18,
                "runs_conceded_by_bowler": 18, "wickets": 1,
                "phase_balls_powerplay": 8, "phase_runs_scored_powerplay": 6,
                "phase_runs_conceded_powerplay": 4, "phase_wickets_powerplay": 1,
            }]

        def get_bowler_situation_performance(self):
            return [{
                "bowler_id": "bowler-1", "bowler_name": "Bowler One",
                "situation_type": "phase", "situation_value": "death",
                "cricket_over": 18, "balls": 30, "runs_conceded": 20,
                "wickets": 2, "economy": 4,
                "strike_rate_balls_per_wicket": 15,
                "wicket_rate_per_100_legal_balls": 6.67, "dot_ball_pct": 33.33,
            }]

        def get_season_bowling_performance(self):
            return [{
                "bowler_id": "bowler-1", "bowler_name": "Bowler One",
                "season": "2024", "season_matches": 4, "season_balls": 60,
                "season_runs": 45, "season_wickets": 3,
                "season_economy": 4.5, "season_average": 15,
            }]

        def get_batter_career_performance(self):
            return [{
                "batter_id": "batter-1", "batter_name": "Batter One",
                "matches_batted": 4, "innings_batted": 4, "balls_faced": 30,
                "runs_scored": 36, "dismissals": 2, "fours": 4, "sixes": 1,
                "dot_balls_faced": 10, "strike_rate": 120,
                "batting_average": 18, "boundary_run_pct": 66.67,
            }]

        def get_wicket_events(self):
            return [{
                "wicket_event_id": 1, "match_id": "match-1", "season": "2024",
                "innings_number": 1, "over_number": 18, "ball_in_over": 2,
                "over_phase": "Death", "bowler_id": "bowler-1",
                "bowler_name": "Bowler One", "player_out_id": "batter-1",
                "player_out_name": "Batter One", "kind": "bowled",
                "is_bowler_credited": True,
            }]

        def get_dismissal_types(self):
            return [{"kind": "bowled", "is_bowler_credited": True}]

        def get_dashboard_counts(self):
            return {
                "matches": 1, "deliveries": 60, "wicket_events": 1,
                "matchup_records": 1, "batters_in_matchups": 1, "datasets": 7,
            }

    repository = RepositoryStub()
    engine = RecommendationEngine.from_repository(repository)
    dashboard = PostgresDashboardData(repository, engine)

    overview = dashboard.overview(min_balls="0")
    matchup = dashboard.matchups(phase="Powerplay", min_balls="0")
    batter = dashboard.batters("batter-1")["selected_batter"]
    situation = dashboard.situations(situation_type="phase", situation_value="death")
    wickets = dashboard.wickets()

    assert overview["source"] == "PostgreSQL analytical views"
    assert overview["kpis"]["datasets"] == 7
    assert matchup["rows"][0]["runs_conceded"] == 4
    assert matchup["rows"][0]["batter_runs"] == 6
    assert batter["strike_rate"] == 120
    assert situation["rows"][0]["cricket_over"] == 18
    assert wickets["events"][0]["is_bowler_credited"] is True
