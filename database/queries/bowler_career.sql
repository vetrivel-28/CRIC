-- Query: Top Bowlers by Career Wickets and Economy
SELECT
    bowler_name,
    country,
    bowling_category,
    matches_bowled,
    legal_balls / 6 AS overs_bowled,
    runs_conceded,
    wickets,
    economy,
    average,
    strike_rate,
    dot_ball_pct
FROM cricket_analytics.v_bowler_career_performance
WHERE legal_balls >= 300
ORDER BY wickets DESC, economy ASC
LIMIT 50;
