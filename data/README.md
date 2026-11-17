# CRIC Data Assets & Schema Reference

This directory contains raw, derived, processed, and manifest datasets supporting the CRIC cricket analytics platform.

---

## Directory Organization

```
data/
├── raw/            # Canonical source datasets (matches, deliveries, players, wickets, powerplays)
├── derived/        # Pre-calculated analytics datasets (head-to-head matchups, situation splits, profiles)
├── processed/      # Validated pipeline aggregates and historical manifests
└── manifests/      # SHA-256 cryptographic parity and ingestion tracking manifests
```

---

## Canonical Ingestion Datasets

The PostgreSQL warehouse `cric_analytics` ingests data from these six core datasets:

| Target PostgreSQL Table | Grain Description | Source File Path | Rows | Size | GitHub Tracking |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `cricket_dim.dim_player` | 1 row per unique cricketer | `data/raw/combined_data.csv` | 5,261 | 0.55 MB | Tracked |
| `cricket_dim.dim_match` | 1 row per match | `data/raw/matches.csv` | 4,230 | 0.85 MB | Tracked |
| `cricket_fact.fact_delivery` | 1 row per ball delivered | `data/raw/deliveries.csv` | 966,985 | 135.13 MB | Local (Exceeds 100MB limit) |
| `cricket_fact.fact_wicket` | 1 row per dismissal event | `data/derived/wicket_events.csv` | 53,294 | 4.57 MB | Tracked |
| `cricket_fact.fact_matchup` | 1 row per bowler-batter pair | `data/derived/bowler_batter_matchup_stats_v2.csv` | 131,294 | 28.21 MB | Tracked |
| `cricket_fact.fact_bowler_situation` | 1 row per situation split | `data/derived/bowler_situation_stats_v2.csv` | 101,163 | 13.81 MB | Tracked |

---

## Full `deliveries.csv` Acquisition & Setup

Because `data/raw/deliveries.csv` contains 966,985 ball-by-ball records and is **135.13 MB**, it exceeds GitHub's 100 MB hard limit.

### For Local Development & Evaluation
- If you have the full project dataset archive, ensure `deliveries.csv` is located at:
  ```
  data/raw/deliveries.csv
  ```
- **Quick Test Sample**: A representative 1,000-delivery sample is provided at:
  ```
  data/raw/deliveries_sample.csv
  ```
  To test ingestion without the full 135 MB file, you can copy the sample:
  ```cmd
  copy data\raw\deliveries_sample.csv data\raw\deliveries.csv
  ```

---

## Data Tier Summary

### 1. `data/raw/`
- `combined_data.csv`: Player biographical profiles, bowling type, bowling category, primary role, batting/bowling hands.
- `matches.csv`: Match metadata, competition, season, date, venue, city, toss decisions, winners, outcomes.
- `deliveries.csv`: Complete ball-by-ball delivery event ledger.
- `wickets.csv`: Raw dismissal events including fielder counts and dismissals.
- `innings.csv`, `match_playing_xi.csv`, `officials.csv`, `powerplays.csv`, `wicket_fielders.csv`: Match-level context datasets.

### 2. `data/derived/`
- `wicket_events.csv`: Standardized wicket events with deterministic bowler-crediting flags (`is_bowler_credited`).
- `bowler_batter_matchup_stats_v2.csv`: Precomputed head-to-head metrics with sample shrinkage weights.
- `bowler_situation_stats_v2.csv`: Situation-based bowling splits (cricket over, phase, pressure index).
- `bowler_career_performance_v1.csv`, `bowler_phase_performance_v1.csv`, `bowler_wicket_profile.csv`: Verified career and phase rate baselines.

### 3. `data/processed/`
- `career_aggregates_phase2.csv`, `phase_aggregates_phase2.csv`, `credited_wickets_phase2.csv`: Pipeline aggregated analytical checkpoints.
- `hdfs_integrity_manifest.csv`: Historical verification manifest proving bit-for-bit parity with post-Hadoop data exports.

### 4. `data/manifests/`
- `ingestion_manifest.csv`: Audit ledger recording source files, SHA-256 hashes, source row counts, and timestamps.
