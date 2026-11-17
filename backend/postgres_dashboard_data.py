"""Read-only dashboard projections over PostgreSQL analytics views."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from backend.dashboard_data import DashboardData, DashboardDataError, DashboardRequestError
from backend.database.repository import CricketRepository
from backend.recommendation_engine import RecommendationEngine, normalize_id, normalize_label


class PostgresDashboardData:
    """Expose the existing dashboard response contracts using PostgreSQL data."""

    VIEW_PURPOSES = {
        "bowler-career": "Historical bowler performance from the career analytics view.",
        "bowler-phase": "Bowler performance grouped by the source-defined match phase.",
        "bowler-batter-matchups": "Validated bowler-batter aggregates and source phase splits.",
        "bowler-situation": "Historical bowling aggregates by documented situation dimensions.",
        "wicket-profiles": "Bowler dismissal profiles with credited and uncredited totals.",
        "season-bowling": "Season-wise bowling performance from credited wicket aggregates.",
        "batter-career": "Historical batter performance from the batter career view.",
    }

    def __init__(
        self,
        repository: CricketRepository,
        engine: RecommendationEngine,
        source_records: dict[str, Any] | None = None,
    ):
        self.repository = repository
        self.engine = engine
        self._career_rows = (
            source_records["career"] if source_records is not None
            else repository.get_bowler_career_performance()
        )
        self._phase_rows = (
            source_records["phase"] if source_records is not None
            else repository.get_bowler_phase_performance()
        )
        self._matchup_rows = (
            source_records["matchup"] if source_records is not None
            else repository.get_bowler_batter_matchups()
        )
        self._situation_rows = (
            source_records["situation"] if source_records is not None
            else repository.get_bowler_situation_performance()
        )
        self._season_rows = repository.get_season_bowling_performance()
        self._batter_rows = repository.get_batter_career_performance()
        self._wicket_rows = repository.get_wicket_events()
        self._dismissal_types = repository.get_dismissal_types()
        self._counts = repository.get_dashboard_counts()
        self._career_by_id = {
            normalize_id(row["bowler_id"]): row for row in self._career_rows
        }
        self._season_names = {
            str(row["season"]).strip()
            for row in self._season_rows
            if row.get("season") is not None
        }
        self._dismissal_names = {
            str(row["kind"]).strip()
            for row in self._dismissal_types
            if row.get("kind")
        }
        self._batter_by_id = {
            normalize_id(str(row["batter_id"])): row for row in self._batter_rows
        }

    @staticmethod
    def _value(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    @classmethod
    def _integer(cls, value: Any) -> int | None:
        number = cls._value(value)
        return int(number) if number is not None and number.is_integer() else None

    @classmethod
    def _performance_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        legal_balls = cls._integer(row.get("legal_balls")) or 0
        wickets = cls._integer(row.get("wickets")) or 0
        return {
            "bowler_id": str(row.get("bowler_id") or ""),
            "bowler_name": str(row.get("bowler_name") or ""),
            "phase": row.get("match_phase"),
            "legal_balls": legal_balls,
            "runs_conceded": cls._value(row.get("runs_conceded")),
            "wickets": wickets,
            "economy": cls._value(row.get("economy")),
            "bowling_average": cls._value(row.get("bowling_average")),
            "bowling_strike_rate": cls._value(row.get("bowling_strike_rate_balls_per_wicket")),
            "wicket_rate_per_100_legal_balls": cls._value(row.get("wicket_rate_per_100_legal_balls")),
            "dot_ball_pct": cls._value(row.get("dot_ball_pct")),
            "sample_size_flag": row.get("sample_size_flag") or "",
            "small_sample_flag": row.get("small_sample_flag") or "",
        }

    def _phase_key(self, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        key = normalize_label(value)
        if key not in self.engine.phase_labels:
            raise DashboardRequestError("phase must match a phase available in the loaded dataset")
        return key

    @staticmethod
    def _season_key(value: str) -> tuple[Any, ...]:
        return (
            value == "Unresolved",
            not value.isdigit(),
            int(value) if value.isdigit() else value.casefold(),
        )

    @staticmethod
    def _season_matches(season: str | None, season_value: str) -> bool:
        if not season:
            return True
        label = season.strip()
        if not label:
            return True
        normalized = label.casefold()
        candidate = str(season_value).strip()
        if normalized in {"all", "all seasons"}:
            return True
        if normalized.endswith("+") and normalized[:-1].isdigit():
            return candidate.isdigit() and int(candidate) >= int(normalized[:-1])
        if normalized.endswith(" onwards"):
            base = normalized[:-8]
            if not base.isdigit():
                return False
            return candidate.isdigit() and int(candidate) >= int(base)
        return candidate == label

    def filter_options(self) -> dict[str, Any]:
        batters = {
            str(row["batter_id"]): str(row.get("batter_name") or row["batter_id"])
            for row in self._batter_rows
        }
        situations: dict[str, set[str]] = {}
        for row in self._situation_rows:
            situation_type = str(row.get("situation_type") or "").strip()
            situation_value = str(row.get("situation_value") or "").strip()
            if situation_type and situation_value:
                situations.setdefault(situation_type, set()).add(situation_value)
        return {
            "phases": sorted(self.engine.phase_labels.values()),
            "seasons": sorted(self._season_names, key=self._season_key),
            "dismissal_types": sorted(self._dismissal_names, key=str.casefold),
            "situations": [
                {"type": situation_type, "values": sorted(values)}
                for situation_type, values in sorted(situations.items())
            ],
            "bowlers": [
                {"id": bowler_id, "name": str(row.get("bowler_name") or bowler_id)}
                for bowler_id, row in sorted(
                    self._career_by_id.items(),
                    key=lambda item: (str(item[1].get("bowler_name") or "").casefold(), item[0]),
                )
            ],
            "batters": [
                {"id": batter_id, "name": name}
                for batter_id, name in sorted(
                    batters.items(), key=lambda item: (item[1].casefold(), item[0])
                )
            ],
        }

    def overview(
        self, phase: str | None = None, season: str | None = None, min_balls: str | None = None
    ) -> dict[str, Any]:
        phase_key = self._phase_key(phase)
        minimum = DashboardData._nonnegative_number(min_balls, "min_balls", 180)
        if season and not any(self._season_matches(season, str(row.get("season") or "")) for row in self._season_rows):
            raise DashboardRequestError("season must match a season available in the dataset")
        phase_totals: dict[str, dict[str, float]] = {}
        for row in self._phase_rows:
            key = normalize_label(str(row.get("match_phase") or ""))
            totals = phase_totals.setdefault(
                key, {"legal_balls": 0.0, "wickets": 0.0, "runs_conceded": 0.0}
            )
            for field in ("legal_balls", "wickets", "runs_conceded"):
                totals[field] += self._value(row.get(field)) or 0

        performances = self._phase_rows if phase_key else self._career_rows
        performances = [
            row for row in performances
            if (not phase_key or normalize_label(str(row.get("match_phase") or "")) == phase_key)
            and (self._value(row.get("legal_balls")) or 0) >= minimum
        ]
        top_bowlers = sorted(
            (self._performance_row(row) for row in performances),
            key=lambda row: (-row["wickets"], row["bowler_name"].casefold()),
        )[:12]
        scatter = [
            {
                "bowler_id": item["bowler_id"],
                "bowler_name": item["bowler_name"],
                "economy": item["economy"],
                "bowling_strike_rate": item["bowling_strike_rate"],
                "wickets": item["wickets"],
                "legal_balls": item["legal_balls"],
                "sample_flag": item["sample_size_flag"],
            }
            for item in sorted(
                (self._performance_row(row) for row in performances),
                key=lambda item: -item["wickets"],
            )[:600]
            if item["wickets"] > 0 and item["economy"] is not None
            and item["bowling_strike_rate"] is not None
        ]
        dismissal_counts: Counter[str] = Counter()
        credited_counts: Counter[str] = Counter()
        for row in self._wicket_rows:
            kind = str(row.get("kind") or "").strip()
            if not kind:
                continue
            event_phase = normalize_label(str(row.get("over_phase") or ""))
            event_season = str(row.get("season") or "Unresolved")
            if phase_key and event_phase != phase_key:
                continue
            if season and event_season != season:
                continue
            dismissal_counts[kind] += 1
            if row.get("is_bowler_credited"):
                credited_counts[kind] += 1
        dismissal_types = [
            {"kind": kind, "events": count, "bowler_credited": credited_counts[kind]}
            for kind, count in sorted(
                dismissal_counts.items(), key=lambda item: (-item[1], item[0].casefold())
            )
        ]
        season_counts: Counter[str] = Counter()
        for row in self._season_rows:
            year = str(row.get("season") or "Unresolved").strip()
            if season and year != season:
                continue
            season_counts[year] += self._integer(row.get("season_wickets")) or 0

        return {
            "source": "PostgreSQL analytical views",
            "execution_mode": "postgresql",
            "filters": {
                "phase": self.engine.phase_labels.get(phase_key) if phase_key else None,
                "season": season or None,
                "minimum_legal_balls": minimum,
            },
            "kpis": {
                "matches": self._counts["matches"],
                "bowlers": len(self._career_rows),
                "batters_in_matchups": self._counts["batters_in_matchups"],
                "deliveries": self._counts["deliveries"],
                "legal_balls": sum(self._integer(row.get("legal_balls")) or 0 for row in self._career_rows),
                "bowler_credited_wickets": sum(self._integer(row.get("wickets")) or 0 for row in self._career_rows),
                "wicket_events": self._counts["wicket_events"],
                "matchup_records": self._counts["matchup_records"],
                "phases": len(self.engine.phase_labels),
                "datasets": self._counts["datasets"],
            },
            "phase_distribution": [
                {
                    "phase": self.engine.phase_labels[key],
                    **{name: round(value, 2) for name, value in totals.items()},
                }
                for key, totals in sorted(
                    phase_totals.items(),
                    key=lambda item: {"powerplay": 0, "middle": 1, "death": 2}.get(item[0], 99),
                )
                if key in self.engine.phase_labels
            ],
            "dismissal_types": dismissal_types,
            "top_bowlers": top_bowlers,
            "economy_vs_strike_rate": scatter,
            "wickets_by_phase": [
                {"phase": self.engine.phase_labels[key], "wickets": round(totals["wickets"])}
                for key, totals in sorted(
                    phase_totals.items(),
                    key=lambda item: {"powerplay": 0, "middle": 1, "death": 2}.get(item[0], 99),
                )
                if key in self.engine.phase_labels
            ],
            "wickets_by_season": [
                {"season": year, "wickets": wickets}
                for year, wickets in sorted(season_counts.items(), key=lambda item: self._season_key(item[0]))
            ],
            "unresolved_season_wickets": season_counts.get("Unresolved", 0),
        }

    def bowler(
        self,
        bowler_id: str | None,
        phase: str | None = None,
        season: str | None = None,
        min_balls: str | None = None,
    ) -> dict[str, Any]:
        phase_key = self._phase_key(phase)
        minimum = DashboardData._nonnegative_number(min_balls, "min_balls", 180)
        if season and not any(self._season_matches(season, str(row.get("season") or "")) for row in self._season_rows):
            raise DashboardRequestError("season must match a season available in the dataset")
        selected_id = normalize_id(bowler_id) if bowler_id else None
        if selected_id and selected_id not in self._career_by_id:
            raise DashboardRequestError("bowler_id must match a bowler in the loaded dataset", 404)
        career = self._career_by_id.get(selected_id) if selected_id else None
        selected_phases = [
            row for row in self._phase_rows
            if (not selected_id or normalize_id(str(row.get("bowler_id") or "")) == selected_id)
        ]
        comparisons = [
            self._performance_row(row) for row in self._phase_rows if phase_key
            and normalize_label(str(row.get("match_phase") or "")) == phase_key
            and (self._value(row.get("legal_balls")) or 0) >= minimum
        ] if phase_key else [
            self._performance_row(row) for row in self._career_rows
            if (self._value(row.get("legal_balls")) or 0) >= minimum
        ]
        comparisons.sort(key=lambda row: (-row["wickets"], row["bowler_name"].casefold()))
        seasons = [
            {
                "season": str(row.get("season") or ""),
                "wickets": self._integer(row.get("season_wickets")) or 0,
            }
            for row in self._season_rows
            if (not selected_id or normalize_id(str(row.get("bowler_id") or "")) == selected_id)
            and (not season or self._season_matches(season, str(row.get("season") or "").strip()))
        ]
        seasons.sort(key=lambda row: self._season_key(row["season"]))
        return {
            "selected_bowler": self._performance_row(career) if career else None,
            "phase_performance": [
                self._performance_row(row) for row in selected_phases
            ],
            "season_wickets": seasons,
            "phase_comparison": comparisons[:12],
            "filters": {
                "bowler_id": selected_id,
                "phase": self.engine.phase_labels.get(phase_key) if phase_key else None,
                "season": season or None,
                "minimum_legal_balls": minimum,
            },
            "season_source": "cricket_analytics.v_season_bowling_performance",
            "note": "Career and phase performance are all-history aggregates; the season filter affects only the season-wicket series.",
        }

    def batters(
        self, batter_id: str | None = None, season: str | None = None, search: str | None = None
    ) -> dict[str, Any]:
        selected_id = normalize_id(batter_id) if batter_id else None
        if season and not any(self._season_matches(season, str(row.get("season") or "")) for row in self._season_rows):
            raise DashboardRequestError("season must match a season available in the dataset")
        if selected_id and selected_id not in self._batter_by_id:
            raise DashboardRequestError("batter_id must match a batter in the loaded dataset", 404)
        query = (search or "").strip().casefold()
        if len(query) > 160:
            raise DashboardRequestError("search must be 160 characters or fewer")
        rows = [
            row for row in self._batter_rows
            if not query or query in " ".join(
                str(row.get(field) or "").casefold()
                for field in ("batter_id", "batter_name", "country", "batting_hand")
            )
        ]
        rows.sort(
            key=lambda row: (
                -(self._integer(row.get("runs_scored")) or 0),
                str(row.get("batter_name") or "").casefold(),
            )
        )
        selected = self._batter_by_id.get(selected_id) if selected_id else None
        return {
            "selected_batter": selected,
            "leaders": rows[:12],
            "total": len(rows),
            "filters": {"batter_id": selected_id, "season": season or None, "search": search or ""},
            "source": "cricket_analytics.v_batter_career_performance",
            "notes": [
                "Balls faced exclude wides; strike rate is runs scored divided by valid balls faced × 100.",
                "Batting average is runs scored divided by dismissals; undefined zero-denominator rates remain unavailable.",
            ],
        }

    def situations(
        self, bowler_id: str | None = None, situation_type: str | None = None,
        situation_value: str | None = None, season: str | None = None, search: str | None = None,
    ) -> dict[str, Any]:
        selected_bowler = normalize_id(bowler_id) if bowler_id else None
        if season and not any(self._season_matches(season, str(row.get("season") or "")) for row in self._season_rows):
            raise DashboardRequestError("season must match a season available in the dataset")
        if selected_bowler and selected_bowler not in self._career_by_id:
            raise DashboardRequestError("bowler_id must match a bowler in the loaded dataset", 404)
        selected_type = normalize_label(situation_type) if situation_type else None
        selected_value = situation_value.strip().casefold() if situation_value else None
        query = (search or "").strip().casefold()
        if len(query) > 160:
            raise DashboardRequestError("search must be 160 characters or fewer")
        rows = [
            row for row in self._situation_rows
            if (not selected_bowler or normalize_id(str(row.get("bowler_id") or "")) == selected_bowler)
            and (not selected_type or normalize_label(str(row.get("situation_type") or "")) == selected_type)
            and (not selected_value or str(row.get("situation_value") or "").strip().casefold() == selected_value)
            and (not query or query in " ".join(
                str(row.get(field) or "").casefold()
                for field in ("bowler_name", "bowler_id", "situation_type", "situation_value")
            ))
        ]
        result_rows = [
            {
                "bowler_id": str(row.get("bowler_id") or ""),
                "bowler_name": str(row.get("bowler_name") or ""),
                "situation_type": str(row.get("situation_type") or ""),
                "situation_value": str(row.get("situation_value") or ""),
                "cricket_over": self._value(row.get("cricket_over")),
                "balls": self._integer(row.get("balls")) or 0,
                "runs_conceded": self._value(row.get("runs_conceded")),
                "wickets": self._integer(row.get("wickets")) or 0,
                "economy": self._value(row.get("economy")),
                "bowling_strike_rate": self._value(row.get("strike_rate_balls_per_wicket")),
                "wicket_rate_per_100_legal_balls": self._value(row.get("wicket_rate_per_100_legal_balls")),
                "dot_ball_pct": self._value(row.get("dot_ball_pct")),
                "sample_size_flag": str(row.get("sample_size_flag") or ""),
            }
            for row in rows
        ]
        result_rows.sort(key=lambda row: (-row["balls"], row["situation_type"], row["situation_value"]))
        return {
            "rows": result_rows[:50],
            "total": len(rows),
            "filters": {
                "bowler_id": selected_bowler,
                "situation_type": situation_type or None,
                "situation_value": situation_value or None,
                "season": season or None,
                "search": search or "",
            },
            "note": "Situation aggregates are historical evidence; they do not form a phase-by-situation prediction.",
        }

    def _matchup_row(self, row: dict[str, Any], phase_key: str | None) -> dict[str, Any]:
        if phase_key:
            balls = self._value(row.get(f"phase_balls_{phase_key}")) or 0
            runs = self._value(row.get(f"phase_runs_conceded_{phase_key}")) or 0
            wickets = self._value(row.get(f"phase_wickets_{phase_key}")) or 0
            batter_balls = balls
            batter_runs = self._value(row.get(f"phase_runs_scored_{phase_key}")) or 0
        else:
            balls = self._value(row.get("balls")) or 0
            runs = self._value(row.get("runs_conceded_by_bowler")) or 0
            wickets = self._value(row.get("wickets")) or 0
            batter_balls = balls
            batter_runs = self._value(row.get("runs_scored_by_batter")) or 0
        return {
            "bowler_id": str(row.get("bowler_id") or ""),
            "bowler_name": str(row.get("bowler_name") or ""),
            "batter_id": str(row.get("batter_id") or ""),
            "batter_name": str(row.get("batter_name") or ""),
            "legal_balls": int(round(balls)),
            "runs_conceded": round(runs, 2),
            "batter_runs": round(batter_runs, 2),
            "batter_strike_rate": round(batter_runs * 100 / batter_balls, 2) if batter_balls > 0 else None,
            "wickets": int(round(wickets)),
            "economy": round(runs * 6 / balls, 2) if balls > 0 else None,
            "bowling_strike_rate": round(balls / wickets, 2) if balls > 0 and wickets > 0 else None,
            "sample_assessment": DashboardData._sample_label(balls),
        }

    def matchups(
        self, bowler_id: str | None = None, batter_id: str | None = None,
        phase: str | None = None, season: str | None = None, min_balls: str | None = None,
        search: str | None = None, page: str | None = None, page_size: str | None = None,
        sort: str | None = None, order: str | None = None,
    ) -> dict[str, Any]:
        phase_key = self._phase_key(phase)
        minimum = DashboardData._nonnegative_number(min_balls, "min_balls", 30)
        if season and not any(self._season_matches(season, str(row.get("season") or "")) for row in self._season_rows):
            raise DashboardRequestError("season must match a season available in the dataset")
        page_number, size = DashboardData._page_args(page, page_size)
        query = (search or "").strip().casefold()
        if len(query) > 160:
            raise DashboardRequestError("search must be 160 characters or fewer")
        selected_bowler = normalize_id(bowler_id) if bowler_id else None
        selected_batter = normalize_id(batter_id) if batter_id else None
        if selected_bowler and selected_bowler not in self._career_by_id:
            raise DashboardRequestError("bowler_id must match a bowler in the loaded dataset", 404)
        if selected_batter and selected_batter not in self.engine.players:
            raise DashboardRequestError("batter_id must match a player in the loaded dataset", 404)
        sort_field = sort or "wickets"
        allowed = {
            "bowler_name", "batter_name", "legal_balls", "runs_conceded", "batter_runs",
            "batter_strike_rate", "wickets", "economy", "bowling_strike_rate",
        }
        if sort_field not in allowed:
            raise DashboardRequestError("sort must name a supported matchup table column")
        descending = (order or "desc").casefold() == "desc"
        if order and order.casefold() not in {"asc", "desc"}:
            raise DashboardRequestError("order must be asc or desc")
        rows = [
            self._matchup_row(row, phase_key)
            for row in self._matchup_rows
            if (not selected_bowler or normalize_id(str(row.get("bowler_id") or "")) == selected_bowler)
            and (not selected_batter or normalize_id(str(row.get("batter_id") or "")) == selected_batter)
        ]
        rows = [
            row for row in rows
            if row["legal_balls"] >= minimum
            and (not query or query in " ".join(
                str(row[field]).casefold()
                for field in ("bowler_name", "bowler_id", "batter_name", "batter_id")
            ))
        ]
        def sort_key(row: dict[str, Any]) -> tuple[bool, Any]:
            missing, value = DashboardData._sort_key(row[sort_field])
            return (not missing, value) if descending else (missing, value)

        rows.sort(key=sort_key, reverse=descending)
        total = len(rows)
        offset = (page_number - 1) * size
        selected_rows = rows[offset:offset + size]
        return {
            "rows": selected_rows,
            "total": total,
            "page": page_number,
            "page_size": size,
            "summary": {
                "legal_balls": sum(row["legal_balls"] for row in rows),
                "runs_conceded": round(sum(row["runs_conceded"] for row in rows), 2),
                "wickets": sum(row["wickets"] for row in rows),
            },
            "filters": {
                "bowler_id": selected_bowler,
                "batter_id": selected_batter,
                "phase": self.engine.phase_labels.get(phase_key) if phase_key else None,
                "season": season or None,
                "minimum_legal_balls": minimum,
                "search": search or "",
            },
            "notes": [
                "Matchup statistics are historical bowler-batter aggregates, not match-level records.",
                "Batter SR is batter runs per valid ball faced × 100; Bowling SR is legal balls per bowler-credited wicket.",
                "Phase-specific batter-run and valid-ball fields come from the staged matchup aggregate.",
                "Samples under 30 legal balls are flagged and should not be treated as stable evidence.",
            ],
        }

    def wickets(
        self, phase: str | None = None, season: str | None = None,
        dismissal_type: str | None = None, min_wickets: str | None = None,
        search: str | None = None, page: str | None = None,
        page_size: str | None = None, sort: str | None = None,
        order: str | None = None, bowler_id: str | None = None,
    ) -> dict[str, Any]:
        phase_key = self._phase_key(phase)
        selected_bowler = normalize_id(bowler_id) if bowler_id else None
        if selected_bowler and selected_bowler not in self._career_by_id:
            raise DashboardRequestError("bowler_id must match a bowler in the loaded dataset", 404)
        if season and not any(self._season_matches(season, str(row.get("season") or "")) for row in self._season_rows):
            raise DashboardRequestError("season must match a season available in the dataset")
        if dismissal_type and dismissal_type not in self._dismissal_names:
            raise DashboardRequestError("dismissal_type must match an available dismissal kind")
        minimum = DashboardData._nonnegative_number(min_wickets, "min_wickets", 0)
        page_number, size = DashboardData._page_args(page, page_size)
        query = (search or "").strip().casefold()
        if len(query) > 160:
            raise DashboardRequestError("search must be 160 characters or fewer")
        sort_field = sort or "wicket_event_id"
        fields = {
            "wicket_event_id", "season", "over_phase", "kind", "bowler_name",
            "player_out_name", "is_bowler_credited",
        }
        if sort_field not in fields:
            raise DashboardRequestError("sort must name a supported wicket table column")
        descending = (order or "desc").casefold() == "desc"
        if order and order.casefold() not in {"asc", "desc"}:
            raise DashboardRequestError("order must be asc or desc")
        filtered = [
            row for row in self._wicket_rows
            if (not selected_bowler or normalize_id(str(row.get("bowler_id") or "")) == selected_bowler)
            and (not season or self._season_matches(season, str(row.get("season") or "Unresolved")))
            and (not phase_key or normalize_label(str(row.get("over_phase") or "")) == phase_key)
            and (not dismissal_type or str(row.get("kind") or "").casefold() == dismissal_type.casefold())
        ]
        event_total = len(filtered)
        credited_total = sum(bool(row.get("is_bowler_credited")) for row in filtered)
        dismissal_counts: Counter[str] = Counter(str(row.get("kind") or "") for row in filtered if row.get("kind"))
        credited_counts: Counter[str] = Counter(
            str(row.get("kind") or "") for row in filtered
            if row.get("kind") and row.get("is_bowler_credited")
        )
        phase_counts: Counter[str] = Counter(
            str(row.get("over_phase") or "") for row in filtered if row.get("over_phase")
        )
        credited_phase_counts: Counter[str] = Counter(
            str(row.get("over_phase") or "") for row in filtered
            if row.get("over_phase") and row.get("is_bowler_credited")
        )
        top_bowler_counts: Counter[str] = Counter(
            normalize_id(str(row.get("bowler_id") or "")) for row in filtered
            if row.get("is_bowler_credited") and row.get("bowler_id")
        )
        top_bowlers = [
            {
                "bowler_id": key,
                "bowler_name": str(self._career_by_id.get(key, {}).get("bowler_name") or key),
                "wickets": count,
                "legal_balls": (
                    self._integer(self._career_by_id[key].get("legal_balls"))
                    if not phase_key and not season else None
                ),
            }
            for key, count in top_bowler_counts.items() if count >= minimum
        ]
        top_bowlers.sort(key=lambda row: (-row["wickets"], row["bowler_name"].casefold()))
        searchable = [
            row for row in filtered
            if not query or query in " ".join(
                str(row.get(field) or "").casefold()
                for field in ("bowler_name", "player_out_name", "match_id", "kind")
            )
        ]
        def wicket_sort_key(row: dict[str, Any]) -> tuple[bool, Any]:
            missing, value = DashboardData._sort_key(row.get(sort_field))
            return (not missing, value) if descending else (missing, value)

        searchable.sort(key=wicket_sort_key, reverse=descending)
        offset = (page_number - 1) * size
        events = [
            {
                "wicket_event_id": row.get("wicket_event_id"),
                "match_id": row.get("match_id"),
                "season": row.get("season") or "Unresolved",
                "innings_number": row.get("innings_number"),
                "over_number": row.get("over_number"),
                "ball_in_over": row.get("ball_in_over"),
                "over_phase": row.get("over_phase"),
                "bowler_id": row.get("bowler_id"),
                "player_out_name": row.get("player_out_name"),
                "bowler_name": row.get("bowler_name"),
                "kind": row.get("kind"),
                "is_bowler_credited": bool(row.get("is_bowler_credited")),
            }
            for row in searchable[offset:offset + size]
        ]
        return {
            "events": events,
            "total": len(searchable),
            "page": page_number,
            "page_size": size,
            "event_count": event_total,
            "bowler_credited_event_count": credited_total,
            "dismissal_types": [
                {"kind": kind, "events": count, "bowler_credited": credited_counts[kind]}
                for kind, count in sorted(dismissal_counts.items(), key=lambda item: (-item[1], item[0].casefold()))
            ],
            "events_by_phase": [
                {"phase": name, "events": count, "bowler_credited": credited_phase_counts[name]}
                for name, count in sorted(phase_counts.items())
            ],
            "top_bowlers": top_bowlers[:12],
            "filters": {
                "bowler_id": selected_bowler,
                "phase": self.engine.phase_labels.get(phase_key) if phase_key else None,
                "season": season or None,
                "dismissal_type": dismissal_type or None,
                "minimum_wickets": minimum,
                "search": search or "",
            },
            "notes": [
                "Dismissal counts include all wicket events; only is_bowler_credited=true events are bowler wickets.",
                "Season is joined from cricket_dim.dim_match by match_id; unmatched rows are labeled Unresolved.",
                "Phase performance does not contain season cross-tabs, so phase comparisons remain all-history.",
            ],
        }

    def datasets(self) -> dict[str, Any]:
        entries = []
        for view_id, view_name in self.repository.ANALYTICAL_VIEWS.items():
            rows, total, columns = self.repository.get_analytical_view_rows(
                view_id, limit=0, offset=0
            )
            entries.append({
                "id": view_id,
                "name": view_name,
                "file_name": view_name,
                "category": "PostgreSQL analytics",
                "path": f"cricket_analytics.{view_name}",
                "rows": total,
                "columns": columns,
                "column_count": len(columns),
                "size_bytes": None,
                "purpose": self.VIEW_PURPOSES[view_id],
                "integrity_status": None,
            })
        return {"count": len(entries), "datasets": entries}

    def dataset_page(
        self, dataset_id: str, page: str | None = None,
        page_size: str | None = None, search: str | None = None,
        sort: str | None = None, order: str | None = None,
    ) -> dict[str, Any]:
        page_number, size = DashboardData._page_args(page, page_size)
        query = (search or "").strip()
        if len(query) > 160:
            raise DashboardRequestError("search must be 160 characters or fewer")
        if order and order.casefold() not in {"asc", "desc"}:
            raise DashboardRequestError("order must be asc or desc")
        try:
            rows, total, columns = self.repository.get_analytical_view_rows(
                dataset_id,
                limit=size,
                offset=(page_number - 1) * size,
                search=query,
                sort=sort,
                descending=(order or "asc").casefold() == "desc",
            )
        except ValueError as exc:
            raise DashboardRequestError(str(exc), 404 if dataset_id not in self.repository.ANALYTICAL_VIEWS else 400) from exc
        if not rows and page_number > 1 and (page_number - 1) * size >= total:
            raise DashboardRequestError("page is beyond the available dataset rows")
        types: dict[str, str] = {}
        missing: dict[str, int] = {}
        for column in columns:
            values = [row.get(column) for row in rows]
            missing[column] = sum(value is None for value in values)
            present = [value for value in values if value is not None]
            if not present:
                types[column] = "empty"
            elif all(isinstance(value, bool) for value in present):
                types[column] = "boolean"
            elif all(isinstance(value, int) for value in present):
                types[column] = "integer"
            elif all(isinstance(value, (int, float)) for value in present):
                types[column] = "number"
            elif all(hasattr(value, "isoformat") for value in present):
                types[column] = "date"
            else:
                types[column] = "string"
        profile = {
            "rows": total,
            "columns": columns,
            "column_count": len(columns),
            "types": types,
            "missing_values": missing,
        }
        view_name = self.repository.ANALYTICAL_VIEWS[dataset_id]
        return {
            "dataset": dataset_id,
            "page": page_number,
            "page_size": size,
            "total": total,
            "rows": rows,
            "profile": profile,
            "sort": {"column": sort or columns[0], "order": (order or "asc").casefold()},
            "view_name": view_name,
        }
