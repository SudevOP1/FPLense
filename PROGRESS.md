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
