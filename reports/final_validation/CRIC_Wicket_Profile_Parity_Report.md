# CRIC Wicket Profile Parity Report

## Executive result

**Status: reconciled and no source-data deletion performed.**

The PostgreSQL view contains 2,744 rows and the derived CSV contains 2,717 rows. The 27-row SQL excess is not evidence of 27 missing bowler wickets:

- 26 additional SQL population groups are bowlers with only uncredited wicket events or zero credited wickets.
- 24 of these groups are represented solely by one or more run-outs.
- 1 group is a retired-hurt event.
- 1 SQL-only group has no matching row in `cricket_fact.fact_wicket`; it is retained as a view inconsistency to investigate, not treated as an actual bowler wicket.
- 1 duplicate-extra row is caused by `bowler_id` `3086f7a4` appearing under two `bowler_name` values in the view: `Mohammad Nawaz` and `Mohammad Nawaz (3)`.

The CSV is a credited-bowler dismissal-profile dataset. It does not include run-outs or retired-hurt records. It has 2,717 unique bowler IDs and no CSV-only bowler IDs.

## Additional PostgreSQL records

| Bowler ID | Bowler name | SQL total wicket events | Credited wickets | Recorded dismissal classification |
|---|---|---:|---:|---|
| 123ab754 | Syed Faizan Tahir | 1 | 0 | run out |
| 16605a1b | AA Kazi | 1 | 0 | run out |
| 24076663 | Oliver Rowe | 1 | 0 | run out |
| 27b8d7b6 | K Birkenstock | 1 | 0 | run out |
| 3317dc7a | P Jayeshbhai Patel | 1 | 0 | run out |
| 3b107df5 | ME Leoela | 1 | 0 | run out |
| 5ef7b1ba | Ebrahim Naseri | 1 | 0 | run out |
| 60cc80ac | Razmal Shigiwal | 1 | 0 | run out |
| 62c4b38b | CG Campbell | 1 | 0 | run out |
| 692d4cbe | M Gherasim | 1 | 0 | run out |
| 79b2d37a | Adnan Gondal | 2 | 0 | run out |
| 864c199e | AC Voges | 1 | 0 | run out |
| 90ddee48 | I Master | 2 | 0 | run outs |
| 93f72fdc | AK Muslar | 1 | 0 | run out |
| 9c3a8776 | D Nikolov | 1 | 0 | run out |
| 9c93a8776 | Y Saranonnakkun | 1 | 0 | No matching fact-wicket row found |
| a025c156 | Muhammad Saleem | 1 | 0 | retired hurt |
| a28a7fba | A Johnson | 1 | 0 | run out |
| c15e2193 | FY Fazal | 1 | 0 | run out |
| cc3ebe28 | Haroon Shahid | 1 | 0 | run out |
| d3c260a6 | Usman Rafiq | 1 | 0 | run out |
| e1370b54 | WJR Robertson | 1 | 0 | run out |
| f31740ce | H Pattenden | 1 | 0 | run out |
| f80bd415 | LKW Ezechiel | 2 | 0 | run out and retired out |
| f9260467 | D Gaikwad | 1 | 0 | run out |
| fffa744b | Naman Dhir | 1 | 0 | run out |

## Name-identifier duplicate

`3086f7a4` / `Mohammad Nawaz` and `3086f7a4` / `Mohammad Nawaz (3)` are separate view rows only because the view groups by both bowler ID and bowler name.

| Source | Total wickets | Credited wickets |
|---|---:|---:|
| SQL `Mohammad Nawaz` | 74 | 73 |
| SQL `Mohammad Nawaz (3)` | 21 | 20 |
| SQL combined | 95 | 93 |
| CSV `Mohammad Nawaz (3)` | 93 | 93 by dismissal-profile calculation |

The SQL split includes 2 run-outs; the CSV profile is based on credited dismissal totals and is correct for bowler-credited performance.

## Root cause

1. `v_wicket_profiles` is grouped by `bowler_id, bowler_name` and includes every fact-wicket row, including non-bowler-credited dismissals.
2. `bowler_wicket_profile.csv` is a bowler-credited profile and does not include uncredited events.
3. One bowler ID has inconsistent name variants in source wicket facts, causing the SQL view to emit two rows.
4. One SQL-only orphan is not supported by `cricket_fact.fact_wicket` and should remain flagged for data-quality follow-up rather than credited to a bowler.

## Source-of-truth decision

- Authoritative for total wicket-event analysis: `cricket_fact.fact_wicket` and `cricket_dim.dim_dismissal`.
- Authoritative for bowler-credited wicket performance: `COUNT(*) FILTER (WHERE is_bowler_credited)` in `v_wicket_profiles` and the equivalent PostgreSQL and DAX logic.
- Authoritative CSV reference for credited bowler dismissal profiles: `data/derived/bowler_wicket_profile.csv`.
- Parity should compare CSV to `v_wicket_profiles` filtered to `credited_wickets > 0`, after normalizing the bowler name variant for `3086f7a4`. Raw row-count equality is not expected.

No SQL view or source data was modified because the extra population is analytically legitimate except for the documented duplicate-name grouping and orphan candidate.
