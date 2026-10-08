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
