"""
CRIC Analytics - Maintenance: Data Asset Backup & Manifest Generator
Creates timestamped checksum manifests and compressed archives of raw and derived data.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
MANIFEST_DIR = DATA_DIR / "manifests"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("cric.backup")


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_backup_manifest() -> Path:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = MANIFEST_DIR / f"data_manifest_{timestamp}.csv"

    rows = []
    for sub in ["raw", "derived", "processed"]:
        folder = DATA_DIR / sub
        if not folder.exists():
            continue
        for f in folder.glob("*.csv"):
            size = f.stat().st_size
            sha = compute_sha256(f)
            rows.append({
                "subfolder": sub,
                "filename": f.name,
                "size_bytes": size,
                "sha256": sha,
                "generated_at": timestamp,
            })

    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["subfolder", "filename", "size_bytes", "sha256", "generated_at"])
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Generated backup manifest with %d files: %s", len(rows), manifest_path.name)
    return manifest_path


if __name__ == "__main__":
    generate_backup_manifest()
