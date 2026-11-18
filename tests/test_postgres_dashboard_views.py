"""
CRIC Analytics - Test All 8 Dashboard Views with PostgreSQL Backed Data
Validates:
1. Executive Overview
2. Bowler Intelligence
3. Batter Intelligence
4. Bowler vs Batter Matchups
5. Phase Analysis
6. Situation Intelligence
7. Wicket Intelligence
8. Match Strategy / Decision Support
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database.connection import DatabaseConnection
from backend.database.repository import CricketRepository
from backend.postgres_dashboard_data import PostgresDashboardData
from backend.recommendation_engine import DatasetPaths, RecommendationEngine


def test_all_eight_dashboard_views():
    print("=" * 80)
    print("TESTING ALL 8 CRIC DASHBOARD VIEWS VIA POSTGRESQL BACKEND")
    print("=" * 80)

    db = DatabaseConnection()
    assert db.ping(), "Database must be reachable!"
    repo = CricketRepository(db)
    
    # Initialize engine directly from PostgreSQL repository records
    source_records = RecommendationEngine.load_repository_records(repo)
    engine = RecommendationEngine(None, records=source_records)

    # Initialize PostgresDashboardData
    dashboard = PostgresDashboardData(repo, engine, source_records=source_records)

    # 1. Executive Overview
    print("\n[View 1: Executive Overview]")
    overview_all = dashboard.overview()
    print("  KPIs:", overview_all["kpis"])
    assert overview_all["kpis"]["matches"] == 4230
    assert overview_all["kpis"]["bowlers"] == 3190
    assert overview_all["kpis"]["batters_in_matchups"] == 4267

    # Test with default global season: "2022 onwards"
    overview_2022 = dashboard.overview(season="2022 onwards")
    print("  Matches (2022 onwards):", overview_2022["kpis"]["matches"])
    assert overview_2022["kpis"]["matches"] > 0
    print("  View 1 PASS!")

    # 2. Bowler Intelligence
    print("\n[View 2: Bowler Intelligence]")
    sample_bowler_id = list(dashboard._career_by_id.keys())[0]
    bowler_data = dashboard.bowler(bowler_id=sample_bowler_id)
    bowler_obj = bowler_data["selected_bowler"]
    print(f"  Bowler {bowler_obj['bowler_name']}:")
    print("    Balls:", bowler_obj["legal_balls"])
    print("    Wickets:", bowler_obj["wickets"])
    print("    Economy:", bowler_obj["economy"])
    assert bowler_obj["legal_balls"] >= 0
    print("  View 2 PASS!")

    # 3. Batter Intelligence
    print("\n[View 3: Batter Intelligence]")
    batters_data = dashboard.batters()
    print("  Total batters available:", batters_data["total"])
    print(f"  Top batter: {batters_data['leaders'][0]['batter_name']} ({batters_data['leaders'][0]['runs_scored']} runs)")
    assert batters_data["total"] == 4267
    assert batters_data["leaders"][0]["runs_scored"] > 0
    print("  View 3 PASS!")

    # 4. Bowler vs Batter Matchups
    print("\n[View 4: Bowler vs Batter Matchups]")
    matchup_data = dashboard.matchups(bowler_id=sample_bowler_id, min_balls="0")
    print(f"  Matchups for {sample_bowler_id}: {matchup_data['total']} matchups found.")
    assert matchup_data["total"] >= 0
    print("  View 4 PASS!")

    # 5. Phase Analysis
    print("\n[View 5: Phase Analysis]")
    phase_overview = dashboard.overview(phase="Powerplay")
    print(f"  Powerplay overview wickets: {phase_overview['kpis']['bowler_credited_wickets']}")
    assert phase_overview["kpis"]["bowler_credited_wickets"] > 0
    print("  View 5 PASS!")

    # 6. Situation Intelligence
    print("\n[View 6: Situation Intelligence]")
    sit_data = dashboard.situations()
    print(f"  Total situation rows returned: {sit_data['total']}")
    assert sit_data["total"] > 0
    print("  View 6 PASS!")

    # 7. Wicket Intelligence
    print("\n[View 7: Wicket Intelligence]")
    wicket_data = dashboard.wickets()
    print(f"  Wicket profile records: {wicket_data['total']}")
    assert wicket_data["total"] > 0
    print("  View 7 PASS!")

    # 8. Match Strategy / Decision Support
    print("\n[View 8: Match Strategy / Decision Support]")
    sample_batter_id = list(dashboard._batter_by_id.keys())[0]
    candidate_ids = list(dashboard._career_by_id.keys())[:5]
    recommend_req = {
        "batter_id": sample_batter_id,
        "phase": "Powerplay",
        "candidates": [{"bowler_id": bid} for bid in candidate_ids]
    }
    rec_result = engine.recommend(recommend_req)
    print(f"  Target Batter: {sample_batter_id}, Phase: Powerplay")
    print(f"  Top recommended bowler: {rec_result['recommendations'][0]['bowler_id']} (score: {rec_result['recommendations'][0]['score']})")
    assert len(rec_result["recommendations"]) == 5
    assert rec_result["recommendations"][0]["score"] >= rec_result["recommendations"][1]["score"]
    print("  View 8 PASS!")

    print("\n" + "=" * 80)
    print("ALL 8 DASHBOARD VIEWS TESTED AND VALIDATED AGAINST POSTGRESQL - 100% SUCCESS")
    print("=" * 80)


if __name__ == "__main__":
    test_all_eight_dashboard_views()
