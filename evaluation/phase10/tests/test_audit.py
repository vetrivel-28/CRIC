import csv
import hashlib
import json
from pathlib import Path

from evaluation.phase10.audit import audit_roster, hash_tree, source_inventory, roster_anomaly_rows


def _csv(path: Path, fields: list[str], rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _fixture_tree(root: Path) -> dict[str, Path]:
    data = root / "data"
    paths = {
        "matches.csv": _csv(
            data / "matches.csv",
            ["match_id", "team_1", "team_2", "date"],
            [
                {"match_id": "M1", "team_1": "A", "team_2": "B", "date": "2020-01-01"},
                {"match_id": "M2", "team_1": "A", "team_2": "B", "date": "2020-01-02"},
            ],
        ),
        "players.csv": _csv(
            data / "players.csv",
            ["player_id", "player_name"],
            [{"player_id": pid, "player_name": pid.upper()} for pid in ("p1", "p2", "p3", "p4", "p5")],
        ),
        "combined_data.csv": _csv(
            data / "combined_data.csv",
            ["player_id", "bowls_flag"],
            [
                {"player_id": "p1", "bowls_flag": "true"},
                {"player_id": "p2", "bowls_flag": ""},
                {"player_id": "p3", "bowls_flag": "false"},
                {"player_id": "p4", "bowls_flag": ""},
                {"player_id": "p5", "bowls_flag": "true"},
            ],
        ),
        "deliveries.csv": _csv(
            data / "deliveries.csv",
            ["match_id", "batter_id", "bowler_id", "batting_team", "bowling_team", "is_legal_delivery"],
            [
                {"match_id": "M1", "batter_id": "p1", "bowler_id": "p3", "batting_team": "A", "bowling_team": "B", "is_legal_delivery": "true"},
                {"match_id": "M1", "batter_id": "p5", "bowler_id": "p3", "batting_team": "A", "bowling_team": "B", "is_legal_delivery": "true"},
            ],
        ),
        "match_playing_xi.csv": _csv(
            data / "match_playing_xi.csv",
            ["match_id", "team", "player_id", "player_name"],
            [
                {"match_id": "M1", "team": "A", "player_id": "p1", "player_name": "P1"},
                {"match_id": "M1", "team": "A", "player_id": "p1", "player_name": "P1 duplicate"},
                {"match_id": "M1", "team": "A", "player_id": "p2", "player_name": "P2"},
                {"match_id": "M1", "team": "B", "player_id": "p3", "player_name": "P3"},
                {"match_id": "M1", "team": "A", "player_id": "p4", "player_name": "P4"},
                {"match_id": "M1", "team": "B", "player_id": "p4", "player_name": "P4"},
                {"match_id": "M1", "team": "C", "player_id": "unknown", "player_name": "Unknown"},
                {"match_id": "NO_MATCH", "team": "A", "player_id": "p4", "player_name": "P4"},
            ],
        ),
        "wicket_events.csv": _csv(
            data / "wicket_events.csv",
            ["wicket_event_id", "match_id", "innings_number", "over_number", "ball_in_over", "is_bowler_credited"],
            [],
        ),
    }
    return paths


def test_roster_audit_counts_duplicates_conflicts_and_missing_participation_without_mutating_sources(tmp_path):
    paths = _fixture_tree(tmp_path)
    before = hash_tree(tmp_path / "data")
    audit = audit_roster(paths)
    after = hash_tree(tmp_path / "data")

    assert before == after
    assert audit["duplicate_match_player_extra_rows"] == 2
    assert len(audit["cross_team_assignments"]) == 1
    assert audit["same_team_duplicate_keys"][0]["player_id"] == "p1"
    assert audit["rows_without_match_participation"] == 5
    assert audit["unique_roster_ids_absent_from_all_deliveries"] == 3
    assert audit["unique_roster_ids_with_missing_bowls_flag"] == 3
    assert audit["unknown_match_rows"] == 1
    assert audit["unknown_player_rows"] == 1
    assert audit["wrong_team_rows"] == 1
    assert audit["delivery_participant_match_keys_absent_from_roster"] == 1
    assert audit["delivery_participant_team_keys_absent_from_roster"] == 1
    assert audit["delivery_matches_without_roster"] == 0
    assert audit["matches_without_roster"] == 1
    anomalies = roster_anomaly_rows(audit)
    assert any(row["finding"] == "Duplicate match-player assignments" for row in anomalies)


def test_source_inventory_is_repeatable_and_does_not_modify_source_files(tmp_path):
    _fixture_tree(tmp_path)
    before = hash_tree(tmp_path / "data")
    first = source_inventory(tmp_path)
    second = source_inventory(tmp_path)
    after = hash_tree(tmp_path / "data")

    assert first == second
    assert before == after
    assert any(row["relative_path"] == "data/match_playing_xi.csv" for row in first)
    xi = next(row for row in first if row["relative_path"] == "data/match_playing_xi.csv")
    assert xi["row_count"] == 8
    assert len(xi["sha256"]) == hashlib.sha256().digest_size * 2
