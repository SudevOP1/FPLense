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
