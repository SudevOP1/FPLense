"""``/api/compare``: 2 or 3 teams side by side, each from its own source and gameweek."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from fPLense import config
from fPLense.api import schemas, views
from fPLense.api.deps import get_proxy, get_store, rate_limit
from fPLense.api.fpl_proxy import FplProxy
from fPLense.api.store import Store

router = APIRouter(tags=["compare"], dependencies=[Depends(rate_limit)])
LETTERS = ["A", "B", "C"]


def _last_finished(store: Store) -> int:
    done = store.finished_gws()
    if not done:
        raise views.NotFound("no finished gameweek yet")
    return max(done)


async def _picks(slot: schemas.Slot, store: Store, proxy: FplProxy) -> tuple[int, dict]:
    if not isinstance(slot.value, int) or isinstance(slot.value, bool) or slot.value <= 0:
        raise views.BadRequest("an entry slot needs a team id as its value", "invalid")
    gw = slot.gw or _last_finished(store)
    return gw, await proxy.picks(slot.value, gw, finished=gw in store.finished_gws())


def _resolve(slot: schemas.Slot, store: Store, picks: dict | None) -> schemas.Squad:
    label = slot.label
    if slot.kind == "model_pick":
        sq = views.model_pick(store, slot.gw)
    elif slot.kind == "hindsight":
        sq = views.hindsight(store, slot.gw or _last_finished(store))
    elif slot.kind == "entry":
        gw = slot.gw or _last_finished(store)
        ids, starters, bench, captain, vice = views.picks_lineup(picks)
        ctx = views.gw_context(store, gw)
        sq = views.build_squad(
            ctx,
            ids,
            starters,
            bench,
            captain,
            vice,
            "entry",
            f"Team {slot.value} GW{gw}",
            enforce_budget=False,
        )
    elif slot.kind == "code":
        if not isinstance(slot.value, str):
            raise views.BadRequest("a code slot needs the team code as its value", "invalid")
        sq, _ = views.decode_code(store, slot.value, slot.gw)
    else:
        if not isinstance(slot.value, list) or len(slot.value) != 15:
            raise views.BadRequest("a squad slot needs 15 player ids as its value", "invalid")
        ctx = views.gw_context(store, slot.gw)
        sq = views.build_squad(
            ctx,
            slot.value,
            slot.starters,
            None,
            slot.captain,
            slot.vice,
            "squad",
            "Custom squad",
        )
    if label:
        sq.label = label
    return sq


def _slot_out(letter: str, kind: str, sq: schemas.Squad, others: set[int]) -> schemas.SlotOut:
    by_id = {p.id: p for p in sq.players}
    cap = by_id[sq.captain]
    bench = [by_id[i] for i in sq.bench]
    xi = [by_id[i] for i in sq.starters]
    finished = sq.actual_points is not None
    return schemas.SlotOut(
        letter=letter,
        kind=kind,
        squad=sq,
        captain_expected=cap.expected,
        captain_actual=cap.actual if finished else None,
        bench_expected=round(sum(p.expected or 0 for p in bench), 3),
        bench_actual=sum(p.actual or 0 for p in bench) if finished else None,
        by_position=[
            schemas.PositionPoints(
                pos=pos,
                expected=round(sum(p.expected or 0 for p in xi if p.pos == pos), 3),
                actual=sum(p.actual or 0 for p in xi if p.pos == pos) if finished else None,
            )
            for pos in config.SQUAD_QUOTAS
        ],
        differentials=[p.id for p in sq.players if p.id not in others],
    )


@router.post("/compare", response_model=schemas.CompareOut)
async def compare(
    body: schemas.CompareIn,
    store: Store = Depends(get_store),
    proxy: FplProxy = Depends(get_proxy),
) -> schemas.CompareOut:
    """Each slot: squad, XI/bench/captain, expected and actual points, cost, points by
    position, captain and bench points. Across slots: shared players, differentials and
    expected points per GW over the horizon."""
    picks = []
    for slot in body.slots:
        picks.append((await _picks(slot, store, proxy))[1] if slot.kind == "entry" else None)

    def build():
        return [_resolve(s, store, p) for s, p in zip(body.slots, picks, strict=True)]

    squads = await run_in_threadpool(build)
    ids = [{p.id for p in sq.players} for sq in squads]
    out = []
    for k, (slot, sq) in enumerate(zip(body.slots, squads, strict=True)):
        others = set().union(*(s for j, s in enumerate(ids) if j != k))
        out.append(_slot_out(LETTERS[k], slot.kind, sq, others))
    counts: dict[int, list[str]] = {}
    for k, s in enumerate(ids):
        for i in s:
            counts.setdefault(i, []).append(LETTERS[k])
    shared = [schemas.SharedPlayer(id=i, slots=v) for i, v in sorted(counts.items()) if len(v) > 1]
    gws = sorted({g.gw for sq in squads for g in sq.horizon_expected})
    horizon = [
        schemas.HorizonRow(
            gw=g,
            points=[
                next((h.points for h in sq.horizon_expected if h.gw == g), None) for sq in squads
            ],
        )
        for g in gws
    ]
    return schemas.CompareOut(slots=out, shared=shared, horizon=horizon)
