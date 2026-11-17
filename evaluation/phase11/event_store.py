from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from evaluation.phase11.schema import (
    SCHEMA_VERSION,
    ELIGIBILITY_CONCEPTS,
    EVENT_TYPES,
    EventValidationError,
    canonical_json,
    event_digest,
    make_event,
)

GENESIS_HASH = "0" * 64
EVENT_NAMESPACE = uuid.UUID("e69fb758-7284-4a15-a74d-137f8dc03396")


def stable_event_id(decision_id: str, event_type: str, source_record_id: str = "") -> str:
    return str(uuid.uuid5(EVENT_NAMESPACE, f"{decision_id}|{event_type}|{source_record_id}"))


class EventStoreError(RuntimeError):
    pass


class EventStore:
    """Append-only SQLite event store; database paths are confined to the Phase 11 store folder."""

    def __init__(self, project_root: Path, store_name: str = "default"):
        if not store_name.isascii() or not store_name.replace("-", "").replace("_", "").isalnum():
            raise EventStoreError("Store name may contain only letters, digits, hyphens, and underscores")
        project = project_root.resolve()
        self.project_root = project
        intended_root = project / "evaluation" / "phase11" / "store"
        if any(part.is_symlink() for part in (
            project / "evaluation", project / "evaluation" / "phase11", intended_root
        ) if part.exists()):
            raise EventStoreError("Event store directories may not be symbolic links")
        self.store_root = intended_root
        unresolved_path = self.store_root / f"{store_name}.sqlite3"
        if unresolved_path.is_symlink():
            raise EventStoreError("Event store may not be a symbolic link")
        self.path = unresolved_path.resolve()
        if self.store_root not in self.path.parents:
            raise EventStoreError("Event store path must remain inside the Phase 11 store directory")
        self.store_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        try:
            with self._connection() as connection:
                connection.execute("PRAGMA journal_mode = DELETE")
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        schema_version INTEGER NOT NULL,
                        event_id TEXT NOT NULL UNIQUE,
                        decision_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        event_time_utc TEXT,
                        logged_at_utc TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        previous_hash TEXT NOT NULL,
                        event_hash TEXT NOT NULL UNIQUE
                    )"""
                )
                connection.execute(
                    "CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'append-only event store'); END"
                )
                connection.execute(
                    "CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'append-only event store'); END"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT OR IGNORE INTO store_meta (key, value) VALUES ('schema_version', '1')"
                )
                version = connection.execute(
                    "SELECT value FROM store_meta WHERE key = 'schema_version'"
                ).fetchone()
                if version is None or version["value"] != str(SCHEMA_VERSION):
                    raise EventStoreError("Event-store schema version is unsupported; no migration was attempted")
        except EventStoreError:
            raise
        except sqlite3.Error as exc:
            raise EventStoreError("Unable to initialize the local event store") from exc

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": row["schema_version"],
            "event_id": row["event_id"],
            "decision_id": row["decision_id"],
            "event_type": row["event_type"],
            "event_time_utc": row["event_time_utc"],
            "logged_at_utc": row["logged_at_utc"],
            "payload": json.loads(row["payload_json"]),
        }

    def append(
        self,
        *,
        event_type: str,
        decision_id: str,
        payload: dict[str, Any],
        event_time_utc: str | None = None,
        event_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        event = make_event(
            event_type=event_type,
            decision_id=decision_id,
            payload=payload,
            event_time_utc=event_time_utc,
            event_id=event_id,
        )
        payload_json = canonical_json(event["payload"])
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                prior = connection.execute(
                    "SELECT * FROM events WHERE event_id = ?", (event["event_id"],)
                ).fetchone()
                if prior is not None:
                    prior_event = self._event_from_row(prior)
                    connection.rollback()
                    comparable_prior = {**prior_event, "logged_at_utc": event["logged_at_utc"]}
                    if comparable_prior == event:
                        return prior_event, False
                    raise EventStoreError("event_id already exists with different event content")
                related_rows = connection.execute(
                    "SELECT event_type, event_id, payload_json FROM events WHERE decision_id = ? ORDER BY sequence",
                    (event["decision_id"],),
                ).fetchall()
                related = [
                    {
                        "event_type": row["event_type"],
                        "event_id": row["event_id"],
                        "payload": json.loads(row["payload_json"]),
                    }
                    for row in related_rows
                ]
                if event["event_type"] == "decision_request":
                    if any(row["event_type"] == "decision_request" for row in related):
                        raise EventStoreError("decision_id already has a decision request")
                else:
                    requests = [row for row in related if row["event_type"] == "decision_request"]
                    if len(requests) != 1:
                        raise EventStoreError("Every non-request event requires exactly one prior decision request")
                    if event["event_type"] in {
                        "candidate_snapshot", "recommendation_snapshot", "actual_selection",
                        "outcome_finalized",
                    } and any(row["event_type"] == event["event_type"] for row in related):
                        if event["event_type"] != "outcome_finalized":
                            raise EventStoreError(f"{event['event_type']} already exists for this decision")
                    if event["event_type"] in {"recommendation_snapshot", "recommendation_error"} and not any(
                        row["event_type"] == "candidate_snapshot" for row in related
                    ):
                        raise EventStoreError("Recommendation events require a prior candidate snapshot")
                    if event["event_type"] == "actual_selection" and not any(
                        row["event_type"] == "candidate_snapshot" for row in related
                    ):
                        raise EventStoreError("Selection events require a prior candidate snapshot")
                    if event["event_type"] == "candidate_snapshot":
                        request_payload = requests[0]["payload"]
                        if request_payload["mode"] == "historical_replay":
                            raise EventStoreError("Historical replay candidate sets cannot be manufactured")
                        requested_ids = {
                            row["bowler_id"].casefold()
                            for row in request_payload["request"].get("candidates", [])
                        }
                        logged_ids = {
                            row["candidate_player_id"].casefold()
                            for row in event["payload"]["candidates"]
                        }
                        if requested_ids != logged_ids:
                            raise EventStoreError("Candidate snapshot must match the recommendation request candidate set")
                        if any(
                            row["eligibility_status"] == "confirmed_eligible"
                            and (
                                not row.get("candidate_team")
                                or not request_payload.get("match_state", {}).get("bowling_team_id")
                                or row["candidate_team"].casefold()
                                != request_payload["match_state"]["bowling_team_id"].casefold()
                            )
                            for row in event["payload"]["candidates"]
                        ):
                            raise EventStoreError("Confirmed eligible candidate team must match the decision bowling team")
                        if event["payload"]["candidates"] and any(
                            row["eligibility_status"] == "confirmed_eligible"
                            and any(
                                row["evidence"].get(concept, {}).get("status") != "confirmed"
                                for concept in ELIGIBILITY_CONCEPTS
                            )
                            for row in event["payload"]["candidates"]
                        ):
                            raise EventStoreError("Candidate eligibility evidence is contradictory")
                    if event["event_type"] == "correction":
                        if not any(
                            row["event_id"] == event["payload"]["supersedes_event_id"]
                            for row in related
                        ):
                            raise EventStoreError("Correction must supersede a prior event for this decision")
                last = connection.execute(
                    "SELECT event_hash FROM events ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                previous_hash = last["event_hash"] if last else GENESIS_HASH
                digest = event_digest(event, previous_hash)
                connection.execute(
                    """INSERT INTO events
                    (schema_version, event_id, decision_id, event_type, event_time_utc,
                     logged_at_utc, payload_json, previous_hash, event_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event["schema_version"], event["event_id"], event["decision_id"],
                        event["event_type"], event["event_time_utc"], event["logged_at_utc"],
                        payload_json, previous_hash, digest,
                    ),
                )
                connection.commit()
                return event, True
        except sqlite3.Error as exc:
            raise EventStoreError("Unable to append event to the local store") from exc

    def events(self, *, decision_id: str | None = None) -> list[dict[str, Any]]:
        try:
            with self._connection() as connection:
                if decision_id is None:
                    rows = connection.execute("SELECT * FROM events ORDER BY sequence").fetchall()
                else:
                    rows = connection.execute(
                        "SELECT * FROM events WHERE decision_id = ? ORDER BY sequence", (decision_id,)
                    ).fetchall()
                return [self._event_from_row(row) for row in rows]
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise EventStoreError("Event store could not be read; no records were omitted") from exc

    def verify(self) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        try:
            with self._connection() as connection:
                check = connection.execute("PRAGMA integrity_check").fetchone()[0]
                if check != "ok":
                    issues.append({"kind": "sqlite_integrity", "detail": str(check)})
                rows = connection.execute("SELECT * FROM events ORDER BY sequence").fetchall()
                previous_hash = GENESIS_HASH
                for row in rows:
                    event = None
                    try:
                        event = self._event_from_row(row)
                        expected = event_digest(event, previous_hash)
                        if row["previous_hash"] != previous_hash:
                            issues.append({"kind": "broken_chain", "event_id": row["event_id"]})
                        if row["event_hash"] != expected:
                            issues.append({"kind": "checksum_mismatch", "event_id": row["event_id"]})
                        if event["schema_version"] != SCHEMA_VERSION:
                            issues.append({"kind": "unrecognized_schema", "event_id": row["event_id"]})
                        else:
                            normalized = make_event(
                                event_type=event["event_type"],
                                decision_id=event["decision_id"],
                                payload=event["payload"],
                                event_time_utc=event["event_time_utc"],
                                event_id=event["event_id"],
                                logged_at_utc=event["logged_at_utc"],
                            )
                            if normalized != event:
                                issues.append({"kind": "invalid_event", "event_id": row["event_id"]})
                        previous_hash = row["event_hash"]
                    except (json.JSONDecodeError, EventValidationError, TypeError, ValueError) as exc:
                        if event is not None and event.get("event_type") not in EVENT_TYPES:
                            issue_kind = "unrecognized_event_type"
                        elif isinstance(exc, json.JSONDecodeError):
                            issue_kind = "corrupt_record"
                        else:
                            issue_kind = "invalid_event"
                        issues.append({"kind": issue_kind, "sequence": row["sequence"], "detail": type(exc).__name__})
                        previous_hash = row["event_hash"]
                return {
                    "integrity": "ok" if not issues else "issues_found",
                    "event_count": len(rows),
                    "issues": issues,
                    "last_event_hash": previous_hash,
                }
        except sqlite3.Error as exc:
            raise EventStoreError("Unable to verify the event store") from exc

    def backup(self, destination: Path) -> Path:
        destination = self._export_destination(destination)
        if destination.exists():
            raise EventStoreError("Backup destination already exists; refusing to overwrite")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as source:
                target = sqlite3.connect(destination)
                try:
                    target.execute("PRAGMA synchronous = FULL")
                    source.backup(target)
                finally:
                    target.close()
        except sqlite3.Error as exc:
            raise EventStoreError("Unable to create event-store backup") from exc
        return destination

    def export_json(self, destination: Path) -> dict[str, Any]:
        destination = self._export_destination(destination)
        if destination.exists():
            raise EventStoreError("Export destination already exists; refusing to overwrite")
        events = self.events()
        integrity = self.verify()
        if integrity["integrity"] != "ok":
            raise EventStoreError("Refusing to export an event store with integrity issues")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT sequence, previous_hash, event_hash FROM events ORDER BY sequence"
            ).fetchall()
        for event, row in zip(events, rows):
            event["sequence"] = row["sequence"]
            event["previous_hash"] = row["previous_hash"]
            event["event_hash"] = row["event_hash"]
        payload = {"schema_version": SCHEMA_VERSION, "events": events, "integrity": integrity}
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return {"event_count": len(events), "sha256": _file_sha256(destination)}

    def _export_destination(self, destination: Path) -> Path:
        destination = destination.resolve()
        reports_root = self.project_root / "reports"
        if (
            destination.parent.parent != reports_root
            or not destination.parent.name.startswith("phase11_export_")
            or destination.parent.is_symlink()
        ):
            raise EventStoreError("Exports and backups must use a new reports/phase11_export_<id> directory")
        return destination


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
