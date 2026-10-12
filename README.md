# FPLense

Fantasy Premier League points forecaster and squad optimizer: a Python ETL and DuckDB feature store, a LightGBM forecast validated walk-forward and explained with SHAP, a PuLP squad optimizer and transfer planner, served by a FastAPI backend to a React web app (see `PLAN.md`).

## Run the API locally

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt; pip install -e .
uvicorn fPLense.api.main:app --reload     # http://127.0.0.1:8000/docs
```

The API reads only `data/published/` (committed). Refresh it with `python -m fPLense.pipeline --refresh --predict --history --horizon 5`.

## Run the web app locally

Needs Node 20+ and the API running (above). The app calls `VITE_API_URL` (default `http://localhost:8000`).

```powershell
cd web
npm ci
npm run dev        # http://localhost:5173 (the dev-only /dev/kitchen-sink route shows every component)
npm run lint; npm run typecheck; npm test -- --run; npm run build
```

Tests never hit the network: MSW answers with fixtures that the real API produced on a synthetic folder (`python scripts/make_web_fixtures.py`). After an API schema change, run `python -m fPLense.api.export_openapi`, `npm run gen:types` and the fixture script.

Code is MIT-licensed. The data it downloads is **not** covered by the code licence; see `PLAN.md` §0.3 for sources and credits. Player photos are hotlinked from the Premier League CDN (© Premier League), never re-hosted. Not affiliated with the Premier League; not betting advice.
