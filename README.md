# CRIC: Cricket Analytics & Intelligent Match Strategy

[![Python Version](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![Database](https://img.shields.io/badge/PostgreSQL-16%2B%20%2F%2018.4-336791.svg)](https://www.postgresql.org/)
[![Testing](https://img.shields.io/badge/pytest-124%20passed-brightgreen.svg)](https://pytest.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

CRIC (Cricket Analytics and Intelligent Match Strategy) is an end-to-end cricket data engineering, analytics, and tactical decision-support platform. Formerly prototyped on a distributed Hadoop ecosystem, CRIC has been completely re-architected into a high-performance **PostgreSQL 18.4 + Python 3.13 + SQL** analytics warehouse designed for downstream business intelligence in **Microsoft Power BI**.

---

## 1. Project Overview

CRIC models ball-by-ball delivery events, historical player outcomes, phase splits, and situational contexts to provide tactical recommendations (such as bowler selection against specific batters in given match overs). The platform integrates relational star schemas, transactional bulk ingestion, cryptographic manifest verification, analytical SQL views, and a deterministic recommendation engine.

---

## 2. Problem Statement

Cricket match strategy often relies on intuition or unweighted career averages that fail to reflect:
- **Sample-size shrinkage**: A bowler with 2 wickets in 4 balls against a batter appears artificially dominant without Bayesian or volume weighting.
- **Phase-specific context**: Bowlers perform differently in the Powerplay (overs 1–6), Middle (overs 7–15), and Death (overs 16–20).
- **Match situation pressure**: Bowler economy changes dramatically depending on whether defending low totals or bowling under high run rates.
- **Legacy architectural overhead**: Big-data batch engines (Hadoop/MapReduce) introduced excessive runtime latency for analytical queries and local BI integration.

---

## 3. Objectives

- Establish a robust, relational analytical data warehouse using **PostgreSQL 16+**.
- Migrate 1.37+ million cricket records across 6 core entities with 100% cryptographic parity.
- Provide zero-denominator-safe SQL views computing career, phase, matchup, situation, and wicket profile rates.
- Deliver a fast, backward-compatible Python tactical recommendation scoring engine.
- Structure data and measures for seamless direct integration with **Microsoft Power BI**.

---

## 4. Key Features

- **Relational Star Schema**: Domain schemas (`cricket_raw`, `cricket_dim`, `cricket_fact`, `cricket_analytics`, `cricket_eval`).
- **Deterministic Identifier Architecture**: Natural composite key hashing for dismissals (`fact_wicket`), preventing duplicate delivery counting.
- **Audit Ledger & Manifests**: Every ingestion run tracks source SHA-256 hashes, true database inserted row counts, and rejection logs.
- **Tactical Recommendation Engine**: Multi-factor scoring combining career performance, matchup dominance, phase economy, and situation pressure with `LEAST(1.0, balls / 30.0)` shrinkage weighting.
- **Automated Validation Suite**: Automated checks for row-count parity, referential integrity, orphan records, and analytical view metrics.

---

## 5. Technology Stack

- **Database Engine**: PostgreSQL 18.4 (ANSI SQL, B-Tree indexing, CTE views)
- **Database Driver**: `psycopg 3` (`psycopg[binary,pool]>=3.1.18`)
- **Data Engineering & Analytics**: Python 3.13, Pandas 2.2+, NumPy 1.26+
- **Test Harness**: Pytest 8.0+
- **Reporting**: ReportLab 4.0+
- **Business Intelligence**: Microsoft Power BI (Semantic model & DAX library prepared)

---

## 6. System Architecture

```mermaid
flowchart TD
    subgraph Data Layer [Data Tier: data/]
        CSV_RAW["Raw CSVs\n(matches, deliveries, players, wickets)"]
        CSV_DER["Derived CSVs\n(matchups, situations, wicket_events)"]
    end

    subgraph Pipeline Layer [Ingestion & Validation: scripts/]
        INIT_DB["scripts/maintenance/init_database.py\n(Safe DB Initialization)"]
        LOAD_PG["scripts/ingestion/load_postgres.py\n(COPY / Parameterized Batch Ingestion)"]
        VAL_PG["scripts/validation/validate_database.py\n(Parity & Integrity Verification)"]
    end

    subgraph Warehouse Layer [PostgreSQL 18.4: cric_analytics]
        RAW_SCHEMA["cricket_raw\n(ingestion_runs, manifest, rejects)"]
        DIM_SCHEMA["cricket_dim\n(dim_player, dim_match, dim_phase, dim_dismissal)"]
        FACT_SCHEMA["cricket_fact\n(fact_delivery, fact_wicket, fact_matchup, fact_bowler_situation)"]
        ANALYTICS_SCHEMA["cricket_analytics\n(Analytical SQL Rate Views)"]
    end

    subgraph Application Layer [Consumers]
        REC_ENG["backend/recommendation_engine.py\n(Tactical Bowler Scoring Engine)"]
        POWER_BI["powerbi/\n(Microsoft Power BI Semantic Model & DAX)"]
    end

    CSV_RAW --> LOAD_PG
    CSV_DER --> LOAD_PG
    INIT_DB --> DIM_SCHEMA
    LOAD_PG --> RAW_SCHEMA
    LOAD_PG --> DIM_SCHEMA
    LOAD_PG --> FACT_SCHEMA
    FACT_SCHEMA --> ANALYTICS_SCHEMA
    DIM_SCHEMA --> ANALYTICS_SCHEMA
    ANALYTICS_SCHEMA --> REC_ENG
    ANALYTICS_SCHEMA --> POWER_BI
    VAL_PG -.-> Warehouse Layer
```

---

## 7. Database Architecture

The `cric_analytics` PostgreSQL database is organized into 5 isolated schemas:

1. **`cricket_raw`**: Ingestion-run audit metadata, file checksum tracking, and reject logging:
   - `ingestion_runs`: Track unique ingestion run IDs, status, and timestamps.
   - `ingestion_file_manifest`: Per-file source records, true inserted rows, and SHA-256 hashes.
   - `ingestion_rejects`: Unparseable records, raw payloads, and rejection reasons.
2. **`cricket_dim`**: Star schema dimensions:
   - `dim_player`: 5,261 unique players (batting/bowling styles, primary role, country).
   - `dim_match`: 4,230 matches (competition, season, date, venue, city, toss, winner).
   - `dim_phase`: Powerplay (1–6), Middle (7–15), Death (16–20) with case aliases.
   - `dim_dismissal`: 14 dismissal classifications with strict `is_bowler_credited` flags.
   - `dim_team`, `dim_venue`.
3. **`cricket_fact`**: Star schema facts:
   - `fact_delivery`: 966,985 ball-by-ball delivery records (unpartitioned, PK: `match_id, innings_number, over_number, ball_in_over`, 6 B-Tree indexes).
   - `fact_wicket`: 53,294 dismissal events (deterministic 63-bit integer event ID).
   - `fact_matchup`: 131,294 head-to-head pairs with sample weights.
   - `fact_bowler_situation`: 101,163 bowler situation records.
4. **`cricket_analytics`**: High-performance analytical views.
5. **`cricket_eval`**: Evaluation audit ledger with Merkle-style hash chaining.

---

## 8. Dataset Overview

| Dataset | Tier | Records | Size | Description |
| :--- | :--- | ---:| ---:| :--- |
| `deliveries.csv` | `data/raw/` | 966,985 | 135.13 MB | Complete ball-by-ball delivery event ledger |
| `matches.csv` | `data/raw/` | 4,230 | 0.85 MB | Match metadata, venues, seasons, and results |
| `combined_data.csv` | `data/raw/` | 5,261 | 0.55 MB | Player profiles, roles, and bowling classifications |
| `wicket_events.csv` | `data/derived/` | 53,294 | 4.57 MB | Dismissal records with verified bowler-crediting flags |
| `bowler_batter_matchup_stats_v2.csv` | `data/derived/` | 131,294 | 28.21 MB | Head-to-head records with shrinkage weight |
| `bowler_situation_stats_v2.csv` | `data/derived/` | 101,163 | 13.81 MB | Over-by-over situational bowling performance |

*Total Canonical Warehouse Records*: **1,375,963 rows**.

---

## 9. Analytical Views

All views in [database/views/05_analytics_views.sql](file:///C:/CRIC/database/views/05_analytics_views.sql) incorporate `NULLIF` zero-division safeguards:

1. **`v_bowler_career_performance`**: Independent CTE aggregation of deliveries and credited wickets. Produces `economy`, `average`, `strike_rate`, `dot_ball_pct` (`runs_total = 0`), and `boundary_pct`.
2. **`v_bowler_phase_performance`**: Phase-partitioned metrics across Powerplay, Middle, and Death overs.
3. **`v_bowler_batter_matchups`**: Head-to-head matchup statistics with shrinkage weight `LEAST(1.0, balls / 30.0)`.
4. **`v_bowler_situation_performance`**: Bowler rate metrics broken down by match state.
5. **`v_wicket_profiles`**: Breakdown of dismissals (`bowled`, `caught`, `lbw`, `stumped`, etc.) and `pct_bowled_or_lbw`.
6. **`v_season_bowling_performance`**: Volume and economy progression across seasons.
7. **`v_batter_career_performance`**: Batting totals, balls faced (`extra_wides = 0`), strike rates, and boundary percentages.

---

## 10. Recommendation Engine Overview

Located at [backend/recommendation_engine.py](file:///C:/CRIC/backend/recommendation_engine.py), the recommendation engine calculates tactical bowler suitability scores for a given batter, match phase, and over.

### Mathematical Scoring Protocol
$$\text{Score} = w_{\text{matchup}} \cdot S_{\text{matchup}} + w_{\text{phase}} \cdot S_{\text{phase}} + w_{\text{situation}} \cdot S_{\text{situation}} + w_{\text{career}} \cdot S_{\text{career}}$$

- **Matchup Weighting**: $\min(1.0, \frac{\text{balls}}{30.0})$. Bowlers with small sample sizes shrink gracefully toward their phase and career baselines.
- **Zero-Division Safety**: Handled via internal validation protocols.
- **Candidate Filtering**: Ranks available roster bowlers, outputting primary score, sub-scores, and contextual notes.

---

## 11. Installation Instructions

### Prerequisites
- Python 3.13 (64-bit)
- PostgreSQL 16+ or 18.4
- Git

### Setup Virtual Environment
```cmd
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 12. PostgreSQL Setup & Configuration

### Start PostgreSQL Service (Windows)
Open Command Prompt as Administrator:
```cmd
net start postgresql-x64-18
```

### Configure Credentials
Create `config/database.ini` from the template:
```cmd
copy config\database.ini.example config\database.ini
```
Edit `config/database.ini` with your credentials:
```ini
[postgresql]
host = localhost
port = 5432
dbname = cric_analytics
user = postgres
password = your_password
```
*(Alternatively, set environment variables: `CRIC_DB_HOST`, `CRIC_DB_PORT`, `CRIC_DB_NAME`, `CRIC_DB_USER`, `CRIC_DB_PASSWORD`)*.

---

## 13. Dataset Setup Instructions

Because `deliveries.csv` is 135.13 MB (exceeding GitHub's 100 MB hard limit), it is preserved on local disk and excluded from Git tracking via `.gitignore`.

1. Verify `data/raw/deliveries.csv` exists locally.
2. For quick test environments without the full 135 MB dataset, a 1,000-row sample is provided:
   ```cmd
   copy data\raw\deliveries_sample.csv data\raw\deliveries.csv
   ```
3. See [data/README.md](file:///C:/CRIC/data/README.md) for full dataset details.

---

## 14. Database Initialization

Run the safe, idempotent database initialization script:
```cmd
python scripts/maintenance/init_database.py
```
This connects to PostgreSQL, checks if `cric_analytics` exists, creates it if absent, and applies the consolidated schema migration and static seeds from [database/migrations/001_initial_schema.sql](file:///C:/CRIC/database/migrations/001_initial_schema.sql).

---

## 15. Data Ingestion

Execute the bulk data ingestion pipeline:
```cmd
python scripts/ingestion/load_postgres.py
```
This loads all dimensions, facts, matchups, situations, and wickets with transactional safety, deterministic 63-bit event IDs, and manifest logging into `cricket_raw.ingestion_runs`.

---

## 16. Validation Commands

Run the automated source-to-database parity and referential integrity suite:
```cmd
python scripts/validation/validate_database.py
```
Run the pre-ingestion referential integrity audit tool:
```cmd
python scripts/validation/audit_referential_integrity.py
```
Run the automated Python test suite:
```cmd
python -m pytest tests/ evaluation/
```

## 17. Running the local application

The application uses PostgreSQL analytics by default and fails clearly if the
database is unavailable; it does not silently substitute CSV results:
```cmd
python -m backend.api --source postgres --port 8765
```
Connection settings are read from `CRIC_DB_*` environment variables, then
`PG*` variables, then the optional untracked `config/database.ini`.
For an explicit offline run against local data:
```cmd
python -m backend.api --source csv --data-root data --port 8765
```
The CSV mode does not provide the PostgreSQL batter-career view.

---

## 18. Power BI Integration Status

- **Status**: **Prepared for Direct Connection (Dashboard Development Pending)**.
- **Specifications**: [powerbi/README.md](file:///C:/CRIC/powerbi/README.md) details the star schema relationships and connection settings.
- **DAX Library**: [powerbi/cric_dax_measures.dax](file:///C:/CRIC/powerbi/cric_dax_measures.dax) provides ready-to-use DAX formulas for Legal Balls, Overs Bowled, Runs Conceded, Dot Ball %, Economy Rate, Bowling Average, and Matchup Shrinkage.

---

## 19. Repository Structure

```
CRIC/
├── README.md                           # Master Project Documentation
├── .gitignore                          # Exclusions for secrets, caches, logs, and >100MB files
├── requirements.txt                    # Active Python 3.13 dependencies
├── pytest.ini                          # Test runner discovery configuration
│
├── config/
│   ├── database.ini.example            # Sanitized connection configuration template
│   └── config_loader.py                # Environment and INI configuration parser
│
├── backend/
│   ├── api.py                          # Local HTTP decision-support API
│   ├── dashboard_data.py               # Analytical aggregation adapter
│   ├── postgres_dashboard_data.py      # PostgreSQL analytics dashboard adapter
│   ├── recommendation_engine.py        # Tactical bowler recommendation scoring engine
│   ├── analytics/                      # Backward-compatible package shim
│   ├── recommendation/                 # Backward-compatible package shim
│   └── database/
│       ├── connection.py               # Psycopg 3 connection manager and pooling
│       └── repository.py               # Data repository and analytical queries
│
├── database/
│   ├── migrations/
│   │   └── 001_initial_schema.sql      # Master idempotent initial migration
│   ├── seeds/
│   │   └── 01_seed_dimensions.sql      # Dimensions seeds (phases, dismissals)
│   ├── views/
│   │   └── 05_analytics_views.sql      # Zero-division-safe analytical SQL views
│   ├── queries/                        # Analytical query templates
│   └── validation/                     # Parity and referential integrity checks
│
├── scripts/
│   ├── ingestion/
│   │   ├── init_database.py            # Database initialization entrypoint
│   │   └── load_postgres.py            # Transactional bulk data ingestion pipeline
│   ├── validation/
│   │   ├── audit_referential_integrity.py  # Pre-ingestion key and ID auditor
│   │   ├── audit_datasets.py           # Dataset size, row, and tier auditor
│   │   └── validate_database.py        # Post-ingestion parity validation harness
│   └── maintenance/
│       ├── init_database.py            # Idempotent DB initialization logic
│       ├── backup_data.py              # SHA-256 data manifest generator
│       └── cleanup_temp.py             # Temporary and cache cleanup utility
│
├── data/
│   ├── README.md                       # Data asset documentation & acquisition guide
│   ├── raw/                            # Matches, deliveries, players, wickets
│   ├── derived/                        # Matchups, situations, wicket events
│   ├── processed/                      # Historical manifests and aggregations
│   └── manifests/                      # Cryptographic ingestion manifests
│
├── docs/
│   ├── architecture/                   # Pipeline architecture, lineage, formulas, UI previews
│   └── database/                       # Data contracts and entity inventories
│
├── evaluation/                         # Historical evaluation protocols (Phases 9, 10, 11)
├── frontend/                           # Lightweight strategy exploration web interface
├── powerbi/                            # Power BI semantic model specs and DAX library
└── tests/                              # Unit, regression, scoring, and pipeline tests
```

---

## 19. Future Enhancements

- **Power BI Dashboard**: Publish interactive operational report connecting directly to `cricket_analytics` views.
- **Dynamic In-Game Win Probability**: Extend recommendation engine with ball-by-ball win-probability added (WPA) features.
- **REST / GraphQL Decision API**: Containerize the recommendation API with FastAPI for microservice deployment.
