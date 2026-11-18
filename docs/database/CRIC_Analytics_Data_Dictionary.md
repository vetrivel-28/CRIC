# CRIC Analytics Data Dictionary

This dictionary freezes the analytical definitions used by CRIC PostgreSQL, the web dashboard and Power BI.

## Shared credit and ball rules

- Legal balls: `fact_delivery.is_legal_delivery = TRUE`.
- Runs conceded: `runs_batter + extra_wides + extra_noballs`; byes and leg-byes are excluded.
- Economy: runs conceded / (legal balls / 6).
- Bowler-credited wicket: `fact_wicket.is_bowler_credited = TRUE`.
- Total wicket event: every `fact_wicket` record.
- A run-out is a total wicket event and is not a credited bowling wicket.
- Missing or zero denominators must produce `NULL`/blank rather than a fabricated value.

## 1. v_batter_career_performance

- Purpose: career batting totals per batter.
- Sources: `cricket_fact.fact_delivery`, `cricket_dim.dim_player`.
- Grouping: `batter_id`, `batter_name`.
- Metrics: runs, balls faced, dismissals, fours, sixes, batting average and batting strike rate.
- Balls faced: legal or all deliveries where the batter faced the ball according to source delivery rules; verify `is_legal_delivery` handling in the view before use.
- Batting average: runs / dismissals.
- Batting strike rate: runs x 100 / balls faced.
- Parity: PostgreSQL and derived CSV expectation is exact; 4,267 rows verified.
- Limitation: minimum sample thresholds are presentation rules and do not alter source aggregates.

## 2. v_bowler_batter_matchups

- Purpose: bowler-versus-batter head-to-head performance.
- Sources: derived fact aggregates or `cricket_fact.fact_delivery`/`fact_wicket`.
- Grouping: bowler ID, bowler name, batter ID, batter name.
- Metrics: balls, conceded runs, wickets, dot balls, economy and strike rate.
- Wickets: bowler-credited wickets only.
- Legal sample reliability: 30-ball prior is the existing CRIC sample heuristic, not predictive confidence.
- Null handling: zero denominators return blank.
- Parity: exact 131,294-row CSV/view match.

## 3. v_bowler_career_performance

- Purpose: all-history bowling performance per bowler.
- Sources: `cricket_fact.fact_delivery`, `cricket_fact.fact_wicket`, `cricket_dim.dim_player`.
- Grouping: bowler ID and bowler name.
- Metrics: matches where available, legal balls, runs conceded, credited wickets, economy, bowling average and bowling strike rate.
- Bowling strike rate: legal balls / credited wickets.
- Wicket rate: credited wickets / legal balls.
- Parity: exact 3,190-row CSV/view match.

## 4. v_bowler_phase_performance

- Purpose: bowler performance by match phase.
- Sources: delivery and phase dimensions.
- Grouping: bowler ID, bowler name and canonical match phase.
- Phases: Powerplay, Middle Overs and Death Overs from existing CRIC phase definitions.
- Metrics: phase balls, runs, credited wickets, economy and strike rate.
- Parity: exact 7,976-row CSV/view match.

## 5. v_bowler_situation_performance

- Purpose: bowler performance across actual innings and required-run-rate situations.
- Sources: `cricket_fact.fact_bowler_situation` or equivalent source aggregates.
- Grouping: bowler, situation type and situation value.
- Metrics: balls, runs conceded, credited wickets, economy and dot-ball metrics.
- No synthetic pressure field is added.
- Parity: exact 101,163-row CSV/view match.

## 6. v_season_bowling_performance

- Purpose: complete bowler-season bowling performance.
- Sources: `fact_delivery`, `fact_wicket`, `dim_match`.
- Grouping: bowler ID, bowler name and canonical `dim_match.season`.
- Metrics: season matches, legal balls, runs conceded, credited wickets, economy and average.
- Season semantics: canonical source label is preserved; multi-year labels remain multi-year.
- Includes zero-wicket spells because season deliveries are the base population.
- Authoritative CSV reference: positive-wicket `bowler_season_wickets.csv` only.
- Parity: not expected one-for-one without season normalization and a positive-wicket filter.

## 7. v_wicket_profiles

- Purpose: wicket-event and dismissal-profile analysis per bowler.
- Sources: `cricket_fact.fact_wicket`.
- Grouping: bowler ID and bowler name.
- Metrics: total wicket events, credited wickets and dismissal categories.
- `total_wickets` includes all events with a non-null bowler ID.
- `credited_wickets` includes only `is_bowler_credited = TRUE`.
- CSV reference: credited bowler profile with no uncredited dismissal events.
- Grouping must normalize bowler name variants for reporting when the same ID is reused.
- Parity: raw row equality is not expected.

## Source-of-truth policy

| View | Authoritative source | CSV reference | Parity expectation |
|---|---|---|---|
| Batter career | PostgreSQL view | Derived batter CSV | Exact |
| Bowler-batter matchups | PostgreSQL view | Matchup CSV | Exact |
| Bowler career | PostgreSQL view | Career CSV | Exact |
| Bowler phase | PostgreSQL view | Phase CSV | Exact |
| Bowler situation | PostgreSQL view | Situation CSV | Exact |
| Season bowling | PostgreSQL view | Positive-wicket season CSV | Different population |
| Wicket profiles | PostgreSQL view plus fact-wicket credit rules | Credited profile CSV | Different population |
