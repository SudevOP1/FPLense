"""``/api/history/summary`` and ``/api/history/{gw}`` (Season Replay)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from fPLense.api import schemas, views
from fPLense.api.deps import get_store
from fPLense.api.store import Store

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/summary", response_model=schemas.HistorySummary)
def summary(store: Store = Depends(get_store)) -> schemas.HistorySummary:
    """Per finished GW: model pick expected and actual points, hindsight-best, average and
    highest manager scores, and the capture ratio (model pick / hindsight-best; a product
    stat, not a claim)."""
    doc = store.summary()
    if not doc:
        raise views.NotFound("no season history published yet (run the pipeline's --history)")
    season = store.season() or {"events": []}
    return schemas.HistorySummary(
        season=doc["season"],
        note=doc.get("note", ""),
        gws=doc["gws"],
        events=[schemas.SeasonEvent(**e) for e in season["events"]],
    )


@router.get("/{gw}", response_model=schemas.HistoryGw)
def history_gw(gw: int = Path(ge=1, le=38), store: Store = Depends(get_store)) -> schemas.HistoryGw:
    """One GW: the model's pick (frozen before the deadline) next to the hindsight-best squad,
    both with actual points; ``source`` says whether the pick was live or backfilled."""
    archive = store.archive(gw)
    if archive is None:
        raise views.NotFound(f"GW{gw} isn't archived")
    ctx = views.gw_context(store, gw)
    if ctx.archive is None:  # the live horizon covers this GW: use the frozen archive anyway
        ctx = views.GwContext(
            gw, archive["meta"].get("source", "live"), ctx.finished, ctx.pool, ctx.gw_cols, archive
        )
    pick = views.squad_from_doc(ctx, archive["squad"], "model_pick", f"Model pick GW{gw}")
    hind = views.squad_from_hindsight(ctx, archive["hindsight"]) if archive["hindsight"] else None
    rows = {r["gw"]: r for r in (store.summary() or {}).get("gws", [])}
    meta = archive["meta"]
    return schemas.HistoryGw(
        gw=gw,
        source=meta.get("source", "live"),
        made_at=meta.get("made_at"),
        caveat=meta.get("caveat"),
        model_pick=pick,
        hindsight=hind,
        summary=rows.get(gw),
    )
