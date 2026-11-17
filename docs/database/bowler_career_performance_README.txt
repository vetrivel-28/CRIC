CRIC Bowler Career Performance V1
Source: deliveries.csv and wickets.csv from supplied merged_cricket_data archive.
Aggregation grain: one row per bowler_id and bowler_name.
Runs conceded = runs_batter + extra_wides + extra_noballs; excludes byes, leg-byes and penalty runs.
Credited wickets include bowled, caught, caught and bowled, lbw, stumped, hit wicket.
Legal balls use is_legal_delivery. Dot balls are legal deliveries with runs_total == 0. Fours/sixes count batter runs equal to 4/6.
Economy = runs conceded / (legal balls / 6). Bowling average = runs conceded / credited wickets. Bowling strike rate = legal balls / credited wickets.
Overs are stored as balls notation (e.g. 10.4 means 10 overs and 4 balls), not decimal overs.
Sample flags are descriptive thresholds: <60 legal balls very_small; 60-179 small; >=180 adequate_for_basic_summary. They are not model confidence guarantees.
This is an all-history aggregate and must not be used directly for historical backtesting without point-in-time recomputation to prevent leakage.
