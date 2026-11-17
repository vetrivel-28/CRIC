-- Query: Dismissal Profile & Stumps Attackers (Bowled + LBW %)
SELECT
    bowler_name,
    total_wickets,
    credited_wickets,
    bowled,
    lbw,
    caught,
    stumped,
    caught_and_bowled,
    pct_bowled_or_lbw
FROM cricket_analytics.v_wicket_profiles
WHERE credited_wickets >= 20
ORDER BY pct_bowled_or_lbw DESC
LIMIT 50;
