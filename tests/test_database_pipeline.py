"""
Tests for CRIC PostgreSQL Configuration, Ingestion, and Schema Pipelines.
"""

import os
from pathlib import Path
import pytest

from backend.database.connection import DatabaseConfig, DatabaseConnection
from config.config_loader import load_db_config
from scripts.ingestion.load_postgres import (
    compute_sha256,
    generate_deterministic_wicket_id,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
