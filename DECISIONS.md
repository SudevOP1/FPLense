# FPLense decisions

What was chosen and why. Newest phase at the bottom.

## P1: Setup + historical ETL (2026-10-07)

### Tooling
- **src layout, package `fPLense`, setuptools.** `pip install -e .` makes `python -m fPLense.pipeline` work from anywhere; tests import the installed package, not loose files.
- **`pytest` runs `-m 'not data'` by default** (`addopts` in `pyproject.toml`). `pytest -q` stays fast and network/data-free for CI; `pytest -q -m data` overrides it locally. Data tests also skip via the `lake_dir` fixture (`tests/conftest.py`) when `data/lake/player_match/` is missing.
- **Ruff excludes `*.md`.** Ruff 0.16 formats Python code blocks inside Markdown and rewrote the ILP snippet in `PLAN.md`; docs are not code.
- **HTTP helper is `etl/net.py`, not `etl/http.py`**, so it can never shadow the stdlib `http` package.
- Installed versions at setup: pandas 3.0.6, DuckDB 1.5.6, LightGBM 4.7.0, PuLP 3.3.2 (CBC bundled), ruff 0.16.10, Python 3.12.0.

### HTTP (`etl/net.py`)
- Every call sleeps 0.25 s first (polite to FPL / GitHub), sends `User-Agent: Mozilla/5.0 FPLense`.
- Retries only connection errors and 429/5xx, with exponential backoff (`1 s · 2^attempt`, 4 retries). Other 4xx fail at once: retrying a 404 never helps and just hammers the host.

### Raw download (`etl/load_history.py`)
- Files: `gws/merged_gw.csv`, `players_raw.csv` per season, `fixtures.csv` from 2018-19, root `master_team_list.csv`, and **`teams.csv` from 2019-20**.
- **Why `teams.csv`:** `master_team_list.csv` only covers 2016-17 … 2023-24 (checked 2026-10-07). Team names for 2024-25 and 2025-26 come from each season's `teams.csv` (`id`, `name`); `master_team_list` stays first choice where it has the season.
- SHA-256, URL, size and timestamp per file in `data/raw/manifest.json`; existing files are skipped unless `--force`.
- **CSV encoding: UTF-8 first, latin-1 fallback.** PLAN said latin-1, but only 2016-17 … 2018-19 are latin-1; 2019-20+ are UTF-8, and reading those as latin-1 garbles accented names (`KonatÃ©`). `read_csv` tries UTF-8 and falls back on `UnicodeDecodeError`.

### Normalisation (`etl/normalize.py`)
- **Team per row comes from the fixture, not `players_raw`.** `players_raw.team` is the end-of-season club, so a January mover would be credited to the wrong side for the first half of the season. Own team = `team_h` if `was_home` else `team_a`. From 2018-19 the sides come from `fixtures.csv`; for 2016-17/2017-18 (no `fixtures.csv`) they're recovered from the rows themselves: home-side rows carry the away team as `opponent_team` and vice versa. `players_raw.team` is only a fallback (never needed on the real data).
- **Position**: the season's own `position` column where present (2020-21+), else `players_raw.element_type` (1 GK, 2 DEF, 3 MID, 4 FWD). 2021-22 has 101 rows labelled `GKP`; mapped to `GK`.
- **2024-25 assistant-manager rows dropped (322 rows, position `AM`, `element_type` 5).** They are managers, not players: no position quota, and they'd break `position ∈ {GK, DEF, MID, FWD}`. All 322 had 0 minutes (the minutes>0 count is still 108,687, matching PLAN §3a). This is why the lake has **253,578** rows, not 253,900.
- **Missing columns are NaN (float64), not 0.** xG family before 2022-23, `starts` before 2022-23, `defensive_contribution` before 2025-26. 0 would tell the model "no xG", NaN tells it "unknown"; LightGBM handles NaN natively.
- **`clearances_blocks_interceptions`, `recoveries`, `tackles` exist in 2016-17 … 2018-19 and 2025-26 only** (vaastav's early seasons carried extra Opta columns). Kept where real; NaN in between. `defensive_contribution` itself is 2025-26 only.
- **2019-20 GW 39–47 → 30–38** (COVID restart numbering). `round` is dropped (same information as `GW`).
- **2022-23 has no GW7** (whole round postponed after the Queen's death); GW numbering is kept as FPL published it, not compressed. The schema test pins this exact gap.
- Dropped: `xP` (FPL's own expected points; look-ahead risk per the vaastav README), `mng_*`, `kickoff_time_formatted`, `ea_index`, `loaned_in/out`, `modified`, and one-season extras (e.g. 2016-18 `attempted_passes`, `big_chances_created`) that never appear again. The lake schema is the fixed `SCHEMA` list in `normalize.py`.
- Kept `team_h_difficulty` / `team_a_difficulty` on each row (NaN for 2016-18) so P2's FDR feature needs no extra lake table.
- `price = value / 10` (float, £m); `value` kept as integer tenths for the optimizer.
- `kickoff_time` is a UTC timestamp; `was_home` parsed to bool (2016-17 stores the strings `"True"`/`"False"`).

### Lake layout
- `data/lake/player_match/season=YYYY-YY/part.parquet`, **hive style: `season` is only in the directory name**, not inside the file. Writing it in both places makes pyarrow fail with `Unable to merge: Field season has incompatible types`. `load_history.read_player_match()` reads it back with `season` as a plain string; DuckDB in P2 reads it with `hive_partitioning=true`.

### FPL API fields (confirmed 2026-10-07 by `scripts/explore_api.py`)
Full lists in `tests/fixtures/api_fields.json`; trimmed samples (5 items per list) next to it.
- `bootstrap-static/` top level: `chips, element_stats, element_types, elements, events, game_config, game_settings, phases, teams, total_players`.
  - `elements` (109 fields) include everything P5 needs: `id, web_name, team, element_type, now_cost, status, chance_of_playing_next_round, chance_of_playing_this_round, selected_by_percent, ep_next, minutes, starts, expected_goals, expected_assists, defensive_contribution, news`.
  - `teams`: `id, name, short_name, strength, strength_attack_home/away, strength_defence_home/away, strength_overall_home/away, code`.
  - `events`: `id, deadline_time, deadline_time_epoch, is_current, is_next, is_previous, finished, data_checked`.
- `fixtures/`: `id, code, event, kickoff_time, team_h, team_a, team_h_difficulty, team_a_difficulty, team_h_score, team_a_score, finished, started, minutes, stats` (+ `provisional_start_time, finished_provisional, pulse_id`).
- `element-summary/{id}/`: `history` has the **same per-fixture fields as vaastav `merged_gw`** minus `name/position/team/xP/GW` (`round` instead of `GW`), plus `modified`. `fixtures` uses `is_home` and a single `difficulty`. `history_past` has season totals keyed by `season_name` with `start_cost`/`end_cost` (for the P5 cold-start feature).
- `event/{gw}/live/`: `elements[] = {id, stats, explain, modified}`; `stats` mirrors the history stat columns plus `in_dreamteam`, `played`.
- `entry/{id}/event/{gw}/picks/` not sampled in P1 (needs a team id); P5 samples it for the transfer planner.

## P2: Odds/Elo ETL + DuckDB feature store (2026-10-08)

### Leakage: features frozen per gameweek, not per fixture
- PLAN's windows (`rows … 1 preceding` ordered by kickoff) are fixture-safe but **not deadline-safe in double gameweeks**: a DGW's second fixture would see the first fixture's result, which is played after the FPL deadline. PLAN's own truncation test (GW k rows blanked) would fail on it.
- Fix: windows are computed per fixture, then every outcome-based feature takes `first_value(...) over (partition by season, element|team, gw order by kickoff_time, fixture)`. Both DGW fixtures get the form as it stood before the GW. Same in `v_team_form`.
- Windows order by `gw, kickoff_time, fixture` (not kickoff alone), so "preceding" and "earlier GW" mean the same thing. Checked: GW order never contradicts kickoff order for any team in the lake.
- Kept per fixture because they're known before the deadline: `days_rest` (schedule), `price_change_3` (prices), FDR, home/away.
- Elo is matched to the **gameweek's first kick-off date** (latest snapshot strictly before it), not each match's own date, so a midweek DGW match can't use a snapshot taken after the deadline. Stricter than PLAN's "before kick-off".
- The truncation test blanks **all** outcomes on GW k rows (points, minutes, every stat, scores, `selected`, `transfers_*`), not just the target. That is the true deadline information set, and it also proves ownership/transfers are lagged.
- Sensitivity control: the synthetic test also changes a GW k-1 outcome and asserts GW k features *do* change, so the test can't pass vacuously.

### Odds
- **Closing columns dropped by regex** `^[A-Za-z0-9]+C(H|D|A|>2.5|<2.5|AHH|AHA)$` plus `AHCh`, before any column is selected. Checked against every header 2016-17 … 2026-27: it catches `PSCH`, `B365CAHH`, `BFEC>2.5`… and spares `BbAvAHH`, `HC`/`AC` (corners) and `HxG`. A test perturbs the closing columns and asserts the output is unchanged.
- 1X2 and O/U fall back **independently** per match (avg → B365); `source_1x2` / `source_ou` record which was used. In practice all 3,850 rows had complete market averages.
- Implied-goal solves clip to PLAN's bounds (μ ∈ [0.2, 6], share ∈ [0.05, 0.95]) instead of raising, so an odd price can't crash the ETL.
- Files from 2025-26 on start with a UTF-8 BOM: read as `utf-8-sig`, latin-1 fallback. Old seasons have no `Time` column; it's written as an all-null *string* column (a NULL-typed column broke DuckDB's multi-file read).
- Implied goals are computed in Python at load time (SciPy root-finding) and stored in the lake; SQL only orients them per team.
- The calibration plot is built from the **joined** views (`v_match_odds` × actual goals against), so it checks the home/away orientation of the join as well as the maths.

### Elo
- ClubElo snapshots are semimonthly (1st and 15th). `ASOF LEFT JOIN … on club and gw_start_date > date`.
- **`Nottm Forest` vs `Nott'm Forest`:** ClubElo renamed the club in Jan 2025 but kept publishing a frozen copy (1731.5) under the old name. Both map to `Nott'm Forest`; when both exist on one date, the row that already used the new name wins. Without this, Forest's 2025-26 Elo would be stuck at Dec 2024.
- The Kaggle download runs the CLI as a subprocess (`python -m kaggle`) rather than `import kaggle`, which authenticates at import time and would crash without a token. Token lookup: env vars → `~/.kaggle/access_token` (decoded, UTF-16 tolerated, passed as `KAGGLE_API_TOKEN`) → `kaggle.json` → `KaggleTokenError("Kaggle token not found: see PLAN.md §0.2")`.

### Team names
- `team_names.csv` is keyed by `fpl_name` (unique). FPL renamed three clubs in 2026-27 (`Coventry City`, `Hull City`, `Ipswich Town`; vaastav used `Hull`, `Ipswich`), so both spellings have rows pointing at the same football-data / ClubElo names: 37 rows.
- Only 3 historical names differ from football-data (`Man Utd`/`Man United`, `Spurs`/`Tottenham`, `Sheffield Utd`/`Sheffield United`); ClubElo matches football-data once Forest is canonicalised.

### Feature store
- **43 features, not 42.** PLAN §8's group table sums to 43 (8+4+8+4+4+8+5+2), and every listed feature was built. `opp_xgf_r5` is in the view but not in `FEATURES` (it's not in PLAN's table).
- `defcon_r5` uses `defensive_contribution` only (2025-26), not the CBIT columns that also exist in 2016-19, so the feature means one thing.
- SQL files use `${lake}` / `${team_names}` placeholders filled in by `db/build.py`, so tests build the same views in memory over synthetic or truncated lakes. The on-disk DuckDB holds views only (268 KB) and rebuilds in ~8 s.
- `v_team_match.xg_for` = Σ player xG (NULL before 2022-23), so `team_xgf_r5` / `opp_xga_r5` stay NULL there, never 0.

## P3: EDA, baselines, LightGBM, walk-forward (2026-10-08)

### Evaluation unit and subset
- **Scored per player-gameweek**, not per fixture: predictions are per fixture (the model's unit), then summed over a player's fixtures in the GW, as are the actual points. This is the unit of the resume claim ("next-gameweek points") and of the optimizer. DGWs are a small share of rows, so per-fixture numbers are close.
- **Regulars = lagged `minutes_r3 >= 45`** (`train.add_regular_flag`; NaN, i.e. a player's first fixture of the season, counts as not regular). Both DGW fixtures carry the same frozen `minutes_r3`, so the flag is well defined per player-GW.
- **Every row is used for training**, regulars or not: the optimizer has to price every player, including rotation risks.

### Models
- B0 = `pts_r5` → `pts_season_avg` → 0, exactly PLAN's order. Per GW it's summed over fixtures like the models.
- Ridge: `SimpleImputer(median, add_indicator=True)` → `StandardScaler` on numeric columns, `OneHotEncoder(handle_unknown="ignore")` on `position`, `RidgeCV` over 13 alphas 1e-2 … 1e4. Columns that are all-NaN in a training window (DEFCON in the 2024-25 holdout) are dropped by the imputer with a warning; that's intended.
- **LightGBM early stopping, then refit.** Each window's last 3 (season, GW) pairs are the early-stopping set (patience 100 rounds); the model is then refit on the *whole* window with the best iteration count. Without the refit, every fold would throw away the 3 most recent GWs, which are the most relevant for the next one. Costs 2× training time (~20 s per fold on 24 cores).
- `position` is a pandas `Categorical` with fixed categories `GK, DEF, MID, FWD`, so the codes LightGBM sees are identical across folds and in the saved `model.txt` (P5 reuses `train.lgbm_frame`).
- M2 uses `objective="l1"` (not Huber), so it matches the PLAN §3d sanity check.
- `lightgbm>=4.7`: the sklearn API's `eval_set` is deprecated there in favour of `eval_X`/`eval_y`.

### Walk-forward
- `walk_forward.folds` yields boolean masks: train = seasons `<` target (string order works for `YYYY-YY`) plus target-season GWs `< k`; test = target season GW `k`. GWs with no rows are skipped (2022-23 has no GW7).
- Training cutoff per fold is recorded (`train_last`, e.g. `2025-26 GW4` for k = 5) in the saved predictions, so the fold ordering is auditable.
- Second view: one fit on 2016-17 … 2023-24, scored on 2024-25 GW5+.

### Metrics
- **Block bootstrap over gameweeks:** resample the GWs (with replacement, 1,000×, seed 42), recompute `1 − ΣAE_model / ΣAE_B0`. Errors inside a GW are correlated (same fixtures, same rotation news), so resampling rows would understate the CI. Implemented with `bincount` per GW, so 1,000 reps take milliseconds.
- **Top-20 precision per GW, regulars:** share of the model's top-20 whose actual score is ≥ the 20th-best actual score that GW. Ties at the threshold count as top-20 (FPL scores tie a lot; with strict top-20 sets the metric would depend on arbitrary tie-breaking).
- Spearman per GW is skipped for a GW where predictions or actuals are constant (never happens on real data).

### Ablation
- Ladder: (i) form = form + minutes + market + non-xG attacking/defensive stats + position/gw (26 features); (ii) + fixture/opponent form without xG (`was_home, fdr, opp_gf_r5, opp_ga_r5, team_gf_r5, is_dgw`; 32); (iii) + the 6 xG features (`xg_r5, xa_r5, xgi_r5, xgc_r5, opp_xga_r5, team_xgf_r5`; 38); (iv) + the 5 odds/Elo features = all 43. Plus (iv) trained on 2022-23+ only (the xG era).
- Run walk-forward with `--ablation-step 2` (GW 5, 7, …, 37; 17 refits each), so the ablation rows are comparable with each other but not exactly with the step-1 headline.
- **Fold checkpoints.** The first full run was killed at GW31/38 when the machine ran low on RAM (other apps; 1.6 of 15.7 GB free). Each fold is now saved to `data/eval/folds/<run>/gwKK.parquet` and reused on rerun; `--fresh` deletes them (needed after any feature/model change, or stale folds would be reused).

### Results that shaped decisions
- **L2 stays the production model** although L1 has the lower MAE (2.068 vs 2.246 on regulars): L1 predicts the median, its RMSE is the worst of the learned models (3.28 vs 3.03), and the ILP needs expected points. The resume number is L2's (11.4%), not L1's 18.4%.
- **Odds/Elo kept in the model, but no claim made for them.** In the ablation they move regulars' MAE by −0.003 (2.253 → 2.250), which is noise. They cost nothing, they're forward-looking (useful early in a season, when team form windows are short), and P5's live path already plans for them.
- **All 10 seasons kept for training.** Training on 2022-23+ only (the xG era) gives the same MAE (2.251 vs 2.250), so the older seasons, with NaN xG, don't hurt.
- **The final model has 106 trees** (early stopping at lr 0.03 on the last 3 GWs of 2025-26). Not tuned further: no tuning was done against the evaluation, so the walk-forward number stays honest.

## P4: SHAP, optimizer, transfer planner, backtest (2026-10-08)

### SHAP
- **Sample = 5,000 rows of 2025-26**, not all seasons: it's the only season where every feature (xG, DEFCON, odds, Elo) is populated, so the beeswarm describes the regime the live model runs in.
- `shap.TreeExplainer` for the plots; LightGBM's own `pred_contrib` (same TreeSHAP, verified identical) for `shap_frame`, which P5 runs every week without the SHAP object overhead.
- `position` is shown as text in waterfalls (`display_data`) and as its category code for beeswarm colouring.
- Waterfall examples are picked by rule, not by hand: the priciest regular FWD and the best-predicted regular DEF ≤ £4.5m in the season's last GW. The final model was trained on that GW, so they explain the model, they don't evaluate it.

### Squad ILP
- Followed PLAN's formulation exactly (objective `Σ start·P_h + capt·p1 + 0.1·Σ bench·P_h`). Constraint and variable builders are shared with the transfer planner, so both enforce identical rules.
- Prices validated as integer tenths; floats like 5.5 raise instead of silently passing.
- Vice-captain = highest-p1 starter other than the captain; bench order = outfield by p1, GK last (matches FPL auto-sub order).
- PuLP 3.3 emits 4.0 deprecation warnings for `LpVariable.dicts` / `PULP_CBC_CMD`; we pin `pulp<4` (CLAUDE.md), so pytest filters those warnings rather than switching APIs.
- **Greedy baseline** (`greedy_squad`) adds by `P_h / price` but only if the squad can still be completed with the cheapest *unpicked* players, so it always returns a legal squad. Its XI is chosen by `best_xi` (fill formation minimums, then best remaining outfielders), which is optimal for a fixed squad.

### Transfer planner
- `x_i = s0_i − out_i + in_i`, with `in` variables only for non-squad players and `out` only for squad players, so a player can't be sold and re-bought.
- `h` is an integer variable with `h ≥ T − F`; the objective subtracts `4h`, so the solver sets `h = max(0, T − F)`. Free transfers clipped to 0..5.
- Current squad players are exempt from the availability filter (they must stay sellable); the filter applies to buy candidates only.
- Options the budget can't reach are dropped (T = 0 must always be feasible). Recommended option = largest net gain, ties to fewer transfers.

### Backtest
- **Horizon from the schedule only** (developer's choice): walk-forward has leak-free predictions for GW k only, so `P_h` for GW k+j uses the player's latest per-fixture prediction × his club's fixture count in GW k+j × 0.9^j. Blank and double GWs are priced correctly, no future form is used. A test perturbs later predictions and asserts the GW k pool doesn't change.
- A player missing from GW k although his club plays has left the game → `status "u"`, P_h 0 (sellable, not buyable). A missing player whose club blanks stays active.
- Sold at the current price (no half-of-rise rule; applied to every strategy alike). ≤ 1 free transfer per GW, no rollover, no hits, no chips, as PLAN specifies.
- C (greedy) uses LightGBM predictions, so A vs C isolates the optimizer and A vs B isolates the forecast.
- CIs on total-point differences: bootstrap over the 34 gameweeks (same block idea as P3).
- **Result kept as measured:** A trailed B by 75 points with a CI spanning ±200; no strategy tweaks were tried to make A win, and no backtest claim is made.

## P5: Live API path, predictions, Streamlit app (2026-10-08)

### Live data layout
- **The 2026-27 season lives in `data/lake/live/`, not in `data/lake/player_match/`.** The training lake stays exactly the 10 completed seasons (253,578 rows, pinned by P1's schema tests), and `train.load_features` can never pick up an in-progress season by accident. Same schema, so the same views read it.
- Raw API JSON goes to `data/raw/fpl_api/` (gitignored). `element-summary` responses are cached per *finished* GW (`element-summary/gw05/<id>.json`): a finished GW's history doesn't change, so a second run in the same GW makes no per-player calls.
- **Who gets an `element-summary` call:** only players with minutes > 0 this season (PLAN's rule; 421 of 667). The other 246 get **synthesized 0-minute rows** for each finished fixture of their current club, which is what vaastav's `merged_gw` holds for them. Without those rows their form features would be NaN (= "first appearance") and the model would score unused squad players like cold starts. Approximations on those rows: `value` = today's price, `selected` = today's ownership, transfer counts NaN.
- History rows are kept only for fixtures the fixtures endpoint marks `finished`, and each row's own team comes from the fixture's side (as in P1), so a mid-season mover is credited correctly.

### Feature rows for upcoming fixtures
- **Reuse the views, don't re-implement them.** Each upcoming fixture becomes a lake row with every outcome blanked (points, minutes, stats, scores, ownership, transfers): exactly the truncated lake the P2 leakage test proves gives the training features. `v_features` is read back for that GW, so there is no second copy of the feature logic to drift.
- **One view build per horizon GW** (history + that GW's fixtures only). With all 5 GWs in one build, GW 8's windows would average over blank GW 6-7 rows (`avg` skips NULLs, so `pts_r5` would quietly become a 3-match average and `pts_last1` NULL). Per-GW builds give every GW the form as it stands today; a synthetic-season test checks GW 5 sees the same `pts_last1/pts_r3/pts_r5` as GW 4. Each build covers only the small current season (~2 s).
- `days_rest` is known from the schedule, so for GW 2+ of the horizon it is recomputed from the club's previous *scheduled* fixture (the view would count from the last played match, weeks earlier). GW 1 keeps the view's value, identical to training.
- Rows are scored with `train.lgbm_frame` (fixed position categories) on `model.txt`; no retraining in the live path.

### Odds and the Elo fallback
- `fixtures.csv` E0 rows go through the same `clean_odds` (closing columns dropped first). On 2026-10-08 it had 0 E0 rows (international break), so all of GW 6-10 used the fallback.
- **Elo-only estimate = Poisson GLM** `log lambda = b0 + b1*elo_diff/100 + b2*home`, fitted (sklearn `PoissonRegressor`, no penalty) on all 7,600 historical team-matches with the same pre-GW Elo the views use. Fitted: b0 0.199, b1 0.189 (+100 Elo = about +21% goals), home 0.195 (about +22%). The lambdas go through the same independent-Poisson maths as the odds path (Skellam for win/draw/loss, `exp(-lambda_opp)` for a clean sheet) and are written as odds-lake rows with `source = "elo"`, so the SQL is unchanged and `odds_source` records the choice per fixture.
- Elo for a future fixture: latest snapshot strictly before the GW's first kick-off (the `v_match_odds` rule).
- Known shift: the model was trained on bookmaker-implied features; most horizon fixtures get Elo-implied ones. Accepted because the P3 ablation showed odds/Elo add about 0 to MAE.

### Prediction assembly
- GW points = sum of per-fixture predictions (DGW 2 fixtures, blank 0) x availability. Availability = `chance_of_playing_next_round / 100`, NaN -> 100%, status `u` -> 0, applied to **every** horizon GW (FPL publishes no later-GW estimate; conservative for injured players, who are filtered from the ILP at 0% anyway).
- `P_h` = sum of 0.9^j x GW points over the horizon; the app recomputes it for horizons 1-5 from the published per-GW columns.
- SHAP: LightGBM `pred_contrib` on the next GW's rows, summed over a DGW's fixtures (additivity holds), stored as float32 with the first fixture's feature values. The waterfall shows the raw prediction; the page states the availability factor separately.
- `prev_season_pts_per90` (from `history_past`, season name `"2025/26"`) is **published context only, not a model feature** (developer's choice; adding it needs a retrain and a new walk-forward).

### Pipeline gate
- `--refresh/--predict` check the next deadline first (one bootstrap call, or the cached one for `--predict` alone) and exit 0 unless it's < 48 h away and `predictions_gwXX.parquet` doesn't exist; `--force` overrides. Daily cron + this gate = one refresh per GW before its deadline (PLAN §0.4).
- `latest.json` points the app at the newest files; earlier weeks' predictions stay committed as history.

### App
- **`src/fPLense/app_data.py` holds every non-UI helper** (loaders, horizon recompute, filters, waterfall data, pitch grouping, metrics table) as plain pandas, unit-tested without Streamlit. `app/shared.py` only adds `st.cache_data` (10-minute TTL so a pushed refresh shows up) and shared UI bits.
- Pages re-solve the ILP live (`st.cache_data` keyed on file + settings, ~2 s) rather than only showing the published squad, so the sliders mean something.
- Transfer Planner: picks for the last finished GW (the next GW's picks stay private until its deadline); bank prefilled from `entry_history.bank` and editable; free transfers user-entered (the API doesn't expose them); the recommended row is highlighted and the selling-price caveat is shown.
- Page smoke tests use Streamlit's `AppTest` (runs a page script headless, no server), which the CLAUDE.md "don't launch the app" rule allows; the Transfer Planner test injects the saved picks into session state, so no network call happens.
- `use_container_width` is deprecated in Streamlit 1.65; pages use `width="stretch"`.
- The saved picks sample (`tests/fixtures/picks_sample.json`) is the developer's own team, with their consent.

## P6: FastAPI backend + season-history data layer (2026-10-09)

### Streamlit out, FastAPI in
- **Why:** drag-and-drop team building, a 3-team compare, shareable URLs and a polished mobile UI are hard in Streamlit; splitting a typed API from a React frontend is also the stronger full-stack signal, and it keeps the model offline: the server only reads published files and solves ILPs.
- Deleted `app/`, `tests/test_app_pages.py`, `streamlit`/`plotly`. `app_data.py` → `published.py` (pure helpers reused by the API: `headline`, `waterfall_data`, `with_horizon`...).
- Installed FastAPI 0.143 / pydantic 2.14 / Starlette 1.7. Ruff's B008 (call in argument default) is whitelisted for `fastapi.Depends/Query/Path`: that's FastAPI's idiom.

### Card ratings: FPLense rating only (developer's choice)
- The EA SPORTS FC dataset was **dropped** (PLAN's cut list allows it). Candidates checked on Kaggle on 2026-10-09 for the record: `justdhia/ea-sports-fc-26-player-ratings` (CC0, updated 2026-03-18), `rovnez/fc-26-fifa-26-player-data` (CC BY 4.0, 2025-09-21), `flynn28/eafc26-player-database` (GPL-3.0). No `rapidfuzz` dependency, no overrides CSV.
- `rating = round(50 + 49 × percentile of P_h within position)` among available players (status not `u`, availability > 0); percentile = share of available same-position players with a lower value (+ half the ties), so the worst is 50 and the best 99. Unavailable players are placed on the same scale (a long injury reads low instead of disappearing). Published as `ratings.json` (`element → {code, rating}`, `source: "fplense"`); `--predict` rewrites it each GW, `--ratings` on demand.
- **Photo URL confirmed:** `https://resources.premierleague.com/premierleague25/photos/players/110x140/{code}.png` → HTTP 200 (code 154561); the `p{code}` form under `premierleague25` → 403; `premierleague26` → 502. Only the URL is built; images are never fetched by the backend.

### Model identity and the write-once archive
- `model_meta.json` (sha256 of `model.txt` + `train_max_season`) is what the archive and the backfill refusal read. `train_final` now writes it. For the committed P3 model it was written once on 2026-10-09 with `train_max_season = 2025-26`: `train.load_features` reads only the 10-season lake (`data/lake/player_match/`, the live season lives apart in `data/lake/live/`), so that is a fact, not a guess. A meta whose hash doesn't match `model.txt` raises ("rerun --train").
- `history/gwXX/` is written once; a second write raises `ArchiveExistsError`. `--predict` archives its GW as `live` (a GW already archived is left alone, so `--predict --force` can't rewrite history). `--force-history` rebuilds **backfilled** GWs only; a live archive is never replaced by a backfill.
- **GW6 was archived as `live`** from `predictions_gw06.parquet` / `squad_gw06.json`, which the live path wrote on 2026-10-08 before the GW6 deadline (`made_at` = `latest.json.generated_at`). `--history` does this for any published predictions file without an archive.

### As-of backfill (GW1-5)
- Same mechanism as the P2 leakage test and the live path: lake truncated to GWs `< k`, GW k's fixtures appended with every outcome blanked, read back through the same views (`predict.horizon_features`). A test checks the backfilled GW k features equal the full lake's GW k features exactly, and that changing GW k outcomes doesn't move them while changing GW k-1 does.
- Club and price per player come from his **GW k lake row** (latest earlier row if his club blanked); players whose first lake row is after GW k are dropped. Approximation: 0-minute players' synthesized rows (P5) carry today's price and exist for every finished fixture of today's club, so their GW-k price and registration date are today's. Affects only players who never played, and the archive says `backfill`.
- **Odds:** pre-closing `E0.csv` rows only for GW k's own fixtures (football-data collects them the Friday before the round); later horizon GWs use the Elo estimate, exactly as the live path would have at that deadline. Elo snapshots are cut to dates before GW k's first kick-off.
- Availability unknown for past GWs → 100% (`status a`, chance NaN), stated in `meta.caveat`.
- Squad: the default ILP (£100m, horizon 5, bench weight 0.1) on the backfilled table.

### Actuals, hindsight, summary
- `actuals_2026-27.parquet` per (element, gw): points and minutes summed over a DGW, `price` = first fixture's `value`, `fixtures` (club fixtures) and `fixtures_played` (appearances).
- **Hindsight-best** = the squad ILP with `p1 = P_h = actual points`, bench weight 0, that GW's prices, £100m, all rules. With bench weight 0 the ILP's captain term picks the best actual starter. It's not FPL's Dream Team (no budget/quotas there).
- Model-pick actual points reuse `backtest.score_gw` (auto-subs in bench order keeping a legal formation, captain doubled, vice if the captain didn't play). Players whose club blanked score 0. Chips are ignored.
- Capture ratio = model actual / hindsight-best, **not clipped**. It can't exceed 1 when both squads are priced the same; the only theoretical way above 1 is a price rise between the live prediction and the deadline making the model pick cost > £100m at GW-k prices. Product stat only, never a resume claim.
- `fixtures.json` (schedule, FDR, results) is published so the API can build fixture tickers without the lake.

### Optimizer extensions
- `pick_squad(locked, banned)`: locks bypass the availability filter (you may want an injured player you already own). `check_locks` fails fast with a cause before solving: `quota` (too many of a position), `club limit`, `budget` (locked cost + cheapest fill of the other slots > budget), `conflict` (locked and banned); anything else that's infeasible says so generically. API → 422 `{detail, kind}`.
- `best_lineup`: the squad ILP with every `x_i` fixed to 1, no budget and no club limit (the squad is given). The lineup helper passes next-GW points as both `p1` and `P_h`.
- `rule_problems` works on 0-15 players (for the builder's live chips); the budget can be reported without being a violation (`enforce_budget=False` for real teams and codes).
- **Planner T = 0..5** (`config.MAX_TRANSFERS_PLAN`); the P4 default of 3 (`MAX_TRANSFERS_PLANNED`) stays for the backtest.
- **Path to the target is nested, one move per step.** Solving each T independently gives optimal-but-unrelated move sets (T = 2 might sell different players than T = 1), which can't be shown as an ordered stepper and broke like-for-like pairing. Step T keeps the T-1 earlier moves (`force_in`/`force_out`) and adds the best next one among `target - current` buys and `current - target` sales. Greedy in order, but every step's marginal gain is real and the moves are a sequence the user can follow over weeks. PLAN's "cumulative gain non-decreasing in free moves" is tested as: for each step, more free transfers never lower the net gain, and hits = 4 × max(0, moves − free).
- Recommendation text: make the number of moves with the best net gain now (with free transfers or naming the hits), the rest with later free transfers.

### Making the ILP fast enough to serve
- First API timing: `/transfers/plan` p50 ≈ 40 s. Two fixes, both keeping exact optimality:
  1. **`df.at` → dict lookups** in the constraint/objective builders, and `validate_pool` keeps only the solver's columns as plain numpy/object columns. pandas `.at` on the wide API frame (Arrow strings) cost ~0.1 ms × ~56k lookups per plan.
  2. **Dominance pruning** (`prune_dominated`): drop player `i` when same-position players that cost no more and have `p1` and `P_h` at least as high span ≥ `quota + 5` distinct clubs. Proof sketch: in any squad containing `i`, at most `quota − 1` of those dominators are already picked and at most 5 clubs (15 / 3) are full, so one dominator can replace `i` at no extra cost with an objective at least as high; dominance is a strict order, so repeating ends at an optimal squad without pruned players. Owned/locked players are never pruned or used as dominators. Real GW6 pool: 485 → 230 players; identical objectives on 4 settings and in a randomized test.
- Result: `/optimize` ~0.9-1.1 s, `/transfers/plan` (T = 0..5 + a 12-step path) ~2.5 s locally (PROGRESS.md P6 has the measured p95s).
- CBC gets a 20 s `timeLimit` on request-time solves (free-tier protection).

### Team codes
- Payload exactly as PLAN: version u8, season u16 (2627), 15 × u16 ids (XI GK→FWD then bench order), `captain_idx << 4 | vice_idx`, CRC-8, big-endian = 35 bytes = **56 Crockford base32 chars**, no padding. Full code `FPLN-2627-…` is **66 characters** (PLAN said ≈ 60).
- **CRC-8/SMBUS** (poly 0x07, init 0, check value 0xF4 for "123456789", pinned in the vectors so TypeScript can verify its CRC first). Any error burst ≤ 8 bits is detected, and one base32 character is 5 bits, so every single-character substitution is caught (tested exhaustively on 3 vectors: 56 × 31 typos each).
- Lenient form: any case, whitespace anywhere, optional dashes, `I/L → 1`, `O → 0`, share URLs (`?t=`). Strict content, each with its own `kind`: `junk`, `typo` (length, alphabet, checksum, or an edited season label), `version`, `season`, `duplicate`, `captain`, then (against the player list) `unknown`, `shape`, `club`. Budget reported (`over_budget`), never enforced.
- Vectors in `tests/fixtures/team_code_vectors.json` use **synthetic** players; generated by `scripts/make_team_code_vectors.py`.

### API design
- `Store` loads each published file on first use and caches it with its mtime; a changed file reloads on the next request. No ETL/DuckDB/LightGBM/SHAP/sklearn import anywhere on the API path (a test imports `fPLense.api.main` in a subprocess and checks `sys.modules`).
- A **GW context** = the player pool for one GW: live predictions for GWs in the current horizon, else the frozen archive, with actuals joined once the GW is finished. Every squad response (`Squad`) carries XI/bench/captain/vice, expected points for the GW and per horizon GW, actual points if finished, cost, rule problems and its **team code**.
- GET responses from published data get `Cache-Control: public, max-age=300` and an `ETag` (SHA-1 of the body, `If-None-Match` → 304) from one middleware; `/api/entry/*` and `/api/health` are excluded. GZip ≥ 1 KB (`/api/players` 670 KB → 47 KB).
- Errors are JSON `{detail, kind}`: 404 not found, 422 bad input / infeasible locks (`kind` = cause) / bad codes (`kind` = code error), 429 + `Retry-After`, 503 not published or FPL updating (+ `Retry-After: 60`), 502 other upstream failures.
- Per-IP **token bucket** (20 requests, refilled 1 every 2 s) on `/entry/*`, `/squads/optimize`, `/transfers/*`, `/compare`. CORS from `FPLENSE_CORS_ORIGINS` (default the Vite dev server), methods GET/POST only.
- **FPL proxy**: async `httpx`, one global limiter (≥ 0.25 s between upstream calls), retries with backoff on network errors / 429 / 5xx, schema checks (`fetch_api.check_entry`, `check_entry_history`, `check_picks`). TTL 10 min for `entry`, `history` and current-GW picks; finished-GW picks in an LRU (2,048) with no expiry. Upstream 404 → "No FPL team with ID …" (or "No picks for … GW n" for picks before the deadline).
- Extra endpoint `GET /api/model` (metrics, MAE by GW, SHAP importance, backtest) for P7's Model Card page.
- `/entry/{id}/gw/{gw}` resolves picks on that GW's pool (archived expected + actual points) and runs the lineup helper on `predict_gw` (default: the same GW). `/transfers/plan` with a `team_id` uses the picks of the entry's `current_event` and pre-fills the bank from them.
- `web/openapi.json` is written by `python -m fPLense.api.export_openapi`; a test fails on drift.
- Saved `tests/fixtures/entry_sample.json` and `entry_history_sample.json` from the developer's own team (same consent as the P5 picks sample; leagues list emptied).
- API tests run on `tests/published_mini.py`, a synthetic published folder **built at test time** with the pipeline's own writers (60 players, GW1 backfilled, GW2 live, GW3 next) instead of committed binary Parquet, and a `MockTransport` fake of the FPL API. No network in any test.

### Found while checking the phase
- **Backtest tie-breaking.** Rerunning `--backtest` after the pruning change gave A 1,751 (same), C 1,844 (same), **B 1,842 (was 1,826)**; A − B −91 [−299, +102], still not significant. Cause: B0 predictions are averages of integer points, so many squads tie on the objective (only 16.7% of GW5 regulars' B0 values are distinct vs 100% for LightGBM); pruning changes which tied optimum CBC returns, and the one-path backtest then diverges. The committed P4 artifacts (`backtest.json`, `backtest_cumulative.png`, model card) were **kept at the P4 run**; a future `--backtest` will print ~1,842 for B. Neither number is a claim; the conclusion (no significant decision-layer gain) holds either way.
- **httpx client per event loop.** The proxy first created its `AsyncClient` at app creation; a request on a second event loop (TestClient without `with`, a reloaded worker) reused a pooled connection tied to a closed loop → `RuntimeError: Event loop is closed`. The client (and the limiter's lock) are now created lazily inside the running loop and rebuilt when the loop changes. Found by a real-FPL smoke call; regression test added (MockTransport has no pool, so the offline tests couldn't see it).
- **Real-data check of the scoring:** for the developer's team, `/api/entry/{id}/gw/5` scored the GW5 picks at **56**, FPL's official 56, with the same auto-sub (165 → 15) FPL applied.
