"""``/api/players`` and ``/api/players/{id}``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from fPLense import published
from fPLense.api import schemas, views
from fPLense.api.deps import get_store
from fPLense.api.store import Store

router = APIRouter(tags=["players"])


@router.get("/players", response_model=schemas.PlayersOut)
def players(
    gw: int | None = Query(None, ge=1, le=38, description="default: the next gameweek"),
    store: Store = Depends(get_store),
) -> schemas.PlayersOut:
    """Every player for a GW: price, availability, rating, photo URL, expected points per GW,
    ``P_h``, actual points once the GW is finished, and the next 5 GWs' fixtures with FDR."""
    ctx = views.gw_context(store, gw)
    ticks = views.fixture_ticks(store, ctx.gw)
    pool = ctx.pool.sort_values("P_h", ascending=False)
    return schemas.PlayersOut(
        gw=ctx.gw,
        gws=list(ctx.gw_cols),
        source=ctx.source,
        finished=ctx.finished,
        players=[views.player_out(r, ctx, ticks) for _, r in pool.iterrows()],
    )


@router.get("/players/{player_id}", response_model=schemas.PlayerDetail)
def player(player_id: int = Path(gt=0), store: Store = Depends(get_store)) -> schemas.PlayerDetail:
    """One player: expected vs actual points each GW this season, the next-GW SHAP waterfall
    ("why the model thinks this"), fixtures and ownership."""
    ctx = views.gw_context(store)
    if player_id not in ctx.pool.index:
        raise views.NotFound(f"no player with id {player_id}")
    r = ctx.pool.loc[player_id]
    ticks = views.fixture_ticks(store, ctx.gw)
    base = views.player_out(r, ctx, ticks).model_dump()

    season = []
    act = store.actuals()
    for gw in store.archived_gws():
        a = store.archive(gw)
        p = a["predictions"]
        row = act[(act["element"] == player_id) & (act["gw"] == gw)] if act is not None else None
        done = gw in store.finished_gws()
        season.append(
            schemas.PlayerGw(
                gw=gw,
                expected=views._f(p.at[player_id, "p"]) if player_id in p.index else None,
                actual=int(row["total_points"].sum()) if done and row is not None else None,
                minutes=int(row["minutes"].sum()) if done and row is not None else None,
                source=a["meta"].get("source"),
            )
        )
    for g, c in ctx.gw_cols.items():
        if g not in store.archived_gws():
            season.append(
                schemas.PlayerGw(
                    gw=g, expected=views._f(r[c]), actual=None, minutes=None, source="latest"
                )
            )

    shap_items, base_value, prediction = [], None, None
    sv = store.shap()
    if sv is not None and player_id in sv.index:
        srow = sv.loc[player_id]
        wf = published.waterfall_data(srow, k=10)
        base_value = views._f(srow.get("base_value"))
        prediction = (base_value or 0.0) + float(srow.filter(like="shap_").astype(float).sum())
        for w in wf.itertuples(index=False):
            v = w.value
            v = views._f(v) if views._f(v) is not None else (v if isinstance(v, str) else None)
            shap_items.append(schemas.ShapItem(feature=w.feature, shap=float(w.shap), value=v))
    return schemas.PlayerDetail(
        **base,
        season_points=views._i(r.get("season_points")),
        season_minutes=views._i(r.get("season_minutes")),
        prev_season_pts_per90=views._f(r.get("prev_season_pts_per90")),
        top_shap=r.get("top_shap") if isinstance(r.get("top_shap"), str) else None,
        shap_base_value=base_value,
        shap_prediction=prediction,
        shap=shap_items,
        season=season,
    )
