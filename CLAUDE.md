# CLAUDE.md

Guidance for Claude Code working in this repo.

## Project

**FPLense**: a Fantasy Premier League points forecaster and squad optimizer, built to back a resume entry (dated Nov 2026). Repo: `github.com/SudevOP1/FPLense`.

Pipeline: Python ETL (vaastav GitHub history + FPL API + football-data.co.uk odds + Kaggle Elo) → Parquet lake → DuckDB SQL window-function feature views → Ridge / LightGBM, validated walk-forward, explained with SHAP → PuLP ILP squad optimizer + transfer planner → FastAPI backend + React frontend (P6–P7; the P5 Streamlit app is removed in P6), refreshed by GitHub Actions.

- `PLAN.md`: the source of truth. §0.0 phase status table, §0.1 build rules, §7 phase overview, §8 per-phase tasks / tests / "Done when", §9–§10 resume claims.
- `PROGRESS.md`: one note per finished phase (what shipped, deferred, measured numbers).
- `DECISIONS.md`: what was chosen and why (the developer must be able to explain every line in interviews).

## Stack and layout

- Python 3.12, pandas, pyarrow, DuckDB, scikit-learn, LightGBM, SciPy, SHAP, **PuLP pinned `>=3.3,<4`** (bundled CBC, `LpVariable.dicts` API), FastAPI + uvicorn + httpx (backend), React 18 + TypeScript + Vite + Tailwind + TanStack Query + dnd-kit + Recharts (frontend, `web/`), Matplotlib/Seaborn, pytest, ruff, Vitest.
- Package `fPLense` in src layout: `src/fPLense/{config.py, etl/, db/, models/, optimize/, api/, pipeline.py}`. Frontend in `web/`. Notebooks in `notebooks/`. Tests in `tests/`. Full tree in PLAN.md §6.
- Data: `data/raw/`, `data/lake/`, `data/fplense.duckdb` are **gitignored**. Only `data/published/` (predictions, squad JSON, metrics, `model.txt`) is committed.
- Dev machine is Windows (PowerShell). Paths in code use `pathlib`; no hard-coded separators.

## Commands

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt; pip install -e .
ruff check .; ruff format --check .
pytest -q                 # pure-logic tests (no data needed)
pytest -q -m data         # tests that need the downloaded lake
python -m fPLense.pipeline --help
uvicorn fPLense.api.main:app --reload   # developer runs this, not Claude
cd web; npm run lint; npm run typecheck; npm test -- --run; npm run build
npm run dev               # developer runs this, not Claude
```

## Hard rules

- **Keep the resume true** (PLAN.md §0.4, §9, §10). Don't rename the project, repo, package or headline stack. Design facts (250K+ rows, 10 seasons, 30+ features, £100m / 2-5-5-3 / max 3 per club) must actually be built. The ~10% MAE cut is **VERIFY**: report the measured number, never tune the claim to the target or the evaluation to the claim.
- **Leakage:** every rolling window ends at `1 PRECEDING` and partitions by `season, element`; `xP` is dropped; `selected`/`transfers_*` are lagged; bookmaker closing-odds columns (`…C…`, e.g. `AvgCH`, `B365C>2.5`) are dropped at load; Elo via `ASOF JOIN` strictly before kick-off; "regulars" = lagged `minutes_r3 >= 45`. Never break these to improve a metric.
- Missing columns in older seasons become **NaN, not 0**.
- Prices in the optimizer are **integer tenths** (`now_cost`, 55 = £5.5m).
- Never commit raw data, `kaggle.json`, `.env` or secrets. Missing Kaggle token → clear message pointing to PLAN.md §0.2.
- FPL API: browser-like `User-Agent`, ~0.25 s between calls, retries with backoff, schema checks. **Tests never hit the network**; use saved samples in `tests/fixtures/`.
- Tests needing the downloaded lake are marked `@pytest.mark.data` and skip cleanly when `data/lake/` is absent.
- Never skip, `xfail` or weaken a test to make it pass.
- The API reads only `data/published/` and never runs the ETL / DuckDB / model per request; its only network calls are user-triggered FPL `entry/*` calls (cached, rate-limited). The browser talks only to our API (plus hotlinked player photos, never re-hosted). Per-GW `data/published/history/` is write-once.
- Don't run the API server, the Vite dev server, other long-running servers or the full multi-minute data downloads / walk-forward unless the developer asks; give them the commands instead.

## Implementing a phase

When prompted "implement phase N from PLAN.md" (or similar), follow this order every time:

1. **Ask first.** Read `PLAN.md` + `PROGRESS.md` (and `DECISIONS.md`), then ask any clarifying questions up front with `AskUserQuestion` before writing code. Skip only if nothing is genuinely ambiguous.
2. **Implement the entire phase in one pass**: every module, SQL view, notebook, app page and test listed for it in PLAN.md §8. Don't stop for per-file verification.
3. **Run all relevant checks**: `ruff check .`, `ruff format --check .` and `pytest -q` (plus `pytest -q -m data` if the lake exists locally and the phase touches data code; plus the `web/` npm checks once `web/` exists). Fix failures before finishing. Tests yes; servers no.
4. **Finish with a summary**: what shipped, what was deferred (and why), then step-by-step manual-testing instructions with the exact PowerShell commands the developer should run and what to check (row counts, plots, metrics, what to look for on each app page). Then:
   - append the phase note to `PROGRESS.md` (date, shipped, deferred, measured numbers, follow-ups),
   - update the PLAN.md §0.0 status table (status, finish date, key result),
   - fill any measured values in PLAN.md §10 that the phase produced,
   - record non-obvious choices in `DECISIONS.md`.
