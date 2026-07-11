# Valuation model — v1 backtest

**Model:** `v1-gbm-cqr-lags-dpcal` (HistGradientBoosting point model + CQR adaptive intervals + lagged-season features)
**What it does:** estimates a player's **production-implied market value** (salary as % of cap) from on-court production. It is *not* given the player's current salary — so the prediction is what production says they're worth, and the gap to actual pay is the signal.
**Framing:** features = production at season *t* → value at *t+1*, strict temporal split (no leakage). Train target-seasons ≤ 2023-24 (4321 rows, 1081 held out for conformal calibration); test ['2024-25', '2025-26'] (803 rows).
**Interval calibration:** five-fold out-of-fold scores from 51 historical contract starts. The nominal 80% interval is calibrated for contract decisions, so all-row coverage may be conservative.

_Note: the newest test season's actual pay is the per-season contract cap hit (Spotrac-sourced), since realized box-score salary tables lag a year. This is the same pay figure the live product compares against, and it is used for evaluation only — never as a training target._

## Headline metrics (test 2024-26)
| Metric | Value |
|---|---|
| MAE | **2.79% of cap** (~$4,127,643) |
| R² | **0.807** |
| Naive (predict mean) MAE | 7.031% of cap |
| 80% interval coverage | **0.877** (target 0.80) |
| 80% interval half-width | mean ±5.36% of cap (min ±1.81, max ±17.03) — **adaptive per player** |

## Decision-point vs mid-contract
Valuation matters where a contract is actually being set. Segments split the test set on whether the target season starts a new Spotrac contract.

| Segment | n | MAE (% cap) | R² | 80% coverage | Persistence MAE |
|---|---|---|---|---|---|
| decision point | 226 | 3.202 | 0.764 | 0.858 | 4.6 |
| mid contract | 577 | 2.628 | 0.826 | 0.884 | 1.212 |

Production alone explains **R²=0.807** of pay and cuts error to 2.79% vs 7.031% for a mean-predictor — i.e. how much salary is driven by production.

## Honest caveat: salary stickiness
A persistence reference (predict next pay = *current* salary, which we deliberately **exclude** as a feature) scores 2.101% MAE on the 762 mid-contract test players — better than this model on those rows. That's expected: their pay is contractually locked, not a production signal. We exclude current salary on purpose so the model answers *worth*, not *what's already on the books*. The v1 upgrade (contract-AAV target via Spotrac) evaluates at contract-decision points directly.

## Bargains & overpays (test set)
Largest gaps between production-implied value and actual pay — the actionable output.

**Most underpaid (production worth more than pay):**
| Player | Season | Value (% cap) | Actual pay (% cap) | Gap |
|---|---|---|---|---|
| Cam Thomas | 2025-26 | 23.04 | 0.55 | +22.5 |
| Damian Lillard | 2025-26 | 26.56 | 9.12 | +17.44 |
| Jalen Williams | 2025-26 | 21.04 | 4.26 | +16.79 |
| Jordan Clarkson | 2025-26 | 16.74 | 1.48 | +15.26 |
| Bradley Beal | 2025-26 | 17.28 | 3.46 | +13.81 |
| DeMar DeRozan | 2024-25 | 30.27 | 16.64 | +13.63 |
| Spencer Dinwiddie | 2024-25 | 13.51 | 1.48 | +12.03 |
| DeMar DeRozan | 2025-26 | 26.83 | 15.89 | +10.94 |

**Most overpaid (paid more than production implies):**
| Player | Season | Value (% cap) | Actual pay (% cap) | Gap |
|---|---|---|---|---|
| Ben Simmons | 2024-25 | 7.87 | 27.92 | -20.06 |
| Anthony Edwards | 2024-25 | 11.44 | 30.0 | -18.56 |
| Bradley Beal | 2024-25 | 19.26 | 35.71 | -16.45 |
| Paul George | 2025-26 | 19.27 | 33.41 | -14.14 |
| Jonathan Isaac | 2024-25 | 4.46 | 17.78 | -13.32 |
| Isaiah Hartenstein | 2024-25 | 8.02 | 21.34 | -13.32 |
| Evan Mobley | 2025-26 | 17.6 | 30.0 | -12.4 |
| Stephen Curry | 2025-26 | 26.89 | 38.54 | -11.65 |

## Interval calibration
Conformal intervals are well-calibrated when empirical ≈ nominal.

| Nominal | Empirical | ± half-width (% cap) |
|---|---|---|
| 0.50 | 0.292 | 2.44 |
| 0.60 | 0.473 | 3.31 |
| 0.70 | 0.699 | 4.25 |
| 0.80 | 0.858 | 5.34 |
| 0.90 | 0.876 | 5.86 |
| 0.95 | 0.996 | 11.24 |

![calibration](coverage_curve.png)
![predicted vs actual](pred_vs_actual.png)

## Top features (permutation importance)
| Feature | Importance |
|---|---|
| pts_pg | 0.3167 |
| age | 0.1244 |
| lag_pts_pg | 0.0659 |
| lag_WS | 0.0429 |
| lag_minutes | 0.0190 |
| tov_pg | 0.0162 |
| lag_BPM | 0.0089 |
| reb_pg | 0.0089 |
| lag_gp | 0.0078 |
| gp_2yr | 0.0078 |
| minutes | 0.0076 |
| ast_pg | 0.0057 |
