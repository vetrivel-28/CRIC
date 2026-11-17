from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


DATA_KEY_COLUMNS = {
    "matches.csv": ("match_id",),
    "innings.csv": ("match_id", "innings_number"),
    "deliveries.csv": ("match_id", "innings_number", "over_number", "ball_in_over"),
    "players.csv": ("player_id",),
    "combined_data.csv": ("player_id",),
    "match_playing_xi.csv": ("match_id", "team", "player_id"),
    "wicket_events.csv": ("wicket_event_id",),
    "wickets.csv": ("match_id", "innings_number", "over_number", "ball_in_over", "player_out_id"),
    "wicket_fielders.csv": (),
    "powerplays.csv": (),
    "bowler_career_performance_v1.csv": ("bowler_id",),
    "bowler_phase_performance_v1.csv": ("bowler_id", "match_phase"),
    "bowler_batter_matchup_stats_v2.csv": ("bowler_id", "batter_id"),
    "bowler_situation_stats_v2.csv": ("bowler_id", "situation_type", "situation_value"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_tree(root: Path) -> dict[str, dict[str, int | str]]:
    return {
        path.relative_to(root).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _source_description(path: Path, project_root: Path) -> tuple[str, str, str, str]:
    relative = path.relative_to(project_root).as_posix()
    parts = Path(relative).parts
    name = path.name
    if len(parts) > 1 and parts[0] == "data":
        package = parts[1]
        if package.startswith("merged_cricket_data-"):
            return (
                "source package; external origin, URL, license, and extraction lineage not established",
                "raw dataset",
                "raw/package export",
                "No transformation specification located for the roster or merged source package.",
            )
        if package.startswith("wickets_derived_Dataset-"):
            return (
                "derived package; source export metadata not present in inspected local files",
                "derived dataset",
                "derived",
                "wicket_events.csv matches wickets.csv row count and is used by the Phase 9 raw feature builder; exact generator lineage not established.",
            )
        if package.startswith("CRIC_bowler_career_performance_v1-"):
            return (
                "documented local aggregate; upstream acquisition provenance unknown",
                "derived aggregate or validation report",
                "derived/report",
                "README specifies deliveries.csv and wickets.csv inputs, all-history aggregation, and formulas.",
            )
        if package.startswith("CRIC_bowler_phase_performance_v1-"):
            return (
                "documented local aggregate; upstream acquisition provenance unknown",
                "derived aggregate or validation report",
                "derived/report",
                "README specifies deliveries.csv and wicket_events.csv inputs, source phase labels, and formulas.",
            )
        if package.startswith("bowler_matchup_situation_Dataset-"):
            return (
                "local archive/package; external origin and license not established",
                "derived aggregate or validation report",
                "derived/report",
                "Local validation report records 42 removed situation duplicate rows; exact generator source not located.",
            )
        if package == "processed":
            return (
                "local validation artifact",
                "integrity/provenance report",
                "report",
                "Generated locally by ingestion or HDFS integrity tooling; not a cricket observation source.",
            )
        return (
            "origin not established from local evidence",
            "dataset or report",
            "unknown",
            "No authoritative transformation lineage located.",
        )
    if parts[:2] == ("phase2_outputs",):
        return (
            "generated locally by Phase 2 validation pipeline",
            "derived output or report",
            "derived/report",
            "Phase 2 execution and validation summaries identify the local pipeline and raw data root.",
        )
    if parts[:2] == ("reports", "phase9_complete_06"):
        return (
            "generated locally by Phase 9",
            "audit report",
            "report",
            "Reproducibility manifest records source and Python script hashes.",
        )
    if relative == "scripts/ingest_cric_data.py":
        return (
            "local ingestion tooling",
            "source metadata generator",
            "tooling",
            "Records paths, sizes, SHA-256, modified timestamps, and selected header checks; does not identify source URLs or licenses.",
        )
    if relative == "scripts/validation/phase2_pipeline.py":
        return (
            "local Phase 2 pipeline",
            "transformation code",
            "tooling",
            "Builds Phase 2 outputs from files beneath data; does not establish external roster provenance.",
        )
    if relative.startswith("evaluation/phase9/"):
        return (
            "local Phase 9 audit implementation",
            "audit code or test",
            "tooling",
            "Reconstructs prior-only feature snapshots from matches, deliveries, and wicket events.",
        )
    return (
        "local supporting evidence; external source not established",
        "supporting file",
        "supporting",
        "Supporting file inspected for source lineage and transformation notes.",
    )


def _row_key(path: Path, fields: list[str]) -> str:
    candidates = DATA_KEY_COLUMNS.get(path.name)
    if candidates is None:
        candidates = tuple(
            field for field in fields
            if field.casefold() in {"match_id", "player_id", "bowler_id", "batter_id"}
        )
    if not candidates:
        return "not established"
    if any(column not in fields for column in candidates):
        return "candidate unavailable: required column missing"
    return ";".join(candidates)


def source_inventory(project_root: Path) -> list[dict]:
    data_root = project_root / "data"
    paths = set(path for path in data_root.rglob("*.csv") if path.is_file())
    paths.update(
        path for path in data_root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".txt", ".zip"}
    )
    paths.update(path for path in (project_root / "phase2_outputs").rglob("*") if path.is_file())
    phase9_root = project_root / "reports" / "phase9_complete_06"
    if phase9_root.exists():
        paths.update(path for path in phase9_root.iterdir() if path.is_file())
    paths.update(
        {
            project_root / "scripts" / "ingest_cric_data.py",
            project_root / "scripts" / "validation" / "phase2_pipeline.py",
            project_root / "docs" / "phase2_dataset_lineage.md",
        }
    )
    paths.update(path for path in (project_root / "evaluation" / "phase9").rglob("*.py") if path.is_file())

    inventory = []
    for path in sorted(path for path in paths if path.is_file()):
        header = ""
        row_count: int | str = ""
        null_counts: dict[str, int] = {}
        if path.suffix.casefold() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                fields = reader.fieldnames or []
                header = ";".join(fields)
                relevant = [
                    column for column in fields
                    if column.casefold().endswith("_id")
                    or column.casefold() in {
                        "match_id", "team", "date", "bowls_flag", "is_bowler_credited",
                        "is_legal_delivery", "runs_batter", "runs_extras",
                    }
                ]
                row_count = 0
                for row in reader:
                    row_count += 1
                    for column in relevant:
                        if not (row.get(column) or "").strip():
                            null_counts[column] = null_counts.get(column, 0) + 1
            key_columns = _row_key(path, fields)
        else:
            key_columns = "not applicable"
        provenance, role, source_type, transformation = _source_description(path, project_root)
        inventory.append(
            {
                "relative_path": path.relative_to(project_root).as_posix(),
                "format": path.suffix.lstrip(".").casefold() or "no extension",
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
                "header": header,
                "row_count": row_count,
                "candidate_key": key_columns,
                "relevant_null_counts": json.dumps(null_counts, sort_keys=True),
                "provenance_status": provenance,
                "source_role": role,
                "source_type": source_type,
                "transformation_history": transformation,
            }
        )
    return inventory


def audit_roster(paths: dict[str, Path]) -> dict:
    with paths["matches.csv"].open("r", encoding="utf-8-sig", newline="") as handle:
        matches = {row["match_id"]: row for row in csv.DictReader(handle)}
    with paths["players.csv"].open("r", encoding="utf-8-sig", newline="") as handle:
        players = {row["player_id"]: row for row in csv.DictReader(handle)}
    with paths["combined_data.csv"].open("r", encoding="utf-8-sig", newline="") as handle:
        profiles = {row["player_id"]: row for row in csv.DictReader(handle)}

    participation: set[tuple[str, str]] = set()
    participant_teams: set[tuple[str, str, str]] = set()
    delivery_player_ids: set[str] = set()
    delivery_match_ids: set[str] = set()
    participant_team_mismatches: list[dict] = []
    delivery_rows_count = legal_deliveries = 0
    with paths["deliveries.csv"].open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            delivery_rows_count += 1
            legal_value = row["is_legal_delivery"].strip().casefold()
            if legal_value not in {"true", "false", "1", "0"}:
                raise ValueError("deliveries.csv contains an invalid is_legal_delivery value")
            legal_deliveries += legal_value in {"true", "1"}
            match_id = row["match_id"]
            delivery_match_ids.add(match_id)
            for player_column, team_column in (
                ("batter_id", "batting_team"),
                ("bowler_id", "bowling_team"),
            ):
                player_id = row[player_column]
                delivery_player_ids.add(player_id)
                participation.add((match_id, player_id))
                participant_teams.add((match_id, player_id, row[team_column]))

    roster_rows = []
    roster_by_match: Counter = Counter()
    roster_by_match_team: Counter = Counter()
    match_player_counts: Counter = Counter()
    match_player_teams: dict[tuple[str, str], set[str]] = defaultdict(set)
    roster_team_assignments: set[tuple[str, str, str]] = set()
    team_size_examples: dict[int, list[str]] = defaultdict(list)
    missing_role_players: set[str] = set()
    missing_role_rows = 0
    role_rows: Counter = Counter()
    no_participation: list[dict] = []
    unknown_match_rows: list[dict] = []
    unknown_player_rows: list[dict] = []
    wrong_team_rows: list[dict] = []

    with paths["match_playing_xi.csv"].open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            roster_rows.append(row)
            match_id, team, player_id = row["match_id"], row["team"], row["player_id"]
            roster_by_match[match_id] += 1
            roster_by_match_team[(match_id, team)] += 1
            match_player_counts[(match_id, player_id)] += 1
            match_player_teams[(match_id, player_id)].add(team)
            roster_team_assignments.add((match_id, player_id, team))
            if not participation.__contains__((match_id, player_id)) and len(no_participation) < 10000:
                no_participation.append(row)
            if match_id not in matches:
                unknown_match_rows.append(row)
            elif team not in {matches[match_id]["team_1"], matches[match_id]["team_2"]}:
                wrong_team_rows.append(row)
            if player_id not in players:
                unknown_player_rows.append(row)
            profile_flag = (profiles.get(player_id, {}).get("bowls_flag") or "").strip().casefold()
            role_rows[profile_flag or "missing"] += 1
            if not profile_flag:
                missing_role_rows += 1
                missing_role_players.add(player_id)

    team_size_counts = Counter(roster_by_match_team.values())
    for (match_id, _), count in roster_by_match_team.items():
        if len(team_size_examples[count]) < 8:
            team_size_examples[count].append(match_id)

    cross_team = [
        {"match_id": key[0], "player_id": key[1], "teams": sorted(teams), "row_count": match_player_counts[key]}
        for key, teams in sorted(match_player_teams.items())
        if len(teams) > 1
    ]
    repeated_same_team = [
        {"match_id": key[0], "player_id": key[1], "teams": sorted(match_player_teams[key]), "row_count": count}
        for key, count in sorted(match_player_counts.items())
        if count > 1 and len(match_player_teams[key]) == 1
    ]
    players_absent_everywhere = sorted(
        player_id for player_id in {row["player_id"] for row in roster_rows}
        if player_id not in delivery_player_ids
    )
    no_delivery_examples = [
        {key: row[key] for key in ("match_id", "team", "player_id", "player_name")}
        for row in no_participation[:8]
    ]
    absent_player_examples = [
        {
            "player_id": player_id,
            "player_name": players.get(player_id, {}).get("player_name", ""),
        }
        for player_id in players_absent_everywhere[:8]
    ]
    roster_ids = {row["player_id"] for row in roster_rows}
    roster_match_player_keys = set(match_player_counts)
    missing_matches = sorted(set(matches) - set(roster_by_match))
    participants_without_roster = sorted(
        (match_id, player_id)
        for match_id, player_id in participation - roster_match_player_keys
    )
    participant_team_mismatches = sorted(participant_teams - roster_team_assignments)
    wicket_event_rows = bowler_credited_wickets = 0
    with paths["wicket_events.csv"].open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            wicket_event_rows += 1
            credited_value = row["is_bowler_credited"].strip().casefold()
            if credited_value in {"true", "1"}:
                bowler_credited_wickets += 1
            elif credited_value not in {"false", "0"}:
                raise ValueError("wicket_events.csv contains an invalid credit flag")
    return {
        "match_count": len(matches),
        "delivery_rows": delivery_rows_count,
        "legal_deliveries": legal_deliveries,
        "wicket_event_rows": wicket_event_rows,
        "bowler_credited_wickets": bowler_credited_wickets,
        "delivery_player_ids": len(delivery_player_ids),
        "roster_rows": len(roster_rows),
        "matches_with_roster": len(roster_by_match),
        "matches_without_roster": len(missing_matches),
        "match_roster_row_counts": dict(sorted(Counter(roster_by_match.values()).items())),
        "match_roster_size_examples": {str(k): v for k, v in sorted(team_size_examples.items())},
        "team_roster_size_counts": dict(sorted(team_size_counts.items())),
        "team_roster_size_examples": {
            str(size): sorted(
                f"{match_id}:{team}"
                for (match_id, team), count in roster_by_match_team.items()
                if count == size
            )[:8]
            for size in sorted(team_size_counts)
        },
        "duplicate_match_player_extra_rows": sum(max(0, count - 1) for count in match_player_counts.values()),
        "duplicate_match_player_keys": [
            {"match_id": mid, "player_id": pid, "rows": count}
            for (mid, pid), count in sorted(match_player_counts.items()) if count > 1
        ],
        "same_team_duplicate_keys": repeated_same_team,
        "cross_team_assignments": cross_team,
        "rows_without_match_participation": len(no_participation),
        "rows_without_match_participation_examples": no_delivery_examples,
        "unique_roster_ids": len(roster_ids),
        "unique_roster_ids_absent_from_all_deliveries": len(players_absent_everywhere),
        "absent_roster_player_examples": absent_player_examples,
        "bowls_flag_row_counts": dict(role_rows),
        "rows_with_missing_bowls_flag": missing_role_rows,
        "unique_roster_ids_with_missing_bowls_flag": len(missing_role_players),
        "missing_role_player_examples": [
            {
                "player_id": player_id,
                "player_name": players.get(player_id, {}).get("player_name", ""),
            }
            for player_id in sorted(missing_role_players)[:8]
        ],
        "unknown_match_rows": len(unknown_match_rows),
        "unknown_player_rows": len(unknown_player_rows),
        "wrong_team_rows": len(wrong_team_rows),
        "wrong_team_examples": [
            {key: row[key] for key in ("match_id", "team", "player_id", "player_name")}
            for row in wrong_team_rows[:8]
        ],
        "delivery_participant_ids": len(delivery_player_ids),
        "delivery_participant_match_keys_absent_from_roster": len(participants_without_roster),
        "delivery_participant_absent_examples": [
            {"match_id": match_id, "player_id": player_id}
            for match_id, player_id in participants_without_roster[:8]
        ],
        "delivery_participant_team_keys_absent_from_roster": len(participant_team_mismatches),
        "delivery_participant_team_examples": [
            {"match_id": match_id, "player_id": player_id, "team": team}
            for match_id, player_id, team in participant_team_mismatches[:8]
        ],
        "delivery_matches_without_roster": len(delivery_match_ids - set(roster_by_match)),
        "all_match_metadata": matches,
    }


def roster_anomaly_rows(audit: dict) -> list[dict]:
    return [
        {
            "finding": "Roster row counts per match",
            "affected_rows": audit["roster_rows"],
            "affected_players": "",
            "affected_matches": audit["matches_with_roster"],
            "exact_distribution": json.dumps(audit["match_roster_row_counts"], sort_keys=True),
            "examples": json.dumps(audit["match_roster_size_examples"], sort_keys=True),
            "assessment": "Verified row-count distribution; not evidence of XI, squad, or availability semantics.",
            "action": "Retain as source data; flag non-22 counts for provenance review; exclude no rows solely by count.",
        },
        {
            "finding": "Team roster rows per match-team",
            "affected_rows": audit["roster_rows"],
            "affected_players": "",
            "affected_matches": audit["matches_with_roster"],
            "exact_distribution": json.dumps(audit["team_roster_size_counts"], sort_keys=True),
            "examples": json.dumps(audit["team_roster_size_examples"], sort_keys=True),
            "assessment": "Team sizes range from 10 to 13; no record semantics explain the variation.",
            "action": "Retain and flag; obtain official team sheets and substitutions before eligibility use.",
        },
        {
            "finding": "Duplicate match-player assignments",
            "affected_rows": audit["duplicate_match_player_extra_rows"],
            "affected_players": len(audit["duplicate_match_player_keys"]),
            "affected_matches": len({item["match_id"] for item in audit["duplicate_match_player_keys"]}),
            "exact_distribution": json.dumps(audit["duplicate_match_player_keys"], sort_keys=True),
            "examples": json.dumps(audit["cross_team_assignments"], sort_keys=True),
            "assessment": "One repeated key is a cross-team assignment in match 1229824; same-team duplicate keys are absent.",
            "action": "Flag the conflicting match-player assignment; do not select either team without source correction.",
        },
        {
            "finding": "Roster entries without same-match delivery participation",
            "affected_rows": audit["rows_without_match_participation"],
            "affected_players": "",
            "affected_matches": "",
            "exact_distribution": "5189 rows in the current source snapshot",
            "examples": json.dumps(audit["rows_without_match_participation_examples"], sort_keys=True),
            "assessment": "No batter/bowler delivery row for that player and match; does not establish unused status, absence, or ineligibility.",
            "action": "Retain; leave participation/availability interpretation unresolved.",
        },
        {
            "finding": "Roster player IDs absent from all delivery records",
            "affected_rows": "",
            "affected_players": audit["unique_roster_ids_absent_from_all_deliveries"],
            "affected_matches": "",
            "exact_distribution": "Unique IDs across the full local delivery dataset",
            "examples": json.dumps(audit["absent_roster_player_examples"], sort_keys=True),
            "assessment": "No delivery participation anywhere; possible nonparticipants or source/ID issue cannot be distinguished.",
            "action": "Retain; obtain authoritative roster source and player ID mapping.",
        },
        {
            "finding": "Missing bowling-role flags",
            "affected_rows": audit["rows_with_missing_bowls_flag"],
            "affected_players": audit["unique_roster_ids_with_missing_bowls_flag"],
            "affected_matches": "",
            "exact_distribution": json.dumps(audit["bowls_flag_row_counts"], sort_keys=True),
            "examples": json.dumps(audit["missing_role_player_examples"], sort_keys=True),
            "assessment": "The current combined player catalog has blank bowls_flag; role source and temporal validity are not documented.",
            "action": "Do not infer role from delivery participation; obtain dated authoritative player-role evidence.",
        },
        {
            "finding": "Identifier and team joins",
            "affected_rows": audit["unknown_match_rows"] + audit["unknown_player_rows"] + audit["wrong_team_rows"],
            "affected_players": "",
            "affected_matches": "",
            "exact_distribution": json.dumps({
                "unknown_match_rows": audit["unknown_match_rows"],
                "unknown_player_rows": audit["unknown_player_rows"],
                "wrong_team_rows": audit["wrong_team_rows"],
                "delivery_participant_match_keys_absent_from_roster": audit["delivery_participant_match_keys_absent_from_roster"],
                "delivery_participant_team_keys_absent_from_roster": audit["delivery_participant_team_keys_absent_from_roster"],
                "matches_without_roster": audit["matches_without_roster"],
            }, sort_keys=True),
            "examples": json.dumps(audit["wrong_team_examples"], sort_keys=True),
            "assessment": "Roster identifiers join to local match/player catalogs and delivery participant IDs are covered, but authority/provenance of those catalogs is not established.",
            "action": "Preserve the clean local joins; do not treat them as proof of authoritative lineup or availability.",
        },
    ]
