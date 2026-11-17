# CRIC Phase 2 dataset lineage

## Source provenance

The original source files are kept under the extracted archives in `C:\CRIC\data` and are never modified. The project reads the source CSVs directly and writes derived outputs only to `C:\CRIC\phase2_outputs`.

Primary source datasets reviewed for Phase 2:
- `data/merged_cricket_data-20261012T042833Z-1-001/merged_cricket_data/deliveries.csv`
- `data/wickets_derived_Dataset-20261012T042841Z-1-001/wickets_derived_Dataset/wicket_events.csv`
- `data/CRIC_bowler_career_performance_v1-20261012T042830Z-1-001/CRIC_bowler_career_performance_v1/bowler_career_performance_v1.csv`
- `data/CRIC_bowler_phase_performance_v1-20261012T042831Z-1-001/CRIC_bowler_phase_performance_v1/bowler_phase_performance_v1.csv`
- `data/bowler_matchup_situation_Dataset-20261012T042831Z-1-001/bowler_matchup_situation_Dataset/bowler_batter_matchup_stats_v2.csv`
- `data/bowler_matchup_situation_Dataset-20261012T042831Z-1-001/bowler_matchup_situation_Dataset/bowler_situation_stats_v2.csv`

## Output lineage

Produced outputs under `C:\CRIC\phase2_outputs`:
- `validation_report.csv` — schema and integrity checks for source files.
- `validation_summary.json` — machine-readable summary for reruns and traceability.
- `processed/career_aggregates_phase2.csv` — local repro of bowler career aggregates using the source legal-ball rules.
- `processed/phase_aggregates_phase2.csv` — local repro of bowler phase aggregates.
- `processed/credited_wickets_phase2.csv` — credited wicket totals by bowler.
- `recommendation_contract.csv` — exact contract for the future recommendation engine.
- `execution_summary.json` — runtime metadata including file counts and validation outcomes.

## Legal-ball and wicket rules

- Legal delivery means `is_legal_delivery == True`.
- Credited wicket means `wicket_events.is_bowler_credited == True`.
- A wide ball with zero legal balls remains valid if the source row has `is_legal_delivery = False` and `extra_wides = 1`; it is not silently converted to zero.
- The Sajid Patel edge case (one legal-ball-less wide) is retained as a valid record.

## Recommendation contract for the future engine

The future recommendation engine should consume matchup-level records with these fields and types:

| field | type | required | purpose |
|---|---|---:|---|
| bowler_id | string | Yes | unique bowler identifier |
| batter_id | string | Yes | unique batter identifier |
| bowler_name | string | No | readable label |
| batter_name | string | No | readable label |
| balls | integer | Yes | legal-delivery sample size |
| runs_conceded_by_bowler | float | Yes | runs conceded in the matchup sample |
| wickets | integer | Yes | credited wickets within the sample |
| match_phase | string | No | optional phase filter |

This contract is documented in `C:\CRIC\phase2_outputs\recommendation_contract.csv` and is deliberately limited to the fields already validated by the source and derived outputs.
