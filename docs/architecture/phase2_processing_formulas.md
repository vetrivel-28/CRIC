# CRIC Phase 2 processing formulas

## Provenance and rules

These formulas reflect the validated Phase 1 project rules and were confirmed against the user-provided audit results:

- Legal deliveries are `is_legal_delivery == True`.
- Runs conceded exclude byes, leg-byes and penalty runs: `runs_batter + extra_wides + extra_noballs`.
- A wicket is credited to the bowler only when the wicket row has `is_bowler_credited == True`.
- Zero-denominator metrics remain undefined rather than being converted to zero.
- Valid wide-ball-only records are preserved if they are legitimate source records; they are not treated as invalid data without an evidence-based rule.

## Formula set

- Economy: `runs_conceded / (legal_balls / 6)`
- Bowling average: `runs_conceded / credited_wickets` when wickets > 0
- Bowling strike rate: `legal_balls / credited_wickets` when wickets > 0
- Wicket rate per 100 legal balls: `(credited_wickets / legal_balls) * 100`
- Dot-ball percentage: `(dot_balls / legal_balls) * 100`
- Boundary percentage: `((fours + sixes) / legal_balls) * 100`
- Overs notation: stored as ball notation such as `10.4`, not decimal overs

## Grouping keys

- Career aggregate grain: `bowler_id`, `bowler_name`
- Phase aggregate grain: `bowler_id`, `match_phase`
- Matchup aggregate grain: `bowler_id`, `batter_id`
- Situation aggregate grain: `bowler_id`, `situation_type`, `situation_value`

## Null behavior and exclusions

- Missing `bowler_id` or `batter_id` values are treated as schema errors and are not silently inferred.
- Records with missing `match_phase` are excluded from phase-level aggregation because the phase label is required for the output grain.
- Fields whose denominator is zero remain undefined; output rows may still be present but rates must not be filled with zero unless the project explicitly defines that rule in a future update.
- No source rows are deleted from the original files; only staged or derived outputs are created under `phase2_outputs`.
