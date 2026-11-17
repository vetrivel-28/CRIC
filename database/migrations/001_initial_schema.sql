-- ============================================================================
-- CRIC ANALYTICS: 001_initial_schema.sql
-- Consolidated Initial Migration for PostgreSQL 16+
-- Verified against raw and derived CSV datasets with complete referential integrity
-- ============================================================================

BEGIN;

-- 1. Create isolated domain schemas
CREATE SCHEMA IF NOT EXISTS cricket_raw;
CREATE SCHEMA IF NOT EXISTS cricket_dim;
CREATE SCHEMA IF NOT EXISTS cricket_fact;
CREATE SCHEMA IF NOT EXISTS cricket_analytics;
CREATE SCHEMA IF NOT EXISTS cricket_eval;

-- 2. Ingestion Audit and Tracking Tables (cricket_raw)
CREATE TABLE IF NOT EXISTS cricket_raw.ingestion_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    status VARCHAR(32) DEFAULT 'RUNNING',  -- RUNNING, COMPLETED, FAILED
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS cricket_raw.ingestion_file_manifest (
    manifest_id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64) REFERENCES cricket_raw.ingestion_runs(run_id) ON DELETE CASCADE,
    target_table VARCHAR(128) NOT NULL,
    source_file_path TEXT NOT NULL,
    source_file_name VARCHAR(128) NOT NULL,
    sha256_checksum VARCHAR(64) NOT NULL,
    source_row_count BIGINT NOT NULL,
    inserted_row_count BIGINT NOT NULL,
    rejected_row_count BIGINT NOT NULL DEFAULT 0,
    elapsed_seconds NUMERIC(10, 3),
    status VARCHAR(32) NOT NULL, -- SUCCESS, PARTIAL, FAILED
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cricket_raw.ingestion_rejects (
    reject_id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64) REFERENCES cricket_raw.ingestion_runs(run_id) ON DELETE CASCADE,
    target_table VARCHAR(128) NOT NULL,
    source_file VARCHAR(128) NOT NULL,
    source_row_index BIGINT,
    raw_payload JSONB,
    reject_reason TEXT NOT NULL,
    rejected_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. Dimensions
CREATE TABLE IF NOT EXISTS cricket_dim.dim_player (
    player_id VARCHAR(32) PRIMARY KEY,
    player_name VARCHAR(128) NOT NULL,
    cricinfo_id BIGINT,
    full_name VARCHAR(192),
    country VARCHAR(64),
    dob VARCHAR(32),
    batting_hand VARCHAR(32),
    bowling_hand VARCHAR(32),
    bowling_type VARCHAR(64),
    bowling_category VARCHAR(64),
    primary_role VARCHAR(64),
    bats_flag BOOLEAN DEFAULT FALSE,
    bowls_flag BOOLEAN DEFAULT FALSE,
    birthplace VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dim_player_name ON cricket_dim.dim_player(player_name);
CREATE INDEX IF NOT EXISTS idx_dim_player_country ON cricket_dim.dim_player(country);
CREATE INDEX IF NOT EXISTS idx_dim_player_role ON cricket_dim.dim_player(primary_role);
CREATE INDEX IF NOT EXISTS idx_dim_player_bowling_category ON cricket_dim.dim_player(bowling_category);

CREATE TABLE IF NOT EXISTS cricket_dim.dim_match (
    match_id VARCHAR(32) PRIMARY KEY,
    competition VARCHAR(64),
    season VARCHAR(32),
    match_date DATE,
    match_type VARCHAR(32),
    event_name VARCHAR(128),
    match_number NUMERIC,
    venue VARCHAR(192),
    city VARCHAR(128),
    team_1 VARCHAR(128),
    team_2 VARCHAR(128),
    toss_winner VARCHAR(128),
    toss_decision VARCHAR(32),
    overs INT,
    balls_per_over INT DEFAULT 6,
    gender VARCHAR(16),
    winner VARCHAR(128),
    win_by_runs NUMERIC,
    win_by_wickets NUMERIC,
    result VARCHAR(32),
    outcome_method VARCHAR(64),
    eliminator VARCHAR(128),
    player_of_match VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dim_match_date ON cricket_dim.dim_match(match_date);
CREATE INDEX IF NOT EXISTS idx_dim_match_competition ON cricket_dim.dim_match(competition);
CREATE INDEX IF NOT EXISTS idx_dim_match_season ON cricket_dim.dim_match(season);
CREATE INDEX IF NOT EXISTS idx_dim_match_venue ON cricket_dim.dim_match(venue);
CREATE INDEX IF NOT EXISTS idx_dim_match_teams ON cricket_dim.dim_match(team_1, team_2);

CREATE TABLE IF NOT EXISTS cricket_dim.dim_phase (
    phase_id VARCHAR(32) PRIMARY KEY,
    phase_name VARCHAR(32) NOT NULL UNIQUE,
    start_over INT NOT NULL,
    end_over INT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS cricket_dim.dim_dismissal (
    dismissal_kind VARCHAR(64) PRIMARY KEY,
    is_bowler_credited BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS cricket_dim.dim_team (
    team_name VARCHAR(128) PRIMARY KEY,
    country VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cricket_dim.dim_venue (
    venue_name VARCHAR(192) PRIMARY KEY,
    city VARCHAR(128),
    country VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Seed static dimensions
INSERT INTO cricket_dim.dim_phase (phase_id, phase_name, start_over, end_over, description)
VALUES
    ('Powerplay', 'Powerplay', 1, 6, 'Overs 1 to 6 mandatory field restrictions'),
    ('Middle', 'Middle', 7, 15, 'Overs 7 to 15 innings consolidation, spin, and strike rotation'),
    ('Death', 'Death', 16, 20, 'Overs 16 to 20 closing overs, death bowling, and boundary acceleration'),
    ('powerplay', 'powerplay', 1, 6, 'Lowercase alias: Overs 1 to 6 field restrictions'),
    ('middle', 'middle', 7, 15, 'Lowercase alias: Overs 7 to 15 consolidation'),
    ('death', 'death', 16, 20, 'Lowercase alias: Overs 16 to 20 closing overs')
ON CONFLICT (phase_id) DO UPDATE SET
    start_over = EXCLUDED.start_over,
    end_over = EXCLUDED.end_over,
    description = EXCLUDED.description;

INSERT INTO cricket_dim.dim_dismissal (dismissal_kind, is_bowler_credited, description)
VALUES
    ('bowled', TRUE, 'Bowled: delivery hits wicket directly or off batter equipment'),
    ('caught', TRUE, 'Caught: fielder holds catch from bat or gloves'),
    ('lbw', TRUE, 'Leg Before Wicket: ball pitched in-line/off and would have hit stumps'),
    ('stumped', TRUE, 'Stumped: wicketkeeper dislodges bails while batter is out of crease'),
    ('caught and bowled', TRUE, 'Caught and bowled: return catch fielded directly by bowler'),
    ('hit wicket', TRUE, 'Hit wicket: batter or equipment dislodges bails while preparing/playing shot'),
    ('run out', FALSE, 'Run out: fielder breaks wicket while batter is out of crease (uncredited)'),
    ('retired hurt', FALSE, 'Retired hurt: batter leaves field injured without dismissal (uncredited)'),
    ('retired out', FALSE, 'Retired out: batter voluntarily retires out (uncredited)'),
    ('retired not out', FALSE, 'Retired not out: batter leaves field not out / end of innings (uncredited)'),
    ('handled the ball', FALSE, 'Handled the ball: historical dismissal type (uncredited)'),
    ('obstructing the field', FALSE, 'Obstructing the field: intentional fielder obstruction (uncredited)'),
    ('timed out', FALSE, 'Timed out: batter exceeds allotted arrival time (uncredited)'),
    ('hit the ball twice', FALSE, 'Hit the ball twice: illegal secondary contact (uncredited)')
ON CONFLICT (dismissal_kind) DO UPDATE SET
    is_bowler_credited = EXCLUDED.is_bowler_credited,
    description = EXCLUDED.description;

-- 4. Facts
CREATE TABLE IF NOT EXISTS cricket_fact.fact_delivery (
    match_id VARCHAR(32) NOT NULL REFERENCES cricket_dim.dim_match(match_id) ON DELETE CASCADE,
    innings_number INT NOT NULL,
    batting_team VARCHAR(128),
    bowling_team VARCHAR(128),
    over_number INT NOT NULL,
    ball_in_over INT NOT NULL,
    legal_ball_seq NUMERIC,
    batter_id VARCHAR(32) REFERENCES cricket_dim.dim_player(player_id),
    batter_name VARCHAR(128),
    non_striker_id VARCHAR(32) REFERENCES cricket_dim.dim_player(player_id),
    non_striker_name VARCHAR(128),
    bowler_id VARCHAR(32) REFERENCES cricket_dim.dim_player(player_id),
    bowler_name VARCHAR(128),
    runs_batter INT NOT NULL DEFAULT 0,
    runs_extras INT NOT NULL DEFAULT 0,
    runs_total INT NOT NULL DEFAULT 0,
    extra_wides NUMERIC DEFAULT 0,
    extra_noballs NUMERIC DEFAULT 0,
    extra_byes NUMERIC DEFAULT 0,
    extra_legbyes NUMERIC DEFAULT 0,
    extra_penalty NUMERIC DEFAULT 0,
    is_legal_delivery BOOLEAN NOT NULL DEFAULT TRUE,
    is_wicket BOOLEAN NOT NULL DEFAULT FALSE,
    is_powerplay BOOLEAN NOT NULL DEFAULT FALSE,
    match_phase VARCHAR(32),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_fact_delivery PRIMARY KEY (match_id, innings_number, over_number, ball_in_over)
);

CREATE INDEX IF NOT EXISTS idx_fact_delivery_bowler ON cricket_fact.fact_delivery(bowler_id);
CREATE INDEX IF NOT EXISTS idx_fact_delivery_batter ON cricket_fact.fact_delivery(batter_id);
CREATE INDEX IF NOT EXISTS idx_fact_delivery_bowler_phase ON cricket_fact.fact_delivery(bowler_id, match_phase);
CREATE INDEX IF NOT EXISTS idx_fact_delivery_matchup ON cricket_fact.fact_delivery(bowler_id, batter_id);
CREATE INDEX IF NOT EXISTS idx_fact_delivery_match_inn ON cricket_fact.fact_delivery(match_id, innings_number);
CREATE INDEX IF NOT EXISTS idx_fact_delivery_legal ON cricket_fact.fact_delivery(is_legal_delivery);

CREATE TABLE IF NOT EXISTS cricket_fact.fact_wicket (
    wicket_event_id BIGINT PRIMARY KEY,
    match_id VARCHAR(32) NOT NULL REFERENCES cricket_dim.dim_match(match_id) ON DELETE CASCADE,
    innings_number INT NOT NULL,
    over_number INT NOT NULL,
    ball_in_over INT NOT NULL,
    over_phase VARCHAR(32),
    player_out_id VARCHAR(32) REFERENCES cricket_dim.dim_player(player_id),
    player_out_name VARCHAR(128),
    bowler_id VARCHAR(32) REFERENCES cricket_dim.dim_player(player_id),
    bowler_name VARCHAR(128),
    kind VARCHAR(64) REFERENCES cricket_dim.dim_dismissal(dismissal_kind),
    is_bowler_credited BOOLEAN NOT NULL DEFAULT FALSE,
    fielder_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_wicket_natural_event UNIQUE (match_id, innings_number, over_number, ball_in_over, player_out_id)
);

CREATE INDEX IF NOT EXISTS idx_fact_wicket_bowler ON cricket_fact.fact_wicket(bowler_id);
CREATE INDEX IF NOT EXISTS idx_fact_wicket_player_out ON cricket_fact.fact_wicket(player_out_id);
CREATE INDEX IF NOT EXISTS idx_fact_wicket_kind ON cricket_fact.fact_wicket(kind);
CREATE INDEX IF NOT EXISTS idx_fact_wicket_credited ON cricket_fact.fact_wicket(bowler_id, is_bowler_credited);
CREATE INDEX IF NOT EXISTS idx_fact_wicket_phase ON cricket_fact.fact_wicket(over_phase);

CREATE TABLE IF NOT EXISTS cricket_fact.fact_matchup (
    bowler_id VARCHAR(32) NOT NULL REFERENCES cricket_dim.dim_player(player_id),
    batter_id VARCHAR(32) NOT NULL REFERENCES cricket_dim.dim_player(player_id),
    bowler_name VARCHAR(128),
    batter_name VARCHAR(128),
    matches INT DEFAULT 0,
    innings INT DEFAULT 0,
    deliveries INT DEFAULT 0,
    balls INT DEFAULT 0,
    runs_scored_by_batter INT DEFAULT 0,
    runs_conceded_by_bowler NUMERIC DEFAULT 0,
    wickets INT DEFAULT 0,
    dot_balls INT DEFAULT 0,
    fours INT DEFAULT 0,
    sixes INT DEFAULT 0,
    bowler_strike_rate NUMERIC,
    wicket_rate NUMERIC,
    dot_ball_percentage NUMERIC,
    boundary_percentage NUMERIC,
    matchup_sample_balls NUMERIC,
    matchup_sample_weight NUMERIC,
    extreme_strike_rate_flag INT DEFAULT 0,
    sample_size_flag VARCHAR(32),
    small_sample_flag INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_fact_matchup PRIMARY KEY (bowler_id, batter_id)
);

CREATE INDEX IF NOT EXISTS idx_fact_matchup_batter ON cricket_fact.fact_matchup(batter_id);
CREATE INDEX IF NOT EXISTS idx_fact_matchup_balls ON cricket_fact.fact_matchup(balls);

CREATE TABLE IF NOT EXISTS cricket_fact.fact_bowler_situation (
    bowler_id VARCHAR(32) NOT NULL REFERENCES cricket_dim.dim_player(player_id),
    situation_type VARCHAR(64) NOT NULL,
    situation_value VARCHAR(128) NOT NULL,
    cricket_over NUMERIC NOT NULL,
    bowler_name VARCHAR(128),
    matches INT DEFAULT 0,
    innings INT DEFAULT 0,
    deliveries INT DEFAULT 0,
    balls INT DEFAULT 0,
    runs_conceded NUMERIC DEFAULT 0,
    wickets INT DEFAULT 0,
    dot_balls INT DEFAULT 0,
    fours INT DEFAULT 0,
    sixes INT DEFAULT 0,
    economy NUMERIC,
    strike_rate_balls_per_wicket NUMERIC,
    dot_ball_pct NUMERIC,
    boundary_pct_of_balls NUMERIC,
    sample_size_flag VARCHAR(32),
    small_sample_flag INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_fact_bowler_situation PRIMARY KEY (bowler_id, situation_type, situation_value, cricket_over)
);

CREATE INDEX IF NOT EXISTS idx_fact_bowler_situation_type ON cricket_fact.fact_bowler_situation(situation_type, situation_value);

-- 5. Analytical Views
CREATE OR REPLACE VIEW cricket_analytics.v_bowler_career_performance AS
WITH delivery_stats AS (
    SELECT
        d.bowler_id,
        p.player_name AS bowler_name,
        p.country,
        p.bowling_category,
        p.bowling_type,
        COUNT(DISTINCT d.match_id) AS matches_bowled,
        COUNT(DISTINCT CONCAT(d.match_id, '_', d.innings_number)) AS innings_bowled,
        COUNT(*) AS total_deliveries,
        COUNT(*) FILTER (WHERE d.is_legal_delivery) AS legal_balls,
        SUM(d.runs_batter + COALESCE(d.extra_wides, 0) + COALESCE(d.extra_noballs, 0)) AS runs_conceded,
        COUNT(*) FILTER (WHERE d.is_legal_delivery AND d.runs_total = 0) AS dot_balls,
        COUNT(*) FILTER (WHERE d.runs_batter = 4) AS fours_conceded,
        COUNT(*) FILTER (WHERE d.runs_batter = 6) AS sixes_conceded
    FROM cricket_fact.fact_delivery d
    LEFT JOIN cricket_dim.dim_player p ON d.bowler_id = p.player_id
    WHERE d.bowler_id IS NOT NULL
    GROUP BY d.bowler_id, p.player_name, p.country, p.bowling_category, p.bowling_type
),
wicket_stats AS (
    SELECT
        w.bowler_id,
        COUNT(*) FILTER (WHERE w.is_bowler_credited) AS credited_wickets,
        COUNT(*) AS total_wickets_involving_bowler
    FROM cricket_fact.fact_wicket w
    WHERE w.bowler_id IS NOT NULL
    GROUP BY w.bowler_id
)
SELECT
    ds.bowler_id,
    ds.bowler_name,
    ds.country,
    ds.bowling_category,
    ds.bowling_type,
    ds.matches_bowled,
    ds.innings_bowled,
    ds.total_deliveries,
    ds.legal_balls,
    ds.runs_conceded,
    COALESCE(ws.credited_wickets, 0) AS wickets,
    ds.dot_balls,
    ds.fours_conceded,
    ds.sixes_conceded,
    ROUND(CAST(ds.runs_conceded / NULLIF(ds.legal_balls / 6.0, 0) AS NUMERIC), 2) AS economy,
    ROUND(CAST(ds.runs_conceded / NULLIF(COALESCE(ws.credited_wickets, 0), 0) AS NUMERIC), 2) AS average,
    ROUND(CAST(ds.legal_balls / NULLIF(COALESCE(ws.credited_wickets, 0), 0) AS NUMERIC), 2) AS strike_rate,
    ROUND(CAST(100.0 * ds.dot_balls / NULLIF(ds.legal_balls, 0) AS NUMERIC), 2) AS dot_ball_pct,
    ROUND(CAST(100.0 * (ds.fours_conceded + ds.sixes_conceded) / NULLIF(ds.legal_balls, 0) AS NUMERIC), 2) AS boundary_pct
FROM delivery_stats ds
LEFT JOIN wicket_stats ws ON ds.bowler_id = ws.bowler_id;

CREATE OR REPLACE VIEW cricket_analytics.v_bowler_phase_performance AS
WITH phase_deliveries AS (
    SELECT
        d.bowler_id,
        p.player_name AS bowler_name,
        INITCAP(d.match_phase) AS match_phase,
        COUNT(*) FILTER (WHERE d.is_legal_delivery) AS phase_balls,
        SUM(d.runs_batter + COALESCE(d.extra_wides, 0) + COALESCE(d.extra_noballs, 0)) AS phase_runs_conceded,
        COUNT(*) FILTER (WHERE d.is_legal_delivery AND d.runs_total = 0) AS phase_dots,
        COUNT(*) FILTER (WHERE d.runs_batter = 4) AS phase_fours,
        COUNT(*) FILTER (WHERE d.runs_batter = 6) AS phase_sixes
    FROM cricket_fact.fact_delivery d
    LEFT JOIN cricket_dim.dim_player p ON d.bowler_id = p.player_id
    WHERE d.bowler_id IS NOT NULL AND d.match_phase IS NOT NULL
    GROUP BY d.bowler_id, p.player_name, INITCAP(d.match_phase)
),
phase_wickets AS (
    SELECT
        w.bowler_id,
        INITCAP(w.over_phase) AS match_phase,
        COUNT(*) FILTER (WHERE w.is_bowler_credited) AS phase_wickets
    FROM cricket_fact.fact_wicket w
    WHERE w.bowler_id IS NOT NULL AND w.over_phase IS NOT NULL
    GROUP BY w.bowler_id, INITCAP(w.over_phase)
)
SELECT
    pd.bowler_id,
    pd.bowler_name,
    pd.match_phase,
    pd.phase_balls,
    pd.phase_runs_conceded,
    COALESCE(pw.phase_wickets, 0) AS phase_wickets,
    pd.phase_dots,
    pd.phase_fours,
    pd.phase_sixes,
    ROUND(CAST(pd.phase_runs_conceded / NULLIF(pd.phase_balls / 6.0, 0) AS NUMERIC), 2) AS phase_economy,
    ROUND(CAST(pd.phase_runs_conceded / NULLIF(COALESCE(pw.phase_wickets, 0), 0) AS NUMERIC), 2) AS phase_average,
    ROUND(CAST(pd.phase_balls / NULLIF(COALESCE(pw.phase_wickets, 0), 0) AS NUMERIC), 2) AS phase_strike_rate,
    ROUND(CAST(100.0 * pd.phase_dots / NULLIF(pd.phase_balls, 0) AS NUMERIC), 2) AS phase_dot_pct
FROM phase_deliveries pd
LEFT JOIN phase_wickets pw ON pd.bowler_id = pw.bowler_id AND pd.match_phase = pw.match_phase;

CREATE OR REPLACE VIEW cricket_analytics.v_bowler_batter_matchups AS
SELECT
    m.bowler_id,
    m.batter_id,
    m.bowler_name,
    m.batter_name,
    m.matches,
    m.innings,
    m.balls,
    m.runs_scored_by_batter,
    m.runs_conceded_by_bowler,
    m.wickets,
    m.dot_balls,
    m.fours,
    m.sixes,
    ROUND(CAST(m.runs_conceded_by_bowler / NULLIF(m.balls / 6.0, 0) AS NUMERIC), 2) AS economy,
    ROUND(CAST(m.runs_conceded_by_bowler / NULLIF(m.wickets, 0) AS NUMERIC), 2) AS average,
    ROUND(CAST(m.balls / NULLIF(m.wickets, 0) AS NUMERIC), 2) AS strike_rate,
    ROUND(CAST(100.0 * m.dot_balls / NULLIF(m.balls, 0) AS NUMERIC), 2) AS dot_ball_pct,
    ROUND(CAST(100.0 * (m.fours + m.sixes) / NULLIF(m.balls, 0) AS NUMERIC), 2) AS boundary_pct,
    ROUND(CAST(LEAST(1.0, m.balls / 30.0) AS NUMERIC), 3) AS matchup_sample_weight,
    m.sample_size_flag
FROM cricket_fact.fact_matchup m;

CREATE OR REPLACE VIEW cricket_analytics.v_bowler_situation_performance AS
SELECT
    s.bowler_id,
    s.bowler_name,
    s.situation_type,
    s.situation_value,
    s.cricket_over,
    s.matches,
    s.balls,
    s.runs_conceded,
    s.wickets,
    s.dot_balls,
    s.economy,
    s.strike_rate_balls_per_wicket,
    s.dot_ball_pct,
    s.boundary_pct_of_balls,
    s.sample_size_flag
FROM cricket_fact.fact_bowler_situation s;

CREATE OR REPLACE VIEW cricket_analytics.v_wicket_profiles AS
SELECT
    w.bowler_id,
    w.bowler_name,
    COUNT(*) AS total_wickets,
    COUNT(*) FILTER (WHERE w.is_bowler_credited) AS credited_wickets,
    COUNT(*) FILTER (WHERE w.kind = 'bowled') AS bowled,
    COUNT(*) FILTER (WHERE w.kind = 'caught') AS caught,
    COUNT(*) FILTER (WHERE w.kind = 'lbw') AS lbw,
    COUNT(*) FILTER (WHERE w.kind = 'stumped') AS stumped,
    COUNT(*) FILTER (WHERE w.kind = 'caught and bowled') AS caught_and_bowled,
    COUNT(*) FILTER (WHERE w.kind = 'hit wicket') AS hit_wicket,
    COUNT(*) FILTER (WHERE w.kind = 'run out') AS run_outs,
    ROUND(CAST(100.0 * COUNT(*) FILTER (WHERE w.kind IN ('bowled', 'lbw')) / NULLIF(COUNT(*) FILTER (WHERE w.is_bowler_credited), 0) AS NUMERIC), 2) AS pct_bowled_or_lbw
FROM cricket_fact.fact_wicket w
WHERE w.bowler_id IS NOT NULL
GROUP BY w.bowler_id, w.bowler_name;

CREATE OR REPLACE VIEW cricket_analytics.v_season_bowling_performance AS
WITH season_deliveries AS (
    SELECT
        d.bowler_id,
        d.bowler_name,
        m.season,
        COUNT(DISTINCT d.match_id) AS season_matches,
        COUNT(*) FILTER (WHERE d.is_legal_delivery) AS season_balls,
        SUM(d.runs_batter + COALESCE(d.extra_wides, 0) + COALESCE(d.extra_noballs, 0)) AS season_runs
    FROM cricket_fact.fact_delivery d
    JOIN cricket_dim.dim_match m ON d.match_id = m.match_id
    WHERE d.bowler_id IS NOT NULL
    GROUP BY d.bowler_id, d.bowler_name, m.season
),
season_wickets AS (
    SELECT
        w.bowler_id,
        m.season,
        COUNT(*) FILTER (WHERE w.is_bowler_credited) AS season_wickets
    FROM cricket_fact.fact_wicket w
    JOIN cricket_dim.dim_match m ON w.match_id = m.match_id
    WHERE w.bowler_id IS NOT NULL
    GROUP BY w.bowler_id, m.season
)
SELECT
    sd.bowler_id,
    sd.bowler_name,
    sd.season,
    sd.season_matches,
    sd.season_balls,
    sd.season_runs,
    COALESCE(sw.season_wickets, 0) AS season_wickets,
    ROUND(CAST(sd.season_runs / NULLIF(sd.season_balls / 6.0, 0) AS NUMERIC), 2) AS season_economy,
    ROUND(CAST(sd.season_runs / NULLIF(COALESCE(sw.season_wickets, 0), 0) AS NUMERIC), 2) AS season_average
FROM season_deliveries sd
LEFT JOIN season_wickets sw ON sd.bowler_id = sw.bowler_id AND sd.season = sw.season;

CREATE OR REPLACE VIEW cricket_analytics.v_batter_career_performance AS
WITH batter_deliveries AS (
    SELECT
        d.batter_id,
        p.player_name AS batter_name,
        p.country,
        p.batting_hand,
        COUNT(DISTINCT d.match_id) AS matches_batted,
        COUNT(DISTINCT CONCAT(d.match_id, '_', d.innings_number)) AS innings_batted,
        COUNT(*) FILTER (WHERE COALESCE(d.extra_wides, 0) = 0) AS balls_faced,
        SUM(d.runs_batter) AS runs_scored,
        COUNT(*) FILTER (WHERE d.runs_batter = 4) AS fours,
        COUNT(*) FILTER (WHERE d.runs_batter = 6) AS sixes,
        COUNT(*) FILTER (WHERE d.runs_batter = 0 AND COALESCE(d.extra_wides, 0) = 0) AS dot_balls_faced
    FROM cricket_fact.fact_delivery d
    LEFT JOIN cricket_dim.dim_player p ON d.batter_id = p.player_id
    WHERE d.batter_id IS NOT NULL
    GROUP BY d.batter_id, p.player_name, p.country, p.batting_hand
),
batter_dismissals AS (
    SELECT
        w.player_out_id AS batter_id,
        COUNT(*) AS dismissals
    FROM cricket_fact.fact_wicket w
    GROUP BY w.player_out_id
)
SELECT
    bd.batter_id,
    bd.batter_name,
    bd.country,
    bd.batting_hand,
    bd.matches_batted,
    bd.innings_batted,
    bd.balls_faced,
    bd.runs_scored,
    COALESCE(bdis.dismissals, 0) AS dismissals,
    bd.fours,
    bd.sixes,
    bd.dot_balls_faced,
    ROUND(CAST(100.0 * bd.runs_scored / NULLIF(bd.balls_faced, 0) AS NUMERIC), 2) AS strike_rate,
    ROUND(CAST(bd.runs_scored / NULLIF(COALESCE(bdis.dismissals, 0), 0) AS NUMERIC), 2) AS batting_average,
    ROUND(CAST(100.0 * (bd.fours * 4 + bd.sixes * 6) / NULLIF(bd.runs_scored, 0) AS NUMERIC), 2) AS boundary_run_pct
FROM batter_deliveries bd
LEFT JOIN batter_dismissals bdis ON bd.batter_id = bdis.batter_id;

-- 6. Evaluation Store
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

COMMIT;
