-- ============================================================================
-- CRIC ANALYTICS: 02_raw_staging.sql
-- Raw staging tables matching original CSV structure with metadata tracking
-- ============================================================================

-- Staging: Deliveries (966,985 records)
CREATE TABLE IF NOT EXISTS cricket_raw.raw_deliveries (
    match_id TEXT,
    innings_number INT,
    batting_team TEXT,
    bowling_team TEXT,
    over_number INT,
    ball_in_over INT,
    legal_ball_seq NUMERIC,
    batter_id TEXT,
    batter_name TEXT,
    non_striker_id TEXT,
    non_striker_name TEXT,
    bowler_id TEXT,
    bowler_name TEXT,
    runs_batter INT,
    runs_extras INT,
    runs_total INT,
    extra_wides NUMERIC,
    extra_noballs NUMERIC,
    extra_byes NUMERIC,
    extra_legbyes NUMERIC,
    extra_penalty NUMERIC,
    is_legal_delivery BOOLEAN,
    is_wicket BOOLEAN,
    is_powerplay BOOLEAN,
    match_phase TEXT,
    _ingestion_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    _source_file TEXT DEFAULT 'deliveries.csv'
);

-- Staging: Matches (4,230 records)
CREATE TABLE IF NOT EXISTS cricket_raw.raw_matches (
    match_id TEXT,
    source_file TEXT,
    competition TEXT,
    season TEXT,
    date DATE,
    match_type TEXT,
    event_name TEXT,
    match_number NUMERIC,
    venue TEXT,
    city TEXT,
    team_1 TEXT,
    team_2 TEXT,
    toss_winner TEXT,
    toss_decision TEXT,
    overs INT,
    balls_per_over INT,
    gender TEXT,
    winner TEXT,
    win_by_runs NUMERIC,
    win_by_wickets NUMERIC,
    result TEXT,
    outcome_method TEXT,
    eliminator TEXT,
    player_of_match TEXT,
    _ingestion_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Staging: Players (5,261 records)
CREATE TABLE IF NOT EXISTS cricket_raw.raw_players (
    player_id TEXT,
    player_name TEXT,
    _ingestion_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Staging: Combined Player Metadata (5,261 records)
CREATE TABLE IF NOT EXISTS cricket_raw.raw_combined_players (
    player_id TEXT,
    player_name TEXT,
    cricinfo_id NUMERIC,
    full_name TEXT,
    country TEXT,
    dob TEXT,
    batting_hand TEXT,
    bowling_hand TEXT,
    bowling_type TEXT,
    bowling_category TEXT,
    primary_role TEXT,
    bats_flag TEXT,
    bowls_flag TEXT,
    birthplace TEXT,
    _ingestion_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Staging: Raw Wickets (53,294 records)
CREATE TABLE IF NOT EXISTS cricket_raw.raw_wickets (
    match_id TEXT,
    innings_number INT,
    over_number INT,
    ball_in_over INT,
    player_out_id TEXT,
    player_out_name TEXT,
    bowler_id TEXT,
    bowler_name TEXT,
    kind TEXT,
    fielder_count INT,
    _ingestion_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Staging: Wicket Events with Crediting (53,294 records)
CREATE TABLE IF NOT EXISTS cricket_raw.raw_wicket_events (
    wicket_event_id BIGINT,
    match_id TEXT,
    innings_number INT,
    over_number INT,
    ball_in_over INT,
    over_phase TEXT,
    player_out_id TEXT,
    player_out_name TEXT,
    bowler_id TEXT,
    bowler_name TEXT,
    kind TEXT,
    is_bowler_credited BOOLEAN,
    fielder_count INT,
    _ingestion_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Staging: Bowler-Batter Matchup Stats (131,294 records)
CREATE TABLE IF NOT EXISTS cricket_raw.raw_matchups (
    bowler_id TEXT,
    batter_id TEXT,
    bowler_name TEXT,
    batter_name TEXT,
    matches INT,
    innings INT,
    deliveries INT,
    balls INT,
    runs_scored_by_batter INT,
    runs_conceded_by_bowler NUMERIC,
    wickets INT,
    dot_balls INT,
    fours INT,
    sixes INT,
    bowler_strike_rate_balls_per_wicket NUMERIC,
    wicket_rate_per_100_balls NUMERIC,
    dot_ball_pct NUMERIC,
    caught_wickets INT,
    bowled_wickets INT,
    lbw_wickets INT,
    caught_and_bowled_wickets INT,
    stumped_wickets INT,
    hit_wicket_wickets INT,
    phase_balls_powerplay INT,
    phase_runs_scored_powerplay INT,
    phase_runs_conceded_powerplay NUMERIC,
    phase_wickets_powerplay NUMERIC,
    phase_dots_powerplay INT,
    phase_fours_powerplay INT,
    phase_sixes_powerplay INT,
    phase_balls_middle INT,
    phase_runs_scored_middle INT,
    phase_runs_conceded_middle NUMERIC,
    phase_wickets_middle NUMERIC,
    phase_dots_middle INT,
    phase_fours_middle INT,
    phase_sixes_middle INT,
    phase_balls_death INT,
    phase_runs_scored_death INT,
    phase_runs_conceded_death NUMERIC,
    phase_wickets_death NUMERIC,
    phase_dots_death INT,
    phase_fours_death INT,
    phase_sixes_death INT,
    bowler_strike_rate NUMERIC,
    wicket_rate NUMERIC,
    dot_ball_percentage NUMERIC,
    boundary_percentage NUMERIC,
    boundary_pct_of_balls NUMERIC,
    strike_rate_balls_per_wicket NUMERIC,
    matchup_sample_balls NUMERIC,
    matchup_sample_weight NUMERIC,
    extreme_strike_rate_flag INT,
    sample_size_flag TEXT,
    small_sample_flag INT,
    _ingestion_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Staging: Bowler Situation Stats (101,163 records)
CREATE TABLE IF NOT EXISTS cricket_raw.raw_situations (
    bowler_id TEXT,
    bowler_name TEXT,
    situation_type TEXT,
    situation_value TEXT,
    cricket_over NUMERIC,
    matches INT,
    innings INT,
    deliveries INT,
    balls INT,
    runs_conceded NUMERIC,
    runs_batter_faced INT,
    wickets INT,
    dot_balls INT,
    fours INT,
    sixes INT,
    economy NUMERIC,
    strike_rate_balls_per_wicket NUMERIC,
    wicket_rate_per_100_balls NUMERIC,
    dot_ball_pct NUMERIC,
    boundary_pct_of_balls NUMERIC,
    average_runs_per_wicket NUMERIC,
    sample_size_flag TEXT,
    small_sample_flag INT,
    _ingestion_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================================
-- Ingestion Tracking & Audit Tables
-- ============================================================================

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
