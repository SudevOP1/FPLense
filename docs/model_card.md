# Model card: FPLense points model

_Last updated 2026-10-08 (phase P4). Numbers come from `data/published/metrics.json`,
`data/published/shap_importance.json` and `data/published/backtest.json`._

## Model details

| | |
|---|---|
| Model | LightGBM gradient-boosted trees, L2 (squared-error) objective, `data/published/model.txt` |
| Hyperparameters | `n_estimators` from early stopping (final model: **106 trees**), `learning_rate=0.03`, `num_leaves=31`, `min_child_samples=50`, `subsample=0.8`, `colsample_bytree=0.8`. Not tuned against the evaluation. |
| Target | FPL `total_points` for one player in one **fixture** |
| Prediction unit | Per fixture; a gameweek forecast is the sum over the player's fixtures in that GW (blank GW = 0, double GW = 2 fixtures). Live predictions (P5) are multiplied by availability (`chance_of_playing_next_round / 100`, NaN = 100%). |
| Baselines | B0 rolling form (`pts_r5` → `pts_season_avg` → 0); B1 Ridge (impute + indicators → scale → `RidgeCV`) |
| Code | `src/fPLense/models/{train,walk_forward,evaluate,explain}.py` |

## Intended use

- Ranking and pricing players for the next 1–5 gameweeks, as input to the squad ILP and transfer
  planner (`src/fPLense/optimize/`).
- A portfolio / learning project. **Not betting advice**, not affiliated with the Premier League.

Out of scope: in-play or same-day decisions after team news, chips, price-change prediction,
anything that needs calibrated probabilities of individual events (goals, clean sheets).

## Data

- 10 seasons of FPL per-fixture history (2016-17 … 2025-26) from `vaastav/Fantasy-Premier-League`:
  **253,578 player-fixture rows** after dropping 322 assistant-manager rows.
- Pre-match bookmaker odds from football-data.co.uk (3,800 / 3,800 fixtures matched), de-vigged into
  implied goals and clean-sheet probability. Closing-odds columns are dropped at load.
- ClubElo ratings (Kaggle `adamgbor/club-football-match-data-2000-2025`), the latest snapshot
  strictly before the gameweek's first kick-off (`ASOF JOIN`).
- Missing stats in older seasons (xG before 2022-23, DEFCON before 2025-26, FDR before 2018-19) stay
  **NaN**, never 0; LightGBM routes them natively.

## Features (43)

| Group | Features |
|---|---|
| Form (8) | `pts_last1, pts_r3, pts_r5, pts_season_avg, pts_per90_season, bps_r5, bonus_r5, ict_r5` |
| Minutes / role (4) | `minutes_r3, minutes_r5, played60_r5, days_rest` |
| Attacking (8) | `xg_r5, xa_r5, xgi_r5, goals_r5, assists_r5, threat_r5, creativity_r5, influence_r5` |
| Defensive (4) | `xgc_r5, cs_r5, saves_r5, defcon_r5` |
| Market (4) | `price, price_change_3, log_selected_lag1, transfers_balance_lag1` |
| Fixture (8) | `was_home, fdr, opp_gf_r5, opp_ga_r5, opp_xga_r5, team_gf_r5, team_xgf_r5, is_dgw` |
| Odds / Elo (5) | `team_xg_implied, opp_xg_implied, p_clean_sheet, p_win, elo_diff` |
| Categorical (2) | `position, gw` |

## Leakage rules

- Every rolling window is `rows between N preceding and 1 preceding`, partitioned by
  `season, element` (or `season, team`), and is **frozen per gameweek**: both fixtures of a double
  gameweek see the form as it stood at the deadline.
- FPL's own `xP` is dropped. Ownership (`selected`) and transfers are lagged one gameweek.
- Bookmaker closing-odds columns (`…C…`, e.g. `AvgCH`, `B365C>2.5`) are dropped at load; only the
  Friday/Tuesday pre-match prices are used.
- Elo comes from the snapshot strictly before the gameweek's first kick-off.
- "Regulars" (the headline subset) are defined from **lagged** minutes (`minutes_r3 >= 45`).
- `tests/test_no_leakage.py` rebuilds features from a lake truncated at gameweek k (with GW k
  outcomes blanked) and asserts GW k's features are identical to the full build.

## Evaluation

Walk-forward over 2025-26 GW5–38: for each GW k, train on all earlier seasons plus 2025-26 GWs < k,
predict GW k (34 refits). Scored per **player-gameweek**. CIs: 1,000× block bootstrap over gameweeks.

**Regulars (lagged `minutes_r3 >= 45`), n = 7,365 player-GWs**

| Model | MAE | RMSE | MAE gain vs B0 [95% CI] | Spearman / GW | Top-20 precision / GW |
|---|---:|---:|---|---:|---:|
| B0 rolling form | 2.535 | 3.346 | | 0.174 | 0.166 |
| B1 Ridge | 2.295 | 3.051 | +9.5% [8.5, 10.4] | 0.299 | 0.235 |
| **LightGBM L2 (production)** | **2.246** | **3.030** | **+11.4% [10.2, 12.6]** | **0.323** | 0.225 |
| LightGBM L1 (comparison) | 2.068 | 3.279 | +18.4% [16.7, 20.0] | 0.317 | 0.212 |

- **All rows** (n = 26,491, including the ~57% who don't play): B0 1.037 → LightGBM 0.966
  (+6.8% [5.7, 7.9]).
- LightGBM beats B0 in **34 / 34** gameweeks.
- By position (regulars, MAE gain vs B0): GK +10.3%, DEF +11.9%, MID +12.0%, FWD +8.4%.
- Second view, 2024-25 holdout (one fit on 2016-17 … 2023-24): +10.6% [9.2, 12.1].
- L1 has the lowest MAE because it predicts the median and under-rates hauls (worst RMSE). The
  optimizer needs expected points, so **L2 is the production model** and the headline number.
- Ablation (regulars MAE): form only 2.294 → + fixture 2.260 → + xG 2.253 → + odds/Elo 2.250.
  **Odds/Elo add nothing measurable** once fixture form and xG are in.

## Explainability (SHAP)

`shap.TreeExplainer` on a 5,000-row sample of 2025-26 (base value ≈ 1.25 points per fixture).
Plots: `docs/img/shap_beeswarm.png`, `shap_dependence_{minutes_r3,xgi_r5,fdr}.png`,
`shap_waterfall_{premium_fwd,budget_def}.png`.

| Rank | Feature | Mean \|SHAP\| (points / fixture) |
|---:|---|---:|
| 1 | `minutes_r3` | 0.575 |
| 2 | `pts_last1` | 0.246 |
| 3 | `pts_season_avg` | 0.146 |
| 4 | `price` | 0.084 |
| 5 | `pts_r3` | 0.081 |
| 6 | `ict_r5` | 0.047 |
| 7 | `p_win` | 0.046 |
| 8 | `minutes_r5` | 0.038 |
| 9 | `log_selected_lag1` | 0.033 |
| 10 | `fdr` | 0.026 |

- By group: minutes 0.62, form 0.53, market 0.13, odds/Elo 0.11, fixture 0.05, attacking 0.03,
  defensive 0.03. Minutes/role is the single biggest driver; xG features are individually tiny
  (`xgi_r5` 0.003) because ICT/threat and points form carry the same signal.
- Odds/Elo get SHAP mass but added nothing in the ablation: they substitute for FDR and opponent
  form rather than add information.
- Waterfalls (2025-26 GW38): Erling Haaland (FWD, £14.7m) predicted 5.87 (price +1.14, minutes
  +0.99, recent points +1.1); scored 0. Konstantinos Mavropanos (DEF, £4.5m) predicted 4.24
  (minutes +1.27, DEFCON form +0.26, low price −0.14); scored 8.

## Optimizer backtest

2025-26 GW5–38 with real per-GW prices, £100m at GW5, ≤ 1 free transfer per GW, no hits, no chips,
horizon 3, simplified auto-subs (`notebooks/04_optimizer_backtest.ipynb`).

| Strategy | Total points |
|---|---:|
| A: squad ILP + transfer planner, LightGBM predictions | 1,751 |
| B: same optimizer, rolling-form (B0) predictions | 1,826 |
| C: greedy points-per-£, LightGBM predictions | 1,844 |

A − B = **−75** (gameweek-bootstrap 95% CI [−276, +118]; A ahead in 17 / 34 GWs). The lower
forecast error did **not** show up as more points in this one-season, one-path simulation; the
difference is within noise. No backtest claim is made.

## Known limitations

- **Rotation and injuries.** The model sees only lagged minutes; it can't know a manager's team
  news. Live predictions are scaled by FPL's `chance_of_playing_next_round`, which is coarse.
- **Cold start.** New signings and promoted players have no rolling form for their first fixtures
  (features are NaN); predictions for them lean on price and position.
- **2026/27 BPS rule change** (no penalty for being tackled, +1 BPS per 3 CBI, more for GK saves)
  shifts bonus points. The model is trained on the old rules: monitor residuals by position.
- **DEFCON** points only exist since 2025-26, so `defcon_r5` is NaN for 9 of the 10 seasons.
- **Noise ceiling.** Points per appearance have an SD of about 3; a regular's MAE of ~2.2 is close
  to what any pre-deadline model can reach. Spearman per GW among regulars is only ~0.32.
- **Point predictions only.** No uncertainty / haul probability (quantile models are a stretch
  goal); the optimizer is risk-neutral.
- **No chips**, and the transfer planner values the current squad at `now_cost` because the public
  API doesn't expose selling prices.
- Odds for upcoming fixtures only exist for the next round (and not during international breaks);
  the live path falls back to an Elo-only estimate (P5), recorded per fixture in `odds_source`.

## Retraining

- `python -m fPLense.pipeline --train` refits on every completed season (and, in season, on the
  current season's history) and writes `model.txt`.
- Cadence: monthly during the season, or after a rule change; re-run `--evaluate` before replacing
  the published model, and never tune against the walk-forward test GWs.
- Predictions refresh once per gameweek (GitHub Actions daily check that runs only when the next
  deadline is < 48 h away; P6).
