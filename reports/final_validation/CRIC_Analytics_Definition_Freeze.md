# CRIC Analytics Definition Freeze

**Freeze date:** 2026-11-18

The following definitions are approved for PostgreSQL analysis and Power BI implementation.

## Frozen formulas

| Metric | Approved formula |
|---|---|
| Economy | Runs conceded / (Legal balls / 6) |
| Bowling average | Runs conceded / Credited wickets |
| Bowling strike rate | Legal balls / Credited wickets |
| Wicket rate | Credited wickets / Legal balls |
| Batting average | Runs / Dismissals |
| Batting strike rate | (Runs / Balls faced) x 100 |
| Matchup economy | Matchup runs conceded x 6 / Matchup legal balls |
| Situation economy | Situation runs conceded x 6 / Situation legal balls |

DAX must use `DIVIDE()` and should not convert missing values to zero unless zero is mathematically correct.

## Frozen exclusions

- Byes and leg-byes are excluded from runs conceded.
- Run-outs and retired-hurt events are not credited bowling wickets.
- Raw wicket events are not interchangeable with credited wickets.
- Zero legal-ball denominators do not produce an economy value.

## Frozen season rules

- Canonical season values come from `cricket_dim.dim_match.season`.
- Multi-year values remain canonical labels in PostgreSQL and Power BI.
- The report may provide a validated starting-year mapping for UI normalization.
- `2022 onwards` means source seasons starting from calendar season 2022, subject to canonical mapping validation.
- Records that cannot be associated reliably with a season remain excluded from season-only analysis.

## Frozen view population rules

| View | Population |
|---|---|
| Career views | All valid source aggregates |
| Phase view | Three established CRIC phases only |
| Matchup view | All valid bowler-batter pairs |
| Situation view | Existing situation dimensions only |
| Season bowling | All bowlers with season deliveries, including zero credited wickets |
| Wicket profiles | All wicket events by bowler ID/name, with separate credited-wicket counts |

## Freeze decisions

- Wicket-profile parity is resolved as two legitimately different populations plus a one-ID duplicate-name grouping.
- Season-bowling parity is resolved by preserving the complete PostgreSQL population and canonical seasons.
- Power BI must not implement a different economy or credit rule.
- The Match Strategy page must use the production engine or be labelled historical analysis.

The detailed definitions are maintained in [CRIC_Analytics_Data_Dictionary.md](/CRIC/docs/database/CRIC_Analytics_Data_Dictionary.md).
