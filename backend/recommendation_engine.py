"""Local, deterministic bowler recommendation engine."""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


class RecommendationError(Exception):
    """An expected error that can be returned to an API caller."""


class InvalidRequest(RecommendationError):
    pass


class UnknownIdentifier(RecommendationError):
    pass


class DatasetError(RuntimeError):
    pass


def normalize_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().casefold()

def normalize_label(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())

def normalize_situation_value(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).casefold().strip())

def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            result = float(text)
        except ValueError as exc:
            raise DatasetError(f"Expected a numeric dataset value, got {value!r}") from exc
    return result if math.isfinite(result) else None

def _read_rows(path: Path, required: set[str], label: str) -> Iterator[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames:
                raise DatasetError(f"CSV has no header: {path.name}")
            columns = {str(column).strip().casefold() for column in reader.fieldnames}
            missing = required - columns
            if missing:
                raise DatasetError(f"{label} is missing required columns: {', '.join(sorted(missing))}")
            found = False
            for raw_row in reader:
                found = True
                yield {
                    str(key).strip().casefold(): (value or "").strip()
                    for key, value in raw_row.items()
                    if key
                }
            if not found:
                raise DatasetError(f"Dataset is empty: {label}")
    except OSError as exc:
        raise DatasetError(f"Unable to read dataset {path.name}") from exc


@dataclass(frozen=True)
class DatasetPaths:
    players: Path
    career: Path
    phase: Path
    matchup: Path
    situation: Path

    @classmethod
    def discover(cls, data_root: Path) -> "DatasetPaths":
        filenames = {
            "players": "players.csv",
            "career": "bowler_career_performance_v1.csv",
            "phase": "bowler_phase_performance_v1.csv",
            "matchup": "bowler_batter_matchup_stats_v2.csv",
            "situation": "bowler_situation_stats_v2.csv",
        }
        found: dict[str, Path] = {}
        for key, filename in filenames.items():
            matches = sorted(
                path for path in data_root.rglob("*")
                if path.is_file() and path.name.casefold() == filename.casefold()
            )
            if len(matches) != 1:
                raise DatasetError(
                    f"Expected exactly one {filename} beneath {data_root}; found {len(matches)}"
                )
            found[key] = matches[0]
        return cls(**found)


@dataclass(frozen=True)
class RecommendationConfig:
    component_weights: Mapping[str, float] = field(
        default_factory=lambda: {"performance": 0.60, "matchup": 0.30, "situation": 0.10}
    )
    metric_weights: Mapping[str, Mapping[str, float]] = field(
        default_factory=lambda: {
            "performance": {"economy": 0.45, "strike_rate": 0.25, "wicket_rate": 0.30},
            "matchup": {"economy": 0.35, "strike_rate": 0.25, "wicket_rate": 0.40},
            "situation": {"economy": 0.50, "wicket_rate": 0.50},
        }
    )
    reliability_prior_balls: float = 30.0
    very_small_sample_balls: int = 12
    limited_sample_balls: int = 30

    def __post_init__(self) -> None:
        if set(self.component_weights) != {"performance", "matchup", "situation"}:
            raise ValueError("Component weights must define performance, matchup, and situation")
        if any(not math.isfinite(value) or value < 0 for value in self.component_weights.values()):
            raise ValueError("Component weights must be finite and nonnegative")
        if sum(self.component_weights.values()) <= 0:
            raise ValueError("At least one component weight must be positive")
        if not math.isfinite(self.reliability_prior_balls) or self.reliability_prior_balls <= 0:
            raise ValueError("Reliability prior must be finite and positive")
        if self.very_small_sample_balls < 0 or self.limited_sample_balls < self.very_small_sample_balls:
            raise ValueError("Sample warning thresholds are invalid")
        expected_metrics = {
            "performance": {"economy", "strike_rate", "wicket_rate"},
            "matchup": {"economy", "strike_rate", "wicket_rate"},
            "situation": {"economy", "wicket_rate"},
        }
        if set(self.metric_weights) != set(expected_metrics):
            raise ValueError("Metric weights must define all recommendation components")
        for component, expected in expected_metrics.items():
            weights = self.metric_weights[component]
            if set(weights) != expected:
                raise ValueError(f"Metric weights for {component} are incomplete")
            if any(not math.isfinite(value) or value < 0 for value in weights.values()):
                raise ValueError(f"Metric weights for {component} must be finite and nonnegative")
            if sum(weights.values()) <= 0:
                raise ValueError(f"Metric weights for {component} must include a positive weight")


@dataclass
class Performance:
    name: str
    balls: float
    values: dict[str, float | None]
    runs_conceded: float | None = None
    dismissals: float | None = None
    dot_balls: float | None = None
    dot_ball_pct: float | None = None


@dataclass
class Evidence:
    balls: float
    values: dict[str, float | None]
    phase_totals: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    runs_conceded: float | None = None
    dismissals: float | None = None
    dot_balls: float | None = None
    dot_ball_pct: float | None = None
    phase_dot_balls: dict[str, float] = field(default_factory=dict)
    batter_balls: float | None = None
    batter_runs: float | None = None
    phase_batter_totals: dict[str, tuple[float, float]] = field(default_factory=dict)


class RecommendationEngine:
    MAX_CANDIDATES = 30
    METRIC_DIRECTIONS = {
        "economy": "lower",
        "strike_rate": "lower",
        "wicket_rate": "higher",
    }

    def __init__(
        self,
        paths: DatasetPaths | None,
        config: RecommendationConfig | None = None,
        records: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    ):
        self.paths = paths
        self.config = config or RecommendationConfig()
        self.players: dict[str, str] = {}
        self.career: dict[str, Performance] = {}
        self.phase: dict[tuple[str, str], Performance] = {}
        self.matchups: dict[tuple[str, str], Evidence] = {}
        self.situations: dict[tuple[str, str, str], Evidence] = {}
        if records is None:
            if paths is None:
                raise DatasetError("Dataset paths or in-memory analytics records are required")
            self._load()
        else:
            self._load_records(records)
        self.known_bowlers = set(self.career) | {key[0] for key in self.phase}
        self.known_bowlers |= {key[0] for key in self.matchups} | {key[0] for key in self.situations}

    @classmethod
    def from_data_root(
        cls, data_root: Path, config: RecommendationConfig | None = None
    ) -> "RecommendationEngine":
        return cls(DatasetPaths.discover(data_root), config)

    @classmethod
    def from_repository(
        cls, repository: Any, config: RecommendationConfig | None = None
    ) -> "RecommendationEngine":
        return cls(None, config, cls.load_repository_records(repository))

    @staticmethod
    def load_repository_records(repository: Any) -> dict[str, Iterable[Mapping[str, Any]]]:
        records = {
            "players": repository.get_players(),
            "career": repository.get_bowler_career_performance(),
            "phase": repository.get_bowler_phase_performance(),
            "matchup": repository.get_bowler_batter_matchups(),
            "situation": repository.get_bowler_situation_performance(),
        }
        return records

    @property
    def ready(self) -> bool:
        return bool(self.career and self.players)

    @staticmethod
    def _metric_values(row: Mapping[str, str], balls: float) -> dict[str, float | None]:
        if balls == 0:
            return {"economy": None, "strike_rate": None, "wicket_rate": None}
        return {
            "economy": _number(row.get("economy")),
            "strike_rate": _number(row.get("bowling_strike_rate_balls_per_wicket")),
            "wicket_rate": _number(row.get("wicket_rate_per_100_legal_balls")),
        }

    @staticmethod
    def _dot_ball_pct(balls: float, dot_balls: float | None, recorded_pct: float | None) -> float | None:
        if balls <= 0:
            return None
        if recorded_pct is not None:
            return recorded_pct
        if dot_balls is not None:
            return dot_balls * 100 / balls
        return None

    def _load(self) -> None:
        assert self.paths is not None
        self._load_records({
            "players": _read_rows(self.paths.players, {"player_id", "player_name"}, "players"),
            "career": _read_rows(
                self.paths.career,
                {
                    "bowler_id", "bowler_name", "legal_balls", "economy",
                    "bowling_strike_rate_balls_per_wicket",
                    "wicket_rate_per_100_legal_balls",
                },
                "career",
            ),
            "phase": _read_rows(
                self.paths.phase,
                {
                    "bowler_id", "bowler_name", "match_phase", "legal_balls",
                    "economy", "bowling_strike_rate_balls_per_wicket",
                    "wicket_rate_per_100_legal_balls",
                },
                "phase",
            ),
            "matchup": _read_rows(
                self.paths.matchup,
                {"bowler_id", "batter_id", "balls", "runs_conceded_by_bowler", "wickets"},
                "matchup",
            ),
            "situation": _read_rows(
                self.paths.situation,
                {
                    "bowler_id", "situation_type", "situation_value", "balls",
                    "runs_conceded", "wickets",
                },
                "situation",
            ),
        })

    @staticmethod
    def _records(
        records: Iterable[Mapping[str, Any]], required: set[str], label: str
    ) -> Iterator[dict[str, str]]:
        found = False
        for raw in records:
            found = True
            row = {
                str(key).strip().casefold(): "" if value is None else str(value).strip()
                for key, value in raw.items()
            }
            missing = required - row.keys()
            if missing:
                raise DatasetError(f"{label} is missing required columns: {', '.join(sorted(missing))}")
            yield row
        if not found:
            raise DatasetError(f"Dataset is empty: {label}")

    def _load_records(self, records: Mapping[str, Iterable[Mapping[str, Any]]]) -> None:
        for row in self._records(records["players"], {"player_id", "player_name"}, "players"):
            player_id = normalize_id(row["player_id"])
            player_name = row["player_name"].strip()
            if not player_id or not player_name:
                raise DatasetError("Players dataset has a blank player ID or name")
            if player_id in self.players:
                raise DatasetError("Players dataset has a duplicate player ID")
            self.players[player_id] = player_name

        career_columns = {
            "bowler_id", "bowler_name", "legal_balls", "economy",
            "bowling_strike_rate_balls_per_wicket",
            "wicket_rate_per_100_legal_balls",
        }
        for row in self._records(records["career"], career_columns, "career"):
            bowler_id = normalize_id(row["bowler_id"])
            if not bowler_id or bowler_id in self.career:
                raise DatasetError("Career dataset has a blank or duplicate bowler ID")
            balls = _number(row["legal_balls"])
            if balls is None or balls < 0:
                raise DatasetError("Career dataset has invalid legal-ball sample size")
            dot_balls = _number(row.get("dot_balls"))
            self.career[bowler_id] = Performance(
                row["bowler_name"],
                balls,
                self._metric_values(row, balls),
                _number(row.get("runs_conceded")),
                _number(row.get("wickets")),
                dot_balls,
                self._dot_ball_pct(balls, dot_balls, _number(row.get("dot_ball_pct"))),
            )

        phase_columns = {
            "bowler_id",
            "bowler_name",
            "match_phase",
            "legal_balls",
            "economy",
            "bowling_strike_rate_balls_per_wicket",
            "wicket_rate_per_100_legal_balls",
        }
        phase_labels: dict[str, str] = {}
        for row in self._records(records["phase"], phase_columns, "phase"):
            bowler_id = normalize_id(row["bowler_id"])
            phase_key = normalize_label(row["match_phase"])
            balls = _number(row["legal_balls"])
            if not bowler_id or not phase_key or balls is None or balls < 0:
                raise DatasetError("Phase dataset has an invalid identifier or sample size")
            key = (bowler_id, phase_key)
            if key in self.phase:
                raise DatasetError("Phase dataset has a duplicate bowler/phase record")
            dot_balls = _number(row.get("dot_balls"))
            self.phase[key] = Performance(
                row["bowler_name"],
                balls,
                self._metric_values(row, balls),
                _number(row.get("runs_conceded")),
                _number(row.get("wickets")),
                dot_balls,
                self._dot_ball_pct(balls, dot_balls, _number(row.get("dot_ball_pct"))),
            )
            phase_labels.setdefault(phase_key, row["match_phase"])
        self.phase_labels = phase_labels

        matchup_columns = {"bowler_id", "batter_id", "balls", "runs_conceded_by_bowler", "wickets"}
        for row in self._records(records["matchup"], matchup_columns, "matchup"):
            bowler_id, batter_id = normalize_id(row["bowler_id"]), normalize_id(row["batter_id"])
            balls = _number(row["balls"])
            runs = _number(row["runs_conceded_by_bowler"])
            wickets = _number(row["wickets"])
            if not bowler_id or not batter_id or balls is None or balls < 0 or runs is None or wickets is None:
                raise DatasetError("Matchup dataset has an invalid identifier or metric")
            key = (bowler_id, batter_id)
            if key in self.matchups:
                raise DatasetError("Matchup dataset has a duplicate bowler/batter record")
            phase_totals: dict[str, tuple[float, float, float]] = {}
            phase_dot_balls: dict[str, float] = {}
            phase_batter_totals: dict[str, tuple[float, float]] = {}
            for phase_key in self.phase_labels:
                phase_balls = _number(row.get(f"phase_balls_{phase_key}"))
                phase_runs = _number(row.get(f"phase_runs_conceded_{phase_key}"))
                phase_wickets = _number(row.get(f"phase_wickets_{phase_key}"))
                if phase_balls is not None and phase_runs is not None and phase_wickets is not None:
                    phase_totals[phase_key] = (phase_balls, phase_runs, phase_wickets)
                phase_batter_runs = _number(row.get(f"phase_runs_scored_{phase_key}"))
                if phase_balls is not None and phase_batter_runs is not None:
                    phase_batter_totals[phase_key] = (phase_balls, phase_batter_runs)
                phase_dots = _number(row.get(f"phase_dots_{phase_key}"))
                if phase_dots is not None:
                    phase_dot_balls[phase_key] = phase_dots
            dot_balls = _number(row.get("dot_balls"))
            self.matchups[key] = Evidence(
                balls,
                self._derived_values(balls, runs, wickets),
                phase_totals,
                runs,
                wickets,
                dot_balls,
                self._dot_ball_pct(balls, dot_balls, _number(row.get("dot_ball_pct"))),
                phase_dot_balls,
                balls,
                _number(row.get("runs_scored_by_batter")),
                phase_batter_totals,
            )

        situation_columns = {
            "bowler_id", "situation_type", "situation_value", "balls", "runs_conceded", "wickets"
        }
        for row in self._records(records["situation"], situation_columns, "situation"):
            bowler_id = normalize_id(row["bowler_id"])
            situation_type = normalize_label(row["situation_type"])
            situation_value = normalize_situation_value(row["situation_value"])
            balls = _number(row["balls"])
            runs, wickets = _number(row["runs_conceded"]), _number(row["wickets"])
            if not bowler_id or not situation_type or not situation_value or balls is None or balls < 0 or runs is None or wickets is None:
                raise DatasetError("Situation dataset has an invalid identifier or metric")
            key = (bowler_id, situation_type, situation_value)
            if key in self.situations:
                raise DatasetError("Situation dataset has a duplicate bowler/situation record")
            dot_balls = _number(row.get("dot_balls"))
            self.situations[key] = Evidence(
                balls,
                self._derived_values(balls, runs, wickets),
                runs_conceded=runs,
                dismissals=wickets,
                dot_balls=dot_balls,
                dot_ball_pct=self._dot_ball_pct(
                    balls, dot_balls, _number(row.get("dot_ball_pct"))
                ),
            )

    @staticmethod
    def _derived_values(balls: float, runs: float, wickets: float) -> dict[str, float | None]:
        return {
            "economy": runs * 6 / balls if balls > 0 else None,
            "strike_rate": balls / wickets if balls > 0 and wickets > 0 else None,
            "wicket_rate": wickets * 100 / balls if balls > 0 else None,
        }

    def _sample_assessment(self, balls: float) -> str:
        if balls == 0:
            return "no_legal_balls"
        if balls < self.config.very_small_sample_balls:
            return "very_small_sample"
        if balls < self.config.limited_sample_balls:
            return "limited_sample"
        return "broader_sample"

    @staticmethod
    def _validate_nonnegative_number(value: Any, field_name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise InvalidRequest(f"{field_name} must be a finite nonnegative number")
        return float(value)

    @staticmethod
    def _validate_context(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise InvalidRequest("context must be an object")
        allowed = {"match_id", "innings_number", "batting_team", "bowling_team", "over"}
        if set(value) - allowed:
            raise InvalidRequest(f"Unsupported context fields: {', '.join(sorted(set(value) - allowed))}")
        context: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"match_id", "batting_team", "bowling_team"}:
                if not isinstance(item, str) or not item.strip():
                    raise InvalidRequest(f"context.{key} must be a nonempty string")
                context[key] = item.strip()
            else:
                if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) or item < 0:
                    raise InvalidRequest(f"context.{key} must be a finite nonnegative number")
                context[key] = item
        return context

    @staticmethod
    def _normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
        total = sum(weights.values())
        return {key: value / total for key, value in weights.items()}

    def _candidate_features(
        self, bowler_id: str, batter_id: str, phase_key: str | None, situation_key: tuple[str, str] | None
    ) -> dict[str, Evidence | Performance | None]:
        performance = self.phase.get((bowler_id, phase_key)) if phase_key else None
        if performance is None:
            performance = self.career.get(bowler_id)

        matchup = self.matchups.get((bowler_id, batter_id))
        if matchup is not None:
            if phase_key:
                phase_totals = matchup.phase_totals.get(phase_key)
                if phase_totals is None or phase_totals[0] <= 0:
                    matchup = None
                else:
                    balls, runs, wickets = phase_totals
                    dots = matchup.phase_dot_balls.get(phase_key)
                    matchup = Evidence(
                        balls,
                        self._derived_values(balls, runs, wickets),
                        runs_conceded=runs,
                        dismissals=wickets,
                        dot_balls=dots,
                        dot_ball_pct=self._dot_ball_pct(balls, dots, None),
                    )

        situation = None
        if situation_key is not None:
            situation = self.situations.get((bowler_id, situation_key[0], situation_key[1]))
        return {"performance": performance, "matchup": matchup, "situation": situation}

    def recommend(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise InvalidRequest("Request body must be a JSON object")
        allowed = {"batter_id", "phase", "situation", "context", "candidates"}
        if set(request) - allowed:
            raise InvalidRequest(f"Unsupported request fields: {', '.join(sorted(set(request) - allowed))}")

        batter_value = request.get("batter_id")
        if not isinstance(batter_value, str) or not batter_value.strip():
            raise InvalidRequest("batter_id must be a nonempty string")
        batter_id = normalize_id(batter_value)
        if batter_id not in self.players:
            raise UnknownIdentifier(f"Unknown batter_id: {batter_value.strip()}")

        phase_value = request.get("phase")
        phase_key = None
        phase_label = None
        if phase_value is not None:
            if not isinstance(phase_value, str) or not phase_value.strip():
                raise InvalidRequest("phase must be a nonempty string")
            phase_key = normalize_label(phase_value)
            if phase_key not in self.phase_labels:
                raise InvalidRequest("phase must match a supported match phase")
            phase_label = self.phase_labels[phase_key]

        situation_value = request.get("situation")
        situation_key = None
        situation_response = None
        if situation_value is not None:
            if not isinstance(situation_value, dict) or set(situation_value) != {"type", "value"}:
                raise InvalidRequest("situation must contain exactly string fields 'type' and 'value'")
            kind, value = situation_value["type"], situation_value["value"]
            if not isinstance(kind, str) or not kind.strip() or not isinstance(value, str) or not value.strip():
                raise InvalidRequest("situation type and value must be nonempty strings")
            situation_key = (normalize_label(kind), normalize_situation_value(value))
            situation_response = {"type": kind.strip(), "value": value.strip()}

        context = self._validate_context(request.get("context"))
        candidates = request.get("candidates")
        if not isinstance(candidates, list):
            raise InvalidRequest("candidates must be an array")
        if len(candidates) > self.MAX_CANDIDATES:
            raise InvalidRequest(f"At most {self.MAX_CANDIDATES} candidate bowlers are allowed")

        normalized_candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, dict) or set(candidate) - {
                "bowler_id", "available", "overs_bowled", "overs_remaining"
            }:
                raise InvalidRequest("Each candidate must be an object with supported fields")
            value = candidate.get("bowler_id")
            if not isinstance(value, str) or not value.strip():
                raise InvalidRequest("Each candidate requires a nonempty string bowler_id")
            bowler_id = normalize_id(value)
            if bowler_id in seen:
                raise InvalidRequest("Candidate bowler IDs must be unique")
            seen.add(bowler_id)
            if bowler_id not in self.known_bowlers:
                raise UnknownIdentifier(f"Unknown bowler_id: {value.strip()}")
            available = candidate.get("available", True)
            if not isinstance(available, bool):
                raise InvalidRequest("candidate.available must be a boolean")
            overs: dict[str, float] = {}
            for field_name in ("overs_bowled", "overs_remaining"):
                if field_name in candidate:
                    overs[field_name] = self._validate_nonnegative_number(candidate[field_name], field_name)
            normalized_candidates.append(
                {
                    "bowler_id": bowler_id,
                    "available": available,
                    "overs": overs,
                }
            )

        eligible: list[dict[str, Any]] = []
        excluded: list[dict[str, str]] = []
        for candidate in normalized_candidates:
            reason = None
            if not candidate["available"]:
                reason = "unavailable"
            elif candidate["overs"].get("overs_remaining") == 0:
                reason = "no_overs_remaining"
            if reason:
                excluded.append({"bowler_id": candidate["bowler_id"], "reason": reason})
            else:
                eligible.append(candidate)

        candidate_features: dict[str, dict[str, Evidence | Performance | None]] = {
            item["bowler_id"]: self._candidate_features(
                item["bowler_id"], batter_id, phase_key, situation_key
            )
            for item in eligible
        }
        utilities: dict[str, dict[str, float]] = {key: {} for key in candidate_features}
        samples: dict[str, dict[str, float]] = {key: {} for key in candidate_features}
        reliability: dict[str, dict[str, float]] = {key: {} for key in candidate_features}

        for source in ("performance", "matchup", "situation"):
            for metric, weight in self.config.metric_weights[source].items():
                observations: dict[str, tuple[float, float]] = {}
                for bowler_id, features in candidate_features.items():
                    evidence = features[source]
                    if evidence is None:
                        continue
                    value = evidence.values.get(metric)
                    if value is None or evidence.balls <= 0:
                        continue
                    observations[bowler_id] = (value, evidence.balls)
                if not observations or weight <= 0:
                    continue
                values = [item[0] for item in observations.values()]
                minimum, maximum = min(values), max(values)
                for bowler_id, (value, balls) in observations.items():
                    if minimum == maximum:
                        raw_utility = 0.5
                    elif self.METRIC_DIRECTIONS[metric] == "lower":
                        raw_utility = (maximum - value) / (maximum - minimum)
                    else:
                        raw_utility = (value - minimum) / (maximum - minimum)
                    metric_reliability = balls / (balls + self.config.reliability_prior_balls)
                    adjusted = 0.5 + metric_reliability * (raw_utility - 0.5)
                    utilities[bowler_id][f"{source}.{metric}"] = adjusted
                    samples[bowler_id][source] = balls
                    reliability.setdefault(bowler_id, {})[f"{source}.{metric}"] = metric_reliability

        recommendations: list[dict[str, Any]] = []
        for candidate in eligible:
            bowler_id = candidate["bowler_id"]
            features = candidate_features[bowler_id]
            component_scores: dict[str, float] = {}
            for source in ("performance", "matchup", "situation"):
                if self.config.component_weights[source] == 0:
                    continue
                metrics = self.config.metric_weights[source]
                observed = {
                    metric: utilities[bowler_id][f"{source}.{metric}"]
                    for metric in metrics
                    if f"{source}.{metric}" in utilities[bowler_id]
                }
                if observed:
                    normalized = self._normalize_weights({key: metrics[key] for key in observed})
                    component_scores[source] = sum(observed[key] * normalized[key] for key in observed)

            available_sources = {
                source: self.config.component_weights[source]
                for source in component_scores
                if self.config.component_weights[source] > 0
            }
            overall_score = None
            normalized_sources: dict[str, float] = {}
            if available_sources:
                normalized_sources = self._normalize_weights(available_sources)
                overall_score = sum(component_scores[key] * normalized_sources[key] for key in available_sources)

            performance = features["performance"]
            matchup = features["matchup"]
            situation = features["situation"]
            metric_payload: dict[str, Any] = {}
            for source, evidence in (
                ("performance", performance),
                ("matchup", matchup),
                ("situation", situation),
            ):
                if evidence is not None:
                    metric_payload[source] = {
                        "economy": evidence.values.get("economy"),
                        "bowling_strike_rate_balls_per_wicket": evidence.values.get("strike_rate"),
                        "wicket_rate_per_100_legal_balls": evidence.values.get("wicket_rate"),
                        "sample_balls": evidence.balls,
                        "sample_assessment": self._sample_assessment(evidence.balls),
                        "runs_conceded": evidence.runs_conceded,
                        "dismissals": evidence.dismissals,
                        "dot_balls": evidence.dot_balls,
                        "dot_ball_pct": evidence.dot_ball_pct,
                    }

            warnings: list[str] = []
            for source, balls in samples[bowler_id].items():
                if balls < self.config.very_small_sample_balls:
                    warnings.append(f"{source}: very_small_sample ({balls:g} balls)")
                elif balls < self.config.limited_sample_balls:
                    warnings.append(f"{source}: limited_sample ({balls:g} balls)")
            for source, evidence in features.items():
                if evidence is not None and evidence.balls == 0:
                    warnings.append(f"{source}: no ball sample; rate metrics are unavailable.")
            availability = {
                "performance": "phase" if phase_key and self.phase.get((bowler_id, phase_key)) else "career",
                "matchup": "available" if matchup is not None else "no_matchup_evidence",
                "situation": (
                    "available" if situation is not None else
                    "not_requested" if situation_key is None else "no_situation_evidence"
                ),
            }
            if matchup is None:
                if phase_key:
                    warnings.append("No historical matchup evidence for this batter in the requested phase.")
                else:
                    warnings.append("No historical matchup evidence for this batter.")
            if situation_key is not None and situation is None:
                warnings.append("No historical evidence for the requested situation.")
            if overall_score is None:
                warnings.append("No usable historical metric evidence; score is unavailable.")
            evidence_text = []
            for source in component_scores:
                evidence = features[source]
                metric_labels = {
                    "economy": "economy (runs per six legal balls)",
                    "strike_rate": "bowling strike rate (legal balls per credited wicket)",
                    "wicket_rate": "credited-wicket rate per 100 legal balls",
                }
                metric_details = [
                    f"{metric_labels[metric]} {evidence.values[metric]:.2f}"
                    for metric in self.config.metric_weights[source]
                    if evidence.values.get(metric) is not None
                ]
                detail_text = (
                    f" using {', '.join(metric_details)} over {evidence.balls:g} legal balls"
                    if metric_details
                    else ""
                )
                evidence_text.append(
                    f"{source.capitalize()} component score: {component_scores[source] * 100:.1f}/100 "
                    f"after metric sample adjustment{detail_text}; effective weight "
                    f"{normalized_sources[source] * 100:.1f}% of this candidate's overall score."
                )
            reliability_values = list(reliability[bowler_id].values())
            recommendations.append(
                {
                    "bowler_id": bowler_id,
                    "bowler_name": (
                        self.career.get(bowler_id).name if bowler_id in self.career else
                        next((item.name for (candidate_id, _), item in self.phase.items() if candidate_id == bowler_id), bowler_id)
                    ),
                    "score": round(overall_score * 100, 2) if overall_score is not None else None,
                    "score_scale": "0_to_100_candidate_relative",
                    "sample_reliability": round(sum(reliability_values) / len(reliability_values), 3) if reliability_values else None,
                    "metrics": metric_payload,
                    "score_components": {key: round(value * 100, 2) for key, value in component_scores.items()},
                    "evidence": evidence_text,
                    "warnings": warnings,
                    "data_availability": availability,
                    "_sort_score": overall_score,
                }
            )

        recommendations.sort(
            key=lambda item: (
                item["_sort_score"] is None,
                -(item["_sort_score"] or 0.0),
                item["bowler_id"],
            )
        )
        for rank, item in enumerate(recommendations, start=1):
            item["rank"] = rank
            del item["_sort_score"]

        response_warnings = ["Scores are relative to the submitted eligible candidate set."]
        if not eligible:
            response_warnings.append("No eligible candidate bowlers were provided.")
        if any(item["score"] is None for item in recommendations):
            response_warnings.append("Some candidates have no usable historical metric evidence.")
        if len({tuple(item["data_availability"].values()) for item in recommendations}) > 1:
            response_warnings.append("Candidates have different historical evidence coverage.")

        return {
            "status": "ok",
            "execution_mode": "local_python",
            "model_type": "deterministic_interpretable_baseline",
            "batter_id": batter_id,
            "phase": phase_label,
            "situation": situation_response,
            "context": {"values": context, "source": "caller_supplied_not_live_verified"},
            "recommendations": recommendations,
            "excluded": excluded,
            "warnings": response_warnings,
        }
