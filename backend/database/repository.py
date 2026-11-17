"""
Database Repository Module for CRIC.
Provides high-level, read-only access to the PostgreSQL analytical views.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence

from backend.database.connection import DatabaseConnection

LOGGER = logging.getLogger("cric.database.repository")


class CricketRepository:
    """Repository accessing the PostgreSQL cric_analytics analytical data store."""

    ANALYTICAL_VIEWS = {
        "bowler-career": "v_bowler_career_performance",
        "bowler-phase": "v_bowler_phase_performance",
        "bowler-batter-matchups": "v_bowler_batter_matchups",
        "bowler-situation": "v_bowler_situation_performance",
        "wicket-profiles": "v_wicket_profiles",
        "season-bowling": "v_season_bowling_performance",
        "batter-career": "v_batter_career_performance",
    }

    def __init__(self, db: DatabaseConnection | None = None):
        self.db = db or DatabaseConnection()

    def get_players(self) -> list[dict[str, Any]]:
        """Returns the shared player dimension for recommendation selectors."""
        return self._fetch_all(
            """
                SELECT player_id, player_name
                FROM cricket_dim.dim_player
                ORDER BY player_name, player_id
            """
        )

    def get_dashboard_counts(self) -> dict[str, int]:
        """Returns source table and analytic view counts used by dashboard KPIs."""
        names = {
            "matches": "SELECT COUNT(*) FROM cricket_dim.dim_match",
            "deliveries": "SELECT COUNT(*) FROM cricket_fact.fact_delivery",
            "wicket_events": "SELECT COUNT(*) FROM cricket_fact.fact_wicket",
            "datasets": None,
            "matchup_records": "SELECT COUNT(*) FROM cricket_analytics.v_bowler_batter_matchups",
        }
        counts: dict[str, int] = {}
        with self.db.cursor(read_only=True) as cur:
            for key, query in names.items():
                if query is None:
                    counts[key] = len(self.ANALYTICAL_VIEWS)
                else:
                    cur.execute(query)
                    counts[key] = int(cur.fetchone()[0])
            cur.execute(
                "SELECT COUNT(DISTINCT batter_id) FROM cricket_analytics.v_bowler_batter_matchups"
            )
            counts["batters_in_matchups"] = int(cur.fetchone()[0])
        return counts

    def get_dismissal_types(self) -> list[dict[str, Any]]:
        return self._fetch_all(
            """
                SELECT dismissal_kind AS kind, is_bowler_credited
                FROM cricket_dim.dim_dismissal
                ORDER BY dismissal_kind
            """
        )

    def get_wicket_events(self) -> list[dict[str, Any]]:
        """Returns dismissal facts with their season dimension for drill-through."""
        return self._fetch_all(
            """
                SELECT
                    w.wicket_event_id, w.match_id, m.season, w.innings_number,
                    w.over_number, w.ball_in_over, w.over_phase, w.bowler_id,
                    w.bowler_name, w.player_out_id, w.player_out_name, w.kind,
                    w.is_bowler_credited
                FROM cricket_fact.fact_wicket AS w
                LEFT JOIN cricket_dim.dim_match AS m ON m.match_id = w.match_id
                ORDER BY w.wicket_event_id DESC
            """
        )

    def get_analytical_view_rows(
        self, view_id: str, *, limit: int, offset: int, search: str = "",
        sort: str | None = None, descending: bool = False,
    ) -> tuple[list[dict[str, Any]], int, list[str]]:
        """Reads a bounded page from an allow-listed analytics view."""
        view_name = self.ANALYTICAL_VIEWS.get(view_id)
        if view_name is None:
            raise ValueError("Unknown analytical view")
        with self.db.cursor(read_only=True) as cur:
            cur.execute(
                """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'cricket_analytics' AND table_name = %s
                    ORDER BY ordinal_position
                """,
                (view_name,),
            )
            columns = [row[0] for row in cur.fetchall()]
            if not columns:
                raise RuntimeError(f"Analytics view {view_name} has no visible columns")
            if sort and sort not in columns:
                raise ValueError("sort must match a column in the selected analytics view")
            where = " WHERE row_to_json(v)::text ILIKE %s" if search else ""
            params: list[Any] = [f"%{search}%"] if search else []
            cur.execute(
                f"SELECT COUNT(*) FROM cricket_analytics.{view_name} AS v{where}",
                params,
            )
            total = int(cur.fetchone()[0])
            order_by = f' ORDER BY "{sort}" {"DESC" if descending else "ASC"} NULLS LAST' if sort else ""
            cur.execute(
                f"SELECT * FROM cricket_analytics.{view_name} AS v{where}{order_by} LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            rows = [
                {column: self._json_value(value) for column, value in zip(columns, row)}
                for row in cur.fetchall()
            ]
        return rows, total, columns

    def _fetch_all(
        self, query: str, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        with self.db.cursor(read_only=True) as cur:
            cur.execute(query, params)
            columns = [description[0] for description in cur.description]
            return [
                {column: self._json_value(value) for column, value in zip(columns, row)}
                for row in cur.fetchall()
            ]

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else float(value)
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return value

    def get_bowler_career_performance(
        self, bowler_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Queries the career view using the column names it actually exposes."""
        query = """
            SELECT
                bowler_id, bowler_name, country, bowling_category, bowling_type,
                matches_bowled AS matches, innings_bowled AS innings,
                total_deliveries AS deliveries, legal_balls, runs_conceded, wickets,
                economy, average AS bowling_average,
                strike_rate AS bowling_strike_rate_balls_per_wicket,
                ROUND(CAST(100.0 * wickets / NULLIF(legal_balls, 0) AS NUMERIC), 2)
                    AS wicket_rate_per_100_legal_balls,
                dot_balls, dot_ball_pct, fours_conceded AS fours,
                sixes_conceded AS sixes, boundary_pct
            FROM cricket_analytics.v_bowler_career_performance
        """
        params: list[Any] = []
        if bowler_id:
            query += " WHERE bowler_id = %s"
            params.append(bowler_id)
        query += " ORDER BY wickets DESC, economy ASC NULLS LAST"
        return self._fetch_all(query, params)

    def get_bowler_phase_performance(
        self, bowler_id: str | None = None, phase: str | None = None
    ) -> list[dict[str, Any]]:
        """Queries phase aggregates, optionally filtered by bowler and phase label."""
        query = """
            SELECT
                bowler_id, bowler_name, match_phase,
                phase_balls AS legal_balls,
                phase_runs_conceded AS runs_conceded,
                phase_wickets AS wickets,
                phase_dots AS dot_balls,
                phase_fours AS fours,
                phase_sixes AS sixes,
                phase_economy AS economy,
                phase_average AS bowling_average,
                phase_strike_rate AS bowling_strike_rate_balls_per_wicket,
                ROUND(CAST(100.0 * phase_wickets / NULLIF(phase_balls, 0) AS NUMERIC), 2)
                    AS wicket_rate_per_100_legal_balls,
                phase_dot_pct AS dot_ball_pct
            FROM cricket_analytics.v_bowler_phase_performance
        """
        filters: list[str] = []
        params: list[Any] = []
        if bowler_id:
            filters.append("bowler_id = %s")
            params.append(bowler_id)
        if phase:
            filters.append("match_phase = %s")
            params.append(phase)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY bowler_name, match_phase"
        return self._fetch_all(query, params)

    def get_bowler_batter_matchups(
        self, bowler_id: str | None = None, batter_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Queries validated matchup metrics and phase splits from their staged aggregate."""
        query = """
            SELECT
                m.bowler_id, m.batter_id, m.bowler_name, m.batter_name, m.matches, m.innings,
                m.balls, m.runs_scored_by_batter, m.runs_conceded_by_bowler, m.wickets,
                m.dot_balls, m.fours, m.sixes, m.economy,
                m.average AS bowling_average,
                m.strike_rate AS bowling_strike_rate_balls_per_wicket,
                ROUND(CAST(100.0 * m.wickets / NULLIF(m.balls, 0) AS NUMERIC), 2)
                    AS wicket_rate_per_100_legal_balls,
                m.dot_ball_pct, m.boundary_pct, m.matchup_sample_weight, m.sample_size_flag,
                r.phase_balls_powerplay, r.phase_runs_conceded_powerplay,
                r.phase_runs_scored_powerplay, r.phase_wickets_powerplay, r.phase_dots_powerplay,
                r.phase_balls_middle, r.phase_runs_conceded_middle,
                r.phase_runs_scored_middle, r.phase_wickets_middle, r.phase_dots_middle,
                r.phase_balls_death, r.phase_runs_conceded_death,
                r.phase_runs_scored_death, r.phase_wickets_death, r.phase_dots_death
            FROM cricket_analytics.v_bowler_batter_matchups AS m
            LEFT JOIN (
                SELECT
                    bowler_id, batter_id,
                    MAX(phase_balls_powerplay) AS phase_balls_powerplay,
                    MAX(phase_runs_conceded_powerplay) AS phase_runs_conceded_powerplay,
                    MAX(phase_runs_scored_powerplay) AS phase_runs_scored_powerplay,
                    MAX(phase_wickets_powerplay) AS phase_wickets_powerplay,
                    MAX(phase_dots_powerplay) AS phase_dots_powerplay,
                    MAX(phase_balls_middle) AS phase_balls_middle,
                    MAX(phase_runs_conceded_middle) AS phase_runs_conceded_middle,
                    MAX(phase_runs_scored_middle) AS phase_runs_scored_middle,
                    MAX(phase_wickets_middle) AS phase_wickets_middle,
                    MAX(phase_dots_middle) AS phase_dots_middle,
                    MAX(phase_balls_death) AS phase_balls_death,
                    MAX(phase_runs_conceded_death) AS phase_runs_conceded_death,
                    MAX(phase_runs_scored_death) AS phase_runs_scored_death,
                    MAX(phase_wickets_death) AS phase_wickets_death,
                    MAX(phase_dots_death) AS phase_dots_death
                FROM cricket_raw.raw_matchups
                GROUP BY bowler_id, batter_id
                HAVING COUNT(*) = 1
            ) AS r ON m.bowler_id = r.bowler_id AND m.batter_id = r.batter_id
        """
        filters: list[str] = []
        params: list[Any] = []
        if bowler_id:
            filters.append("m.bowler_id = %s")
            params.append(bowler_id)
        if batter_id:
            filters.append("m.batter_id = %s")
            params.append(batter_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY m.bowler_name, m.batter_name"
        return self._fetch_all(query, params)

    def get_bowler_situation_performance(
        self,
        bowler_id: str | None = None,
        situation_type: str | None = None,
        situation_value: str | None = None,
    ) -> list[dict[str, Any]]:
        """Queries the validated bowler-situation aggregate view."""
        query = """
            SELECT
                bowler_id, bowler_name, situation_type, situation_value, cricket_over,
                matches, balls, runs_conceded, wickets, dot_balls, economy,
                strike_rate_balls_per_wicket,
                ROUND(CAST(100.0 * wickets / NULLIF(balls, 0) AS NUMERIC), 2)
                    AS wicket_rate_per_100_legal_balls,
                dot_ball_pct, boundary_pct_of_balls, sample_size_flag
            FROM cricket_analytics.v_bowler_situation_performance
        """
        filters: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("bowler_id", bowler_id),
            ("situation_type", situation_type),
            ("situation_value", situation_value),
        ):
            if value:
                filters.append(f"{column} = %s")
                params.append(value)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY bowler_name, situation_type, situation_value, cricket_over"
        return self._fetch_all(query, params)

    def get_wicket_profiles(self, bowler_id: str | None = None) -> list[dict[str, Any]]:
        """Queries bowler dismissal profiles without assuming unprovided rate columns."""
        query = """
            SELECT
                bowler_id, bowler_name, total_wickets, credited_wickets,
                bowled, caught, lbw, stumped, caught_and_bowled, hit_wicket,
                run_outs, pct_bowled_or_lbw
            FROM cricket_analytics.v_wicket_profiles
        """
        params: list[Any] = []
        if bowler_id:
            query += " WHERE bowler_id = %s"
            params.append(bowler_id)
        query += " ORDER BY credited_wickets DESC, bowler_name"
        return self._fetch_all(query, params)

    def get_wicket_profile(self, bowler_id: str) -> dict[str, Any] | None:
        rows = self.get_wicket_profiles(bowler_id)
        return rows[0] if rows else None

    def get_season_bowling_performance(
        self, bowler_id: str | None = None, season: str | None = None
    ) -> list[dict[str, Any]]:
        """Queries season bowling totals and rates."""
        query = """
            SELECT
                bowler_id, bowler_name, season, season_matches, season_balls,
                season_runs, season_wickets, season_economy, season_average
            FROM cricket_analytics.v_season_bowling_performance
        """
        filters: list[str] = []
        params: list[Any] = []
        if bowler_id:
            filters.append("bowler_id = %s")
            params.append(bowler_id)
        if season:
            filters.append("season = %s")
            params.append(season)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY season, bowler_name"
        return self._fetch_all(query, params)

    def get_batter_career_performance(
        self, batter_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Queries the batter career view for historical batting intelligence."""
        query = """
            SELECT
                batter_id, batter_name, country, batting_hand, matches_batted,
                innings_batted, balls_faced, runs_scored, dismissals, fours, sixes,
                dot_balls_faced, strike_rate, batting_average, boundary_run_pct
            FROM cricket_analytics.v_batter_career_performance
        """
        params: list[Any] = []
        if batter_id:
            query += " WHERE batter_id = %s"
            params.append(batter_id)
        query += " ORDER BY runs_scored DESC, batter_name"
        return self._fetch_all(query, params)

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
        with self.db.cursor(read_only=True) as cur:
            for key, table_sql in tables.items():
                cur.execute(f"SELECT COUNT(*) FROM {table_sql}")
                counts[key] = cur.fetchone()[0]
        return counts
