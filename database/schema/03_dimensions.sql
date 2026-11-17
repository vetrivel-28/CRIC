-- ============================================================================
-- CRIC ANALYTICS: 03_dimensions.sql
-- Star Schema Dimension Tables
-- ============================================================================

-- 1. Dim Player
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

-- 2. Dim Match
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

-- 3. Dim Phase
CREATE TABLE IF NOT EXISTS cricket_dim.dim_phase (
    phase_id VARCHAR(32) PRIMARY KEY,
    phase_name VARCHAR(32) NOT NULL UNIQUE,
    start_over INT NOT NULL,
    end_over INT NOT NULL,
    description TEXT
);

-- 4. Dim Dismissal
CREATE TABLE IF NOT EXISTS cricket_dim.dim_dismissal (
    dismissal_kind VARCHAR(64) PRIMARY KEY,
    is_bowler_credited BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT
);

-- 5. Dim Team
CREATE TABLE IF NOT EXISTS cricket_dim.dim_team (
    team_name VARCHAR(128) PRIMARY KEY,
    country VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 6. Dim Venue
CREATE TABLE IF NOT EXISTS cricket_dim.dim_venue (
    venue_name VARCHAR(192) PRIMARY KEY,
    city VARCHAR(128),
    country VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
