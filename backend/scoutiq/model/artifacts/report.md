# Valuation model — v0 backtest

**Model:** `v0-gbm-conformal` (HistGradientBoosting + split-conformal intervals)  
**What it does:** estimates a player's **production-implied market value** (salary as % of cap) from on-court production. It is *not* given the player's current salary — so the prediction is what production says they're worth, and the gap to actual pay is the signal.  
**Framing:** features = production at season *t* → value at *t+1*, strict temporal split (no leakage). Train target-seasons ≤ 2022-23 (3923 rows, 981 held out for conformal calibration); test ['2023-24', '2024-25'] (796 rows).

## Headline metrics (test 2023-25)
| Metric | Value |
|---|---|
| MAE | **2.916% of cap** (~$4,032,446) |
| R² | **0.774** |
| Naive (predict mean) MAE | 6.856% of cap |
| 80% interval coverage | **0.847** (target 0.80) |
| 80% interval half-width | ±5.36% of cap |

Production alone explains **R²=0.774** of pay and cuts error to 2.916% vs 6.856% for a mean-predictor — i.e. how much salary is driven by production.

## Honest caveat: salary stickiness
A persistence reference (predict next pay = *current* salary, which we deliberately **exclude** as a feature) scores 2.186% MAE on the 768 mid-contract test players — better than this model on those rows. That's expected: their pay is contractually locked, not a production signal. We exclude current salary on purpose so the model answers *worth*, not *what's already on the books*. The v1 upgrade (contract-AAV target via Spotrac) evaluates at contract-decision points directly.

## Bargains & overpays (test set)
Largest gaps between production-implied value and actual pay — the actionable output.

**Most underpaid (production worth more than pay):**
| Player | Season | Value (% cap) | Actual pay (% cap) | Gap |
|---|---|---|---|---|
| Desmond Bane | 2023-24 | 23.94 | 2.83 | +21.12 |
| Russell Westbrook | 2023-24 | 22.87 | 2.82 | +20.05 |
| Christian Wood | 2023-24 | 16.22 | 1.99 | +14.23 |
| Tyrese Haliburton | 2023-24 | 16.55 | 4.27 | +12.28 |
| Jalen Williams | 2024-25 | 15.38 | 3.4 | +11.98 |
| Skylar Mays | 2023-24 | 12.8 | 1.32 | +11.48 |
| DeMar DeRozan | 2024-25 | 27.26 | 16.64 | +10.61 |
| Lauri Markkanen | 2023-24 | 23.14 | 12.69 | +10.45 |

**Most overpaid (paid more than production implies):**
| Player | Season | Value (% cap) | Actual pay (% cap) | Gap |
|---|---|---|---|---|
| Ben Simmons | 2024-25 | 8.37 | 27.92 | -19.55 |
| Zach LaVine | 2024-25 | 12.95 | 31.68 | -18.73 |
| Bradley Beal | 2024-25 | 17.3 | 35.71 | -18.41 |
| Anthony Edwards | 2024-25 | 12.05 | 30.0 | -17.95 |
| Rudy Gobert | 2023-24 | 13.11 | 30.14 | -17.03 |
| Ben Simmons | 2023-24 | 11.62 | 27.86 | -16.24 |
| Zion Williamson | 2023-24 | 10.4 | 25.0 | -14.6 |
| Kyle Lowry | 2023-24 | 8.96 | 21.82 | -12.86 |

## Interval calibration
Conformal intervals are well-calibrated when empirical ≈ nominal.

| Nominal | Empirical | ± half-width (% cap) |
|---|---|---|
| 0.50 | 0.531 | 2.09 |
| 0.60 | 0.648 | 2.87 |
| 0.70 | 0.751 | 3.99 |
| 0.80 | 0.847 | 5.36 |
| 0.90 | 0.918 | 7.74 |
| 0.95 | 0.964 | 10.6 |

![calibration](coverage_curve.png)
![predicted vs actual](pred_vs_actual.png)

## Top features (permutation importance)
| Feature | Importance |
|---|---|
| pts_pg | 0.5435 |
| age | 0.2153 |
| reb_pg | 0.0189 |
| WS | 0.0120 |
| ast_pg | 0.0106 |
| tov_pg | 0.0101 |
| NET_RATING | 0.0095 |
| minutes | 0.0087 |
| gp | 0.0081 |
| OREB_PCT | 0.0060 |
| PACE | 0.0056 |
| OBPM | 0.0053 |
