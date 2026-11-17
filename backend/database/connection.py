"""
PostgreSQL Database Connection and Management Module for CRIC.
Uses psycopg 3 with environment-based configuration, transaction management, and connection pooling.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator, Iterator, Sequence

LOGGER = logging.getLogger("cric.database")

# Default connection parameters (can be overridden via environment variables or .env)
DEFAULT_HOST = os.getenv("PGHOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("PGPORT", "5432"))
DEFAULT_DATABASE = os.getenv("PGDATABASE", "cric_analytics")
DEFAULT_USER = os.getenv("PGUSER", "postgres")
DEFAULT_PASSWORD = os.getenv("PGPASSWORD", "")


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    database: str = DEFAULT_DATABASE
    user: str = DEFAULT_USER
    password: str = DEFAULT_PASSWORD

    @property
    def conninfo(self) -> str:
        parts = [
            f"host={self.host}",
            f"port={self.port}",
            f"dbname={self.database}",
            f"user={self.user}",
        ]
        if self.password:
            parts.append(f"password={self.password}")
        return " ".join(parts)


def get_config_from_env() -> DatabaseConfig:
    return DatabaseConfig(
        host=os.getenv("CRIC_DB_HOST", os.getenv("PGHOST", DEFAULT_HOST)),
        port=int(os.getenv("CRIC_DB_PORT", os.getenv("PGPORT", str(DEFAULT_PORT)))),
        database=os.getenv("CRIC_DB_NAME", os.getenv("PGDATABASE", DEFAULT_DATABASE)),
        user=os.getenv("CRIC_DB_USER", os.getenv("PGUSER", DEFAULT_USER)),
        password=os.getenv("CRIC_DB_PASSWORD", os.getenv("PGPASSWORD", DEFAULT_PASSWORD)),
    )


class DatabaseConnection:
    """Manages connections to the PostgreSQL cric_analytics warehouse."""

    def __init__(self, config: DatabaseConfig | None = None):
        self.config = config or get_config_from_env()

    def ping(self) -> bool:
        """Tests whether the database is reachable. Returns False instead of raising on connection error."""
        try:
            with self.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    return cur.fetchone() == (1,)
        except Exception:
            return False

    @contextmanager
    def connect(self) -> Generator[Any, None, None]:
        """Provides a managed psycopg connection with automatic commit/rollback."""
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "The 'psycopg' (psycopg 3) library is required to connect to PostgreSQL. "
                "Install it using: pip install 'psycopg[binary]>=3.1.18'"
            ) from exc

        conn = psycopg.connect(self.config.conninfo)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def cursor(self) -> Generator[Any, None, None]:
        """Provides a managed psycopg cursor within a connection."""
        with self.connect() as conn:
            with conn.cursor() as cur:
                yield cur

    def execute_query(self, query: str, params: Sequence[Any] | None = None) -> list[tuple]:
        """Executes a read-only query and returns all rows."""
        with self.cursor() as cur:
            cur.execute(query, params or ())
            return cur.fetchall()

    def execute_statement(self, sql: str, params: Sequence[Any] | None = None) -> int:
        """Executes a DDL or DML statement and returns rowcount."""
        with self.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.rowcount

    def execute_script(self, script_path: Path) -> None:
        """Executes a multi-statement SQL script file."""
        if not script_path.exists():
            raise FileNotFoundError(f"SQL script not found: {script_path}")
        sql_content = script_path.read_text(encoding="utf-8")
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_content)
        LOGGER.info("Executed script: %s", script_path.name)
