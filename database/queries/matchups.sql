-- Query: Key Batter-Bowler Head-to-Head Dominance
SELECT
    bowler_name,
    batter_name,
    matches,
    balls,
    runs_scored_by_batter,
    runs_conceded_by_bowler,
    wickets,
    economy,
    strike_rate,
    dot_ball_pct,
    matchup_sample_weight
FROM cricket_analytics.v_bowler_batter_matchups
WHERE balls >= 24
ORDER BY wickets DESC, economy ASC
LIMIT 50;
