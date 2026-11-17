"""
CRIC Analytics - Safe Database Initialization Entrypoint (Alias)
Delegates to scripts.maintenance.init_database.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.maintenance.init_database import initialize_cric_database

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Safely initialize the CRIC PostgreSQL database.")
    parser.add_argument("--host", help="PostgreSQL host")
    parser.add_argument("--port", type=int, help="PostgreSQL port")
    parser.add_argument("--dbname", default="cric_analytics", help="Target database name")
    parser.add_argument("--user", help="PostgreSQL user")
    parser.add_argument("--password", help="PostgreSQL password")
    parser.add_argument("--admin-db", default="postgres", help="Administrative database")
    args = parser.parse_args()

    initialize_cric_database(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
        admin_db=args.admin_db
    )
