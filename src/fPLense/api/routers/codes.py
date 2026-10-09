"""``/api/codes/decode`` and ``/api/codes/encode``: copy-paste team codes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from fPLense import config, team_code
from fPLense.api import schemas, views
from fPLense.api.deps import get_store
from fPLense.api.store import Store

router = APIRouter(prefix="/codes", tags=["codes"])


@router.post("/decode", response_model=schemas.DecodeOut)
def decode(body: schemas.DecodeIn, store: Store = Depends(get_store)) -> schemas.DecodeOut:
    """A team code (or a share URL containing one) -> the squad with expected points for the
    next GW. Bad codes answer 422 with a specific message (typo, other season, illegal team)."""
    squad, info = views.decode_code(store, body.code)
    return schemas.DecodeOut(
        code=squad.code or team_code.extract(body.code),
        season=config.CURRENT_SEASON,
        squad=squad,
        over_budget=info["over_budget"],
    )


@router.post("/encode", response_model=schemas.EncodeOut)
def encode(body: schemas.EncodeIn, store: Store = Depends(get_store)) -> schemas.EncodeOut:
    """11 starters + 4 bench (in order) + captain and vice -> a shareable code."""
    ctx = views.gw_context(store, None)
    ids = body.starters + body.bench
    unknown = [i for i in ids if i not in ctx.pool.index]
    if unknown:
        raise views.BadRequest(f"unknown player ids: {unknown}", "unknown")
    players = {
        int(i): {"pos": r["pos"], "club": r["club"], "price": int(r["price"])}
        for i, r in ctx.pool.loc[ids, ["pos", "club", "price"]].iterrows()
    }
    starters = views.order_starters(ctx.pool, body.starters)
    code = team_code.encode(starters, body.bench, body.captain, body.vice)
    team_code.validate(team_code.decode(code), players)
    return schemas.EncodeOut(code=code, share_param=f"t={code}")
