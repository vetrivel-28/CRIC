-- ============================================================================
-- CRIC ANALYTICS: parity_checks.sql
-- Source CSV vs Database Fact Table Parity Verification
-- ============================================================================

-- 1. Deliveries Count Parity (Expected: 966,985)
SELECT
    'fact_delivery' AS table_name,
    COUNT(*) AS db_row_count,
    966985 AS expected_count,
    COUNT(*) - 966985 AS difference
FROM cricket_fact.fact_delivery;

-- 2. Matches Count Parity (Expected: 4,230)
SELECT
    'dim_match' AS table_name,
    COUNT(*) AS db_row_count,
    4230 AS expected_count,
    COUNT(*) - 4230 AS difference
FROM cricket_dim.dim_match;

-- 3. Players Count Parity (Expected: 5,261)
SELECT
    'dim_player' AS table_name,
    COUNT(*) AS db_row_count,
    5261 AS expected_count,
    COUNT(*) - 5261 AS difference
FROM cricket_dim.dim_player;

-- 4. Wickets Count Parity (Expected: 53,294)
SELECT
    'fact_wicket' AS table_name,
    COUNT(*) AS db_row_count,
    53294 AS expected_count,
    COUNT(*) - 53294 AS difference
FROM cricket_fact.fact_wicket;

-- 5. Matchups Count Parity (Expected: 131,294)
SELECT
    'fact_matchup' AS table_name,
    COUNT(*) AS db_row_count,
    131294 AS expected_count,
    COUNT(*) - 131294 AS difference
FROM cricket_fact.fact_matchup;

-- 6. Situations Count Parity (Expected: 101,163)
SELECT
    'fact_bowler_situation' AS table_name,
    COUNT(*) AS db_row_count,
    101163 AS expected_count,
    COUNT(*) - 101163 AS difference
FROM cricket_fact.fact_bowler_situation;

-- 7. Dismissals Count Parity (Expected: 14)
SELECT
    'dim_dismissal' AS table_name,
    COUNT(*) AS db_row_count,
    14 AS expected_count,
    COUNT(*) - 14 AS difference
FROM cricket_dim.dim_dismissal;

-- 8. Credited vs Uncredited Wickets Parity
SELECT
    'wicket_crediting_split' AS test_name,
    COUNT(*) FILTER (WHERE is_bowler_credited) AS credited_wickets,
    48983 AS expected_credited,
    COUNT(*) FILTER (WHERE NOT is_bowler_credited) AS uncredited_wickets,
    4311 AS expected_uncredited
FROM cricket_fact.fact_wicket;
