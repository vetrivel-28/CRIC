-- ============================================================================
-- CRIC ANALYTICS: 01_seed_dimensions.sql
-- Static Dimension Seeds for Match Phases and Dismissal Types
-- ============================================================================

-- 1. Dim Phase (Supports both Title Case as found in CSVs and Lowercase aliases)
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

-- 2. Dim Dismissal (Strict Bowler Crediting Rules - 100% verified against raw/derived CSVs)
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
