# CRIC Power BI Analytics Dashboard

## Current deliverable

The supported internal authoring deliverable is `powerbi/CRIC_Analytics_Dashboard_v2.pbip`, with the report and semantic model in:

- `powerbi/CRIC_Analytics_Dashboard_v2.Report`
- `powerbi/CRIC_Analytics_Dashboard_v2.SemanticModel`

The local pbi-tools 1.2.0 release could not compile a PBIT/PBIX because it is incompatible with the installed Power BI Desktop build. No PBIX was fabricated or renamed.

To create the PBIX after opening the PBIP:

1. In Power BI Desktop, open `CRIC_Analytics_Dashboard_v2.pbip`.
2. Enter PostgreSQL credentials through the secure credential dialog.
3. Refresh the semantic model.
4. Save As `C:\CRIC\powerbi\CRIC_Analytics_Dashboard_v2.pbix`.
5. Close and reopen the PBIX and refresh again before certification.

**File:** `powerbi/CRIC_Analytics_Dashboard.pbix`  
**Theme:** `powerbi/cric_premium_ivory_emerald_theme.json`  
**DAX Measures:** `powerbi/cric_dax_measures.dax`  
**Data Warehouse:** PostgreSQL 18.4 (`cric_analytics`)  
**Design Palette:** Premium Ivory + Emerald (`#F6F5EF`, `#075B40`, `#B6D9C5`, `#D6AA46`, `#26352F`, `#FFFFFF`)

---

## 1. Relational Semantic Model & Architecture

The CRIC Power BI semantic model connects directly to PostgreSQL 18.4 running at `127.0.0.1:5432` against the database `cric_analytics`.

### Core Tables & Analytical Views
1. **`dim_player`** (`cricket_dim.dim_player`): Player registry (5,261 players).
2. **`dim_match`** (`cricket_dim.dim_match`): Match metadata across 4,230 fixtures.
3. **`dim_dismissal`** (`cricket_dim.dim_dismissal`): Dismissal mode classifications (14 kinds).
4. **`v_bowler_career_performance`** (`cricket_analytics`): Career bowling statistics across 3,190 bowlers.
5. **`v_bowler_phase_performance`** (`cricket_analytics`): Phase-stratified bowling performance (7,976 records).
6. **`v_bowler_batter_matchups`** (`cricket_analytics`): Head-to-head records across 131,294 pairs.
7. **`v_bowler_situation_performance`** (`cricket_analytics`): Contextual bowling metrics (101,163 records).
8. **`v_wicket_profiles`** (`cricket_analytics`): Dismissal profiles across 2,744 bowlers.
9. **`v_season_bowling_performance`** (`cricket_analytics`): Season-wise performance across 10,414 bowler-seasons.
10. **`v_batter_career_performance`** (`cricket_analytics`): Career batting totals across 4,267 batters.
11. **`CRIC_Measures`**: Dedicated measure container for standardized DAX calculations.

### Model Relationships
- `dim_player[player_id]` 1:M `v_bowler_career_performance[bowler_id]`
- `dim_player[player_id]` 1:M `v_batter_career_performance[batter_id]`
- `dim_player[player_id]` 1:M `v_bowler_phase_performance[bowler_id]`
- `dim_player[player_id]` 1:M `v_bowler_batter_matchups[bowler_id]`
- `dim_match[season]` 1:M `v_season_bowling_performance[season]` (via synchronized slicers)

---

## 2. Report Pages & Visual Structure

### Page 1: Executive Overview
- **KPI Cards:** Total Matches (4,230), Total Bowlers (3,190), Total Batters (4,267), Total Credited Wickets (48,983), Overall Economy (8.07).
- **Phase Breakdown Chart:** Credited wickets by match phase (Powerplay, Middle, Death).
- **Season Trend Chart:** Cumulative and season-wise wickets across all 29 seasons.
- **Global Season Slicer:** Synced across report pages (Default: `2022 onwards`).

### Page 2: Bowler Intelligence
- **Bowler Performance Table:** Bowler Name, Legal Balls, Runs Conceded, Wickets, Economy, Bowling Strike Rate, Bowling Average.
- **Scatter Plot:** Bowling Strike Rate vs Economy Rate (Bubble size = Legal Balls).
- **Selected Bowler Metrics:** Dynamic cards updating on bowler selection.
- **Searchable Slicer:** Single-select dropdown with typeahead search.

### Page 3: Batter Intelligence
- **Batter Rankings Table:** Batter Name, Runs Scored, Balls Faced, Strike Rate, Batting Average, Dismissals.
- **Top 10 Batters Chart:** Horizontal bar chart of all-time leading run-scorers.
- **Strike Rate vs Average:** Scatter analysis of batting efficiency.
- **Searchable Slicer:** Single-select batter filter.

### Page 4: Bowler vs Batter Matchups
- **Matchup Grid:** Bowler Name, Batter Name, Legal Balls, Runs Conceded, Dismissals, Economy, Dot Balls, Sample Reliability Flag.
- **Sample Reliability Indicator:** Highlights matchups exceeding the 30 legal-ball threshold.
- **Interactive Slicers:** Dual Bowler and Batter slicers + minimum ball threshold filter.

### Page 5: Phase Analysis
- **Phase Economy Comparison:** Column chart comparing Powerplay vs Middle vs Death economy rates.
- **Phase Wicket Rates:** Strike rates and wicket frequencies across match intervals.
- **Bowler Rankings by Phase:** Sortable table ranking bowlers within selected phase.

### Page 6: Situation Intelligence
- **Situation Breakdown Table:** Bowler Name, Situation Type (e.g. Innings, RRR Tier), Situation Value, Balls, Runs, Wickets, Economy.
- **Match Context Matrix:** Visualizes bowler effectiveness under chasing pressure.

### Page 7: Wicket Intelligence
- **Dismissal Type Distribution:** Donut chart of all 14 dismissal modes (Caught, Bowled, LBW, Stumped, etc.).
- **Bowler Wicket Profiles:** Stacked bar chart showing bowler-credited breakdown (Bowled vs LBW vs Caught).
- **Wicket Trajectory:** Multi-year trend line of dismissal volumes.

### Page 8: Match Strategy / Decision Support
- **Recommended Bowlers Table:** Rank, Bowler Name, Composite Recommendation Score (0–100), Economy, Strike Rate, Sample Reliability.
- **Decision Support Protocol Card:** Outlines fixed multi-component weights (Performance 60%, Matchup 30%, Situation 10%) and 30-ball prior.

---

## 3. PostgreSQL Connection & Refresh Instructions

### Prerequisites
- PostgreSQL 16+ or 18.4 installed and running locally on port `5432`.
- Target database: `cric_analytics`.
- User credentials configured in `config/database.ini` or system environment (`CRIC_DB_PASSWORD`).

### Step-by-Step Refresh in Power BI Desktop
1. Open `powerbi/CRIC_Analytics_Dashboard.pbix` in Power BI Desktop.
2. In the Home ribbon, click **Transform Data** > **Data Source Settings**.
3. Under **Data sources in current file**, select `PostgreSQL: 127.0.0.1:5432; cric_analytics`.
4. Click **Edit Permissions** > **Credentials: Edit**.
5. Select **Database** authentication, enter username `postgres` and your configured password, and click **Save**.
6. Click **Close & Apply** or click **Refresh** on the Home ribbon.
7. Power BI will execute the M queries against the PostgreSQL views and reload all 1,375,963 records into the in-memory VertiPaq engine.
