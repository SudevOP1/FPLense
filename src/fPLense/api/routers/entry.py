"""``/api/entry/{team_id}`` and ``/api/entry/{team_id}/gw/{gw}``: a public FPL team (My Team)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from starlette.concurrency import run_in_threadpool

from fPLense.api import schemas, views
from fPLense.api.deps import get_proxy, get_store, rate_limit
from fPLense.api.fpl_proxy import FplProxy
from fPLense.api.store import Store

router = APIRouter(prefix="/entry", tags=["entry"], dependencies=[Depends(rate_limit)])

TEAM_ID = Path(gt=0, le=100_000_000, description="the number in your FPL team URL")


@router.get("/{team_id}", response_model=schemas.Entry)
async def entry(
    team_id: int = TEAM_ID,
    store: Store = Depends(get_store),
    proxy: FplProxy = Depends(get_proxy),
) -> schemas.Entry:
    """Team and manager name, rank, value and bank, and every GW's points, rank, transfers,
    hits and chip, next to the model pick, the hindsight-best and the average score."""
    e = await proxy.entry(team_id)
    h = await proxy.history(team_id)
    rows = {r["gw"]: r for r in (store.summary() or {}).get("gws", [])}
    chips = {c["event"]: c["name"] for c in h["chips"]}
    history = []
    for g in h["current"]:
        gw = int(g["event"])
        s = rows.get(gw, {})
        history.append(
            schemas.EntryGw(
                gw=gw,
                points=g["points"],
                total_points=g["total_points"],
                rank=g.get("rank"),
                overall_rank=g.get("overall_rank"),
                bank=g["bank"],
                value=g["value"],
                transfers=g["event_transfers"],
                transfers_cost=g["event_transfers_cost"],
                points_on_bench=g["points_on_bench"],
                chip=chips.get(gw),
                model_pick_points=s.get("model_actual"),
                hindsight_points=s.get("hindsight_points"),
                average_entry_score=s.get("average_entry_score"),
            )
        )
    return schemas.Entry(
        id=int(e["id"]),
        team_name=e["name"],
        manager_name=f"{e['player_first_name']} {e['player_last_name']}".strip(),
        overall_points=e.get("summary_overall_points"),
        overall_rank=e.get("summary_overall_rank"),
        current_event=e.get("current_event"),
        value=e.get("last_deadline_value"),
        bank=e.get("last_deadline_bank"),
        history=history,
        chips=[schemas.Chip(name=c["name"], gw=c["event"]) for c in h["chips"]],
    )


def _context(store: Store, gw: int) -> views.GwContext:
    try:
        return views.gw_context(store, gw)
    except views.NotFound:
        return views.gw_context(store, None)


@router.get("/{team_id}/gw/{gw}", response_model=schemas.EntryGwOut)
async def entry_gw(
    team_id: int = TEAM_ID,
    gw: int = Path(ge=1, le=38),
    predict_gw: int | None = Query(
        None,
        ge=1,
        le=38,
        description="GW the lineup helper optimises (default: this GW if "
        "predictions exist for it, else the next GW)",
    ),
    store: Store = Depends(get_store),
    proxy: FplProxy = Depends(get_proxy),
) -> schemas.EntryGwOut:
    """That GW's picks resolved to players, with expected points (from the frozen archive) and
    actual points, plus the lineup helper's best XI and captain from the same 15."""
    picks = await proxy.picks(team_id, gw, finished=gw in store.finished_gws())

    def build():
        ids, starters, bench, captain, vice = views.picks_lineup(picks)
        ctx = _context(store, gw)
        squad = views.build_squad(
            ctx,
            ids,
            starters,
            bench,
            captain,
            vice,
            "entry",
            f"Team {team_id} GW{gw}",
            enforce_budget=False,
        )
        target = predict_gw or ctx.gw
        pctx = ctx if target == ctx.gw else views.gw_context(store, target)
        lineup = views.build_squad(
            pctx,
            ids,
            None,
            None,
            None,
            None,
            "lineup",
            f"Suggested lineup GW{pctx.gw}",
            enforce_budget=False,
        )
        return squad, lineup, pctx.gw, ids

    squad, lineup, pgw, ids = await run_in_threadpool(build)
    eh = picks["entry_history"]
    return schemas.EntryGwOut(
        team_id=team_id,
        gw=gw,
        predict_gw=pgw,
        active_chip=picks.get("active_chip"),
        points=eh.get("points"),
        bank=eh["bank"],
        value=eh["value"],
        squad=squad,
        automatic_subs=[
            schemas.AutoSub(out=s["element_out"], into=s["element_in"])
            for s in picks.get("automatic_subs", [])
        ],
        lineup=lineup,
        lineup_changes=[i for i in lineup.starters if i not in set(squad.starters)],
    )
