from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.phase9.candidate_eligibility import format_metadata_is_consistent
from evaluation.phase9.historical_features import EvaluationDataError


DATASETS = {
    "matches.csv": ("match_id",),
    "innings.csv": ("match_id", "innings_number"),
    "deliveries.csv": ("match_id", "innings_number", "over_number", "ball_in_over"),
    "players.csv": ("player_id",),
    "match_playing_xi.csv": ("match_id", "player_id"),
    "combined_data.csv": ("player_id",),
    "wicket_events.csv": ("wicket_event_id",),
    "bowler_career_performance_v1.csv": ("bowler_id",),
    "bowler_phase_performance_v1.csv": ("bowler_id", "match_phase"),
    "bowler_batter_matchup_stats_v2.csv": ("bowler_id", "batter_id"),
    "bowler_situation_stats_v2.csv": ("bowler_id", "situation_type", "situation_value"),
}


def find_unique(root: Path, filename: str) -> Path:
    matches = sorted(path for path in root.rglob(filename) if path.is_file())
    if len(matches) != 1:
        raise EvaluationDataError(f"Expected exactly one {filename}; found {len(matches)}")
    return matches[0]


def _rows(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise EvaluationDataError(f"{path.name} has no header")
        yield reader.fieldnames, from_reader(reader)


def from_reader(reader):
    for row in reader:
        yield {key: (value or "").strip() for key, value in row.items() if key}


def _type_guess(name: str, samples: list[str]) -> str:
    lower = name.casefold()
    if lower.endswith("_id") or lower in {"match_id", "source_file"}:
        return "string"
    present = [value for value in samples if value]
    if not present:
        return "unknown"
    normalized = {value.casefold() for value in present}
    if normalized <= {"true", "false", "0", "1"} and any(
        value in {"true", "false"} for value in normalized
    ):
        return "boolean"
    try:
        numbers = [float(value) for value in present[:100]]
        if all(number.is_integer() for number in numbers):
            return "integer"
        return "number"
    except ValueError:
        return "string"


def inspect_sources(root: Path) -> tuple[dict[str, Path], list[dict], dict]:
    paths = {name: find_unique(root, name) for name in DATASETS}
    inventory = []
    counts = {}
    raw = {}
    for name, key_columns in DATASETS.items():
        path = paths[name]
        seen = set()
        duplicate_rows = blank_key_rows = row_count = 0
        samples: dict[str, list[str]] = defaultdict(list)
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames:
                raise EvaluationDataError(f"{name} has no header")
            fields = reader.fieldnames
            for row in reader:
                row_count += 1
                for key, value in row.items():
                    if key and value is not None and len(samples[key]) < 10:
                        samples[key].append(value.strip())
                key = tuple((row.get(column) or "").strip().casefold() for column in key_columns)
                if not all(key):
                    blank_key_rows += 1
                if key in seen:
                    duplicate_rows += 1
                seen.add(key)
        counts[name] = row_count
        raw[name] = {
            "fields": fields,
            "key_columns": key_columns,
            "duplicate_rows": duplicate_rows,
            "blank_key_rows": blank_key_rows,
            "types": {field: _type_guess(field, samples[field]) for field in fields},
        }
        inventory.append(
            {
                "dataset": name,
                "path": str(path),
                "rows": row_count,
                "columns": len(fields),
                "schema": ";".join(f"{field}:{raw[name]['types'][field]}" for field in fields),
                "business_key": ",".join(key_columns),
                "duplicate_key_rows": duplicate_rows,
                "blank_key_rows": blank_key_rows,
                "provenance": path.parent.name,
                "match_or_observation_time": (
                    "match_id/date in matches.csv"
                    if name == "matches.csv"
                    else "delivery match_id joins to matches.csv date"
                    if name in {"deliveries.csv", "innings.csv", "wicket_events.csv", "match_playing_xi.csv"}
                    else "not present; full-period aggregate, unsafe as historical snapshot"
                    if name.startswith("bowler_")
                    else "player catalog; no observation-time history"
                ),
                "historical_leakage_risk": (
                    "NOT_SAFE_AS_SNAPSHOT"
                    if name.startswith("bowler_")
                    else "RAW_RECONSTRUCTION_SOURCE"
                    if name in {"deliveries.csv", "wicket_events.csv", "matches.csv"}
                    else "NOT_A_HISTORICAL_FEATURE"
                ),
            }
        )

    match_dates = {}
    match_teams = {}
    match_overs = {}
    matches_file = paths["matches.csv"]
    with matches_file.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            match_dates[row["match_id"]] = row["date"]
            match_teams[row["match_id"]] = {row["team_1"], row["team_2"]}
            try:
                scheduled_overs = int(row["overs"]) if row["overs"] else None
            except ValueError:
                scheduled_overs = None
            match_overs[row["match_id"]] = (row["match_type"], scheduled_overs)

    players = set()
    player_file = paths["players.csv"]
    with player_file.open(encoding="utf-8-sig", newline="") as source:
        players = {row["player_id"] for row in csv.DictReader(source)}
    combined = {}
    with paths["combined_data.csv"].open(encoding="utf-8-sig", newline="") as source:
        combined = {row["player_id"]: row for row in csv.DictReader(source)}

    xi_by_match = Counter()
    xi_by_team = Counter()
    xi_players = set()
    xi_pairs = Counter()
    xi_pair_teams = defaultdict(set)
    xi_match_orphans = xi_team_orphans = xi_player_orphans = 0
    xi_role_flags = Counter()
    with paths["match_playing_xi.csv"].open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            match_id, team, player_id = row["match_id"], row["team"], row["player_id"]
            xi_by_match[match_id] += 1
            xi_by_team[(match_id, team)] += 1
            xi_players.add(player_id)
            xi_pairs[(match_id, player_id)] += 1
            xi_pair_teams[(match_id, player_id)].add(team)
            xi_match_orphans += match_id not in match_dates
            xi_team_orphans += bool(match_id in match_teams and team not in match_teams[match_id])
            xi_player_orphans += player_id not in players
            flag = (combined.get(player_id, {}).get("bowls_flag") or "").strip().casefold()
            xi_role_flags[flag or "missing"] += 1

    delivery_player_ids = set()
    delivery_keys = set()
    delivery_matches = set()
    delivery_rows = legal_balls = charged_extra_rows = runs_extra_mismatches = 0
    illegal_rows_without_wides_noballs = legal_rows_with_wides_noballs = 0
    phase_values = Counter()
    match_max_over = defaultdict(int)
    with paths["deliveries.csv"].open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            delivery_rows += 1
            delivery_matches.add(row["match_id"])
            delivery_player_ids.update((row["batter_id"], row["bowler_id"]))
            delivery_keys.add(
                (row["match_id"], row["innings_number"], row["over_number"], row["ball_in_over"])
            )
            legal = row["is_legal_delivery"].strip().casefold() in {"true", "1"}
            wide = float(row["extra_wides"] or 0)
            no_ball = float(row["extra_noballs"] or 0)
            legal_balls += legal
            charged_extra_rows += bool(wide or no_ball)
            legal_rows_with_wides_noballs += legal and bool(wide or no_ball)
            illegal_rows_without_wides_noballs += (not legal) and not bool(wide or no_ball)
            expected_extras = sum(
                float(row[column] or 0)
                for column in ("extra_wides", "extra_noballs", "extra_byes", "extra_legbyes", "extra_penalty")
            )
            runs_extra_mismatches += float(row["runs_extras"] or 0) != expected_extras
            phase_values[row["match_phase"]] += 1
            try:
                match_max_over[row["match_id"]] = max(
                    match_max_over[row["match_id"]], int(row["over_number"])
                )
            except ValueError:
                raise EvaluationDataError("Delivery over_number is invalid")

    wicket_rows = 0
    wicket_keys = Counter()
    wicket_match_orphans = wicket_player_orphans = event_bowler_mismatches = 0
    credited_wickets = 0
    with paths["wicket_events.csv"].open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            wicket_rows += 1
            match_id = row["match_id"]
            key = (match_id, row["innings_number"], row["over_number"], row["ball_in_over"])
            wicket_keys[key] += 1
            wicket_match_orphans += match_id not in match_dates
            wicket_player_orphans += row["player_out_id"] not in players
            credited_wickets += row["is_bowler_credited"].strip().casefold() in {"true", "1"}
    delivery_bowler_by_key = {}
    with paths["deliveries.csv"].open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            key = (row["match_id"], row["innings_number"], row["over_number"], row["ball_in_over"])
            if key in wicket_keys:
                delivery_bowler_by_key[key] = row["bowler_id"]
    if set(wicket_keys) - set(delivery_bowler_by_key):
        raise EvaluationDataError("Wicket event keys do not all join to deliveries")
    with paths["wicket_events.csv"].open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            key = (row["match_id"], row["innings_number"], row["over_number"], row["ball_in_over"])
            event_bowler_mismatches += row["bowler_id"] != delivery_bowler_by_key[key]

    overs_anomalies = sorted(
        match_id
        for match_id, (match_type, scheduled_overs) in match_overs.items()
        if not format_metadata_is_consistent(match_type, scheduled_overs)
    )
    shared_dates = Counter(match_dates.values())
    xi_sizes = Counter(xi_by_match.values())
    teams_per_match = Counter()
    team_names_by_match = defaultdict(set)
    for match_id, team in xi_by_team:
        team_names_by_match[match_id].add(team)
    for match_id, names in team_names_by_match.items():
        teams_per_match[len(names)] += 1

    roster_audit = {
        "match_count": len(match_dates),
        "xi_row_count": sum(xi_by_match.values()),
        "xi_match_count": len(xi_by_match),
        "xi_rows_per_match": dict(sorted(xi_sizes.items())),
        "xi_rows_per_team": dict(sorted(Counter(xi_by_team.values()).items())),
        "teams_per_match": dict(sorted(teams_per_match.items())),
        "duplicate_match_player_rows": sum(count - 1 for count in xi_pairs.values() if count > 1),
        "players_assigned_to_multiple_teams_within_match": sum(
            len(teams) > 1 for teams in xi_pair_teams.values()
        ),
        "xi_orphan_match_rows": xi_match_orphans,
        "xi_team_not_in_match_metadata_rows": xi_team_orphans,
        "xi_player_not_in_players_rows": xi_player_orphans,
        "unique_xi_player_ids": len(xi_players),
        "unique_xi_ids_not_in_any_delivery": len(xi_players - delivery_player_ids),
        "xi_role_flag_row_counts": dict(xi_role_flags),
        "unique_xi_ids_with_missing_bowls_flag": sum(
            not (combined.get(player_id, {}).get("bowls_flag") or "").strip()
            for player_id in xi_players
        ),
        "matches_without_xi": len(set(match_dates) - set(xi_by_match)),
        "provenance": "No local XI-generation script or per-row provenance metadata was found; the CSV contains match_id, team, player_id, player_name only.",
    }
    quality = {
        "match_date_min": min(match_dates.values()),
        "match_date_max": max(match_dates.values()),
        "distinct_match_dates": len(shared_dates),
        "dates_with_multiple_matches": sum(count > 1 for count in shared_dates.values()),
        "delivery_match_orphans": len(delivery_matches - set(match_dates)),
        "delivery_player_ids_not_in_players": len(delivery_player_ids - players),
        "delivery_player_ids_not_in_combined": len(delivery_player_ids - set(combined)),
        "delivery_rows": delivery_rows,
        "unique_delivery_keys": len(delivery_keys),
        "legal_balls": legal_balls,
        "rows_with_wide_or_no_ball": charged_extra_rows,
        "legal_rows_with_wides_or_no_balls": legal_rows_with_wides_noballs,
        "illegal_rows_without_wides_or_no_balls": illegal_rows_without_wides_noballs,
        "runs_extras_formula_mismatches": runs_extra_mismatches,
        "phase_values": dict(phase_values),
        "wicket_rows": wicket_rows,
        "credited_wickets": credited_wickets,
        "wicket_delivery_keys_with_multiple_events": sum(count > 1 for count in wicket_keys.values()),
        "wicket_match_orphans": wicket_match_orphans,
        "wicket_player_ids_not_in_players": wicket_player_orphans,
        "event_delivery_bowler_mismatches": event_bowler_mismatches,
        "inconsistent_overs_match_ids": overs_anomalies,
        "inconsistent_overs_actual_max_over": {
            match_id: match_max_over.get(match_id) for match_id in overs_anomalies
        },
        "candidate_eligible_matches_admitted": 0,
        "decision_scenarios_admitted": 0,
        "candidate_block_reason": "Roster inclusion/availability, decision-time quota state, and counterfactual alternative outcomes are not established by local source fields.",
    }
    return paths, inventory, {"counts": counts, "roster": roster_audit, "quality": quality, "raw": raw}
