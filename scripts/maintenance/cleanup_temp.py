"""
CRIC Analytics - Maintenance: Temporary and Cache Cleanup
Cleans temporary artifacts, test caches, and orphaned logs without touching data assets.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("cric.cleanup")

TARGET_PATTERNS = [
    "**/__pycache__",
    "**/.pytest_cache",
    "**/*.pyc",
    "**/*.pyo",
    "**/*.tmp",
]


def clean_project(dry_run: bool = False) -> None:
    logger.info("Scanning for cleanup targets in %s (dry_run=%s)...", PROJECT_ROOT, dry_run)
    cleaned_count = 0

    # Clean __pycache__ directories
    for p in PROJECT_ROOT.rglob("__pycache__"):
        if "archive" in p.parts:
            continue
        logger.info("Found pycache directory: %s", p.relative_to(PROJECT_ROOT))
        if not dry_run:
            shutil.rmtree(p, ignore_errors=True)
        cleaned_count += 1

    # Clean .pytest_cache
    pytest_cache = PROJECT_ROOT / ".pytest_cache"
    if pytest_cache.exists():
        logger.info("Found .pytest_cache directory")
        if not dry_run:
            shutil.rmtree(pytest_cache, ignore_errors=True)
        cleaned_count += 1

    logger.info("Cleanup completed. %d directories/files addressed.", cleaned_count)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Clean CRIC temporary and cache files.")
    parser.add_argument("--dry-run", action="store_true", help="List files without deleting")
    args = parser.parse_args()
    clean_project(args.dry_run)
