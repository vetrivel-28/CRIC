-- ============================================================================
-- CRIC ANALYTICS: 06_eval_audit.sql
-- Evaluation & Shadow Deployment Event Ledger (Merkle-style Hash Chaining)
-- ============================================================================

CREATE TABLE IF NOT EXISTS cricket_eval.eval_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    run_type VARCHAR(64) NOT NULL,
    model_version VARCHAR(32) NOT NULL,
    config_hash VARCHAR(64),
    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    status VARCHAR(32) DEFAULT 'RUNNING',
    metrics_summary JSONB
);

CREATE TABLE IF NOT EXISTS cricket_eval.events (
    event_id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL REFERENCES cricket_eval.eval_runs(run_id) ON DELETE CASCADE,
    sequence_number BIGINT NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    event_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    payload JSONB NOT NULL,
    prev_event_hash VARCHAR(64),
    event_hash VARCHAR(64) NOT NULL,
    CONSTRAINT uq_run_sequence UNIQUE (run_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS idx_eval_events_run_id ON cricket_eval.events(run_id);
CREATE INDEX IF NOT EXISTS idx_eval_events_type ON cricket_eval.events(event_type);

CREATE TABLE IF NOT EXISTS cricket_eval.model_decisions (
    decision_id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64) REFERENCES cricket_eval.eval_runs(run_id) ON DELETE SET NULL,
    match_id VARCHAR(32),
    innings_number INT,
    over_number INT,
    situation_context JSONB,
    recommended_bowler_id VARCHAR(32),
    recommended_bowler_name VARCHAR(128),
    candidate_scores JSONB,
    actual_bowler_id VARCHAR(32),
    actual_runs_conceded INT,
    actual_wickets INT,
    decision_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eval_decisions_match ON cricket_eval.model_decisions(match_id, innings_number, over_number);
