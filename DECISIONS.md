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
