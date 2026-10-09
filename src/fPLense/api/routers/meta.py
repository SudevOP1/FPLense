"""``/api/health`` and ``/api/meta``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from fPLense import config, published
from fPLense.api import schemas
from fPLense.api.deps import get_store
from fPLense.api.store import NotPublishedError, Store

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=schemas.Health)
def health(store: Store = Depends(get_store)) -> schemas.Health:
    """Liveness plus what's published (cheap: the frontend polls it to detect cold starts)."""
    try:
        latest = store.latest()
    except NotPublishedError:
        return schemas.Health(
            status="no_data", season=config.CURRENT_SEASON, next_gw=None, published_at=None
        )
    return schemas.Health(
        status="ok",
        season=latest.get("season", config.CURRENT_SEASON),
        next_gw=latest.get("gw"),
        published_at=latest.get("generated_at"),
    )


@router.get("/meta", response_model=schemas.Meta)
def meta(store: Store = Depends(get_store)) -> schemas.Meta:
    """Season, gameweeks (next, finished, archived live vs backfilled), deadline, headline."""
    latest = store.latest()
    archived = store.archived_gws()
    sources = {gw: (store.archive(gw) or {}).get("meta", {}).get("source") for gw in archived}
    finished = store.finished_gws()
    ratings = store.json(config.RATINGS_PATH.name) or {}
    return schemas.Meta(
        season=latest.get("season", config.CURRENT_SEASON),
        current_gw=max(finished) if finished else latest.get("data_through_gw"),
        next_gw=latest["gw"],
        deadline=latest.get("deadline"),
        gws=latest["gws"],
        finished_gws=finished,
        archived_gws=archived,
        backfilled_gws=[g for g, s in sources.items() if s == "backfill"],
        live_gws=[g for g, s in sources.items() if s == "live"],
        generated_at=latest.get("generated_at"),
        data_through_gw=latest.get("data_through_gw"),
        horizon_max=config.PREDICT_HORIZON_MAX,
        budget=config.BUDGET,
        headline=published.headline(store.metrics()),
        rating_source=ratings.get("source", "fplense"),
    )


@router.get("/model", tags=["meta"])
def model_card(store: Store = Depends(get_store)) -> dict:
    """Metrics with CIs, MAE by GW, SHAP importance and the backtest (Model Card page)."""
    metrics = store.metrics()
    return {
        "headline": published.headline(metrics),
        "metrics": metrics,
        "mae_by_gw": store.mae_by_gw(),
        "shap_importance": store.shap_importance(),
        "backtest": store.backtest(),
    }
