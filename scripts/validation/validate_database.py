"""
CRIC Analytics - PostgreSQL Data & Schema Validation Suite
Verifies source-to-database parity, referential integrity, and analytical view metrics.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database.connection import DatabaseConnection, get_config_from_env
from backend.database.repository import CricketRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("cric.db_validation")


def run_validation(repo: CricketRepository) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "parity_checks": {},
        "referential_integrity": {},
        "view_smoke_tests": {},
        "ingestion_manifest_status": {},
        "all_passed": True,
    }

    if not repo.db.ping():
        logger.error(
            "Database connection failed: PostgreSQL server at %s:%d is unreachable or service is stopped.",
            repo.db.config.host,
            repo.db.config.port
        )
        logger.info("To start the PostgreSQL service on Windows, open an Administrator prompt and run:")
        logger.info("    net start postgresql-x64-18")
        report["connection_status"] = "OFFLINE"
        report["all_passed"] = False
        return report

    # 1. Expected row counts based on verified CSV datasets
    expected_counts = {
        "cricket_fact.fact_delivery": 966985,
        "cricket_dim.dim_match": 4230,
        "cricket_dim.dim_player": 5261,
        "cricket_fact.fact_wicket": 53294,
        "cricket_fact.fact_matchup": 131294,
        "cricket_fact.fact_bowler_situation": 101163,
        "cricket_dim.dim_dismissal": 14,
    }

    logger.info("Executing row count parity checks...")
    actual_counts = repo.get_table_counts()

    for table, expected in expected_counts.items():
        actual = actual_counts.get(table.rsplit(".", 1)[-1], 0)
        passed = (actual == expected)
        report["parity_checks"][table] = {
            "expected": expected,
            "actual": actual,
            "diff": actual - expected,
            "status": "PASS" if passed else "FAIL",
        }
        if not passed:
            report["all_passed"] = False
            logger.warning("Parity check failed for %s: expected %d, got %d", table, expected, actual)
        else:
            logger.info("Parity check passed for %s: %d rows", table, actual)

    # 2. Referential integrity checks
    logger.info("Executing referential integrity checks...")
    orphan_queries = {
        "orphan_deliveries_match": """
            SELECT COUNT(*) FROM cricket_fact.fact_delivery d
            LEFT JOIN cricket_dim.dim_match m ON d.match_id = m.match_id
            WHERE m.match_id IS NULL;
        """,
        "orphan_deliveries_bowler": """
            SELECT COUNT(*) FROM cricket_fact.fact_delivery d
            LEFT JOIN cricket_dim.dim_player p ON d.bowler_id = p.player_id
            WHERE d.bowler_id IS NOT NULL AND p.player_id IS NULL;
        """,
        "orphan_deliveries_batter": """
            SELECT COUNT(*) FROM cricket_fact.fact_delivery d
            LEFT JOIN cricket_dim.dim_player p ON d.batter_id = p.player_id
            WHERE d.batter_id IS NOT NULL AND p.player_id IS NULL;
        """,
        "invalid_dismissal_kinds": """
            SELECT COUNT(*) FROM cricket_fact.fact_wicket w
            LEFT JOIN cricket_dim.dim_dismissal dis ON w.kind = dis.dismissal_kind
            WHERE dis.dismissal_kind IS NULL;
        """,
        "orphan_matchup_entities": """
            SELECT COUNT(*) FROM cricket_fact.fact_matchup m
            WHERE NOT EXISTS (SELECT 1 FROM cricket_dim.dim_player p WHERE p.player_id = m.bowler_id)
               OR NOT EXISTS (SELECT 1 FROM cricket_dim.dim_player p WHERE p.player_id = m.batter_id);
        """
    }

    for name, sql in orphan_queries.items():
        try:
            res = repo.db.execute_query(sql)
            count = res[0][0] if res else 0
            passed = (count == 0)
            report["referential_integrity"][name] = {
                "orphan_count": count,
                "status": "PASS" if passed else "FAIL",
            }
            if not passed:
                report["all_passed"] = False
                logger.error("Referential integrity failed for %s: %d orphans found", name, count)
            else:
                logger.info("Referential integrity passed for %s (0 orphans)", name)
        except Exception as e:
            logger.error("Error running %s: %s", name, e)
            report["referential_integrity"][name] = {"error": str(e), "status": "ERROR"}
            report["all_passed"] = False

    # 3. Analytical Views Smoke Tests
    logger.info("Executing view smoke tests...")
    views = [
        ("v_bowler_career_performance", "SELECT COUNT(*) FROM cricket_analytics.v_bowler_career_performance;"),
        ("v_bowler_phase_performance", "SELECT COUNT(*) FROM cricket_analytics.v_bowler_phase_performance;"),
        ("v_bowler_batter_matchups", "SELECT COUNT(*) FROM cricket_analytics.v_bowler_batter_matchups;"),
        ("v_bowler_situation_performance", "SELECT COUNT(*) FROM cricket_analytics.v_bowler_situation_performance;"),
        ("v_wicket_profiles", "SELECT COUNT(*) FROM cricket_analytics.v_wicket_profiles;"),
        ("v_season_bowling_performance", "SELECT COUNT(*) FROM cricket_analytics.v_season_bowling_performance;"),
        ("v_batter_career_performance", "SELECT COUNT(*) FROM cricket_analytics.v_batter_career_performance;"),
    ]

    for view_name, sql in views:
        try:
            res = repo.db.execute_query(sql)
            rows = res[0][0] if res else 0
            report["view_smoke_tests"][view_name] = {"row_count": rows, "status": "PASS"}
            logger.info("View %s queried successfully: %d rows", view_name, rows)
        except Exception as e:
            logger.error("Failed querying view %s: %s", view_name, e)
            report["view_smoke_tests"][view_name] = {"error": str(e), "status": "ERROR"}
            report["all_passed"] = False

    # 4. Check Ingestion Manifest Runs
    try:
        manifest_sql = """
            SELECT target_table, source_row_count, inserted_row_count, rejected_row_count, status
            FROM cricket_raw.ingestion_file_manifest
            ORDER BY created_at DESC LIMIT 10;
        """
        rows = repo.db.execute_query(manifest_sql)
        report["ingestion_manifest_status"]["recent_loads"] = [
            {"table": r[0], "source": r[1], "inserted": r[2], "rejected": r[3], "status": r[4]}
            for r in rows
        ]
    except Exception as e:
        logger.warning("Could not query ingestion manifest: %s", e)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate CRIC PostgreSQL database state.")
    parser.add_argument("--json-out", type=Path, default=None, help="Path to write JSON validation results")
    args = parser.parse_args()

    db = DatabaseConnection(get_config_from_env())
    repo = CricketRepository(db)
    results = run_validation(repo)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        logger.info("Wrote report to %s", args.json_out)

    if not results["all_passed"]:
        sys.exit(1)
    logger.info("All database validation checks passed.")
