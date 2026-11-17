-- ============================================================================
-- CRIC ANALYTICS: referential_integrity.sql
-- Referential Integrity & Orphan Record Verification
-- ============================================================================

-- 1. Deliveries referencing non-existent matches (Expected: 0)
SELECT
    'orphan_deliveries_match' AS check_name,
    COUNT(*) AS orphan_count
FROM cricket_fact.fact_delivery d
LEFT JOIN cricket_dim.dim_match m ON d.match_id = m.match_id
WHERE m.match_id IS NULL;

-- 2. Deliveries referencing non-existent bowlers (Expected: 0)
SELECT
    'orphan_deliveries_bowler' AS check_name,
    COUNT(*) AS orphan_count
FROM cricket_fact.fact_delivery d
LEFT JOIN cricket_dim.dim_player p ON d.bowler_id = p.player_id
WHERE d.bowler_id IS NOT NULL AND p.player_id IS NULL;

-- 3. Deliveries referencing non-existent batters (Expected: 0)
SELECT
    'orphan_deliveries_batter' AS check_name,
    COUNT(*) AS orphan_count
FROM cricket_fact.fact_delivery d
LEFT JOIN cricket_dim.dim_player p ON d.batter_id = p.player_id
WHERE d.batter_id IS NOT NULL AND p.player_id IS NULL;

-- 4. Deliveries referencing non-existent non-strikers (Expected: 0)
SELECT
    'orphan_deliveries_non_striker' AS check_name,
    COUNT(*) AS orphan_count
FROM cricket_fact.fact_delivery d
LEFT JOIN cricket_dim.dim_player p ON d.non_striker_id = p.player_id
WHERE d.non_striker_id IS NOT NULL AND p.player_id IS NULL;

-- 5. Wickets referencing non-existent matches (Expected: 0)
SELECT
    'orphan_wickets_match' AS check_name,
    COUNT(*) AS orphan_count
FROM cricket_fact.fact_wicket w
LEFT JOIN cricket_dim.dim_match m ON w.match_id = m.match_id
WHERE m.match_id IS NULL;

-- 6. Wickets referencing non-existent dismissed players (Expected: 0)
SELECT
    'orphan_wickets_player_out' AS check_name,
    COUNT(*) AS orphan_count
FROM cricket_fact.fact_wicket w
LEFT JOIN cricket_dim.dim_player p ON w.player_out_id = p.player_id
WHERE p.player_id IS NULL;

-- 7. Wickets referencing non-existent dismissal kinds (Expected: 0)
SELECT
    'invalid_dismissal_kind' AS check_name,
    COUNT(*) AS invalid_count
FROM cricket_fact.fact_wicket w
LEFT JOIN cricket_dim.dim_dismissal dis ON w.kind = dis.dismissal_kind
WHERE dis.dismissal_kind IS NULL;

-- 8. Matchups referencing non-existent bowlers or batters (Expected: 0)
SELECT
    'orphan_matchup_entities' AS check_name,
    COUNT(*) AS orphan_count
FROM cricket_fact.fact_matchup m
WHERE NOT EXISTS (SELECT 1 FROM cricket_dim.dim_player p WHERE p.player_id = m.bowler_id)
   OR NOT EXISTS (SELECT 1 FROM cricket_dim.dim_player p WHERE p.player_id = m.batter_id);
