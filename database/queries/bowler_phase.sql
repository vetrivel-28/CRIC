-- Query: Death Over Specialists (Overs 16-20)
SELECT
    bowler_name,
    match_phase,
    phase_balls / 6 AS overs_in_phase,
    phase_runs_conceded,
    phase_wickets,
    phase_economy,
    phase_average,
    phase_strike_rate,
    phase_dot_pct
FROM cricket_analytics.v_bowler_phase_performance
WHERE match_phase = 'death'
  AND phase_balls >= 120
ORDER BY phase_economy ASC, phase_wickets DESC
LIMIT 30;
