"""Read-only analytics and paginated dataset access for the CRIC dashboard."""

from __future__ import annotations

import csv
import heapq
import math
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from backend.recommendation_engine import RecommendationEngine, normalize_id, normalize_label


class DashboardRequestError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class DashboardDataError(RuntimeError):
    pass


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else None


def _read_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames:
                raise DashboardDataError(f"CSV has no header: {path.name}")
            return [
                {str(key).strip(): (value or "").strip() for key, value in row.items() if key}
                for row in reader
            ]
    except OSError as exc:
        raise DashboardDataError(f"Unable to read dashboard dataset {path.name}") from exc


def _relative_manifest_path(value: str) -> str:
    return value.replace("\\", "/").removeprefix("data/").casefold()


class DashboardData:
    PAGE_SIZES = {10, 25, 50, 100}
    DATASET_EXCLUSIONS = {
        "ingestion_manifest.csv",
        "hdfs_integrity_manifest.csv",
        "bowler_dataset_validation_report.csv",
        "career_validation_report.csv",
        "phase_validation_report.csv",
        "deliveries_sample.csv",
    }
    DESCRIPTIONS = {
        "combined_data.csv": "Combined player reference data from the merged cricket source.",
        "deliveries.csv": "Ball-by-ball match records, including legal-ball and extras fields.",
        "innings.csv": "One record per innings with score target and innings context.",
        "match_playing_xi.csv": "Player appearances by match and team; not a live availability feed.",
        "matches.csv": "Match metadata including competition, season, result, and venue.",
        "officials.csv": "Match officials by role.",
        "players.csv": "Player IDs and names used by the recommendation catalog.",
        "players_15_08.csv": "Player reference data with biographical and playing-role fields.",
        "players_under40.csv": "Filtered player reference data from the source pipeline.",
        "powerplays.csv": "Source-defined powerplay spans by match and innings.",
        "wicket_fielders.csv": "Fielding participants associated with wicket records.",
        "wickets.csv": "Source wicket records, including dismissal types.",
        "bowler_career_performance_v1.csv": "All-history bowler aggregates with legal-ball, run, wicket, and rate metrics.",
        "bowler_phase_performance_v1.csv": "Bowler performance grouped by the source match phase.",
        "bowler_batter_matchup_stats_v2.csv": "Historical bowler-batter aggregates, including sample and phase metrics.",
        "bowler_situation_stats_v2.csv": "Bowler aggregates grouped by documented match-situation dimensions.",
        "bowler_career_wicket_stats.csv": "Derived bowler wicket totals and matches with a credited wicket.",
        "bowler_phase_wicket_stats.csv": "Derived bowler-credited wickets grouped by phase.",
        "bowler_season_wickets.csv": "Derived bowler-credited wicket totals grouped by season.",
        "bowler_wicket_profile.csv": "Derived bowler totals and credited dismissal-type profiles.",
        "wicket_events.csv": "Individual wicket events with an explicit bowler-credit flag.",
        "validation_report.csv": "Dataset validation checks and their results.",
        "bowler_dataset_validation_report.csv": "Validation checks for bowler aggregate datasets.",
    }

    def __init__(self, engine: RecommendationEngine, data_root: Path):
        self.engine = engine
        self.root = data_root.resolve()
        self.catalog_paths = self._discover_csvs()
        self.manifest_rows = self._read_manifest()
        self._profile_cache: dict[str, dict[str, Any]] = {}
        self._career_rows = _read_rows(engine.paths.career)
        self._phase_rows = _read_rows(engine.paths.phase)
        season_path = self._find_optional("bowler_season_wickets.csv")
        self._season_rows = _read_rows(season_path) if season_path else []
        self._event_path = self._find_optional("wicket_events.csv")
        self._matches_path = self._find_optional("matches.csv")
        self._matches_by_id = self._load_match_seasons()

    def _discover_csvs(self) -> dict[str, Path]:
        datasets: dict[str, Path] = {}
        if not self.root.is_dir():
            return datasets
        for path in sorted(self.root.rglob("*.csv")):
            if path.name.casefold() in self.DATASET_EXCLUSIONS:
                continue
            try:
                resolved = path.resolve()
                relative = resolved.relative_to(self.root).as_posix()
            except (OSError, ValueError):
                continue
            datasets[relative] = resolved
        return datasets

    def _find_optional(self, filename: str) -> Path | None:
        matches = [
            path for path in self.root.rglob("*")
            if path.is_file() and path.name.casefold() == filename.casefold()
        ]
        if len(matches) > 1:
            raise DashboardDataError(f"Multiple dashboard inputs named {filename} were found.")
        return matches[0] if matches else None

    def _read_manifest(self) -> dict[str, dict[str, str]]:
        path = self._find_optional("hdfs_integrity_manifest.csv")
        if not path:
            return {}
        try:
            rows = _read_rows(path)
        except DashboardDataError:
            return {}
        return {
            _relative_manifest_path(row.get("relative_local_path", "")): row
            for row in rows
            if row.get("relative_local_path")
        }

    def _manifest_for(self, relative_path: str) -> dict[str, str] | None:
        normalized = _relative_manifest_path(relative_path)
        if normalized in self.manifest_rows:
            return self.manifest_rows[normalized]
        return next(
            (
                row
                for key, row in self.manifest_rows.items()
                if key.endswith(f"/{normalized}") or normalized.endswith(f"/{key}")
            ),
            None,
        )

    def _row_count(self, path: Path | None) -> int | None:
        if not path:
            return None
        try:
            relative = path.resolve().relative_to(self.root).as_posix()
        except (OSError, ValueError):
            return None
        manifest = self._manifest_for(relative)
        if manifest:
            count = _integer(manifest.get("local_data_rows"))
            if count is not None and count >= 0:
                return count
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                return max(0, sum(1 for _ in csv.reader(source)) - 1)
        except (OSError, csv.Error):
            return None

    def _load_match_seasons(self) -> dict[str, str]:
        if not self._matches_path:
            return {}
        return {
            row["match_id"]: row.get("season", "").strip() or "Unresolved"
            for row in _read_rows(self._matches_path)
            if row.get("match_id")
        }

    def _phase_key(self, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        key = normalize_label(value)
        if key not in self.engine.phase_labels:
            raise DashboardRequestError("phase must match a phase available in the loaded dataset")
        return key

    @staticmethod
    def _nonnegative_number(value: str | None, name: str, default: float) -> float:
        if value is None or value == "":
            return default
        try:
            number = float(value)
        except ValueError as exc:
            raise DashboardRequestError(f"{name} must be a nonnegative number") from exc
        if not math.isfinite(number) or number < 0:
            raise DashboardRequestError(f"{name} must be a nonnegative number")
        return number

    @staticmethod
    def _page_args(page: str | None, page_size: str | None) -> tuple[int, int]:
        try:
            page_number = int(page or "1")
            size = int(page_size or "25")
        except ValueError as exc:
            raise DashboardRequestError("page and page_size must be whole numbers") from exc
        if page_number < 1 or page_number > 1000:
            raise DashboardRequestError("page must be between 1 and 1000")
        if size not in DashboardData.PAGE_SIZES:
            raise DashboardRequestError("page_size must be 10, 25, 50, or 100")
        return page_number, size

    @staticmethod
    def _sample_label(balls: float) -> str:
        if balls <= 0:
            return "no_legal_balls"
        if balls < 12:
            return "very_small"
        if balls < 30:
            return "limited"
        return "broader"

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
        cand_str = candidate.split("/")[0].strip()
        cand_year = int(cand_str) if cand_str.isdigit() else None
        if normalized.endswith("+") and normalized[:-1].isdigit():
            thresh = int(normalized[:-1])
            return cand_year is not None and cand_year >= thresh
        if normalized.endswith(" onwards"):
            base = normalized[:-8].strip()
            if not base.isdigit():
                return False
            return cand_year is not None and cand_year >= int(base)
        return candidate.casefold() == label.casefold()

    def filter_options(self) -> dict[str, Any]:
        raw_seasons = sorted(
            {row.get("season", "").strip() for row in self._season_rows if row.get("season", "").strip()},
            key=lambda value: (value == "Unresolved", value.isdigit() is False, int(value) if value.isdigit() else value.casefold()),
        )
        seasons = ["2022 onwards"] + [s for s in raw_seasons if s != "2022 onwards"]
        dismissal_types: set[str] = set()
        if self._event_path:
            dismissal_types = {
                row.get("kind", "").strip()
                for row in _read_rows(self._event_path)
                if row.get("kind", "").strip()
            }
        batters = {
            batter_id
            for _, batter_id in self.engine.matchups
            if batter_id in self.engine.players
        }
        situations: dict[str, set[str]] = {}
        for _, situation_type, situation_value in self.engine.situations:
            situations.setdefault(situation_type, set()).add(situation_value)
        return {
            "phases": sorted(self.engine.phase_labels.values()),
            "seasons": seasons,
            "dismissal_types": sorted(dismissal_types, key=str.casefold),
            "situations": [
                {"type": situation_type, "values": sorted(values)}
                for situation_type, values in sorted(situations.items())
            ],
            "bowlers": [
                {"id": bowler_id, "name": record.name}
                for bowler_id, record in sorted(
                    self.engine.career.items(), key=lambda item: (item[1].name.casefold(), item[0])
                )
            ],
            "batters": [
                {"id": batter_id, "name": self.engine.players[batter_id]}
                for batter_id in sorted(batters, key=lambda item: (self.engine.players[item].casefold(), item))
            ],
        }

    def overview(
        self, phase: str | None = None, season: str | None = None, min_balls: str | None = None
    ) -> dict[str, Any]:
        phase_key = self._phase_key(phase)
        minimum = self._nonnegative_number(min_balls, "min_balls", 180)
        available_seasons = {row.get("season", "").strip() for row in self._season_rows}
        if season and not any(self._season_matches(season, value) for value in available_seasons):
            raise DashboardRequestError("season must match a season available in the dataset")

        career_by_id = {normalize_id(row.get("bowler_id", "")): row for row in self._career_rows}
        phase_rows = self._phase_rows
        phase_counts: dict[str, dict[str, float]] = {}
        for row in phase_rows:
            key = normalize_label(row.get("match_phase", ""))
            totals = phase_counts.setdefault(key, {"legal_balls": 0, "wickets": 0, "runs_conceded": 0})
            for field, target in (
                ("legal_balls", "legal_balls"),
                ("wickets", "wickets"),
                ("runs_conceded", "runs_conceded"),
            ):
                value = _number(row.get(field))
                if value is not None:
                    totals[target] += value

        career_bowlers = len(career_by_id)
        batters = {batter_id for _, batter_id in self.engine.matchups}
        total_legal_balls = sum(_integer(row.get("legal_balls")) or 0 for row in self._career_rows)
        credited_wickets = sum(_integer(row.get("wickets")) or 0 for row in self._career_rows)
        match_count = self._row_count(self._matches_path)
        delivery_path = self._find_optional("deliveries.csv")
        delivery_count = self._row_count(delivery_path)

        performances = self._phase_rows if phase_key else self._career_rows
        performances = [
            row for row in performances
            if (not phase_key or normalize_label(row.get("match_phase", "")) == phase_key)
            and (_number(row.get("legal_balls")) or 0) >= minimum
        ]
        top_bowlers = sorted(
            (
                self._performance_row(row)
                for row in performances
            ),
            key=lambda row: (-row["wickets"], row["bowler_name"].casefold()),
        )[:12]
        scatter = sorted(performances, key=lambda row: -(_integer(row.get("wickets")) or 0))[:600]
        scatter = [
            {
                "bowler_id": row.get("bowler_id", ""),
                "bowler_name": row.get("bowler_name", ""),
                "economy": _number(row.get("economy")),
                "bowling_strike_rate": _number(row.get("bowling_strike_rate_balls_per_wicket")),
                "wickets": _integer(row.get("wickets")) or 0,
                "legal_balls": _integer(row.get("legal_balls")) or 0,
                "sample_flag": row.get("sample_size_flag", ""),
            }
            for row in scatter
            if (_integer(row.get("wickets")) or 0) > 0
            and _number(row.get("economy")) is not None
            and _number(row.get("bowling_strike_rate_balls_per_wicket")) is not None
        ]

        phase_distribution = [
            {
                "phase": self.engine.phase_labels[key],
                **{name: round(value, 2) for name, value in totals.items()},
            }
            for key, totals in sorted(
                phase_counts.items(),
                key=lambda item: {
                    "powerplay": 0,
                    "middle": 1,
                    "death": 2,
                }.get(item[0], 99),
            )
            if key in self.engine.phase_labels
        ]

        dismissal_counts: Counter[str] = Counter()
        credited_by_kind: Counter[str] = Counter()
        event_count = 0
        if self._event_path:
            for row in _read_rows(self._event_path):
                kind = row.get("kind", "").strip()
                if not kind:
                    continue
                event_count += 1
                dismissal_counts[kind] += 1
                if row.get("is_bowler_credited", "").casefold() == "true":
                    credited_by_kind[kind] += 1
        dismissal_types = [
            {"kind": kind, "events": count, "bowler_credited": credited_by_kind[kind]}
            for kind, count in sorted(dismissal_counts.items(), key=lambda item: (-item[1], item[0].casefold()))
        ]

        season_counts: Counter[str] = Counter()
        for row in self._season_rows:
            year = row.get("season", "").strip() or "Unresolved"
            if season and not self._season_matches(season, year):
                continue
            wickets = _integer(row.get("wickets"))
            if wickets is not None:
                season_counts[year] += wickets
        season_series = [
            {"season": year, "wickets": wickets}
            for year, wickets in sorted(
                season_counts.items(),
                key=lambda item: (item[0] == "Unresolved", item[0].isdigit() is False, int(item[0]) if item[0].isdigit() else item[0].casefold()),
            )
        ]
        unresolved_wickets = season_counts.get("Unresolved", 0)

        dataset_count = len(self.catalog_paths)
        return {
            "source": "local CSV aggregates",
            "execution_mode": "local_python",
            "filters": {"phase": self.engine.phase_labels.get(phase_key) if phase_key else None, "season": season or None, "minimum_legal_balls": minimum},
            "kpis": {
                "matches": match_count,
                "bowlers": career_bowlers,
                "batters_in_matchups": len(batters),
                "deliveries": delivery_count,
                "legal_balls": total_legal_balls,
                "bowler_credited_wickets": credited_wickets,
                "wicket_events": event_count if self._event_path else None,
                "matchup_records": len(self.engine.matchups),
                "phases": len(self.engine.phase_labels),
                "datasets": dataset_count,
            },
            "phase_distribution": phase_distribution,
            "dismissal_types": dismissal_types,
            "top_bowlers": top_bowlers,
            "economy_vs_strike_rate": scatter,
            "wickets_by_phase": [
                {
                    "phase": self.engine.phase_labels[key],
                    "wickets": round(totals["wickets"]),
                }
                for key, totals in sorted(
                    phase_counts.items(),
                    key=lambda item: {"powerplay": 0, "middle": 1, "death": 2}.get(item[0], 99),
                )
                if key in self.engine.phase_labels
            ],
            "wickets_by_season": season_series,
            "unresolved_season_wickets": unresolved_wickets,
        }

    @staticmethod
    def _performance_row(row: dict[str, str]) -> dict[str, Any]:
        return {
            "bowler_id": row.get("bowler_id", ""),
            "bowler_name": row.get("bowler_name", ""),
            "phase": row.get("match_phase"),
            "legal_balls": _integer(row.get("legal_balls")) or 0,
            "runs_conceded": _number(row.get("runs_conceded")),
            "wickets": _integer(row.get("wickets")) or 0,
            "economy": _number(row.get("economy")),
            "bowling_average": _number(row.get("bowling_average")),
            "bowling_strike_rate": _number(row.get("bowling_strike_rate_balls_per_wicket")),
            "wicket_rate_per_100_legal_balls": _number(row.get("wicket_rate_per_100_legal_balls")),
            "dot_ball_pct": _number(row.get("dot_ball_pct")),
            "boundary_pct_of_legal_balls": _number(row.get("boundary_pct_of_legal_balls")),
            "sample_size_flag": row.get("sample_size_flag", ""),
            "small_sample_flag": row.get("small_sample_flag", ""),
        }

    def bowler(
        self,
        bowler_id: str | None,
        phase: str | None = None,
        season: str | None = None,
        min_balls: str | None = None,
    ) -> dict[str, Any]:
        phase_key = self._phase_key(phase)
        minimum = self._nonnegative_number(min_balls, "min_balls", 180)
        if season and not any(self._season_matches(season, row.get("season", "").strip()) for row in self._season_rows):
            raise DashboardRequestError("season must match a season available in the dataset")
        selected_id = normalize_id(bowler_id) if bowler_id else None
        if selected_id and selected_id not in self.engine.career:
            raise DashboardRequestError("bowler_id must match a bowler in the loaded dataset", 404)

        selected_performance = self._phase_rows if phase_key else self._career_rows
        if selected_id:
            selected_performance = [
                row for row in selected_performance
                if normalize_id(row.get("bowler_id", "")) == selected_id
                and (not phase_key or normalize_label(row.get("match_phase", "")) == phase_key)
            ]
        comparisons = [
            self._performance_row(row)
            for row in (self._phase_rows if phase_key else self._career_rows)
            if (not phase_key or normalize_label(row.get("match_phase", "")) == phase_key)
            and (_number(row.get("legal_balls")) or 0) >= minimum
        ]
        comparisons.sort(key=lambda row: (-row["wickets"], row["bowler_name"].casefold()))

        career = next(
            (row for row in self._career_rows if normalize_id(row.get("bowler_id", "")) == selected_id),
            None,
        ) if selected_id else None
        phases = [
            self._performance_row(row)
            for row in self._phase_rows
            if selected_id and normalize_id(row.get("bowler_id", "")) == selected_id
        ]
        seasons = [
            {
                "season": row.get("season", ""),
                "wickets": _integer(row.get("wickets")) or 0,
            }
            for row in self._season_rows
            if selected_id and normalize_id(row.get("bowler_id", "")) == selected_id
            and (not season or self._season_matches(season, row.get("season", "").strip()))
        ]
        seasons.sort(key=lambda row: (row["season"] == "Unresolved", row["season"].isdigit() is False, int(row["season"]) if row["season"].isdigit() else row["season"].casefold()))
        return {
            "selected_bowler": self._performance_row(career) if career else None,
            "phase_performance": phases,
            "season_wickets": seasons,
            "phase_comparison": comparisons[:12],
            "filters": {
                "bowler_id": selected_id,
                "phase": self.engine.phase_labels.get(phase_key) if phase_key else None,
                "season": season or None,
                "minimum_legal_balls": minimum,
            },
            "season_source": "bowler_season_wickets.csv",
            "note": "Career and phase performance are all-history aggregates; the season filter affects only the season-wicket series.",
        }

    def batters(
        self, batter_id: str | None = None, season: str | None = None, search: str | None = None
    ) -> dict[str, Any]:
        selected_id = normalize_id(batter_id) if batter_id else None
        if season and not any(self._season_matches(season, row.get("season", "").strip()) for row in self._season_rows):
            raise DashboardRequestError("season must match a season available in the dataset")
        if selected_id and selected_id not in self.engine.players:
            raise DashboardRequestError("batter_id must match a batter in the loaded dataset", 404)
        query = (search or "").strip().casefold()
        if len(query) > 160:
            raise DashboardRequestError("search must be 160 characters or fewer")
        rows = [
            {
                "batter_id": batter_id,
                "batter_name": self.engine.players.get(batter_id, batter_id),
                "runs_scored": 0,
                "balls_faced": 0,
                "strike_rate": None,
                "batting_average": None,
                "dismissals": 0,
            }
            for batter_id in sorted(self.engine.players)
            if not selected_id or normalize_id(batter_id) == selected_id
        ]
        if query:
            rows = [
                row for row in rows
                if query in " ".join(str(value or "").casefold() for value in (row["batter_id"], row["batter_name"]))
            ]
        rows.sort(key=lambda row: (row["batter_name"].casefold(), row["batter_id"]))
        selected = rows[0] if len(rows) == 1 else next((row for row in rows if row["batter_id"] == batter_id), None)
        return {
            "selected_batter": selected,
            "leaders": rows[:12],
            "total": len(rows),
            "filters": {"batter_id": selected_id, "season": season or None, "search": search or ""},
            "source": "local CSV aggregates",
            "notes": [
                "Historical batter totals are derived from the locally available CSV aggregate files.",
                "Season filtering validates the selected season but does not change career-level batter totals.",
            ],
        }

    def _matchup_row(
        self, bowler_id: str, batter_id: str, phase_key: str | None
    ) -> dict[str, Any]:
        evidence = self.engine.matchups[(bowler_id, batter_id)]
        if phase_key:
            balls, runs, wickets = evidence.phase_totals.get(phase_key, (0, 0, 0))
            batter_balls, batter_runs = evidence.phase_batter_totals.get(phase_key, (0, 0))
        else:
            balls = evidence.balls
            economy = evidence.values.get("economy")
            wicket_rate = evidence.values.get("wicket_rate")
            runs = (economy * balls / 6) if economy is not None and balls else 0
            wickets = (wicket_rate * balls / 100) if wicket_rate is not None and balls else 0
            batter_balls = evidence.batter_balls or 0
            batter_runs = evidence.batter_runs or 0
        economy = runs * 6 / balls if balls > 0 else None
        strike_rate = balls / wickets if balls > 0 and wickets > 0 else None
        batter_strike_rate = batter_runs * 100 / batter_balls if batter_balls > 0 else None
        wickets_value = int(round(wickets))
        bowler = self.engine.career.get(bowler_id)
        return {
            "bowler_id": bowler_id,
            "bowler_name": bowler.name if bowler else self.engine.players.get(bowler_id, bowler_id),
            "batter_id": batter_id,
            "batter_name": self.engine.players.get(batter_id, batter_id),
            "legal_balls": int(round(balls)),
            "runs_conceded": round(runs, 2),
            "batter_runs": round(batter_runs, 2),
            "batter_strike_rate": round(batter_strike_rate, 2) if batter_strike_rate is not None else None,
            "wickets": wickets_value,
            "economy": round(economy, 2) if economy is not None else None,
            "bowling_strike_rate": round(strike_rate, 2) if strike_rate is not None else None,
            "sample_assessment": self._sample_label(balls),
        }

    @staticmethod
    def _sort_key(value: Any) -> tuple[bool, Any]:
        if value is None or value == "":
            return True, ""
        if isinstance(value, (float, int)):
            return False, value
        return False, str(value).casefold()

    def matchups(
        self,
        bowler_id: str | None = None,
        batter_id: str | None = None,
        phase: str | None = None,
        season: str | None = None,
        min_balls: str | None = None,
        search: str | None = None,
        page: str | None = None,
        page_size: str | None = None,
        sort: str | None = None,
        order: str | None = None,
    ) -> dict[str, Any]:
        phase_key = self._phase_key(phase)
        minimum = self._nonnegative_number(min_balls, "min_balls", 30)
        if season and not any(self._season_matches(season, row.get("season", "").strip()) for row in self._season_rows):
            raise DashboardRequestError("season must match a season available in the dataset")
        page_number, size = self._page_args(page, page_size)
        query = (search or "").strip().casefold()
        if len(query) > 160:
            raise DashboardRequestError("search must be 160 characters or fewer")

        selected_bowler = normalize_id(bowler_id) if bowler_id else None
        selected_batter = normalize_id(batter_id) if batter_id else None
        if selected_bowler and selected_bowler not in self.engine.career:
            raise DashboardRequestError("bowler_id must match a bowler in the loaded dataset", 404)
        if selected_batter and selected_batter not in self.engine.players:
            raise DashboardRequestError("batter_id must match a player in the loaded dataset", 404)

        sort_field = sort or "wickets"
        allowed_sorts = {
            "bowler_name", "batter_name", "legal_balls", "runs_conceded", "batter_runs",
            "batter_strike_rate", "wickets", "economy", "bowling_strike_rate",
        }
        if sort_field not in allowed_sorts:
            raise DashboardRequestError("sort must name a supported matchup table column")
        descending = (order or "desc").casefold() == "desc"
        if order and order.casefold() not in {"asc", "desc"}:
            raise DashboardRequestError("order must be asc or desc")
        offset = (page_number - 1) * size
        selected_total = 0
        balls_total = 0
        runs_total = 0.0
        wickets_total = 0

        def matching_rows() -> Iterator[dict[str, Any]]:
            nonlocal selected_total, balls_total, runs_total, wickets_total
            for key_bowler, key_batter in self.engine.matchups:
                if selected_bowler and key_bowler != selected_bowler:
                    continue
                if selected_batter and key_batter != selected_batter:
                    continue
                row = self._matchup_row(key_bowler, key_batter, phase_key)
                if row["legal_balls"] < minimum:
                    continue
                if query and query not in " ".join(
                    str(row[field]).casefold()
                    for field in ("bowler_name", "bowler_id", "batter_name", "batter_id")
                ):
                    continue
                selected_total += 1
                balls_total += row["legal_balls"]
                runs_total += row["runs_conceded"]
                wickets_total += row["wickets"]
                yield row

        count_to_sort = offset + size
        selector = heapq.nlargest if descending else heapq.nsmallest
        def matchup_sort_key(row: dict[str, Any]) -> tuple[bool, Any]:
            value = row[sort_field]
            missing, comparable = self._sort_key(value)
            return (not missing, comparable) if descending else (missing, comparable)

        rows = selector(count_to_sort, matching_rows(), key=matchup_sort_key)
        page_rows = rows[offset:offset + size]
        return {
            "rows": page_rows,
            "total": selected_total,
            "page": page_number,
            "page_size": size,
            "summary": {
                "legal_balls": balls_total,
                "runs_conceded": round(runs_total, 2),
                "wickets": wickets_total,
            },
            "filters": {
                "bowler_id": selected_bowler,
                "batter_id": selected_batter,
                "phase": self.engine.phase_labels.get(phase_key) if phase_key else None,
                "minimum_legal_balls": minimum,
                "search": search or "",
            },
            "notes": [
                "Matchup statistics are historical bowler-batter aggregates, not match-level records.",
                "Batter SR is batter runs per valid ball faced × 100; Bowling SR is legal balls per bowler-credited wicket.",
                "Phase-specific batter-run and valid-ball fields are used when a phase is selected.",
                "Samples under 30 legal balls are flagged and should not be treated as stable evidence.",
            ],
        }

    def situations(
        self,
        bowler_id: str | None = None,
        situation_type: str | None = None,
        situation_value: str | None = None,
        season: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        selected_bowler = normalize_id(bowler_id) if bowler_id else None
        if season and not any(self._season_matches(season, row.get("season", "").strip()) for row in self._season_rows):
            raise DashboardRequestError("season must match a season available in the dataset")
        if selected_bowler and selected_bowler not in self.engine.career:
            raise DashboardRequestError("bowler_id must match a bowler in the loaded dataset", 404)
        selected_type = normalize_label(situation_type) if situation_type else None
        selected_value = " ".join((situation_value or "").casefold().split()) or None
        query = (search or "").strip().casefold()
        if len(query) > 160:
            raise DashboardRequestError("search must be 160 characters or fewer")
        rows = []
        for (key_bowler, key_type, key_value), evidence in self.engine.situations.items():
            if selected_bowler and key_bowler != selected_bowler:
                continue
            if selected_type and key_type != selected_type:
                continue
            if selected_value and key_value != selected_value:
                continue
            performance = self.engine.career.get(key_bowler)
            bowler_name = performance.name if performance else self.engine.players.get(key_bowler, key_bowler)
            if query and query not in " ".join(
                (bowler_name, key_bowler, key_type, key_value)
            ).casefold():
                continue
            rows.append({
                "bowler_id": key_bowler,
                "bowler_name": bowler_name,
                "situation_type": key_type,
                "situation_value": key_value,
                "cricket_over": None,
                "balls": int(round(evidence.balls)),
                "runs_conceded": evidence.runs_conceded,
                "wickets": int(round(evidence.dismissals or 0)),
                "economy": evidence.values.get("economy"),
                "bowling_strike_rate": evidence.values.get("strike_rate"),
                "wicket_rate_per_100_legal_balls": evidence.values.get("wicket_rate"),
                "dot_ball_pct": evidence.dot_ball_pct,
                "sample_size_flag": self._sample_label(evidence.balls),
            })
        rows.sort(key=lambda row: (
            row["situation_type"], row["situation_value"],
            row["bowler_name"].casefold(), row["bowler_id"],
        ))
        return {
            "rows": sorted(
                rows,
                key=lambda row: (-row["balls"], row["situation_type"], row["situation_value"]),
            )[:50],
            "total": len(rows),
            "filters": {
                "bowler_id": selected_bowler,
                "situation_type": situation_type or None,
                "situation_value": situation_value or None,
                "search": search or "",
            },
            "note": "Situation aggregates are historical evidence; they do not form a phase-by-situation prediction.",
        }

    def wickets(
        self,
        phase: str | None = None,
        season: str | None = None,
        dismissal_type: str | None = None,
        min_wickets: str | None = None,
        search: str | None = None,
        page: str | None = None,
        page_size: str | None = None,
        sort: str | None = None,
        order: str | None = None,
        bowler_id: str | None = None,
    ) -> dict[str, Any]:
        if not self._event_path:
            raise DashboardRequestError("The wicket_events.csv dataset is unavailable.", 503)
        phase_key = self._phase_key(phase)
        selected_bowler_id = normalize_id(bowler_id) if bowler_id else None
        if selected_bowler_id and selected_bowler_id not in self.engine.career:
            raise DashboardRequestError("bowler_id must match a bowler in the loaded dataset", 404)
        if season and not any(self._season_matches(season, row.get("season", "").strip()) for row in self._season_rows):
            raise DashboardRequestError("season must match a season available in the dataset")
        minimum_wickets = self._nonnegative_number(min_wickets, "min_wickets", 0)
        page_number, size = self._page_args(page, page_size)
        query = (search or "").strip().casefold()
        if len(query) > 160:
            raise DashboardRequestError("search must be 160 characters or fewer")

        sort_field = sort or "wicket_event_id"
        fields = {"wicket_event_id", "season", "over_phase", "kind", "bowler_name", "player_out_name", "is_bowler_credited"}
        if sort_field not in fields:
            raise DashboardRequestError("sort must name a supported wicket table column")
        descending = (order or "desc").casefold() == "desc"
        if order and order.casefold() not in {"asc", "desc"}:
            raise DashboardRequestError("order must be asc or desc")

        dismissal_counts: Counter[str] = Counter()
        credited_by_kind: Counter[str] = Counter()
        phase_counts: Counter[str] = Counter()
        credited_by_phase: Counter[str] = Counter()
        credited_by_bowler: Counter[str] = Counter()
        bowler_names: dict[str, str] = {}
        event_total = 0
        credited_total = 0
        selected_total = 0

        def matching_rows() -> Iterator[dict[str, Any]]:
            nonlocal event_total, credited_total, selected_total
            for row in _read_rows(self._event_path):
                event_phase = row.get("over_phase", "").strip()
                phase_value = normalize_label(event_phase)
                event_season = self._matches_by_id.get(row.get("match_id", ""), "Unresolved")
                kind = row.get("kind", "").strip()
                credited = row.get("is_bowler_credited", "").casefold() == "true"

                if selected_bowler_id and normalize_id(row.get("bowler_id", "")) != selected_bowler_id:
                    continue
                if season and not self._season_matches(season, event_season):
                    continue
                if phase_key and phase_value != phase_key:
                    continue
                if dismissal_type and kind.casefold() != dismissal_type.casefold():
                    continue
                if kind:
                    event_total += 1
                    dismissal_counts[kind] += 1
                    if credited:
                        credited_by_kind[kind] += 1
                if event_phase:
                    phase_counts[event_phase] += 1
                    if credited:
                        credited_by_phase[event_phase] += 1
                if credited:
                    credited_total += 1
                    event_bowler_id = normalize_id(row.get("bowler_id", ""))
                    if event_bowler_id:
                        credited_by_bowler[event_bowler_id] += 1
                        bowler_names[event_bowler_id] = row.get("bowler_name", "")
                searchable = " ".join(
                    str(value).casefold()
                    for value in (row.get("bowler_name"), row.get("player_out_name"), row.get("match_id"), kind)
                )
                if query and query not in searchable:
                    continue
                result = {
                    "wicket_event_id": row.get("wicket_event_id", ""),
                    "match_id": row.get("match_id", ""),
                    "season": event_season,
                    "innings_number": _integer(row.get("innings_number")),
                    "over_number": _integer(row.get("over_number")),
                    "ball_in_over": _integer(row.get("ball_in_over")),
                    "over_phase": event_phase or None,
                    "bowler_id": row.get("bowler_id", ""),
                    "player_out_name": row.get("player_out_name", ""),
                    "bowler_name": row.get("bowler_name", ""),
                    "kind": kind,
                    "is_bowler_credited": credited,
                }
                selected_total += 1
                yield result

        offset = (page_number - 1) * size
        selector = heapq.nlargest if descending else heapq.nsmallest
        records = selector(offset + size, matching_rows(), key=lambda row: self._sort_key(row.get(sort_field)))

        career_balls = {
            normalize_id(row.get("bowler_id", "")): _integer(row.get("legal_balls"))
            for row in self._career_rows
        }
        phase_balls = {
            (normalize_id(row.get("bowler_id", "")), normalize_label(row.get("match_phase", ""))): _integer(row.get("legal_balls"))
            for row in self._phase_rows
        }
        top_bowlers = []
        for selected_id, wickets in credited_by_bowler.items():
            if wickets < minimum_wickets:
                continue
            if phase_key and not season:
                balls = phase_balls.get((selected_id, phase_key))
            elif not phase_key and not season:
                balls = career_balls.get(selected_id)
            else:
                balls = None
            top_bowlers.append({
                "bowler_id": selected_id,
                "bowler_name": bowler_names.get(selected_id, ""),
                "wickets": wickets,
                "legal_balls": balls,
            })
        top_bowlers.sort(key=lambda row: (-row["wickets"], row["bowler_name"].casefold()))
        dismissal_types = [
            {"kind": kind, "events": count, "bowler_credited": credited_by_kind[kind]}
            for kind, count in sorted(dismissal_counts.items(), key=lambda item: (-item[1], item[0].casefold()))
        ]
        phase_series = [
            {"phase": label, "events": count, "bowler_credited": credited_by_phase[label]}
            for label, count in sorted(phase_counts.items())
        ]
        return {
            "events": records[offset:offset + size],
            "total": selected_total,
            "page": page_number,
            "page_size": size,
            "event_count": event_total,
            "bowler_credited_event_count": credited_total,
            "dismissal_types": dismissal_types,
            "events_by_phase": phase_series,
            "top_bowlers": top_bowlers[:12],
            "filters": {
                "bowler_id": selected_bowler_id,
                "phase": self.engine.phase_labels.get(phase_key) if phase_key else None,
                "season": season or None,
                "dismissal_type": dismissal_type or None,
                "minimum_wickets": minimum_wickets,
                "search": search or "",
            },
            "notes": [
                "Dismissal counts include all wicket events; only is_bowler_credited=true events are bowler wickets.",
                "Season is joined from matches.csv by match_id; unmapped events are labeled Unresolved.",
                "Phase performance does not contain season cross-tabs, so phase comparisons remain all-history.",
            ],
        }

    def datasets(self) -> dict[str, Any]:
        entries = []
        for relative, path in self.catalog_paths.items():
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as source:
                    reader = csv.DictReader(source)
                    columns = reader.fieldnames or []
            except (OSError, csv.Error):
                columns = []
            manifest = self._manifest_for(relative)
            row_count = _integer(manifest.get("local_data_rows")) if manifest else None
            if row_count is None:
                row_count = self._row_count(path)
            entries.append({
                "id": relative,
                "name": path.stem,
                "file_name": path.name,
                "category": Path(relative).parent.name,
                "path": relative,
                "rows": row_count,
                "columns": columns,
                "column_count": len(columns),
                "size_bytes": path.stat().st_size,
                "purpose": self.DESCRIPTIONS.get(path.name, "Purpose not documented in the project metadata."),
                "integrity_status": manifest.get("verification_status") if manifest else None,
            })
        return {"count": len(entries), "datasets": entries}

    def _profile(self, dataset_id: str, path: Path) -> dict[str, Any]:
        if dataset_id in self._profile_cache:
            return self._profile_cache[dataset_id]
        missing: Counter[str] = Counter()
        type_flags: dict[str, dict[str, bool]] = {}
        row_count = 0
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                columns = reader.fieldnames or []
                if not columns:
                    raise DashboardDataError("CSV has no header.")
                type_flags = {
                    column: {"integer": True, "number": True, "boolean": True, "date": True, "observed": False}
                    for column in columns
                }
                for row in reader:
                    row_count += 1
                    for column in columns:
                        value = (row.get(column) or "").strip()
                        if not value:
                            missing[column] += 1
                            continue
                        flags = type_flags[column]
                        flags["observed"] = True
                        flags["integer"] = flags["integer"] and value.lstrip("+-").isdigit()
                        flags["number"] = flags["number"] and _number(value) is not None
                        flags["boolean"] = flags["boolean"] and value.casefold() in {"true", "false"}
                        try:
                            date.fromisoformat(value)
                        except ValueError:
                            flags["date"] = False
        except (OSError, csv.Error) as exc:
            raise DashboardDataError(f"Unable to profile dataset {path.name}") from exc

        inferred_types = {}
        for column, flags in type_flags.items():
            inferred_types[column] = (
                "empty" if not flags["observed"] else
                "boolean" if flags["boolean"] else
                "integer" if flags["integer"] else
                "number" if flags["number"] else
                "date" if flags["date"] else
                "string"
            )
        profile = {
            "rows": row_count,
            "columns": columns,
            "column_count": len(columns),
            "types": inferred_types,
            "missing_values": {column: missing[column] for column in columns},
        }
        self._profile_cache[dataset_id] = profile
        return profile

    def dataset_page(
        self,
        dataset_id: str,
        page: str | None = None,
        page_size: str | None = None,
        search: str | None = None,
        sort: str | None = None,
        order: str | None = None,
    ) -> dict[str, Any]:
        path = self.catalog_paths.get(dataset_id)
        if not path:
            raise DashboardRequestError("dataset must match an available CSV dataset", 404)
        page_number, size = self._page_args(page, page_size)
        query = (search or "").strip().casefold()
        if len(query) > 160:
            raise DashboardRequestError("search must be 160 characters or fewer")
        profile = self._profile(dataset_id, path)
        sort_field = sort or profile["columns"][0]
        if sort_field not in profile["columns"]:
            raise DashboardRequestError("sort must match a column in the selected dataset")
        descending = (order or "asc").casefold() == "desc"
        if order and order.casefold() not in {"asc", "desc"}:
            raise DashboardRequestError("order must be asc or desc")

        def matching_rows() -> Iterator[dict[str, str]]:
            nonlocal total_matches
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as source:
                    reader = csv.DictReader(source)
                    for row in reader:
                        normalized = {str(key): (value or "").strip() for key, value in row.items() if key}
                        if query and query not in " ".join(normalized.values()).casefold():
                            continue
                        total_matches += 1
                        yield normalized
            except (OSError, csv.Error) as exc:
                raise DashboardDataError(f"Unable to read dataset {path.name}") from exc

        total_matches = 0

        def key(row: dict[str, str]) -> tuple[bool, Any]:
            value = row.get(sort_field, "")
            if value == "":
                return (False, "") if descending else (True, "")
            if profile["types"][sort_field] in {"integer", "number"}:
                number = _number(value)
                key_value = number if number is not None else 0
            else:
                key_value = value.casefold()
            return (True, key_value) if descending else (False, key_value)

        offset = (page_number - 1) * size
        selector = heapq.nlargest if descending else heapq.nsmallest
        rows = selector(offset + size, matching_rows(), key=key)
        return {
            "dataset": dataset_id,
            "page": page_number,
            "page_size": size,
            "total": total_matches,
            "rows": rows[offset:offset + size],
            "profile": profile,
            "sort": {"column": sort_field, "order": "desc" if descending else "asc"},
        }
