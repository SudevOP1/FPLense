"""``/api/transfers/plan``: T = 0..5 options and the path to the best team."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from fPLense import config
from fPLense.api import schemas, views
from fPLense.api.deps import get_proxy, get_store, rate_limit
from fPLense.api.fpl_proxy import FplProxy
from fPLense.api.store import Store
from fPLense.optimize import transfers as planner
from fPLense.optimize.squad_ilp import pick_squad

router = APIRouter(prefix="/transfers", tags=["transfers"], dependencies=[Depends(rate_limit)])

CAVEAT = (
    "FPL doesn't publish selling prices (you keep only half of any price rise), so your players "
    "are valued at today's price. If you'd get less for someone, lower the bank to match."
)


def _moves(ctx: views.GwContext, outs: list[int], ins: list[int]) -> list[schemas.Move]:
    pool = ctx.pool
    moves = []
    for o, n in planner.pair_moves(pool, outs, ins):
        moves.append(
            schemas.Move(
                out=views.squad_player(pool.loc[o], False, None, False, False, ctx),
                into=views.squad_player(pool.loc[n], False, None, False, False, ctx),
                gain=round(float(pool.at[n, "P_h"] - pool.at[o, "P_h"]), 3),
            )
        )
    return moves


@router.post("/plan", response_model=schemas.TransferOut)
async def plan(
    body: schemas.TransferIn,
    store: Store = Depends(get_store),
    proxy: FplProxy = Depends(get_proxy),
) -> schemas.TransferOut:
    """Best moves for T = 0..5 transfers (net of -4 hits beyond your free ones) and a
    step-by-step path from your squad to the model's best squad."""
    if body.team_id is None and body.squad is None:
        raise views.BadRequest("send a team_id or a squad of 15 player ids", "invalid")
    starters = captain = vice = None
    bank = body.bank
    if body.squad is not None:
        current = list(body.squad)
    else:
        e = await proxy.entry(body.team_id)
        gw = e.get("current_event")
        if not gw:
            raise views.NotFound(f"FPL team {body.team_id} hasn't played a gameweek yet")
        picks = await proxy.picks(body.team_id, gw, finished=gw in store.finished_gws())
        current, starters, _, captain, vice = views.picks_lineup(picks)
        bank = picks["entry_history"]["bank"] if bank is None else bank
    bank = 0 if bank is None else bank

    def solve():
        ctx = views.gw_context(store, None, horizon=body.horizon)
        pool = ctx.pool.assign(price=ctx.pool["price"].astype(int))
        unknown = [i for i in current if i not in pool.index]
        if unknown:
            raise views.BadRequest(f"unknown player ids: {unknown}", "unknown")
        if len(set(current)) != 15:
            raise views.BadRequest("the squad must have 15 different players", "shape")
        if body.path:
            target = (
                body.target or pick_squad(pool, time_limit=config.API_SOLVER_TIME_LIMIT_S).squad
            )
        else:
            target = None
        result = planner.plan(
            pool, current, bank, body.free_transfers, body.max_transfers, target=target
        )
        return ctx, result, target

    ctx, result, target = await run_in_threadpool(solve)
    cur = views.build_squad(
        ctx,
        current,
        starters,
        None,
        captain,
        vice,
        "entry" if body.team_id else "squad",
        "Your squad",
        enforce_budget=False,
    )
    rec = result["recommended"].n_transfers
    options = [
        schemas.TransferOptionOut(
            n_transfers=o.n_transfers,
            moves=_moves(ctx, o.outs, o.ins),
            hits=o.hits,
            expected_points=round(o.result.expected_points, 3),
            net_gain=round(o.gain_vs_hold, 3),
            bank_after=o.bank_after,
            recommended=o.n_transfers == rec,
        )
        for o in result["options"]
    ]
    path = None
    if result["path"] is not None:
        p = result["path"]
        path = schemas.PathOut(
            target=views.build_squad(
                ctx, target, None, None, None, None, "model_pick", "Best team"
            ),
            steps=[
                schemas.PathStepOut(
                    n_moves=s.n_moves,
                    new_moves=_moves(ctx, [s.new_out], [s.new_in]),
                    gain_before_hits=round(s.gain_before_hits, 3),
                    hits=s.hits,
                    net_gain=round(s.net_gain, 3),
                    bank_after=s.option.bank_after,
                )
                for s in p["steps"]
            ],
            make_now=p["make_now"],
            advice=p["advice"],
        )
    return schemas.TransferOut(
        gw=ctx.gw,
        current=cur,
        bank=bank,
        free_transfers=body.free_transfers,
        options=options,
        recommended=rec,
        path=path,
        caveat=CAVEAT,
    )
