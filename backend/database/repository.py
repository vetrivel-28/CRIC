"""
Database Repository Module for CRIC.
Provides high-level repository methods for querying dimensional models, facts, and analytical views in cric_analytics.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.database.connection import DatabaseConnection

LOGGER = logging.getLogger("cric.database.repository")


class CricketRepository:
    """Repository accessing the PostgreSQL cric_analytics analytical data store."""

    def __init__(self, db: DatabaseConnection | None = None):
        self.db = db or DatabaseConnection()

    def get_bowler_career_performance(self, bowler_id: str | None = None) -> list[dict[str, Any]]:
        """Queries career bowling performance metrics from cricket_analytics.v_bowler_career_performance."""
        query = """
            SELECT
                bowler_id, bowler_name, matches, innings, total_deliveries,
                legal_balls, overs, runs_conceded, wickets, economy,
                bowling_average, strike_rate, dot_balls, dot_ball_pct,
                boundary_pct, sample_size_flag
            FROM cricket_analytics.v_bowler_career_performance
        """
        params: list[Any] = []
        if bowler_id:
            query += " WHERE bowler_id = %s"
            params.append(bowler_id)
        query += " ORDER BY wickets DESC, economy ASC"

        with self.db.cursor() as cur:
            cur.execute(query, params)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_bowler_phase_performance(self, bowler_id: str, phase_id: str | None = None) -> list[dict[str, Any]]:
        """Queries phase-specific bowling metrics (powerplay, middle, death)."""
        query = """
            SELECT
                bowler_id, bowler_name, phase_id, phase_name, matches,
                legal_balls, overs, runs_conceded, wickets, economy,
                bowling_average, strike_rate, dot_balls, dot_ball_pct
            FROM cricket_analytics.v_bowler_phase_performance
            WHERE bowler_id = %s
        """
        params: list[Any] = [bowler_id]
        if phase_id:
            query += " AND phase_id = %s"
            params.append(phase_id)
        query += " ORDER BY phase_id"

        with self.db.cursor() as cur:
            cur.execute(query, params)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_head_to_head_matchup(self, bowler_id: str, batter_id: str) -> dict[str, Any] | None:
        """Queries head-to-head matchup statistics between a specific bowler and batter."""
        query = """
            SELECT
                bowler_id, batter_id, matches, deliveries, balls,
                runs_scored_by_batter, runs_conceded_by_bowler, wickets,
                dot_balls, fours, sixes, economy, strike_rate,
                matchup_sample_weight, small_sample_flag
            FROM cricket_fact.fact_matchup
            WHERE bowler_id = %s AND batter_id = %s
        """
        with self.db.cursor() as cur:
            cur.execute(query, (bowler_id, batter_id))
            row = cur.fetchone()
            if not row:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))

    def get_wicket_profile(self, bowler_id: str) -> dict[str, Any] | None:
        """Queries dismissal mode breakdown percentages for a bowler."""
        query = """
            SELECT
                bowler_id, bowler_name, total_wickets,
                bowled_count, bowled_pct, caught_count, caught_pct,
                lbw_count, lbw_pct, stumped_count, stumped_pct,
                caught_and_bowled_count, caught_and_bowled_pct,
                hit_wicket_count, hit_wicket_pct
            FROM cricket_analytics.v_wicket_profiles
            WHERE bowler_id = %s
        """
        with self.db.cursor() as cur:
            cur.execute(query, (bowler_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))

    def get_table_counts(self) -> dict[str, int]:
        """Returns row counts for existing dimension and fact tables."""
        tables = {
            "dim_player": "cricket_dim.dim_player",
            "dim_match": "cricket_dim.dim_match",
            "dim_phase": "cricket_dim.dim_phase",
            "dim_dismissal": "cricket_dim.dim_dismissal",
            "fact_delivery": "cricket_fact.fact_delivery",
            "fact_wicket": "cricket_fact.fact_wicket",
            "fact_matchup": "cricket_fact.fact_matchup",
            "fact_bowler_situation": "cricket_fact.fact_bowler_situation",
        }

        counts: dict[str, int] = {}

        with self.db.cursor() as cur:
            for key, table_sql in tables.items():
                cur.execute(f"SELECT COUNT(*) FROM {table_sql}")
                counts[key] = cur.fetchone()[0]

        return counts
