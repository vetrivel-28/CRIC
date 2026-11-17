-- ============================================================================
-- CRIC ANALYTICS: 04_facts.sql
-- Star Schema Central Fact Tables
-- ============================================================================

-- 1. Fact Delivery (Grain: One row per ball delivered, unpartitioned table)
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

-- 2. Fact Wicket (Grain: One row per dismissal event)
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
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fact_wicket_bowler ON cricket_fact.fact_wicket(bowler_id);
CREATE INDEX IF NOT EXISTS idx_fact_wicket_player_out ON cricket_fact.fact_wicket(player_out_id);
CREATE INDEX IF NOT EXISTS idx_fact_wicket_kind ON cricket_fact.fact_wicket(kind);
CREATE INDEX IF NOT EXISTS idx_fact_wicket_credited ON cricket_fact.fact_wicket(bowler_id, is_bowler_credited);
CREATE INDEX IF NOT EXISTS idx_fact_wicket_phase ON cricket_fact.fact_wicket(over_phase);

-- 3. Fact Matchup (Grain: Bowler vs Batter Head-to-Head Aggregates)
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

-- 4. Fact Bowler Situation (Grain: Bowler performance by match state / context)
CREATE TABLE IF NOT EXISTS cricket_fact.fact_bowler_situation (
    bowler_id VARCHAR(32) NOT NULL REFERENCES cricket_dim.dim_player(player_id),
    situation_type VARCHAR(64) NOT NULL,
    situation_value VARCHAR(64) NOT NULL,
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
