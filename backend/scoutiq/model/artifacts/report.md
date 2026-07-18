# Valuation model — v1 backtest

**Model:** `v1-gbm-cqr-lags-dpcal` (HistGradientBoosting point model + CQR adaptive intervals + lagged-season features)
**What it does:** estimates a player's **production-implied market value** (salary as % of cap) from on-court production. It is *not* given the player's current salary — so the prediction is what production says they're worth, and the gap to actual pay is the signal.
**Framing:** features = production at season *t* → value at *t+1*, strict temporal split (no leakage). Train target-seasons ≤ 2023-24 (4321 rows, 1081 held out for conformal calibration); test ['2024-25', '2025-26'] (803 rows).
**Interval calibration:** five-fold out-of-fold scores from 51 historical contract starts. The nominal 80% interval is calibrated for contract decisions, so all-row coverage may be conservative.

_Note: the newest test season's actual pay is the per-season contract cap hit (Spotrac-sourced), since realized box-score salary tables lag a year. This is the same pay figure the live product compares against, and it is used for evaluation only — never as a training target._

## Headline metrics (test 2024-26)
| Metric | Value |
|---|---|
| MAE | **2.761% of cap** (~$4,085,996) |
| R² | **0.808** |
| Naive (predict mean) MAE | 7.031% of cap |
| 80% interval coverage | **0.863** (target 0.80) |
| 80% interval half-width | mean ±4.88% of cap (min ±1.4, max ±15.01) — **adaptive per player** |

## Decision-point vs mid-contract
Valuation matters where a contract is actually being set. Segments split the test set on whether the target season starts a new Spotrac contract.

| Segment | n | MAE (% cap) | R² | 80% coverage | Persistence MAE |
|---|---|---|---|---|---|
| decision point | 226 | 3.146 | 0.772 | 0.827 | 4.6 |
| mid contract | 577 | 2.611 | 0.824 | 0.877 | 1.212 |

Production alone explains **R²=0.808** of pay and cuts error to 2.761% vs 7.031% for a mean-predictor — i.e. how much salary is driven by production.

## Honest caveat: salary stickiness
A persistence reference (predict next pay = *current* salary, which we deliberately **exclude** as a feature) scores 2.101% MAE on the 762 mid-contract test players — better than this model on those rows. That's expected: their pay is contractually locked, not a production signal. We exclude current salary on purpose so the model answers *worth*, not *what's already on the books*. The v1 upgrade (contract-AAV target via Spotrac) evaluates at contract-decision points directly.

## Bargains & overpays (test set)
Largest gaps between production-implied value and actual pay — the actionable output.

**Most underpaid (production worth more than pay):**
| Player | Season | Value (% cap) | Actual pay (% cap) | Gap |
|---|---|---|---|---|
| Cam Thomas | 2025-26 | 22.74 | 0.55 | +22.2 |
| Damian Lillard | 2025-26 | 28.0 | 9.12 | +18.88 |
| Jalen Williams | 2025-26 | 23.07 | 4.26 | +18.81 |
| Jordan Clarkson | 2025-26 | 16.76 | 1.48 | +15.27 |
| DeMar DeRozan | 2024-25 | 29.91 | 16.64 | +13.26 |
| Spencer Dinwiddie | 2024-25 | 14.04 | 1.48 | +12.55 |
| Bradley Beal | 2025-26 | 15.93 | 3.46 | +12.47 |
| DeMar DeRozan | 2025-26 | 27.61 | 15.89 | +11.72 |

**Most overpaid (paid more than production implies):**
| Player | Season | Value (% cap) | Actual pay (% cap) | Gap |
|---|---|---|---|---|
| Ben Simmons | 2024-25 | 8.67 | 27.92 | -19.25 |
| Anthony Edwards | 2024-25 | 11.42 | 30.0 | -18.58 |
| Bradley Beal | 2024-25 | 19.06 | 35.71 | -16.65 |
| Paul George | 2025-26 | 17.32 | 33.41 | -16.09 |
| Isaiah Hartenstein | 2024-25 | 7.0 | 21.34 | -14.34 |
| Jonathan Isaac | 2024-25 | 4.63 | 17.78 | -13.15 |
| Evan Mobley | 2025-26 | 18.33 | 30.0 | -11.67 |
| Jonathan Kuminga | 2025-26 | 4.16 | 15.39 | -11.23 |

## Interval calibration
Conformal intervals are well-calibrated when empirical ≈ nominal.

| Nominal | Empirical | ± half-width (% cap) |
|---|---|---|
| 0.50 | 0.336 | 2.56 |
| 0.60 | 0.358 | 2.77 |
| 0.70 | 0.602 | 3.51 |
| 0.80 | 0.827 | 4.79 |
| 0.90 | 0.858 | 5.47 |
| 0.95 | 0.973 | 9.57 |

![calibration](coverage_curve.png)
![predicted vs actual](pred_vs_actual.png)

## Top features (permutation importance)
| Feature | Importance |
|---|---|
| pts_pg | 0.3192 |
| age | 0.1238 |
| lag_pts_pg | 0.0699 |
| lag_WS | 0.0407 |
| lag_minutes | 0.0209 |
| tov_pg | 0.0155 |
| lag_BPM | 0.0086 |
| reb_pg | 0.0082 |
| gp_2yr | 0.0080 |
| lag_gp | 0.0079 |
| WS | 0.0067 |
| ast_pg | 0.0063 |
