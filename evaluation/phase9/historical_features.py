from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable


class EvaluationDataError(ValueError):
    """Raised when source records cannot support a reproducible snapshot."""


def _parse_bool(value: str, label: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise EvaluationDataError(f"{label} must be a boolean value")


def _parse_number(value: str, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EvaluationDataError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise EvaluationDataError(f"{label} must be finite")
    return number


def _read_csv(path: Path, required: set[str]):
    try:
        source = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise EvaluationDataError(f"Unable to read {path.name}") from exc
    with source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise EvaluationDataError(f"{path.name} has no header")
        columns = {name.strip().casefold() for name in reader.fieldnames if name}
        missing = required - columns
        if missing:
            raise EvaluationDataError(
                f"{path.name} is missing columns: {', '.join(sorted(missing))}"
            )
        for row in reader:
            yield {key.strip().casefold(): (value or "").strip() for key, value in row.items() if key}


def _iso_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise EvaluationDataError(f"{label} must be an ISO date") from exc


@dataclass
class BowlingStats:
    delivery_rows: int = 0
    legal_balls: int = 0
    runs_conceded: float = 0.0
    credited_wickets: int = 0

    def add_delivery(self, legal: bool, runs_conceded: float) -> None:
        self.delivery_rows += 1
        self.legal_balls += int(legal)
        self.runs_conceded += runs_conceded

    def add_wicket(self) -> None:
        self.credited_wickets += 1

    def metrics(self) -> dict[str, float | None]:
        balls = self.legal_balls
        wickets = self.credited_wickets
        return {
            "economy": self.runs_conceded * 6 / balls if balls else None,
            "strike_rate": balls / wickets if balls and wickets else None,
            "wicket_rate_per_100_legal_balls": wickets * 100 / balls if balls else None,
        }


@dataclass(frozen=True)
class MatchInfo:
    match_date: date
    competition: str
    season: str
    team_1: str
    team_2: str
    venue: str
    match_type: str
    scheduled_overs: int | None


@dataclass
class FeatureSnapshot:
    cutoff_date: date
    evaluation_match_id: str | None
    history_match_ids: frozenset[str]
    history_match_dates: dict[str, date]
    excluded_match_ids: frozenset[str]
    prior_delivery_rows: int
    prior_legal_deliveries: int
    prior_credited_wickets: int
    career: dict[str, BowlingStats] = field(default_factory=dict)
    phase: dict[tuple[str, str], BowlingStats] = field(default_factory=dict)
    matchup: dict[tuple[str, str], BowlingStats] = field(default_factory=dict)
    phase_matchup: dict[tuple[str, str, str], BowlingStats] = field(default_factory=dict)
    situation: dict[tuple[str, str, str], BowlingStats] = field(default_factory=dict)

    @property
    def prior_match_count(self) -> int:
        return len(self.history_match_ids)

    def assert_leakage_free(self) -> None:
        if self.evaluation_match_id and self.evaluation_match_id in self.history_match_ids:
            raise EvaluationDataError("Evaluation match is present in historical features")
        for match_id, match_date in self.history_match_dates.items():
            if match_id in self.excluded_match_ids or match_date >= self.cutoff_date:
                raise EvaluationDataError("Feature history includes an excluded or non-prior match")


def read_matches(path: Path) -> dict[str, MatchInfo]:
    rows = {}
    required = {
        "match_id", "date", "competition", "season", "team_1", "team_2",
        "venue", "match_type", "overs",
    }
    for row in _read_csv(path, required):
        match_id = row["match_id"]
        if not match_id or match_id in rows:
            raise EvaluationDataError("matches.csv has a blank or duplicate match_id")
        overs: int | None
        try:
            overs = int(row["overs"]) if row["overs"] else None
        except ValueError:
            overs = None
        rows[match_id] = MatchInfo(
            match_date=_iso_date(row["date"], f"matches.csv date for {match_id}"),
            competition=row["competition"],
            season=row["season"],
            team_1=row["team_1"],
            team_2=row["team_2"],
            venue=row["venue"],
            match_type=row["match_type"],
            scheduled_overs=overs,
        )
    if not rows:
        raise EvaluationDataError("matches.csv is empty")
    return rows


def build_historical_snapshot(
    matches_path: Path,
    deliveries_path: Path,
    wickets_path: Path,
    cutoff_date: str | date,
    evaluation_match_id: str | None = None,
    excluded_match_ids: Iterable[str] = (),
) -> FeatureSnapshot:
    """Build past-only features by streaming raw deliveries; no aggregate inputs are accepted."""
    cutoff = _iso_date(cutoff_date, "cutoff_date") if isinstance(cutoff_date, str) else cutoff_date
    match_info = read_matches(matches_path)
    if evaluation_match_id:
        evaluation = match_info.get(evaluation_match_id)
        if evaluation is None or evaluation.match_date != cutoff:
            raise EvaluationDataError("Evaluation match must exist on the cutoff date")

    excluded = frozenset(excluded_match_ids)
    history_dates = {
        match_id: info.match_date
        for match_id, info in match_info.items()
        if info.match_date < cutoff and match_id not in excluded
    }
    event_columns = {
        "match_id", "innings_number", "over_number", "ball_in_over",
        "player_out_id", "bowler_id", "is_bowler_credited",
    }
    events_by_key: dict[tuple[str, str, str, str], list[tuple[str, str, bool]]] = defaultdict(list)
    for event in _read_csv(wickets_path, event_columns):
        match_id = event["match_id"]
        if match_id not in match_info:
            raise EvaluationDataError(f"Wicket event has unknown match_id: {match_id}")
        key = (
            match_id, event["innings_number"], event["over_number"], event["ball_in_over"]
        )
        events_by_key[key].append(
            (
                event["bowler_id"].casefold(),
                event["player_out_id"].casefold(),
                _parse_bool(event["is_bowler_credited"], "is_bowler_credited"),
            )
        )

    deliveries_required = {
        "match_id", "innings_number", "over_number", "ball_in_over",
        "batter_id", "bowler_id", "runs_batter", "extra_wides", "extra_noballs",
        "runs_extras", "extra_byes", "extra_legbyes", "extra_penalty",
        "is_legal_delivery", "match_phase", "batting_team",
    }
    career: dict[str, BowlingStats] = defaultdict(BowlingStats)
    phase: dict[tuple[str, str], BowlingStats] = defaultdict(BowlingStats)
    matchup: dict[tuple[str, str], BowlingStats] = defaultdict(BowlingStats)
    phase_matchup: dict[tuple[str, str, str], BowlingStats] = defaultdict(BowlingStats)
    situation: dict[tuple[str, str, str], BowlingStats] = defaultdict(BowlingStats)
    observed_matches: set[str] = set()
    matched_event_keys: set[tuple[str, str, str, str]] = set()
    delivery_rows = legal_rows = credited_wickets = 0

    for row in _read_csv(deliveries_path, deliveries_required):
        match_id = row["match_id"]
        info = match_info.get(match_id)
        if info is None:
            raise EvaluationDataError(f"Delivery has unknown match_id: {match_id}")
        key = (match_id, row["innings_number"], row["over_number"], row["ball_in_over"])
        events = events_by_key.get(key, ())
        if events:
            matched_event_keys.add(key)
            bowler_id = row["bowler_id"].casefold()
            if any(event_bowler != bowler_id for event_bowler, _, _ in events):
                raise EvaluationDataError("Wicket-event bowler does not match its delivery")

        if info.match_date >= cutoff or match_id in excluded:
            continue
        bowler_id = row["bowler_id"].casefold()
        batter_id = row["batter_id"].casefold()
        if not bowler_id or not batter_id:
            raise EvaluationDataError("Historical delivery has a blank batter or bowler ID")
        phase_label = row["match_phase"].strip().casefold()
        phase_names = {"powerplay": "Powerplay", "middle": "Middle", "death": "Death"}
        if phase_label not in phase_names:
            raise EvaluationDataError(f"Unsupported match_phase value: {row['match_phase']}")
        phase_name = phase_names[phase_label]
        legal = _parse_bool(row["is_legal_delivery"], "is_legal_delivery")
        extra_columns = (
            "extra_wides", "extra_noballs", "extra_byes", "extra_legbyes", "extra_penalty"
        )
        extras = {
            column: 0.0 if not row[column] else _parse_number(row[column], column)
            for column in extra_columns
        }
        if _parse_number(row["runs_extras"], "runs_extras") != sum(extras.values()):
            raise EvaluationDataError("runs_extras does not equal its component extras")
        runs_conceded = (
            _parse_number(row["runs_batter"], "runs_batter")
            + extras["extra_wides"]
            + extras["extra_noballs"]
        )
        if runs_conceded < 0:
            raise EvaluationDataError("Bowler-charged runs cannot be negative")
        observed_matches.add(match_id)
        delivery_rows += 1
        legal_rows += int(legal)
        targets = (
            career[bowler_id],
            phase[(bowler_id, phase_name)],
            matchup[(bowler_id, batter_id)],
            phase_matchup[(bowler_id, batter_id, phase_name.casefold())],
            situation[(bowler_id, "phase", phase_name.casefold())],
            situation[(bowler_id, "competition", info.competition.casefold())],
            situation[(bowler_id, "season", info.season.casefold())],
            situation[(bowler_id, "venue", info.venue.casefold())],
            situation[(bowler_id, "exact_over", str(int(row["over_number"])))],
            situation[(bowler_id, "innings", str(int(row["innings_number"])))],
            situation[(bowler_id, "opposition", row["batting_team"].casefold())],
        )
        for stats in targets:
            stats.add_delivery(legal, runs_conceded)
        for event_bowler, player_out, credited in events:
            if not credited:
                continue
            if event_bowler != bowler_id:
                raise EvaluationDataError("Credited wicket attribution mismatch")
            career[bowler_id].add_wicket()
            phase[(bowler_id, phase_name)].add_wicket()
            situation[(bowler_id, "phase", phase_name.casefold())].add_wicket()
            situation[(bowler_id, "competition", info.competition.casefold())].add_wicket()
            situation[(bowler_id, "season", info.season.casefold())].add_wicket()
            situation[(bowler_id, "venue", info.venue.casefold())].add_wicket()
            situation[(bowler_id, "exact_over", str(int(row["over_number"])))].add_wicket()
            situation[(bowler_id, "innings", str(int(row["innings_number"])))].add_wicket()
            situation[(bowler_id, "opposition", row["batting_team"].casefold())].add_wicket()
            if player_out:
                matchup[(bowler_id, player_out)].add_wicket()
                phase_matchup[(bowler_id, player_out, phase_name.casefold())].add_wicket()
            credited_wickets += 1

    missing_event_keys = set(events_by_key) - matched_event_keys
    if missing_event_keys:
        raise EvaluationDataError(f"{len(missing_event_keys)} wicket event keys have no delivery")

    snapshot = FeatureSnapshot(
        cutoff_date=cutoff,
        evaluation_match_id=evaluation_match_id,
        history_match_ids=frozenset(history_dates),
        history_match_dates=history_dates,
        excluded_match_ids=excluded,
        prior_delivery_rows=delivery_rows,
        prior_legal_deliveries=legal_rows,
        prior_credited_wickets=credited_wickets,
        career=dict(career),
        phase=dict(phase),
        matchup=dict(matchup),
        phase_matchup=dict(phase_matchup),
        situation=dict(situation),
    )
    snapshot.assert_leakage_free()
    return snapshot


def assert_split_isolation(
    train_match_ids: Iterable[str],
    validation_match_ids: Iterable[str],
    test_match_ids: Iterable[str],
    match_dates: dict[str, date],
) -> None:
    groups = [set(train_match_ids), set(validation_match_ids), set(test_match_ids)]
    if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise EvaluationDataError("Chronological splits overlap in match IDs")
    all_dates = [{match_dates[mid] for mid in group} for group in groups]
    for left, right in ((0, 1), (1, 2)):
        if all_dates[left] and all_dates[right] and max(all_dates[left]) >= min(all_dates[right]):
            raise EvaluationDataError("Chronological splits are not strictly date ordered")
