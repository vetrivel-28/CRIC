"""
CRIC Analytics - Configuration Loader
Safely loads database and application settings from environment variables
or an optional local configuration file (without committing credentials).
"""

from __future__ import annotations

import os
import configparser
from pathlib import Path
from typing import Dict, Any


def load_db_config(config_path: Path | str | None = None) -> Dict[str, Any]:
    """
    Load PostgreSQL configuration dictionary.
    Priority:
    1. Environment variables (CRIC_DB_HOST, CRIC_DB_PORT, CRIC_DB_NAME, CRIC_DB_USER, CRIC_DB_PASSWORD)
    2. Local ini file if present (e.g. config/database.ini or .env)
    3. Safe development defaults
    """
    config: Dict[str, Any] = {
        "host": os.getenv("CRIC_DB_HOST", "localhost"),
        "port": int(os.getenv("CRIC_DB_PORT", "5432")),
        "dbname": os.getenv("CRIC_DB_NAME", "cric_analytics"),
        "user": os.getenv("CRIC_DB_USER", "postgres"),
        "password": os.getenv("CRIC_DB_PASSWORD", ""),
        "sslmode": os.getenv("CRIC_DB_SSLMODE", "prefer"),
    }

    if config_path is None:
        default_ini = Path(__file__).resolve().parent / "database.ini"
        if default_ini.exists():
            config_path = default_ini

    if config_path and Path(config_path).exists():
        parser = configparser.ConfigParser()
        parser.read(config_path)
        if "postgresql" in parser:
            sec = parser["postgresql"]
            if not os.getenv("CRIC_DB_HOST") and "host" in sec:
                config["host"] = sec["host"]
            if not os.getenv("CRIC_DB_PORT") and "port" in sec:
                config["port"] = int(sec["port"])
            if not os.getenv("CRIC_DB_NAME") and "dbname" in sec:
                config["dbname"] = sec["dbname"]
            if not os.getenv("CRIC_DB_USER") and "user" in sec:
                config["user"] = sec["user"]
            if not os.getenv("CRIC_DB_PASSWORD") and "password" in sec:
                config["password"] = sec["password"]
            if not os.getenv("CRIC_DB_SSLMODE") and "sslmode" in sec:
                config["sslmode"] = sec["sslmode"]

    return config
