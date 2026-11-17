# CRIC Power BI reporting assets

These are source assets for the CRIC semantic model, not a finished `.pbix`.
Power BI Desktop is installed, but the only open document is an untitled model
containing unrelated sample sales data. That document was left untouched. No
CRIC `.pbix` has been created.

## PostgreSQL model

Use the existing normalized tables for detail and the seven validated
`cricket_analytics` views for aggregate analysis:

1. `v_bowler_career_performance`
2. `v_bowler_phase_performance`
3. `v_bowler_batter_matchups`
4. `v_bowler_situation_performance`
5. `v_wicket_profiles`
6. `v_season_bowling_performance`
7. `v_batter_career_performance`

Keep the event facts at their native grain: one row per delivery in
`fact_delivery` and one row per dismissal in `fact_wicket`. Matchup and
situation records are already pre-aggregated; do not aggregate them again from
deliveries for equivalent measures.

The Python recommendation path reads overall matchup values from
`v_bowler_batter_matchups`. That view does not expose phase splits, so the
backend attaches the existing phase fields from `cricket_raw.raw_matchups` by
the `(bowler_id, batter_id)` key. Phase fields are used only when the staging
key has exactly one row; duplicate staging keys are not resolved by selecting
an arbitrary record. The staging source is not an additional analytics view.

### Relationships

- Create role-playing `Dim Bowler` and `Dim Batter` projections of
  `cricket_dim.dim_player`. Use one-to-many, single-direction relationships
  from each player dimension to its corresponding fact/view key.
- Connect `Dim Bowler` to `fact_delivery[bowler_id]`,
  `fact_wicket[bowler_id]`, and the bowler key of career, phase, matchup,
  situation, season, and wicket-profile analytics.
- Connect `Dim Batter` to `fact_delivery[batter_id]`,
  `fact_wicket[player_out_id]`, and the batter key of the batter-career and
  matchup analytics.
- Connect `Dim Match` to delivery and wicket facts by `match_id`. Create a
  distinct `Dim Season` from `dim_match[season]` for season-level aggregates;
  do not relate a non-unique season column as a dimension key.
- Connect `Dim Phase` to delivery and wicket phase labels and the phase
  aggregate view. Connect `Dim Dismissal` to `fact_wicket[kind]`.
- Avoid fact-to-fact relationships and many-to-many player joins. Validate
  filter propagation independently for every role-playing dimension.

## Report pages and interactions

Build these eight pages from real PostgreSQL data:

1. **Executive Overview** — match/player totals, credited wickets, phase
   distribution, and leaders with sample-size tooltips.
2. **Bowler Intelligence** — career, phase, season, and dismissal profile.
3. **Batter Intelligence** — runs, balls faced, strike rate, average, and
   dismissal context.
4. **Bowler vs Batter Matchups** — historical runs, wickets, economy, dots,
   boundaries, balls, and sample flags.
5. **Phase Analysis** — phase comparisons with legal-ball samples.
6. **Situation Intelligence** — situation type/value and over-level historical
   evidence.
7. **Wicket Intelligence** — dismissal type and bowler-credit breakdown.
8. **Match Strategy** — historical shortlist evidence and the existing
   deterministic recommendation rank, not a claim of future success.

Use slicers for season, phase, bowler, batter, dismissal type, situation type,
and situation value where the selected source supports them. Add bowler and
batter drill-through targets, match-level drill-through for event facts, and
tooltips containing the denominator and legal-ball sample. Historical rates
must remain blank for zero denominators. Credited wicket measures must filter
`is_bowler_credited = TRUE`; total dismissal events are a separate measure.

## Theme and DAX

- Import `cric_premium_ivory_emerald_theme.json` in Power BI Desktop.
- Add measures from `cric_dax_measures.dax` to the model. Set percent measures
  to the intended display format and retain blank results for undefined rates.
- The DAX uses the same run-concession and wicket-credit rules as the SQL
  views: batter runs plus wides and no-balls, and only credited wickets for
  bowling rates.
- Verify each measure and equivalent filter selection against PostgreSQL before
  publishing.

## Current validation status

The view definitions, DAX, and repository query contracts have been inspected
and aligned statically. The application now defaults to read-only PostgreSQL
analytics, with CSV available only through the explicit `--source csv` option.
Live SQL parity and Power BI visual parity are not verified: neither
`CRIC_DB_PASSWORD` nor `PGPASSWORD` is available in the process, user, or
machine environment. The installed Power BI Desktop is currently occupied by
the unrelated untitled sample model, which was not overwritten. Do not treat
this specification as a generated or validated `.pbix`.
