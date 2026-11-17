"""
CRIC Analytics - Safe Database Initialization Script
Safely creates the cric_analytics PostgreSQL database if it does not exist,
applies the base schema migrations, and seeds static dimensional entities.
Never drops or truncates existing databases or data.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database.connection import DatabaseConfig
from config.config_loader import load_db_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("cric.init_db")


def check_and_create_database(
    admin_cfg: DatabaseConfig,
    target_dbname: str = "cric_analytics"
) -> bool:
    """
    Connects to the PostgreSQL admin database (default 'postgres'),
    verifies if target_dbname exists, and creates it only if absent.
    Returns True if created or already existed.
    """
    try:
        import psycopg
    except ImportError as exc:
        logger.error(
            "psycopg (psycopg 3) is required. Install via: pip install 'psycopg[binary]>=3.1.18'"
        )
        raise exc

    # Connect to admin database with autocommit enabled (CREATE DATABASE cannot run inside a transaction)
    admin_conninfo = (
        f"host={admin_cfg.host} port={admin_cfg.port} dbname={admin_cfg.database} "
        f"user={admin_cfg.user}"
    )
    if admin_cfg.password:
        admin_conninfo += f" password={admin_cfg.password}"

    logger.info("Connecting to administrative database '%s' at %s:%d...", admin_cfg.database, admin_cfg.host, admin_cfg.port)
    with psycopg.connect(admin_conninfo, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_dbname,))
            exists = cur.fetchone() is not None

            if exists:
                logger.info("Database '%s' already exists. Skipping database creation.", target_dbname)
            else:
                logger.info("Database '%s' does not exist. Creating database...", target_dbname)
                # Safely quote identifier
                cur.execute(psycopg.sql.SQL("CREATE DATABASE {} WITH ENCODING 'UTF8'").format(
                    psycopg.sql.Identifier(target_dbname)
                ))
                logger.info("Database '%s' created successfully.", target_dbname)
    return True


def apply_migrations(target_cfg: DatabaseConfig) -> None:
    """Connects to the target database and executes schema migrations and static seeds."""
    try:
        import psycopg
    except ImportError as exc:
        raise exc

    migration_file = PROJECT_ROOT / "database" / "migrations" / "001_initial_schema.sql"
    if not migration_file.exists():
        raise FileNotFoundError(f"Migration file not found at {migration_file}")

    logger.info("Connecting to database '%s' to apply initial migrations...", target_cfg.database)
    conninfo = f"host={target_cfg.host} port={target_cfg.port} dbname={target_cfg.database} user={target_cfg.user}"
    if target_cfg.password:
        conninfo += f" password={target_cfg.password}"

    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            logger.info("Applying %s...", migration_file.name)
            with open(migration_file, "r", encoding="utf-8") as f:
                cur.execute(f.read())
        conn.commit()
    logger.info("Schema migrations and seeds applied successfully.")


def initialize_cric_database(
    host: Optional[str] = None,
    port: Optional[int] = None,
    dbname: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    admin_db: str = "postgres"
) -> None:
    env_cfg = load_db_config()
    db_host = host or env_cfg["host"]
    db_port = port or env_cfg["port"]
    target_dbname = dbname or env_cfg["dbname"]
    db_user = user or env_cfg["user"]
    db_pass = password if password is not None else env_cfg["password"]

    admin_cfg = DatabaseConfig(
        host=db_host,
        port=db_port,
        database=admin_db,
        user=db_user,
        password=db_pass
    )

    target_cfg = DatabaseConfig(
        host=db_host,
        port=db_port,
        database=target_dbname,
        user=db_user,
        password=db_pass
    )

    logger.info("=== CRIC PostgreSQL Database Initialization ===")
    check_and_create_database(admin_cfg, target_dbname=target_dbname)
    apply_migrations(target_cfg)
    logger.info("Initialization complete. Database '%s' is ready for ingestion.", target_dbname)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Safely initialize the CRIC PostgreSQL database.")
    parser.add_argument("--host", help="PostgreSQL host (default from env or localhost)")
    parser.add_argument("--port", type=int, help="PostgreSQL port (default 5432)")
    parser.add_argument("--dbname", default="cric_analytics", help="Target database name (default cric_analytics)")
    parser.add_argument("--user", help="PostgreSQL user (default postgres)")
    parser.add_argument("--password", help="PostgreSQL password")
    parser.add_argument("--admin-db", default="postgres", help="Administrative database for initial connection (default postgres)")
    args = parser.parse_args()

    initialize_cric_database(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
        admin_db=args.admin_db
    )
