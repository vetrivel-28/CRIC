-- Query: Bowler Situation Performance in High Pressure / Critical Contexts
SELECT
    bowler_name,
    situation_type,
    situation_value,
    cricket_over,
    matches,
    balls,
    runs_conceded,
    wickets,
    economy,
    strike_rate_balls_per_wicket,
    dot_ball_pct
FROM cricket_analytics.v_bowler_situation_performance
WHERE balls >= 30
ORDER BY wickets DESC, economy ASC
LIMIT 50;
