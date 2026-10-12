# FPLense

Fantasy Premier League points forecaster and squad optimizer

A `Python ETL` and `DuckDB` feature store, a `LightGBM` forecast validated walk-forward and explained with `SHAP`, a `PuLP` squad optimizer and transfer planner, served by a `FastAPI` backend to a `React` web app (see `PLAN.md`).

## Run the API locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
uvicorn fPLense.api.main:app --reload
```

## Run the web app locally

Needs Node 20+ and the API (above) running. The app calls `VITE_API_URL` (default `http://localhost:8000`).

```powershell
cd web
npm ci
npm run dev
```
