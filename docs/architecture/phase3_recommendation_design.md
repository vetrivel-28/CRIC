# Phase 3 Recommendation Engine Design

## Status

This document records the implemented Phase 3 design. Phase 3 is local Python processing over existing CSVs. It does not enable Linux, YARN, MapReduce, Hive, Pig, HBase writes, live-match integration, or machine learning.

## Inspection findings

- `backend\` and `frontend\` have no files or established framework/routes.
- `data\CRIC_project_starter\CRIC_project_starter\src\recommend_bowler.py` is an existing standalone matchup-CSV CLI. It filters a batter by name/ID and ranks aggregate matchups, but assumes columns by aliases, uses unadjusted rank scores, writes beneath a relative `reports\` directory, and has no career/phase/situation context. Preserve it; the new engine is an additive implementation.
- `phase2_outputs\processed\career_aggregates_phase2.csv`, `phase_aggregates_phase2.csv`, and `credited_wickets_phase2.csv` are local outputs. The underlying validated local CSVs include career (3,190 rows), phase (7,976), wicket events (53,294), batter-bowler matchup (131,294), and bowler-situation aggregates (schema-specific rows).
- Source schemas have ID columns such as `bowler_id`, `batter_id`, and `player_id`; matchup metrics include balls, bowler-conceded runs, wickets, and phase-specific totals. Phase labels in data are `Powerplay`, `Middle`, `Death`.
- Prior local/HDFS integrity evidence records 24 matching critical CSVs. The previously verified local deliveries copy was 141,695,079 bytes with SHA-256 `C6DDFD575A5ABA9CEB0F68084688F1DE6350EBAE6DB309D55B7BB78C77B05D7A`. Phase 3 freshly checks 966,985 delivery rows, 925,882 legal balls, 53,294 wicket events, and 48,983 bowler-credited wickets.
- The final targeted Phase 2 + Phase 3 run passes all 30 tests, including the four documented source-count baselines.
- Current local source results are used, not a live query of Windows HDFS. Phase 2 historically reported YARN stopped after a NodeManager permission failure; Phase 3 did not recheck service state. Do not label this as distributed execution.

## Architecture

The Python recommendation module is implemented in `backend\recommendation_engine.py`; the standard-library HTTP API entrypoint is `backend\api.py`. This avoids selecting or installing a new web framework in a project with no backend architecture. Bind the API to `127.0.0.1` by default; use explicit local CLI configuration for data paths. Do not add CORS, authentication, or network exposure until a real deployment boundary is designed.

Components:

1. **Data catalog:** stream the local player, career, phase, matchup, and situation CSVs once at engine startup; normalize column names and player IDs consistently; retain numeric nulls.
2. **Request validation:** require a known batter ID and known bowler IDs; validate phase labels, numeric overs, candidate limit, duplicate IDs, and optional situation shape. Client-supplied context is descriptive only.
3. **Eligibility:** exclude candidates explicitly marked unavailable or with zero overs remaining; report every exclusion.
4. **Scoring:** compute comparable candidate-relative component utilities with sample-size shrinkage; explain metrics, selected source, sample balls, warnings, and missing evidence.
5. **API:** `GET /health` reports service readiness without file paths; `POST /api/v1/recommendations` returns the documented response or an actionable validation error.
6. **No mutable artifacts:** service reads CSVs and returns JSON; it does not write recommendation CSVs or mutate datasets.

No optional model is trained. The output describes a heuristic score, not expected outcomes or win probability.

## Ranking and score

Direction-aware metric utility is min-max normalized across eligible submitted candidates. Lower economy and strike rate are better; higher wicket rate is better. A tie across the candidate set maps to neutral utility 0.5. Undefined values are omitted and weights renormalized; never coerce missing rates to zero.

Sample shrinkage for a metric with `n` balls:

```text
reliability = n / (n + 30)
adjusted_utility = 0.5 + reliability * (utility - 0.5)
```

Component metric weights:

```text
performance = 0.45 economy + 0.25 strike-rate + 0.30 wicket-rate
matchup     = 0.35 economy + 0.25 strike-rate + 0.40 wicket-rate
situation   = 0.50 economy + 0.50 wicket-rate
```

The performance metrics come from the requested phase row when present, otherwise the career row. Matchup values use requested phase-specific aggregate columns when available and sampled, otherwise the full batter-bowler matchup. Situation metrics are used only for an explicitly provided situation key. Blend present component scores at performance/matchup/situation weights `0.60/0.30/0.10`, renormalized over components available to that candidate. Source omissions are explicit warnings. Scores are candidate-relative, non-probabilistic, and are not calibrated.

`backend\recommendation_engine.py` exposes a typed `RecommendationConfig` for weights, reliability prior, and sample warning thresholds. API clients cannot override weights per request, avoiding arbitrary score variation between consumers.

## Data and sport-rule boundaries

The source aggregates provide historical ball/run/wicket data and IDs, but do not provide actual current match status or bowler availability. Accept match, innings, teams, over and status only as caller-supplied context. Do not use `match_playing_xi.csv` as a current availability feed. Do not infer bowling styles.

Preserve:

- legal ball definition `is_legal_delivery == True`;
- conceded runs `runs_batter + extra_wides + extra_noballs`;
- bowler wicket credit from `is_bowler_credited`, distinct from all wicket events;
- zero-legal-ball records and undefined rates;
- phase/matchup/situation grouping grains and missing-phase behavior as documented;
- source names/IDs without integer coercion, because IDs may contain leading zeroes.

## Test plan

Use tmp-path CSV fixtures for deterministic unit/API tests. Cover schema, identifier normalization, unknown IDs, unmatched batter-bowler pairs, absent optional situation rows, null/zero denominator handling, small sample shrinkage, exclusions, directionality, deterministic repeats, empty eligible candidates, malformed JSON/body/request, no source mutation, and local execution labeling. The tests also stream the existing deliveries and wicket-event files and assert 966,985 delivery rows, 925,882 legal balls, 53,294 wicket events, and 48,983 bowler-credited wickets.

## API and integration boundary

The backend directory is empty, so there is no existing service framework to preserve. The first implementation uses Python's standard-library HTTP server and no new runtime dependency. API contract and response example are in [phase3_data_contract.md](./phase3_data_contract.md). The frontend directory is also empty; the API contract is prepared for later UI work, but no frontend or live data feed is included.

## Execution labels

Responses include `execution_mode: "local_python"` and `model_type: "deterministic_interpretable_baseline"`. Phase 2 recorded a NodeManager permission failure and no MapReduce job; Phase 3 did not recheck current YARN service state or submit a job.
