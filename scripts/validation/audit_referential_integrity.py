"""
CRIC Referential Integrity & Data Quality Pre-Ingestion Audit
Audits all player IDs, match IDs, wicket event IDs, and dismissal kinds across raw and derived datasets.
"""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
DERIVED_DIR = PROJECT_ROOT / "data" / "derived"


def run_audit():
    print("=== CRIC REFERENTIAL INTEGRITY AUDIT ===")

    # 1. Matches
    matches_df = pd.read_csv(RAW_DIR / "matches.csv", dtype=str)
    match_ids = set(matches_df["match_id"].dropna().str.strip())
    print(f"Total matches in matches.csv: {len(match_ids)} (rows: {len(matches_df)})")

    # 2. Players
    players_df = pd.read_csv(RAW_DIR / "players.csv", dtype=str)
    players_set = set(players_df["player_id"].dropna().str.strip())
    print(f"Total players in players.csv: {len(players_set)} (rows: {len(players_df)})")

    combined_df = pd.read_csv(RAW_DIR / "combined_data.csv", dtype=str)
    combined_set = set(combined_df["player_id"].dropna().str.strip())
    print(f"Total players in combined_data.csv: {len(combined_set)} (rows: {len(combined_df)})")

    # Union of all known players in dimension sources
    dim_player_pool = players_set | combined_set
    print(f"Union of player IDs in players.csv | combined_data.csv: {len(dim_player_pool)}")

    # 3. Deliveries
    print("\nAuditing deliveries.csv (966,985 records)...")
    deliv_cols = ["match_id", "batter_id", "non_striker_id", "bowler_id", "batter_name", "non_striker_name", "bowler_name", "over_number", "ball_in_over", "innings_number"]
    deliv_df = pd.read_csv(RAW_DIR / "deliveries.csv", usecols=deliv_cols, dtype=str)
    print(f"Total deliveries read: {len(deliv_df)}")

    deliv_match_ids = set(deliv_df["match_id"].dropna().str.strip())
    missing_deliv_matches = deliv_match_ids - match_ids
    print(f"Unique match_ids in deliveries: {len(deliv_match_ids)}")
    print(f"Deliveries with match_id NOT in matches.csv: {len(missing_deliv_matches)}")

    deliv_batters = set(deliv_df["batter_id"].dropna().str.strip())
    missing_batters = deliv_batters - dim_player_pool
    print(f"Unique batters in deliveries: {len(deliv_batters)}, Missing in dim_player_pool: {len(missing_batters)}")

    deliv_non_strikers = set(deliv_df["non_striker_id"].dropna().str.strip())
    missing_non_strikers = deliv_non_strikers - dim_player_pool
    print(f"Unique non-strikers in deliveries: {len(deliv_non_strikers)}, Missing in dim_player_pool: {len(missing_non_strikers)}")

    deliv_bowlers = set(deliv_df["bowler_id"].dropna().str.strip())
    missing_bowlers = deliv_bowlers - dim_player_pool
    print(f"Unique bowlers in deliveries: {len(deliv_bowlers)}, Missing in dim_player_pool: {len(missing_bowlers)}")

    # Total missing players in deliveries
    total_missing_in_deliv = missing_batters | missing_non_strikers | missing_bowlers
    print(f"Total unique player IDs appearing in deliveries but NOT in player dimensions: {len(total_missing_in_deliv)}")
    if total_missing_in_deliv:
        print(f"Sample missing player IDs in deliveries: {list(total_missing_in_deliv)[:10]}")

    # Check composite delivery key uniqueness: (match_id, innings_number, over_number, ball_in_over)
    print("\nAuditing composite delivery key uniqueness (match_id, innings_number, over_number, ball_in_over)...")
    deliv_keys = deliv_df["match_id"] + "_" + deliv_df["innings_number"] + "_" + deliv_df["over_number"] + "_" + deliv_df["ball_in_over"]
    dup_keys = deliv_keys.duplicated().sum()
    print(f"Duplicate delivery composite keys: {dup_keys}")
    if dup_keys > 0:
        print("Sample duplicated delivery keys:", deliv_keys[deliv_keys.duplicated()].head(5).tolist())

    # 4. Wickets
    print("\nAuditing raw wickets.csv (53,294 records)...")
    wickets_df = pd.read_csv(RAW_DIR / "wickets.csv", dtype=str)
    print(f"Total raw wickets: {len(wickets_df)}")
    w_match_ids = set(wickets_df["match_id"].dropna().str.strip())
    print(f"Wickets missing match_id in matches.csv: {len(w_match_ids - match_ids)}")
    w_player_out = set(wickets_df["player_out_id"].dropna().str.strip())
    print(f"Wickets player_out_id missing in dim_player_pool: {len(w_player_out - dim_player_pool)}")
    w_bowler = set(wickets_df["bowler_id"].dropna().str.strip())
    print(f"Wickets bowler_id missing in dim_player_pool: {len(w_bowler - dim_player_pool)}")
    dismissal_kinds = sorted(wickets_df["kind"].dropna().unique().tolist())
    print(f"Raw dismissal kinds found ({len(dismissal_kinds)}): {dismissal_kinds}")

    # Null bowler IDs in wickets (e.g. run outs)
    null_bowler_count = wickets_df["bowler_id"].isna().sum()
    print(f"Wickets with null bowler_id (run outs/retired hurt): {null_bowler_count}")

    # 5. Wicket Events (derived)
    we_path = DERIVED_DIR / "wicket_events.csv"
    if we_path.exists():
        print("\nAuditing derived wicket_events.csv...")
        we_df = pd.read_csv(we_path, dtype=str)
        print(f"wicket_events rows: {len(we_df)}")
        if "wicket_event_id" in we_df.columns:
            u_wid = we_df["wicket_event_id"].nunique()
            print(f"wicket_events.csv wicket_event_id unique count: {u_wid} (total rows: {len(we_df)})")
            we_kinds = sorted(we_df["kind"].dropna().unique().tolist())
            print(f"wicket_events dismissal kinds ({len(we_kinds)}): {we_kinds}")
            credited_summary = we_df.groupby(["kind", "is_bowler_credited"]).size()
            print("Wicket events crediting summary:\n", credited_summary)

    # 6. Matchups
    print("\nAuditing bowler_batter_matchup_stats_v2.csv...")
    matchups_df = pd.read_csv(DERIVED_DIR / "bowler_batter_matchup_stats_v2.csv", dtype=str)
    m_bowlers = set(matchups_df["bowler_id"].dropna().str.strip())
    m_batters = set(matchups_df["batter_id"].dropna().str.strip())
    print(f"Matchup rows: {len(matchups_df)}")
    print(f"Matchup bowlers missing in dim_player_pool: {len(m_bowlers - dim_player_pool)}")
    print(f"Matchup batters missing in dim_player_pool: {len(m_batters - dim_player_pool)}")

    # 7. Situations
    print("\nAuditing bowler_situation_stats_v2.csv...")
    sit_df = pd.read_csv(DERIVED_DIR / "bowler_situation_stats_v2.csv", dtype=str)
    s_bowlers = set(sit_df["bowler_id"].dropna().str.strip())
    print(f"Situation rows: {len(sit_df)}")
    print(f"Situation bowlers missing in dim_player_pool: {len(s_bowlers - dim_player_pool)}")

    # Return summary dict
    return {
        "missing_deliv_matches": len(missing_deliv_matches),
        "total_missing_in_deliv": len(total_missing_in_deliv),
        "dup_delivery_composite_keys": dup_keys,
        "dismissal_kinds": dismissal_kinds,
    }


if __name__ == "__main__":
    run_audit()
