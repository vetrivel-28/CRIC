"""Loopback-only HTTP API for local bowler recommendations."""

from __future__ import annotations

import argparse
import json
import logging
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from backend.dashboard_data import DashboardData, DashboardDataError, DashboardRequestError
from backend.database.connection import DatabaseConnection, get_config_from_env
from backend.database.repository import CricketRepository
from backend.postgres_dashboard_data import PostgresDashboardData
from backend.recommendation_engine import (
    DatasetError,
    InvalidRequest,
    RecommendationEngine,
    UnknownIdentifier,
)

LOGGER = logging.getLogger("cric.recommendation_api")
MAX_REQUEST_BYTES = 1024 * 1024
DASHBOARD_CACHE_ENTRIES = 64
FRONTEND_ROOT = Path(__file__).resolve().parent.parent / "frontend"
STATIC_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


class RecommendationHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        address: tuple[str, int],
        engine: RecommendationEngine,
        dashboard_data: DashboardData | PostgresDashboardData | None = None,
    ):
        self.engine = engine
        self.dashboard_data = dashboard_data
        self.dashboard_cache: OrderedDict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]] = OrderedDict()
        self.dashboard_cache_lock = threading.Lock()
        super().__init__(address, RecommendationRequestHandler)

    def cached_dashboard_response(
        self,
        key: tuple[str, tuple[tuple[str, str], ...]],
        load: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        with self.dashboard_cache_lock:
            cached = self.dashboard_cache.get(key)
            if cached is not None:
                self.dashboard_cache.move_to_end(key)
                return cached
        response = load()
        with self.dashboard_cache_lock:
            self.dashboard_cache[key] = response
            self.dashboard_cache.move_to_end(key)
            while len(self.dashboard_cache) > DASHBOARD_CACHE_ENTRIES:
                self.dashboard_cache.popitem(last=False)
        return response


class RecommendationRequestHandler(BaseHTTPRequestHandler):
    server: RecommendationHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, code: str, message: str) -> None:
        LOGGER.warning("Recommendation request rejected (%s)", code)
        self._send_json(status, {"error": {"code": code, "message": message}})

    def do_GET(self) -> None:
        request_path = urlsplit(self.path).path
        if request_path in STATIC_ASSETS:
            filename, content_type = STATIC_ASSETS[request_path]
            try:
                body = (FRONTEND_ROOT / filename).read_bytes()
            except OSError:
                LOGGER.error("Frontend asset unavailable (%s)", filename)
                self._send_error(500, "frontend_unavailable", "The local frontend is unavailable")
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            return
        if request_path == "/api/v1/options":
            engine = self.server.engine
            situations: dict[str, set[str]] = {}
            for _, situation_type, situation_value in engine.situations:
                situations.setdefault(situation_type, set()).add(situation_value)
            self._send_json(
                200,
                {
                    "phases": sorted(engine.phase_labels.values()),
                    "batters": [
                        {"id": player_id, "name": name}
                        for player_id, name in sorted(
                            engine.players.items(), key=lambda item: (item[1].casefold(), item[0])
                        )
                    ],
                    "bowlers": [
                        {"id": bowler_id, "name": record.name}
                        for bowler_id, record in sorted(
                            engine.career.items(), key=lambda item: (item[1].name.casefold(), item[0])
                        )
                    ],
                    "situations": [
                        {"type": situation_type, "values": sorted(values)}
                        for situation_type, values in sorted(situations.items())
                    ],
                },
            )
            return
        if request_path.startswith("/api/v1/dashboard/"):
            dashboard = self.server.dashboard_data
            if dashboard is None:
                self._send_json(
                    503,
                    {"error": {"code": "dashboard_unavailable", "message": "Dashboard data is not configured for this service."}},
                )
                return
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            values = {key: items[-1] for key, items in query.items() if items}
            try:
                cache_key = (request_path, tuple(sorted(values.items())))
                response = self.server.cached_dashboard_response(
                    cache_key,
                    lambda: self._load_dashboard_response(dashboard, request_path, values),
                )
            except DashboardRequestError as exc:
                self._send_json(exc.status, {"error": {"code": "invalid_request", "message": str(exc)}})
                return
            except DashboardDataError as exc:
                LOGGER.error("Dashboard dataset request failed (%s)", type(exc).__name__)
                self._send_json(
                    503,
                    {"error": {"code": "dashboard_data_unavailable", "message": str(exc)}},
                )
                return
            except Exception as exc:
                LOGGER.error("Dashboard request failed (%s)", type(exc).__name__)
                self._send_json(
                    500,
                    {"error": {"code": "dashboard_internal_error", "message": "Dashboard request failed."}},
                )
                return
            self._send_json(200, response)
            return
        if request_path != "/health":
            self._send_error(404, "not_found", "Endpoint not found")
            return
        self._send_json(
            200 if self.server.engine.ready else 503,
            {
                "status": "ok" if self.server.engine.ready else "not_ready",
                "execution_mode": "local_python",
            },
        )

    @staticmethod
    def _load_dashboard_response(
        dashboard: DashboardData | PostgresDashboardData,
        request_path: str,
        values: dict[str, str],
    ) -> dict[str, Any]:
        if request_path == "/api/v1/dashboard/options":
            return dashboard.filter_options()
        if request_path == "/api/v1/dashboard/overview":
            return dashboard.overview(
                values.get("phase"), values.get("season"), values.get("min_balls")
            )
        if request_path == "/api/v1/dashboard/bowler":
            return dashboard.bowler(
                values.get("bowler_id"),
                values.get("phase"),
                values.get("season"),
                values.get("min_balls"),
            )
        if request_path == "/api/v1/dashboard/batters":
            if not isinstance(dashboard, PostgresDashboardData):
                raise DashboardRequestError(
                    "Batter career intelligence requires the PostgreSQL analytics view.", 503
                )
            return dashboard.batters(values.get("batter_id"), values.get("season"), values.get("search"))
        if request_path == "/api/v1/dashboard/situations":
            return dashboard.situations(
                values.get("bowler_id"),
                values.get("situation_type"),
                values.get("situation_value"),
                values.get("season"),
                values.get("search"),
            )
        if request_path == "/api/v1/dashboard/matchups":
            return dashboard.matchups(
                values.get("bowler_id"),
                values.get("batter_id"),
                values.get("phase"),
                values.get("season"),
                values.get("min_balls"),
                values.get("search"),
                values.get("page"),
                values.get("page_size"),
                values.get("sort"),
                values.get("order"),
            )
        if request_path == "/api/v1/dashboard/wickets":
            return dashboard.wickets(
                values.get("phase"),
                values.get("season"),
                values.get("dismissal_type"),
                values.get("min_wickets"),
                values.get("search"),
                values.get("page"),
                values.get("page_size"),
                values.get("sort"),
                values.get("order"),
                values.get("bowler_id"),
            )
        if request_path == "/api/v1/dashboard/datasets":
            return dashboard.datasets()
        if request_path == "/api/v1/dashboard/dataset":
            return dashboard.dataset_page(
                values.get("dataset", ""),
                values.get("page"),
                values.get("page_size"),
                values.get("search"),
                values.get("sort"),
                values.get("order"),
            )
        raise DashboardRequestError("Endpoint not found", 404)

    def do_POST(self) -> None:
        if self.path != "/api/v1/recommendations":
            self._send_error(404, "not_found", "Endpoint not found")
            return
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            self._send_error(400, "invalid_request", "A valid Content-Length is required")
            return
        if length > MAX_REQUEST_BYTES:
            self.close_connection = True
            if length <= MAX_REQUEST_BYTES * 2:
                # Drain modest oversized bodies so unread bytes do not reset the 413 response.
                original_timeout = self.connection.gettimeout()
                try:
                    self.connection.settimeout(1.0)
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                except (TimeoutError, ConnectionError):
                    pass
                finally:
                    self.connection.settimeout(original_timeout)
            self._send_error(413, "request_too_large", "Request body exceeds 1 MiB")
            return
        try:
            body = self.rfile.read(length)
            request = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            self._send_error(400, "invalid_json", "Request body must be valid UTF-8 JSON")
            return
        try:
            response = self.server.engine.recommend(request)
        except InvalidRequest as exc:
            self._send_error(400, "invalid_request", str(exc))
            return
        except UnknownIdentifier:
            self._send_error(
                404,
                "unknown_identifier",
                "One or more identifiers are not present in the loaded data",
            )
            return
        except Exception as exc:
            LOGGER.error("Recommendation request failed (%s)", type(exc).__name__)
            self._send_json(500, {"error": {"code": "internal_error", "message": "Recommendation request failed"}})
            return
        self._send_json(200, response)

    def _method_not_allowed(self) -> None:
        self._send_error(405, "method_not_allowed", "This HTTP method is not supported")

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()


def create_server(
    engine: RecommendationEngine,
    host: str = "127.0.0.1",
    port: int = 8765,
    data_root: Path | None = None,
) -> RecommendationHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("The recommendation API must bind to 127.0.0.1")
    dashboard = DashboardData(engine, data_root) if data_root is not None else None
    return RecommendationHTTPServer((host, port), engine, dashboard)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local CRIC recommendation API")
    parser.add_argument(
        "--source",
        choices=("postgres", "csv"),
        default="postgres",
        help="Analytics source; PostgreSQL is the application default, CSV is an explicit offline mode",
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.source == "postgres":
        repository = CricketRepository(DatabaseConnection(get_config_from_env()))
        if not repository.db.ping():
            parser.error(
                "PostgreSQL connection failed. Configure CRIC_DB_* or PG* environment variables; "
                "the service does not silently fall back to CSV."
            )
        try:
            source_records = RecommendationEngine.load_repository_records(repository)
            engine = RecommendationEngine(None, records=source_records)
            dashboard = PostgresDashboardData(repository, engine, source_records)
        except DatasetError as exc:
            parser.error(str(exc))
        server = RecommendationHTTPServer(("127.0.0.1", args.port), engine, dashboard)
    else:
        try:
            engine = RecommendationEngine.from_data_root(args.data_root)
        except DatasetError as exc:
            parser.error(str(exc))
        server = create_server(engine, port=args.port, data_root=args.data_root)
    LOGGER.info("Local recommendation API listening on http://127.0.0.1:%d", args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
