# Phase 3 Recommendation Data Contract

## Status and scope

Version 1 is a local, deterministic, explainable ranking contract. It uses the current validated local CSV datasets. It is not a trained model, live-match feed, distributed MapReduce job, or claim of predictive accuracy.

No live match state is present in the local analytics inputs. `match_id`, `innings_number`, teams, batter-at-strike, over, remaining overs, and availability are accepted only when supplied by the caller. The service must label those values as caller supplied; it must not infer current status from historical matches or the playing-XI file.

## Data sources

The engine reads, without modifying:

| Local dataset | Required fields used |
|---|---|
| `players.csv` | `player_id`, `player_name`; identifies known batter IDs |
| `bowler_career_performance_v1.csv` | `bowler_id`, `bowler_name`, `legal_balls`, `economy`, `bowling_strike_rate_balls_per_wicket`, `wicket_rate_per_100_legal_balls` |
| `bowler_phase_performance_v1.csv` | `bowler_id`, `bowler_name`, `match_phase`, `legal_balls`, same rate fields |
| `bowler_batter_matchup_stats_v2.csv` | `bowler_id`, `batter_id`, `balls`, `runs_conceded_by_bowler`, `wickets`; optional phase-specific balls/runs/wickets columns |
| `bowler_situation_stats_v2.csv` | `bowler_id`, `situation_type`, `situation_value`, `balls`, `runs_conceded`, `wickets` |

The discovered phase labels are `Powerplay`, `Middle`, and `Death`. Situation types include `phase`, `exact_over`, `innings`, `competition`, `opposition`, `season`, and `venue`. Actual values are selected from the installed CSVs; no bowler style is present or inferred.

HDFS was not selected as the recommendation runtime source: this Phase 3 execution is local only, and the verified local copies allow deterministic local testing without HDFS/YARN service dependencies. The existing Windows HDFS remains unchanged.

## Request: `POST /api/v1/recommendations`

Content type: `application/json`; maximum request body: 1 MiB; at most 30 candidate bowlers.

```json
{
  "batter_id": "BAT1",
  "phase": "Death",
  "situation": {
    "type": "phase",
    "value": "Death"
  },
  "context": {
    "match_id": "fixture-match",
    "innings_number": 2,
    "over": 17
  },
  "candidates": [
    {
      "bowler_id": "A001"
    },
    {
      "bowler_id": "B001"
    }
  ]
}
```

`BAT1`, `A001`, and `B001` are synthetic test-fixture identifiers. This request is not a live match example.

`phase`, `situation`, and `context` are optional. Context fields are opaque caller-supplied strings/numbers; they do not affect the score. `available` defaults to true when omitted. `overs_bowled` and `overs_remaining` are optional nonnegative numeric metadata; when `overs_remaining` is zero the bowler is excluded. The API does not calculate tournament-specific over quotas or enforce team eligibility because no rules/availability feed is connected.

IDs are strings, trimmed and compared case-insensitively. Do not parse identifier-looking values as numbers (leading zeros may be significant). Duplicate normalized candidate IDs and malformed values are rejected.

Unknown batter or bowler IDs return a validation error. A known batter with no bowler/batter matchup rows remains valid; recommendations can still use phase/career statistics and explicitly disclose the missing matchup. If a situation is requested but no matching row exists, the situation component is omitted and disclosed rather than treated as zero.

## Response: `200 application/json`

```json
{
  "status": "ok",
  "execution_mode": "local_python",
  "model_type": "deterministic_interpretable_baseline",
  "batter_id": "bat1",
  "phase": "Death",
  "context": {
    "values": {
      "match_id": "fixture-match",
      "innings_number": 2,
      "over": 17
    },
    "source": "caller_supplied_not_live_verified"
  },
  "recommendations": [
    {
      "rank": 1,
      "bowler_id": "a001",
      "bowler_name": "Bowler A",
      "score": 77.08,
      "score_scale": "0_to_100_candidate_relative",
      "sample_reliability": 0.51,
      "metrics": {
        "performance": {
          "economy": 5.0,
          "bowling_strike_rate_balls_per_wicket": 12.0,
          "wicket_rate_per_100_legal_balls": 8.33,
          "sample_balls": 60.0
        },
        "matchup": {
          "economy": 4.8,
          "bowling_strike_rate_balls_per_wicket": 10.0,
          "wicket_rate_per_100_legal_balls": 10.0,
          "sample_balls": 10.0
        },
        "situation": {
          "economy": 5.0,
          "bowling_strike_rate_balls_per_wicket": 10.0,
          "wicket_rate_per_100_legal_balls": 10.0,
          "sample_balls": 60.0
        }
      },
      "score_components": {
        "performance": 83.33,
        "matchup": 62.5,
        "situation": 83.33
      },
      "evidence": [
        "Performance evidence contributes 83.3/100 after sample-size adjustment.",
        "Matchup evidence contributes 62.5/100 after sample-size adjustment.",
        "Situation evidence contributes 83.3/100 after sample-size adjustment."
      ],
      "warnings": ["matchup: very_small_sample (10 balls)"],
      "data_availability": {
        "performance": "phase",
        "matchup": "available",
        "situation": "available"
      }
    },
    {
      "rank": 2,
      "bowler_id": "b001",
      "bowler_name": "Bowler B",
      "score": 25.0,
      "score_scale": "0_to_100_candidate_relative",
      "sample_reliability": 0.5,
      "metrics": {
        "performance": {
          "economy": 7.0,
          "bowling_strike_rate_balls_per_wicket": 30.0,
          "wicket_rate_per_100_legal_balls": 3.33,
          "sample_balls": 30.0
        },
        "matchup": {
          "economy": 8.0,
          "bowling_strike_rate_balls_per_wicket": 30.0,
          "wicket_rate_per_100_legal_balls": 3.3333333333333335,
          "sample_balls": 30.0
        },
        "situation": {
          "economy": 9.0,
          "bowling_strike_rate_balls_per_wicket": 30.0,
          "wicket_rate_per_100_legal_balls": 3.3333333333333335,
          "sample_balls": 30.0
        }
      },
      "score_components": {
        "performance": 25.0,
        "matchup": 25.0,
        "situation": 25.0
      },
      "evidence": [
        "Performance evidence contributes 25.0/100 after sample-size adjustment.",
        "Matchup evidence contributes 25.0/100 after sample-size adjustment.",
        "Situation evidence contributes 25.0/100 after sample-size adjustment."
      ],
      "warnings": [],
      "data_availability": {
        "performance": "phase",
        "matchup": "available",
        "situation": "available"
      }
    }
  ],
  "excluded": [],
  "warnings": [
    "Scores are relative to the submitted eligible candidate set."
  ]
}
```

This response is generated by the deterministic test fixture in `tests/test_recommendation_engine.py`. The recommendation is synthetic and does not describe an actual player or match.

`score` is rounded to 2 decimals. It is candidate-relative, not a probability, calibrated confidence, or learned prediction. Excluded entries include `bowler_id` and a clear reason (`unavailable` or `no_overs_remaining`). A valid empty candidate list returns an empty `recommendations` array and an explanatory warning.

## Validation/error contract

| HTTP | Error code | Meaning |
|---|---|---|
| 400 | `invalid_json` | Body is not valid UTF-8 JSON syntax |
| 400 | `invalid_request` | JSON is not a request object or has missing/malformed fields, invalid types, non-finite or negative overs, repeated IDs, invalid phase, or too many candidates |
| 404 | `unknown_identifier` | Batter or candidate bowler ID is absent from the loaded local player/bowler records |
| 413 | `request_too_large` | Request body exceeds 1 MiB |
| 500 | `internal_error` | Unexpected server error; response does not expose paths, data rows, stack traces, or internal details |

Errors use `{ "error": { "code": "...", "message": "..." } }`. `sample_reliability` is the unweighted mean of the reliability terms for the defined metric/source observations contributing to the score; it is not a calibrated confidence probability. Logs record only the error category and never request bodies, player context, secrets, stack traces, or source file contents.

## Deterministic scoring contract

Candidate-relative metric utility is min-max normalized across eligible candidates:

- For economy and bowling strike rate (lower is better): `u = (max(x) - x) / (max(x) - min(x))`.
- For wicket rate (higher is better): `u = (x - min(x)) / (max(x) - min(x))`.
- If all observed candidate values tie, utility is `0.5`.
- Undefined metrics are omitted, not set to zero.

For a metric based on `n` balls, shrink toward neutral utility `0.5`:

```text
reliability = n / (n + 30)
adjusted_utility = 0.5 + reliability * (u - 0.5)
```

Source component utilities:

```text
performance = 0.45 * economy + 0.25 * strike_rate + 0.30 * wicket_rate
matchup     = 0.35 * economy + 0.25 * strike_rate + 0.40 * wicket_rate
situation   = 0.50 * economy + 0.50 * wicket_rate
```

Within each component, omit undefined metrics and renormalize that component's metric weights over defined metrics. The performance source is the requested phase row when present, otherwise the career row. Matchup uses phase-specific columns when the phase is requested and those columns have a positive ball sample; otherwise it uses overall matchup data. Situation evidence is included only for an explicitly requested `(type, value)` row.

Final score:

```text
score_utility =
  (0.60 * performance + 0.30 * matchup + 0.10 * situation)
  / sum(weights for available source components)
score = 100 * score_utility
```

When matchup or situation data are missing, omit that source component for that candidate and disclose it; never substitute zero. This means candidate scores may use different evidence coverage, which the response warns about. Sort descending by score, then normalized bowler ID ascending for deterministic ties.

Sample warnings: fewer than 12 balls is `very_small_sample`; 12–29 is `limited_sample`; 30 or more has no small-sample warning (but is not statistical validation). A zero-ball source reports that its rate metrics are unavailable. Recommender scores and reliability are not calibrated probabilities.

## Source calculation invariants

- Legal balls: `is_legal_delivery == True`.
- Bowler runs conceded: `runs_batter + extra_wides + extra_noballs`; byes, leg-byes and penalty runs are excluded.
- Bowler-credited wickets: count only `wicket_events.is_bowler_credited == True`; keep wicket events separate from credited wickets.
- Do not discard a valid zero-legal-ball bowler. Its undefined economy, strike rate, and wicket rate stay unavailable/null.
- Preserve documented group grains: career `(bowler_id, bowler_name)`, phase `(bowler_id, match_phase)`, matchup `(bowler_id, batter_id)`, situation `(bowler_id, situation_type, situation_value)`.
- No source record is edited by scoring or serving a request.
