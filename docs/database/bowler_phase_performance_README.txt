CRIC Bowler Phase Performance V1
Source inputs: original deliveries.csv and existing wicket_events.csv.
Aggregation key: bowler_id + source match_phase.
Phase labels are taken from deliveries.csv, not invented.
Runs conceded = runs_batter + extra_wides + extra_noballs; byes, leg-byes and penalty runs excluded.
Wickets count only existing wicket_events rows where is_bowler_credited is true, joined by match_id, innings_number, over_number, ball_in_over and bowler_id.
Economy = runs_conceded / legal_balls * 6.
Bowling average = runs_conceded / credited wickets.
Bowling strike rate = legal balls / credited wickets.
Dot balls = legal deliveries with runs_total equal to zero.
Boundary counts use batter runs of 4 or 6 on legal deliveries.
No performance values were imputed. Rates with zero denominator remain blank.
Sample flags are rule-based labels, not confidence probabilities.
This is V1 and must undergo the planned independent source-level audit before model training or historical recommendation evaluation.
