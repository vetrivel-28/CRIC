-- ============================================================================
-- CRIC ANALYTICS: 01_schemas.sql
-- Creates isolated, domain-driven analytical schemas in PostgreSQL 16+
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS cricket_raw;
COMMENT ON SCHEMA cricket_raw IS 'Staging layer for unmutated, raw CSV ingested cricket datasets';

CREATE SCHEMA IF NOT EXISTS cricket_dim;
COMMENT ON SCHEMA cricket_dim IS 'Star schema dimensional entities (players, matches, phases, dismissals, teams, venues)';

CREATE SCHEMA IF NOT EXISTS cricket_fact;
COMMENT ON SCHEMA cricket_fact IS 'Star schema central fact tables (deliveries, wickets, head-to-head matchups, match situations)';

CREATE SCHEMA IF NOT EXISTS cricket_analytics;
COMMENT ON SCHEMA cricket_analytics IS 'Aggregated analytical views and reporting structures powering BI queries';

CREATE SCHEMA IF NOT EXISTS cricket_eval;
COMMENT ON SCHEMA cricket_eval IS 'Decision audit logs, candidate evaluation tracking, and shadow deployment event ledger';
