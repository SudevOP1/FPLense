# FPLense progress log

One note per phase, appended when the phase finishes. Status table lives in PLAN.md §0.0.

Template:

```
## P<N>: <name> (YYYY-MM-DD)
**Shipped:** …
**Deferred:** … (why, and which phase picks it up)
**Measured:** … (row counts, feature count, metrics, URLs)
**Follow-ups / notes:** …
```

---

## P1: Setup + historical ETL (2026-10-07)
**Shipped:**
- Tooling: `pyproject.toml` (src layout, package `fPLense`, ruff, pytest `data` marker; default run excludes `data`), `requirements.txt` (PuLP pinned `>=3.3,<4`), `.gitignore` (secrets, raw/lake/duckdb), MIT `LICENSE`, stub `README.md`, `DECISIONS.md`.
- `config.py`: 10 seasons + `2026-27`, expected row counts, paths, source URLs, request settings.
- `etl/net.py`: browser-like UA, 0.25 s pause per call, retries on connection errors / 429 / 5xx with exponential backoff; other 4xx fail fast.
- `scripts/explore_api.py`: called bootstrap-static, fixtures, element-summary (most-selected player), event/1/live; trimmed samples + full field lists in `tests/fixtures/`; fields recorded in `DECISIONS.md`.
- `etl/load_history.py`: downloads merged_gw / players_raw / fixtures (2018-19+) / teams (2019-20+) / master_team_list, SHA-256 manifest in `data/raw/manifest.json`, skip-unless-`--force`; writes hive-partitioned `data/lake/player_match/season=…/part.parquet`; `read_player_match()` reader.
- `etl/normalize.py`: fixed 51-column schema; 2019-20 GW remap; team per row from fixture sides (handles mid-season movers); position from `players_raw` where missing; `GKP`→`GK`; non-player `AM` rows dropped; missing stats NaN; scores derived; `price = value/10`; `xP`/`mng_*`/etc. dropped.
- `pipeline.py --refresh-history [--force] [--seasons …]`.
- Tests: `test_etl_schema.py` (17 pure + 20 `@data` incl. per-season parametrised raw counts), `test_net.py` (5, fake session, no network).

**Deferred:** none from P1's list. Picks endpoint sample (`entry/{id}/event/{gw}/picks/`) left to P5, which needs it for the transfer planner.

**Measured:**
- Raw `merged_gw.csv` rows: 253,900 total; every season matches PLAN §3a exactly.
- Lake rows after cleaning: **253,578** (2024-25: 27,605 → 27,283 after dropping 322 assistant-manager rows). Rows with minutes > 0: 108,687 (42.9%), unchanged by the drop.
- 380 fixtures in every season (3,800 total), each with exactly 2 teams; 20 teams per season.
- Points per appearance (minutes > 0): 2024-25 mean 2.71 / SD 2.89; 2025-26 mean 2.99 / SD 2.97 (matches §3a).
- 2022-23 has no GW7 (postponed round); all other seasons have GW 1–38.
- Lake size 7.8 MB, raw 50 MB.
- Checks: `ruff check` / `ruff format --check` clean; `pytest -q` 22 passed; `pytest -q -m data` 20 passed.

**Follow-ups / notes:**
- The resume says "250K+ rows": 253,578 holds. PLAN §9 still names 253,900 for `v_player_match`; P2's count should expect 253,578.
- `master_team_list.csv` stops at 2023-24; team names for 2024-25+ come from `teams.csv`. P2's `team_names.csv` should be built from the lake's `team` column.
- CBIT columns exist in 2016-19 and 2025-26 only; P2's `defcon_r5` must stay NaN in between.
- `team_h_difficulty` / `team_a_difficulty` are already on lake rows (NaN 2016-18) for P2's FDR.

## P2: Odds/Elo ETL + DuckDB feature store (2026-10-08)
**Shipped:**
- `etl/load_odds.py`: football-data.co.uk `E0.csv` for 2016-17 … 2025-26 plus the in-progress 2026-27 → `data/lake/odds/season=…/`. Closing-odds columns are dropped first (regex `<prefix>C<market>` + `AHCh`); market average (`Avg*`, or `BbAv*` before 2019-20) with a Bet365 fallback; 380-row assert per completed season; current season always re-fetched; hashes in the shared manifest.
- `etl/odds_features.py`: de-vig, Poisson `mu` from P(over 2.5) via `brentq`, Skellam split into `lam_home/lam_away`, `p_cs = exp(-lam_opp)`; `calibration_table` + `plot_calibration`.
- `etl/load_elo.py`: Kaggle `EloRatings.csv` via a `python -m kaggle` subprocess; ENG from 2016-07-01 → `data/lake/elo/part.parquet`; `Nottm Forest`/`Nott'm Forest` alias merge; clear `Kaggle token not found: see PLAN.md §0.2`; reads UTF-16 `access_token` files.
- `etl/team_names.csv`: 37 rows (34 lake FPL names + the 2026-27 API renames `Coventry City`, `Hull City`, `Ipswich Town`).
- `db/build.py` + `db/sql/01…06`: `v_player_match`, `v_team_match`, `v_team_form`, `v_player_form`, `v_match_odds` (+ helper views `v_team_names`, `v_odds`, `v_elo`, `v_fixture_odds`), `v_features`. The lake path is filled in at build time, so the views can be rebuilt over any lake (the leakage test does this).
- `config.FEATURES` (43, grouped as in PLAN §8), `CATEGORICAL_FEATURES`, `TARGET`, new paths/URLs.
- `pipeline.py --refresh-odds | --refresh-elo | --build` (build prints coverage and saves `docs/img/odds_cs_calibration.png`).
- Tests: `test_odds_features.py` (18), `test_load_elo.py` (8), `test_team_name_map.py` (4 pure + 6 `@data`), `test_no_leakage.py` (14 pure, including a 10-GW synthetic mini-lake with a DGW, + 1 `@data`). Saved `tests/fixtures/teams_2026_27.json` (20 clubs from bootstrap-static).

**Deferred:** nothing from P2's list. Upcoming-fixture odds (`fixtures.csv`) and the Elo-only fallback belong to P5.

**Measured:**
- Odds lake: 380 matches × 10 seasons + 50 (2026-27 so far); every match has implied goals (0 missing).
- Elo lake: 12,847 snapshot rows (2016-07-01 … 2026-09-01, semimonthly).
- **3,800 / 3,800** historical fixtures matched on (season, home, away); football-data and FPL full-time scores agree on all 3,800 (orientation check).
- **7,600 / 7,600** team-fixture rows have `elo_diff`; no snapshot older than 31 days.
- Clean-sheet calibration (7,600 team-matches): implied mean **0.270** vs actual **0.267**; deciles run from 0.081→0.076 up to 0.495→0.496 (the plot sits on the diagonal).
- `v_features`: **253,578 rows × 43 features**. Null shares: form/minutes 2.9% (a player's first appearance of the season), xG family 56.6% (pre-2022-23), `defcon_r5` 88.6% (2025-26 only), `fdr` 18.2% (2016-18), odds/Elo 0%.
- `@data` leakage test (seed 2026) checked 2020-21 GW35, 2022-23 GW25, 2020-21 GW24 and 2023-24 GW35 (all with DGWs): features identical after truncation.
- Build time ~8 s; DuckDB file 268 KB (views only), odds lake 680 KB, Elo lake 68 KB.
- Checks: `ruff check` / `ruff format --check` clean; `pytest -q` 66 passed; `pytest -q -m data` 27 passed.

**Follow-ups / notes:**
- `pts_last1` comes back from DuckDB as nullable `Int64`: P3 should cast features to float before modelling.
- `v_features` keeps `opp_xgf_r5`, `odds_source` and `value` as extra (non-feature) columns; `value` is for the P4 backtest.
- The Kaggle `access_token` on this machine is UTF-16 (PowerShell `>`). The loader copes, but re-saving it as ASCII keeps the plain `kaggle` CLI working.

## P3: EDA + baselines + LightGBM walk-forward (2026-10-08)
**Shipped:**
- `models/baselines.py`: B0 rolling form (`pts_r5` → `pts_season_avg` → 0) and the B1 Ridge pipeline (median impute + indicators → scale → `RidgeCV`, position one-hot).
- `models/train.py`: `load_features` (+ lagged `regular` flag), fixed-category `lgbm_frame`, `fit_lgbm` (early stopping on the window's last 3 GWs, then refit on the whole window at the best iteration), `train_final` → `data/published/model.txt`.
- `models/walk_forward.py`: expanding-window folds (2025-26 GW5–38), the 2024-25 holdout, the ablation ladder, per-fold checkpoints in `data/eval/folds/` (resumable), `run_evaluation` → `metrics.json` + plots.
- `models/evaluate.py`: per player-GW scoring, MAE/RMSE, gain vs B0 with a 1,000× gameweek block-bootstrap CI, Spearman per GW, top-20 precision per GW, calibration deciles, breakdown by position, `metrics_table.png` and `mae_by_gw.png`.
- `pipeline.py --evaluate [--step N] [--ablation-step N] [--no-ablation] [--fresh]` and `--train`.
- `config.py`: evaluation settings, `LGBM_PARAMS`, `ABLATION_SETS` (26 → 32 → 38 → 43 features).
- `notebooks/01_eda.ipynb` (8 charts with takeaways) and `notebooks/02_model_eval.ipynb` (metrics, MAE by GW, calibration, positions, holdout, ablation), both run with their outputs saved.
- Tests: `test_baselines.py` (9) and `test_walk_forward.py` (17 pure + 1 `@data`).

**Deferred:** none.

**Measured** (walk-forward 2025-26 GW5–38, 34 refits, scored per player-GW; regulars = lagged `minutes_r3 >= 45`):

| Regulars (n = 7,365) | MAE | RMSE | Gain vs B0 [95% CI] | Spearman/GW | Top-20 prec./GW |
|---|---:|---:|---|---:|---:|
| B0 rolling form | 2.535 | 3.346 | | 0.174 | 0.166 |
| B1 Ridge | 2.295 | 3.051 | +9.5% [8.5, 10.4] | 0.299 | 0.235 |
| **M1 LightGBM L2** | **2.246** | 3.030 | **+11.4% [10.2, 12.6]** | 0.323 | 0.225 |
| M2 LightGBM L1 | 2.068 | 3.279 | +18.4% [16.7, 20.0] | 0.317 | 0.212 |

- All rows (n = 26,491): B0 1.037 → LightGBM L2 0.966 (+6.8% [5.7, 7.9]); Ridge −0.8%.
- LightGBM L2 beats B0 in **34/34** gameweeks; by position: GK −10.3%, DEF −11.9%, MID −12.0%, FWD −8.4%.
- 2024-25 holdout (one fit on 2016-17…2023-24): LightGBM L2 −10.6% [9.2, 12.1], Ridge −9.5%, L1 −18.6%.
- Calibration (L2, regulars): deciles 1–5 within 0.08 pts; top decile 5.05 predicted vs 4.80 actual.
- Ablation (LightGBM L2, every 2nd GW, regulars MAE): (i) form 2.294 (+9.2%) → (ii) + fixture 2.260 (+10.6%) → (iii) + xG 2.253 (+10.8%) → (iv) + odds/Elo 2.250 (+10.9%); (iv) trained on 2022-23+ only 2.251. (iii) → (iv) by position: GK +0.025, DEF −0.007, MID −0.006, FWD −0.001 (noise level).
- Final model: early stopping picked **106 trees** (lr 0.03); `model.txt` 316 KB.
- EDA: 42.9% of rows have minutes > 0; regulars are 32.4% of rows; lag-1 points autocorrelation among regulars r = 0.14; B0 MAE per fixture on regulars 2.36–2.54 by season (2025-26 hardest).
- Runtime: `--evaluate --train` 45.5 min on the dev laptop (the first attempt was killed at GW31 when the system ran out of RAM; checkpoints were added after that).
- Checks: `ruff check` / `ruff format --check` clean; `pytest -q` 91 passed; `pytest -q -m data` 28 passed.

**Follow-ups / notes:**
- The resume number is backed: 11.4% (CI 10.2–12.6). PLAN §10's bullet now says "by 11%". Update the ML resume's compact entry to match.
- Odds/Elo features don't measurably improve MAE once fixture form + xG are in. Don't claim an odds gain; the README ablation row should say so plainly.
- L1 has the lowest MAE but under-rates hauls (worst RMSE); L2 stays the production model because the optimizer needs expected points.
- Only 106 trees: the early-stopping set (last 3 GWs) is noisy. P4's SHAP runs on this model; tuning stays a stretch goal.
- P5 must build prediction rows with `train.lgbm_frame` (fixed position categories) to match `model.txt`.

## P4: SHAP + model card + PuLP optimizer + transfer planner + backtest (2026-10-08)
**Shipped:**
- `models/explain.py`: `shap.TreeExplainer` on `model.txt` (5,000-row sample of 2025-26), beeswarm, dependence plots (`minutes_r3`, `xgi_r5`, `fdr`), waterfalls for a premium FWD and a budget DEF; `shap_frame` / `top_contributions` for P5's published predictions; summary → `data/published/shap_importance.json`.
- `optimize/squad_ilp.py`: PuLP/CBC squad ILP (integer-tenths budget, 2-5-5-3, ≤3 per club, XI 1 GK / ≥3 DEF / ≥2 MID / ≥1 FWD, one starting captain), vice = best-p1 other starter, bench order, availability pre-filter (`status == "u"`, 0% chance), clear `InfeasibleSquadError`, `discounted_sum` for P_h, a greedy points-per-£ baseline, `check_squad` rule checker.
- `optimize/transfers.py`: transfer planner for T = 0..3 (`x = s0 − out + in`, `h ≥ T − F`, −4 per hit, budget = value(S0) + bank), net gain vs holding, `recommended`, `options_table`. Current squad is never filtered out (can always be sold).
- `optimize/backtest.py`: 2025-26 GW5–38 on the saved walk-forward predictions with real per-GW prices; strategies A (ILP + LightGBM), B (ILP + B0), C (greedy + LightGBM); auto-subs, vice-captain fallback, gameweek-bootstrap CI on the total difference; `docs/img/backtest_cumulative.png`, `data/published/backtest.json`.
- `pipeline.py --explain`, `--backtest`, `--horizon N`. Config: game rules, horizon/discount/bench weight, SHAP and backtest settings.
- `docs/model_card.md`; `notebooks/03_shap.ipynb` and `04_optimizer_backtest.ipynb` (executed, takeaways written); 7 SHAP/backtest images in `docs/img/`.
- Tests: `test_squad_constraints.py` (18), `test_transfers.py` (15), `test_explain.py` (6), `test_backtest.py` (6), shared synthetic pools in `tests/pools.py`.

**Deferred:** none. (Upcoming-fixture prediction rows, published per-row SHAP and the app pages are P5.)

**Measured:**
- SHAP (mean |SHAP|, points per fixture): `minutes_r3` 0.575, `pts_last1` 0.246, `pts_season_avg` 0.146, `price` 0.084, `pts_r3` 0.081, `ict_r5` 0.047, `p_win` 0.046. Groups: minutes 0.62, form 0.53, market 0.13, odds/Elo 0.11, fixture 0.05, attacking 0.03, defensive 0.03. `xgi_r5` only 0.003. Base value 1.247. TreeExplainer = LightGBM `pred_contrib` exactly (max diff 0).
- Waterfalls (2025-26 GW38): Haaland pred 5.87 (actual 0); Mavropanos (DEF £4.5m) pred 4.24 (actual 8).
- ILP on the real 741-player GW5 pool: ~1.7 s; transfer plan for T = 0..3: ~5 s.
- Backtest 2025-26 GW5–38 (horizon 3, ≤1 free transfer/GW, no hits): **A 1,751 · B 1,826 · C 1,844**. A − B = −75 (95% CI [−276, +118], A ahead in 17/34 GWs); A − C = −93 ([−257, +50]). Runtime 175 s. **Not significant; no backtest claim** (PLAN §9).
- Checks: `ruff check` / `ruff format --check` clean; `pytest -q` 136 passed; `pytest -q -m data` 28 passed.

**Follow-ups / notes:**
- The 11% MAE gain doesn't translate into season points in a one-path backtest; week-to-week noise (SD 13–16 per GW) swamps it. Good interview material: forecast accuracy ≠ decision value. Candidate improvements are stretch goals (rolling free transfers/hits, multi-GW ILP, quantile captaincy).
- P5: write `explain.top_contributions(explain.shap_frame(model, rows))` into the predictions Parquet; build pools with `price = now_cost` (integer) and filter via `squad_ilp.eligible`.
- P5's Model Card page should copy the SHAP/backtest images into `data/published/` (the app reads only that folder) or read the JSON summaries.
- `explain.py` no longer forces the Agg backend (it blanked notebook plots); headless runs fall back to Agg automatically.
