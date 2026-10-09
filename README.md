# FPLense

Fantasy Premier League points forecaster and squad optimizer: a Python ETL and DuckDB feature store, a LightGBM forecast validated walk-forward and explained with SHAP, a PuLP squad optimizer and transfer planner, served by a FastAPI backend to a React web app (in progress; see `PLAN.md`).

## Run the API locally

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt; pip install -e .
uvicorn fPLense.api.main:app --reload     # http://127.0.0.1:8000/docs
```

The API reads only `data/published/` (committed). Refresh it with `python -m fPLense.pipeline --refresh --predict --history --horizon 5`.

Code is MIT-licensed. The data it downloads is **not** covered by the code licence; see `PLAN.md` §0.3 for sources and credits. Player photos are hotlinked from the Premier League CDN (© Premier League), never re-hosted. Not affiliated with the Premier League; not betting advice.
