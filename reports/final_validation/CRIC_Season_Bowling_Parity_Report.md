# CRIC Season Bowling Parity Report

## Executive result

**Status: reconciled. PostgreSQL is authoritative for season bowling.**

The CSV contains 7,401 positive-wicket bowler-season rows. PostgreSQL contains 10,414 bowler-season rows. The difference is caused by different populations and canonical season representation:

- 1889 PostgreSQL groups have zero credited wickets.
- 1887 of those zero-wicket groups still have legal deliveries.
- PostgreSQL preserves 29 canonical source seasons, including 12 multi-year labels.
- CSV has 20 season values and no multi-year season labels.
- CSV contains positive-wicket records only.
- PostgreSQL includes all bowlers who delivered in a season, even when credited wickets are zero.

No source rows or season values were deleted or rewritten.

## Season populations

| Population | Rows |
|---|---:|
| CSV bowler-season wickets | 7,401 |
| PostgreSQL bowler-season bowling | 10,414 |
| PostgreSQL zero-wicket groups | 1,889 |
| PostgreSQL zero-wicket groups with legal deliveries | 1,887 |
| PostgreSQL positive-wicket groups | 8,525 |
| CSV seasons | 20 |
| PostgreSQL seasons | 29 |

CSV seasons:

`2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026, Unresolved`

PostgreSQL additionally has canonical multi-year formats:

`2007/08, 2009/10, 2016/17, 2017/18, 2018/19, 2019/20, 2020/21, 2021/22, 2022/23, 2023/24, 2024/25, 2025/26`

## Canonical reconciliation

For record-level reconciliation, SQL multi-year seasons can be normalized to their starting calendar year. This yields:

- Normalized matches: 8,224
- Normalized SQL-only groups: 2,192
- Normalized CSV-only groups: 860

Normalized SQL-only groups include 1,519 zero-wicket groups and 673 positive-wicket groups. The CSV-only population includes positive-wicket records in calendar seasons or unresolved legacy groups that do not have a one-for-one canonical SQL key.

## Root causes

1. The SQL view uses `season_deliveries` as its base and therefore includes every bowler-season with deliveries.
2. The left join to season wickets supplies zero rather than excluding empty wicket populations.
3. The CSV is a positive-wicket aggregate and omits zero-wicket bowling spells.
4. The CSV has 20 normalized calendar-year labels, while SQL preserves 29 canonical source labels.
5. Multi-year labels such as `2020/21` and `2020` require explicit normalization rather than direct string equality.

## Authoritative source

- `cricket_dim.dim_match.season` is authoritative for canonical season values.
- `cricket_analytics.v_season_bowling_performance` is authoritative for complete bowler-season records, because it retains legal balls, runs, matches, zero-wicket spells and canonical source season labels.
- `data/derived/bowler_season_wickets.csv` is a reference dataset containing positive credited-wicket records only.
- Power BI season slicers should use canonical SQL season values and implement `2022 onwards` by validated numeric/canonical mapping.

No SQL view or source data was modified.
