# CRIC Historical Backtesting Limitations and Operational Boundary

1. **Selection Bias & Counterfactual Unobservability:**
   Historical match logs record deliveries only for bowlers who were actually selected by the real-world captain. Counterfactual spell performance for unselected eligible alternatives cannot be observed in historical cricket scorecards.

2. **Utility Scores vs. Calibrated Probabilities:**
   The CRIC Recommendation Engine outputs a composite utility score on a 0–100 scale. This metric reflects multi-attribute ranking priority based on historical rates; it is not a calibrated win-probability or predictive confidence interval.

3. **Innings Quotas & Injury Context:**
   The evaluation candidate pool is defined by active match bowlers in that spell. Real-time dynamic restrictions (e.g. maximum overs per bowler in limited overs matches, mid-match injuries) are respected to the extent captured in match scorecards.

4. **Sample Size Decay in Rare Matchups:**
   Head-to-head batter matchups with fewer than 30 legal balls are shrunken back to career/phase baselines using Bayesian prior shrinkage (30 legal balls) to prevent extreme outlier weights.
