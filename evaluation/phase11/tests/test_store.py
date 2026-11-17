from __future__ import annotations

import json
import sqlite3

import pytest

from evaluation.phase11.event_store import EventStore, EventStoreError, stable_event_id


def _decision(store: EventStore, decision_id: str = "d-1") -> str:
    return store.append(
        event_type="decision_request", decision_id=decision_id,
        payload={
            "mode": "synthetic_test",
            "request": {"batter_id": "bat1", "candidates": []},
            "context_provenance": {"status": "unknown"},
        },
        event_id=stable_event_id(decision_id, "decision_request"),
        event_time_utc="2026-10-12T10:00:00Z",
    )[0]["event_id"]


def test_event_idempotency_same_content_noop_and_changed_content_rejected(tmp_path):
    store = EventStore(tmp_path)
    event_id = stable_event_id("d-1", "decision_request")
    first, created = store.append(
        event_type="decision_request", decision_id="d-1",
        payload={"mode": "synthetic_test", "request": {}, "context_provenance": {"status": "unknown"}},
        event_id=event_id,
    )
    retry, retry_created = store.append(
        event_type="decision_request", decision_id="d-1",
        payload={"mode": "synthetic_test", "request": {}, "context_provenance": {"status": "unknown"}},
        event_id=event_id,
    )
    assert created is True and retry_created is False
    assert retry["event_id"] == first["event_id"]
    assert store.verify()["integrity"] == "ok"
    with pytest.raises(EventStoreError, match="different event content"):
        store.append(
            event_type="decision_request", decision_id="d-1",
            payload={"mode": "prospective_shadow", "request": {}, "context_provenance": {"status": "unknown"}},
            event_id=event_id,
        )


def test_updates_and_deletes_are_rejected(tmp_path):
    store = EventStore(tmp_path)
    _decision(store)
    with sqlite3.connect(store.path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE events SET payload_json = '{}' WHERE sequence = 1")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM events WHERE sequence = 1")


def test_hash_chain_detects_payload_tampering(tmp_path):
    store = EventStore(tmp_path)
    _decision(store)
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TRIGGER events_no_update")
        db.execute("UPDATE events SET payload_json = ? WHERE sequence = 1", (json.dumps({"mode": "synthetic_test"}),))
    result = store.verify()
    assert result["integrity"] == "issues_found"
    assert {row["kind"] for row in result["issues"]} & {"checksum_mismatch", "invalid_event"}


def test_export_is_deterministic_refuses_overwrite_and_is_confined(tmp_path):
    store = EventStore(tmp_path)
    _decision(store)
    export_dir = tmp_path / "reports" / "phase11_export_test"
    export_dir.mkdir(parents=True)
    first = store.export_json(export_dir / "events.json")
    second = store.export_json(export_dir / "events-copy.json")
    assert first["sha256"] == second["sha256"]
    with pytest.raises(EventStoreError, match="already exists"):
        store.export_json(export_dir / "events.json")
    with pytest.raises(EventStoreError, match="phase11_export"):
        store.backup(tmp_path / "untrusted.sqlite3")
    backup = store.backup(export_dir / "events.sqlite3")
    assert backup.is_file()
    parsed = json.loads((export_dir / "events.json").read_text(encoding="utf-8"))
    assert len(parsed["events"]) == 1
    assert len(parsed["events"][0]["event_hash"]) == 64
    assert len(parsed["events"][0]["previous_hash"]) == 64


def test_store_name_rejects_path_traversal(tmp_path):
    with pytest.raises(EventStoreError, match="Store name"):
        EventStore(tmp_path, "..\\..\\private")


def test_unknown_event_type_is_reported_not_ignored(tmp_path):
    store = EventStore(tmp_path)
    _decision(store)
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TRIGGER events_no_update")
        db.execute("UPDATE events SET event_type = 'future_event' WHERE sequence = 1")
    result = store.verify()
    assert result["integrity"] == "issues_found"
    assert "unrecognized_event_type" in {issue["kind"] for issue in result["issues"]}


def test_event_time_is_normalized_to_utc_and_requires_timezone(tmp_path):
    store = EventStore(tmp_path)
    event, _ = store.append(
        event_type="decision_request", decision_id="offset-time",
        payload={"mode": "synthetic_test", "request": {}, "context_provenance": {"status": "unknown"}},
        event_time_utc="2026-10-12T15:30:00+05:30",
    )
    assert event["event_time_utc"] == "2026-10-12T10:00:00.000000Z"
    with pytest.raises(ValueError, match="include a timezone"):
        store.append(
            event_type="decision_request", decision_id="no-zone",
            payload={"mode": "synthetic_test", "request": {}, "context_provenance": {"status": "unknown"}},
            event_time_utc="2026-10-12T10:00:00",
        )
