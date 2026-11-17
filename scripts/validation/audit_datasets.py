"""
CRIC Dataset Inventory & Technical Audit Script
Audits every dataset under data/ to report filename, tier, size, row count, column count, and ingestion usage.
"""

from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

CANONICAL_INGESTION_DATASETS = {
    "deliveries.csv": "Core ball-by-ball fact table (fact_delivery)",
    "matches.csv": "Match metadata dimension table (dim_match)",
    "combined_data.csv": "Player biographical & bowling profile dimension (dim_player)",
    "players.csv": "Player ID & name mapping fallback for dim_player",
    "wicket_events.csv": "Dismissal events fact table (fact_wicket)",
    "wickets.csv": "Raw dismissal events fallback for fact_wicket",
    "bowler_batter_matchup_stats_v2.csv": "Pre-aggregated head-to-head matchup statistics (fact_matchup)",
    "bowler_situation_stats_v2.csv": "Pre-aggregated match situation bowling splits (fact_bowler_situation)"
}


def audit_datasets():
    results = []
    for f in sorted(DATA_DIR.rglob("*.csv")):
        size_mb = f.stat().st_size / (1024 * 1024)
        tier = f.parent.name
        try:
            df = pd.read_csv(f, nrows=2)
            col_count = len(df.columns)
            col_names = df.columns.tolist()
            with open(f, "r", encoding="utf-8-sig", errors="ignore") as fp:
                row_count = sum(1 for _ in fp) - 1
        except Exception as exc:
            col_count = 0
            col_names = []
            row_count = 0

        is_ingestion = f.name in CANONICAL_INGESTION_DATASETS
        purpose = CANONICAL_INGESTION_DATASETS.get(f.name, f"{tier.capitalize()} analytics dataset / pipeline output")

        results.append({
            "filename": f.name,
            "tier": tier,
            "size_mb": round(size_mb, 2),
            "rows": row_count,
            "cols": col_count,
            "used_by_ingestion": is_ingestion,
            "purpose": purpose,
        })

    print(f"{'Filename':<38} | {'Tier':<10} | {'Size MB':<8} | {'Rows':<8} | {'Cols':<5} | {'Ingestion':<9} | Purpose")
    print("-" * 115)
    for r in results:
        ing_str = "YES" if r['used_by_ingestion'] else "no"
        print(f"{r['filename']:<38} | {r['tier']:<10} | {r['size_mb']:<8.2f} | {r['rows']:<8} | {r['cols']:<5} | {ing_str:<9} | {r['purpose']}")

    return results


if __name__ == "__main__":
    audit_datasets()
