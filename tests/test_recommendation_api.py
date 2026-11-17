from __future__ import annotations

import json
import csv
import logging
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

import pytest

from backend.api import create_server
from backend.recommendation_engine import DatasetPaths, RecommendationEngine


@pytest.fixture(scope="module")
def running_api():
    engine = RecommendationEngine(DatasetPaths.discover(Path("C:/CRIC/data")))
    server = create_server(engine, port=0, data_root=Path(r"C:\CRIC\data"))
    assert server.server_address[0] == "127.0.0.1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield base_url, engine
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _post(url: str, body: bytes, content_type: str = "application/json"):
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())
    with response:
        return response.status, json.loads(response.read())


def _get(url: str):
    try:
        response = urllib.request.urlopen(url, timeout=30)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())
    with response:
        return response.status, json.loads(response.read())


def test_health_and_recommendation_endpoint_are_local(running_api):
    base_url, engine = running_api
    with urllib.request.urlopen(f"{base_url}/health", timeout=10) as response:
        health = json.loads(response.read())
        assert response.status == 200
        assert health == {"status": "ok", "execution_mode": "local_python"}
    batter_id = next(iter(engine.players))
    bowler_id = next(iter(engine.career))
    phase = next(iter(engine.phase_labels.values()))
    situation = {"type": "competition", "value": "ipl"}
    status, payload = _post(
        f"{base_url}/api/v1/recommendations",
        json.dumps(
            {
                "batter_id": batter_id,
                "phase": phase,
                "situation": situation,
                "candidates": [{"bowler_id": bowler_id}],
            }
        ).encode(),
    )
    assert status == 200
    assert payload["execution_mode"] == "local_python"
    assert payload["recommendations"][0]["bowler_id"] == bowler_id
    assert payload["phase"] == phase
    assert payload["situation"] == situation
    assert len({row["bowler_id"] for row in payload["recommendations"]}) == len(payload["recommendations"])


def test_options_and_static_frontend_are_served_without_file_access(running_api):
    base_url, engine = running_api
    with urllib.request.urlopen(f"{base_url}/api/v1/options", timeout=10) as response:
        options = json.loads(response.read())
    assert set(options) == {"phases", "batters", "bowlers", "situations"}
    assert set(options["phases"]) == set(engine.phase_labels.values())
    assert len(options["batters"]) == len(engine.players)
    assert len(options["bowlers"]) == len(engine.career)
    assert all(item["id"] in engine.players for item in options["batters"])
    assert all(item["id"] in engine.career for item in options["bowlers"])
    assert all(
        isinstance(item, dict) and set(item) == {"type", "values"}
        for item in options["situations"]
    )
    for path, content_type, marker in (
        ("/", "text/html", "CRIC"),
        ("/app.js", "text/javascript", "api/v1/recommendations"),
        ("/dashboard.js", "text/javascript", "api/v1/dashboard"),
        ("/styles.css", "text/css", "recommendation-card"),
    ):
        with urllib.request.urlopen(f"{base_url}{path}", timeout=10) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert content_type in response.headers["Content-Type"]
            assert marker in body
            if path == "/":
                assert "phase-by-situation cross-tabulation" in body

    status, payload = _post(f"{base_url}/api/v1/options", b"{}")
    assert status == 404
    assert payload["error"]["code"] == "not_found"

    for path in ("/..%2fbackend%2frecommendation_engine.py", "/app.js/../backend/api.py"):
        try:
            response = urllib.request.urlopen(f"{base_url}{path}", timeout=10)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            response.close()
            pytest.fail("Unlisted static paths must not be served")


def test_wicket_endpoint_filters_by_real_bowler_and_splits_credit(running_api):
    base_url, _ = running_api
    status, unfiltered = _get(f"{base_url}/api/v1/dashboard/wickets?page_size=10")
    assert status == 200
    bowler_id = unfiltered["events"][0]["bowler_id"]
    status, filtered = _get(
        f"{base_url}/api/v1/dashboard/wickets?bowler_id={quote(bowler_id)}&page_size=10"
    )
    assert status == 200
    assert filtered["filters"]["bowler_id"] == bowler_id
    assert filtered["events"]
    assert all(row["bowler_id"] == bowler_id for row in filtered["events"])
    assert all(
        item["bowler_credited"] <= item["events"]
        for item in filtered["events_by_phase"]
    )
    assert filtered["event_count"] > 0


def test_dashboard_routes_use_real_local_data_and_validate_filters(running_api):
    base_url, engine = running_api

    status, options = _get(f"{base_url}/api/v1/dashboard/options")
    assert status == 200
    assert {"Powerplay", "Middle", "Death"} <= set(options["phases"])
    assert len(options["bowlers"]) == 3190
    assert options["seasons"]

    status, overview = _get(f"{base_url}/api/v1/dashboard/overview")
    assert status == 200
    assert overview["execution_mode"] == "local_python"
    assert overview["kpis"] == {
        "matches": 4230,
        "bowlers": 3190,
        "batters_in_matchups": 4267,
        "deliveries": 966985,
        "legal_balls": 925882,
        "bowler_credited_wickets": 48983,
        "wicket_events": 53294,
        "matchup_records": 131294,
        "phases": 3,
        "datasets": 24,
    }
    assert sum(item["legal_balls"] for item in overview["phase_distribution"]) == 925882
    assert sum(item["bowler_credited"] for item in overview["dismissal_types"]) == 48983

    status, filtered = _get(
        f"{base_url}/api/v1/dashboard/overview?phase=Powerplay&min_balls=300"
    )
    assert status == 200
    assert filtered["filters"]["phase"] == "Powerplay"
    assert filtered["filters"]["minimum_legal_balls"] == 300
    assert filtered["kpis"] == overview["kpis"]

    status, error = _get(f"{base_url}/api/v1/dashboard/overview?phase=not-a-phase")
    assert status == 400
    assert error["error"]["code"] == "invalid_request"

    status, matchups = _get(
        f"{base_url}/api/v1/dashboard/matchups?page=1&page_size=10&sort=wickets&order=desc"
    )
    assert status == 200
    assert matchups["total"] == 2944
    assert len(matchups["rows"]) == 10
    assert matchups["rows"][0]["wickets"] >= matchups["rows"][-1]["wickets"]
    matchup_sample = matchups["rows"][0]
    with engine.paths.matchup.open("r", encoding="utf-8-sig", newline="") as source:
        raw_sample = next(
            row for row in csv.DictReader(source)
            if row["bowler_id"] == matchup_sample["bowler_id"]
            and row["batter_id"] == matchup_sample["batter_id"]
        )
    sample_balls = int(raw_sample["balls"])
    sample_batter_runs = float(raw_sample["runs_scored_by_batter"])
    sample_bowler_runs = float(raw_sample["runs_conceded_by_bowler"])
    sample_wickets = int(raw_sample["wickets"])
    assert matchup_sample["batter_runs"] == sample_batter_runs
    assert matchup_sample["batter_strike_rate"] == round(sample_batter_runs * 100 / sample_balls, 2)
    assert matchup_sample["economy"] == round(sample_bowler_runs * 6 / sample_balls, 2)
    assert matchup_sample["bowling_strike_rate"] == round(sample_balls / sample_wickets, 2)

    zero_phase_pair = None
    zero_phase = None
    with engine.paths.matchup.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            for phase_key, phase_label in engine.phase_labels.items():
                if int(row.get(f"phase_balls_{phase_key}") or 0) == 0:
                    zero_phase_pair = row
                    zero_phase = phase_label
                    break
            if zero_phase_pair:
                break
    assert zero_phase_pair is not None and zero_phase is not None
    status, zero_denominator = _get(
        f"{base_url}/api/v1/dashboard/matchups?bowler_id={zero_phase_pair['bowler_id']}"
        f"&batter_id={zero_phase_pair['batter_id']}&phase={quote(zero_phase)}&min_balls=0"
    )
    assert status == 200
    assert zero_denominator["total"] == 1
    assert zero_denominator["rows"][0]["batter_strike_rate"] is None
    assert zero_denominator["rows"][0]["economy"] is None
    assert zero_denominator["rows"][0]["bowling_strike_rate"] is None

    status, wickets = _get(f"{base_url}/api/v1/dashboard/wickets?page=1&page_size=10")
    assert status == 200
    assert wickets["event_count"] == 53294
    assert len(wickets["events"]) == 10
    assert all(isinstance(row["is_bowler_credited"], bool) for row in wickets["events"])

    status, catalog = _get(f"{base_url}/api/v1/dashboard/datasets")
    assert status == 200
    assert catalog["count"] == 24
    excluded_artifacts = {
        "derived/bowler_dataset_validation_report.csv",
        "derived/career_validation_report.csv",
        "derived/phase_validation_report.csv",
        "raw/deliveries_sample.csv",
    }
    assert excluded_artifacts.isdisjoint(
        {item["id"] for item in catalog["datasets"]}
    )
    matches_dataset = next(
        item for item in catalog["datasets"] if item["file_name"] == "matches.csv"
    )

    status, page = _get(
        f"{base_url}/api/v1/dashboard/dataset?dataset={quote(matches_dataset['id'], safe='')}&page=1&page_size=10"
    )
    assert status == 200
    assert page["total"] == 4230
    assert len(page["rows"]) == 10
    assert page["profile"]["columns"]
    assert "match_id" in page["profile"]["columns"]

    for url in (
        f"{base_url}/api/v1/dashboard/matchups?page_size=9",
        f"{base_url}/api/v1/dashboard/dataset?dataset=unknown.csv",
    ):
        status, error = _get(url)
        assert status in {400, 404}
        assert error["error"]["code"] == "invalid_request"


def test_dashboard_response_cache_is_filter_keyed_and_bounded(running_api):
    _, engine = running_api
    server = create_server(engine, port=0, data_root=Path(r"C:\CRIC\data"))
    calls = []
    try:
        first_key = ("/api/v1/dashboard/overview", (("phase", "Death"),))
        first = server.cached_dashboard_response(first_key, lambda: calls.append("first") or {"count": 1})
        repeated = server.cached_dashboard_response(first_key, lambda: calls.append("duplicate") or {"count": 2})
        different = server.cached_dashboard_response(
            ("/api/v1/dashboard/overview", (("phase", "Powerplay"),)),
            lambda: calls.append("other-filter") or {"count": 3},
        )
        assert first is repeated
        assert first == {"count": 1}
        assert different == {"count": 3}
        assert calls == ["first", "other-filter"]
        for index in range(70):
            server.cached_dashboard_response(
                ("/api/v1/dashboard/dataset", (("page", str(index)),)),
                lambda index=index: {"page": index},
            )
        assert len(server.dashboard_cache) == 64
        assert first_key not in server.dashboard_cache
    finally:
        server.server_close()


def test_unsupported_http_methods_return_sanitized_405(running_api):
    base_url, _ = running_api
    for method in ("PUT", "PATCH", "DELETE", "OPTIONS"):
        request = urllib.request.Request(
            f"{base_url}/api/v1/recommendations",
            data=b"{}" if method != "OPTIONS" else None,
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            assert exc.code == 405
            body = exc.read().decode("utf-8")
        else:
            response.close()
            pytest.fail(f"{method} should not be supported")
        assert "Traceback" not in body
        assert "C:\\\\" not in body
        assert json.loads(body)["error"]["code"] == "method_not_allowed"


def test_api_returns_clear_validation_errors(running_api):
    base_url, engine = running_api
    status, payload = _post(f"{base_url}/api/v1/recommendations", b"{")
    assert status == 400
    assert payload["error"]["code"] == "invalid_json"
    status, payload = _post(f"{base_url}/api/v1/recommendations", b"null")
    assert status == 400
    assert payload["error"]["code"] == "invalid_request"
    status, payload = _post(
        f"{base_url}/api/v1/recommendations",
        b'{"batter_id":"not-a-player","candidates":[]}',
    )
    assert status == 404
    assert payload["error"]["code"] == "unknown_identifier"
    assert "not-a-player" not in json.dumps(payload)

    status, payload = _post(
        f"{base_url}/api/v1/recommendations",
        json.dumps(
            {
                "batter_id": next(iter(engine.players)),
                "candidates": [{"bowler_id": r"C:\Users\private\secret.txt"}],
            }
        ).encode(),
    )
    assert status == 404
    assert payload["error"]["code"] == "unknown_identifier"
    assert "secret.txt" not in json.dumps(payload)

    status, payload = _post(
        f"{base_url}/api/v1/recommendations",
        b'{"batter_id":"not-a-player","candidates":[{"bowler_id":"unknown"}]}',
    )
    assert status == 404
    assert "Traceback" not in json.dumps(payload)
    assert "C:\\\\" not in json.dumps(payload)

    status, payload = _post(
        f"{base_url}/api/v1/recommendations",
        b" " * (1024 * 1024 + 1),
    )
    assert status == 413
    assert payload["error"]["code"] == "request_too_large"


def test_api_marks_unknown_situation_unavailable_without_claiming_it_scored(running_api):
    base_url, engine = running_api
    batter_id = next(iter(engine.players))
    bowler_id = next(iter(engine.career))
    status, payload = _post(
        f"{base_url}/api/v1/recommendations",
        json.dumps(
            {
                "batter_id": batter_id,
                "situation": {"type": "unsupported", "value": "not-a-historical-value"},
                "candidates": [{"bowler_id": bowler_id}],
            }
        ).encode(),
    )
    assert status == 200
    recommendation = payload["recommendations"][0]
    assert recommendation["data_availability"]["situation"] == "no_situation_evidence"
    assert "situation" not in recommendation["metrics"]
    assert "situation" not in recommendation["score_components"]
    assert all("Situation component score" not in line for line in recommendation["evidence"])
    assert any(
        "No historical evidence for the requested situation" in warning
        for warning in recommendation["warnings"]
    )


def test_api_rejects_missing_and_malformed_fields_and_accepts_empty_candidates(running_api):
    base_url, engine = running_api
    batter_id = next(iter(engine.players))
    bowler_id = next(iter(engine.career))
    payloads = [
        json.dumps({"batter_id": batter_id}).encode(),
        json.dumps({"batter_id": 42, "candidates": []}).encode(),
        json.dumps(
            {
                "batter_id": batter_id,
                "candidates": [{"bowler_id": bowler_id, "available": "yes"}],
            }
        ).encode(),
        json.dumps(
            {
                "batter_id": batter_id,
                "situation": {"type": [], "value": "ipl"},
                "candidates": [],
            }
        ).encode(),
    ]
    for body in payloads:
        status, payload = _post(f"{base_url}/api/v1/recommendations", body)
        assert status == 400
        assert payload["error"]["code"] == "invalid_request"
        assert "Traceback" not in json.dumps(payload)
        assert "C:\\\\" not in json.dumps(payload)

    sensitive_value = r"C:\private\phase-secret.txt"
    status, payload = _post(
        f"{base_url}/api/v1/recommendations",
        json.dumps({"batter_id": batter_id, "phase": sensitive_value, "candidates": []}).encode(),
    )
    assert status == 400
    assert payload["error"]["code"] == "invalid_request"
    assert sensitive_value not in json.dumps(payload)

    status, payload = _post(
        f"{base_url}/api/v1/recommendations",
        json.dumps({"batter_id": batter_id, "candidates": []}).encode(),
    )
    assert status == 200
    assert payload["recommendations"] == []
    assert payload["warnings"]


def test_api_rejects_non_loopback_bind():
    with pytest.raises(ValueError, match="127.0.0.1"):
        create_server(None, host="0.0.0.0")
    with pytest.raises(ValueError, match="127.0.0.1"):
        create_server(None, host="::1")
    with pytest.raises(ValueError, match="127.0.0.1"):
        create_server(None, host="localhost")


def test_api_does_not_allow_a_second_server_to_share_the_port(running_api):
    base_url, engine = running_api
    port = int(base_url.rsplit(":", 1)[1])
    with pytest.raises(OSError):
        create_server(engine, port=port)


def test_unexpected_api_errors_are_sanitized(running_api, caplog):
    base_url, engine = running_api
    original = engine.recommend

    def fail(_request):
        raise RuntimeError(r"C:\private\local-secret.txt token=not-for-response")

    engine.recommend = fail
    try:
        caplog.set_level(logging.ERROR, logger="cric.recommendation_api")
        status, payload = _post(
            f"{base_url}/api/v1/recommendations",
            b'{"batter_id":"valid","candidates":[]}',
        )
    finally:
        engine.recommend = original
    assert status == 500
    assert payload == {
        "error": {"code": "internal_error", "message": "Recommendation request failed"}
    }
    assert "local-secret" not in json.dumps(payload)
    assert "token=" not in json.dumps(payload)
    assert "RuntimeError" in caplog.text
    assert "local-secret" not in caplog.text
    assert "token=" not in caplog.text
