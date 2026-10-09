"""``/api/squads/best``, ``/api/squads/optimize`` and ``/api/squads/evaluate``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from fPLense import config
from fPLense.api import schemas, views
from fPLense.api.deps import get_store, rate_limit
from fPLense.api.store import Store
from fPLense.optimize.squad_ilp import evaluate_squad, pick_squad

router = APIRouter(prefix="/squads", tags=["squads"])


@router.get("/best", response_model=schemas.Squad)
def best(
    gw: int | None = Query(None, ge=1, le=38, description="default: the next gameweek"),
    store: Store = Depends(get_store),
) -> schemas.Squad:
    """The model's pick: the frozen archive for a past GW, the live best team for the next."""
    return views.model_pick(store, gw)


@router.post("/optimize", response_model=schemas.Squad, dependencies=[Depends(rate_limit)])
def optimize(body: schemas.OptimizeIn, store: Store = Depends(get_store)) -> schemas.Squad:
    """Re-solve the squad ILP for the next GW with your budget, horizon, bench weight, locks
    and bans. An impossible lock set answers 422 naming the broken rule."""
    ctx = views.gw_context(store, None, horizon=body.horizon)
    pool = ctx.pool.assign(price=ctx.pool["price"].astype(int))
    unknown = [i for i in body.locked + body.banned if i not in pool.index]
    if unknown:
        raise views.BadRequest(f"unknown player ids: {unknown}", "unknown")
    res = pick_squad(
        pool,
        budget=body.budget,
        bench_w=body.bench_weight,
        locked=body.locked,
        banned=body.banned,
        time_limit=config.API_SOLVER_TIME_LIMIT_S,
    )
    return views.build_squad(
        ctx,
        res.squad,
        res.starters,
        res.bench,
        res.captain,
        res.vice,
        "optimized",
        f"Best team GW{ctx.gw}",
        budget=body.budget,
    )


@router.post("/evaluate", response_model=schemas.EvaluateOut)
def evaluate(body: schemas.EvaluateIn, store: Store = Depends(get_store)) -> schemas.EvaluateOut:
    """Expected (and, for a finished GW, actual) points, cost and a plain-English rule report
    for any 0-15 players; a full squad without an XI gets the lineup helper's."""
    ctx = views.gw_context(store, body.gw)
    pool = ctx.pool
    actual = None
    if ctx.finished:
        actual = pool[["actual", "minutes"]].rename(columns={"actual": "points"})
    out = evaluate_squad(
        pool,
        body.players,
        body.starters,
        body.captain,
        body.vice,
        gw_cols=ctx.gw_cols,
        actual=actual,
    )
    known = [i for i in dict.fromkeys(body.players) if i in pool.index]
    start = set(out["starters"])
    order = {i: k + 1 for k, i in enumerate(out["bench"])}
    players = [
        views.squad_player(
            pool.loc[i], i in start, order.get(i), i == out["captain"], i == out["vice"], ctx
        )
        for i in known
    ]
    first = next(iter(ctx.gw_cols), ctx.gw)
    return schemas.EvaluateOut(
        gw=ctx.gw,
        finished=ctx.finished,
        legal=out["legal"],
        problems=[schemas.Problem(**p) for p in out["problems"]],
        cost=out["cost"],
        bank=out["bank"],
        starters=out["starters"],
        bench=out["bench"],
        captain=out["captain"],
        vice=out["vice"],
        expected_points=round(out["expected"][first], 3) if out["expected"] else None,
        horizon_expected=[
            schemas.GwPoints(gw=g, points=round(v, 3)) for g, v in out["expected"].items()
        ],
        actual_points=out["actual"]["points"] if out["actual"] else None,
        players=players,
    )
