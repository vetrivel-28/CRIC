# CRIC Power BI Semantic Model & Dashboard Specifications

## Architecture Overview

This directory contains specifications, DAX measure definitions, and star schema mapping for the planned Microsoft Power BI reporting layer.

Power BI will connect directly to the **PostgreSQL 16+** `cric_analytics` database using DirectQuery or Import mode.

### Target Star Schema

- **Fact Tables**:
  - `cricket_fact.fact_delivery` (Ball-by-ball events)
  - `cricket_fact.fact_wicket` (Dismissal events)
  - `cricket_fact.fact_matchup` (Pre-aggregated head-to-head pairs)
  - `cricket_fact.fact_bowler_situation` (Pre-aggregated situation splits)

- **Dimension Tables**:
  - `cricket_dim.dim_player` (Player profiles, roles, bowling types)
  - `cricket_dim.dim_match` (Match metadata, venues, seasons, winners)
  - `cricket_dim.dim_phase` (Match phases: Powerplay, Middle, Death)
  - `cricket_dim.dim_dismissal` (Dismissal kinds and bowler crediting rules)

- **Pre-computed Analytical Views**:
  - `cricket_analytics.v_bowler_career_performance`
  - `cricket_analytics.v_bowler_phase_performance`
  - `cricket_analytics.v_bowler_batter_matchups`
  - `cricket_analytics.v_bowler_situation_performance`
  - `cricket_analytics.v_wicket_profiles`
  - `cricket_analytics.v_batter_career_performance`

## Standard Measures Reference

See `cric_dax_measures.dax` for the complete library of formulas:
- Total Overs Bowled (`SUM(fact_delivery[is_legal_delivery]) / 6.0`)
- Economy Rate (`DIVIDE([Runs Conceded], [Overs Bowled], BLANK())`)
- Bowling Average (`DIVIDE([Runs Conceded], [Credited Wickets], BLANK())`)
- Bowling Strike Rate (`DIVIDE([Legal Balls], [Credited Wickets], BLANK())`)
- Dot Ball % (`DIVIDE([Dot Balls], [Legal Balls], BLANK())`)
- Boundary % (`DIVIDE([Boundaries Conceded], [Legal Balls], BLANK())`)
- Matchup Shrinkage Weight (`MIN(1.0, DIVIDE([Matchup Balls], 30.0))`)
