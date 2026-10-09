"""Builds API responses from published data: per-GW player pools, squads, team codes.

A **GW context** is the player pool for one gameweek: the live predictions for GWs in the
current horizon, or the frozen archive (``history/gwXX``) for earlier ones, with actual points
joined once the GW is finished.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fPLense import config, team_code
from fPLense.api import schemas
from fPLense.api.store import Store
from fPLense.optimize.squad_ilp import rule_problems, score_actual

POS_ORDER = {p: k for k, p in enumerate(config.SQUAD_QUOTAS)}
IDENTITY = [
    "element",
    "code",
    "web_name",
    "name",
    "pos",
    "club",
    "club_short",
    "status",
    "chance_of_playing_next_round",
    "news",
    "selected_by_percent",
    "photo_url",
    "rating",
    "rating_source",
]


class NotFound(LookupError):
    """A GW, player or squad that isn't published (-> HTTP 404)."""


class BadRequest(ValueError):
    """A request that can't be served as asked (-> HTTP 422)."""

    def __init__(self, message: str, kind: str = "invalid"):
        super().__init__(message)
        self.kind = kind


@dataclass
class GwContext:
    gw: int
    source: str  # "latest" | "live" | "backfill"
    finished: bool
    pool: pd.DataFrame  # indexed by player id
    gw_cols: dict[int, str]  # GW -> column with expected points (first = this GW)
    archive: dict | None = None
    extra: dict = field(default_factory=dict)


# --- GW contexts ------------------------------------------------------------------------------


def latest_gws(store: Store) -> list[int]:
    return [int(g) for g in store.latest()["gws"]]


def gw_context(store: Store, gw: int | None = None, horizon: int | None = None) -> GwContext:
    latest = store.latest()
    gw = int(latest["gw"]) if gw is None else int(gw)
    finished = gw in store.finished_gws()
    live = store.predictions()
    gws = latest_gws(store)
    archive = store.archive(gw) if gw in store.archived_gws() else None
    if gw in gws and not (finished and archive is not None):
        cols = {g: f"p_gw{g:02d}" for g in gws if g >= gw}
        if horizon is not None:
            cols = dict(list(cols.items())[: max(1, int(horizon))])
        pool = live.copy()
        pool["p"] = pool[cols[gw]].astype(float)
        if horizon is not None or gw != gws[0]:
            from fPLense.optimize.squad_ilp import discounted_sum

            pool["P_h"] = discounted_sum(pool[list(cols.values())].to_numpy(float))
        pool["p1"] = pool["p"]
        ctx = GwContext(gw, "latest", finished, pool, cols, archive)
    elif archive is not None:
        a = archive["predictions"]
        ident = live.reindex(a.index)[[c for c in IDENTITY if c not in a.columns]]
        pool = a.join(ident)
        pool["name"] = pool["name"].fillna(pool["web_name"])
        pool["status"] = pool["status"].fillna("a")
        pool["news"] = pool["news"].fillna("")
        pool["rating_source"] = pool["rating_source"].fillna("fplense")
        pool["p1"] = pool["p"]
        source = archive["meta"].get("source", "live")
        ctx = GwContext(gw, source, finished, pool, {gw: "p"}, archive)
    else:
        raise NotFound(f"no predictions published for GW{gw}")
    if finished:
        act = store.actuals()
        a = act[act["gw"] == gw].set_index("element") if act is not None else pd.DataFrame()
        ctx.pool["actual"] = a["total_points"].reindex(ctx.pool.index).fillna(0).astype(int)
        ctx.pool["minutes"] = a["minutes"].reindex(ctx.pool.index).fillna(0).astype(int)
    return ctx


# --- players ----------------------------------------------------------------------------------


def fixture_ticks(store: Store, start_gw: int, n_gws: int = 5) -> dict[str, list[dict]]:
    """Club name -> its fixtures in GWs ``start_gw .. start_gw + n_gws - 1``."""
    out: dict[str, list[dict]] = {}
    for f in store.fixtures():
        if not start_gw <= f["gw"] < start_gw + n_gws:
            continue
        for home in (True, False):
            own = f["team_h_name"] if home else f["team_a_name"]
            opp = f["team_a_short"] if home else f["team_h_short"]
            fdr = f["team_h_difficulty"] if home else f["team_a_difficulty"]
            out.setdefault(own, []).append(
                {
                    "gw": f["gw"],
                    "opponent": opp or "?",
                    "home": home,
                    "fdr": None if fdr is None else int(fdr),
                    "kickoff": f["kickoff_time"],
                }
            )
    return out


def _f(x) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


def _i(x) -> int | None:
    v = _f(x)
    return None if v is None else int(round(v))


def player_out(r: pd.Series, ctx: GwContext, ticks: dict[str, list[dict]]) -> schemas.Player:
    return schemas.Player(
        id=int(r["element"]),
        code=int(r["code"]) if _f(r.get("code")) is not None else 0,
        web_name=str(r["web_name"]),
        name=str(r.get("name") or r["web_name"]),
        pos=r["pos"],
        club=str(r["club"]),
        club_short=str(r["club_short"]),
        price=int(r["price"]),
        status=str(r.get("status") or "a"),
        chance_of_playing_next_round=_f(r.get("chance_of_playing_next_round")),
        news=str(r.get("news") or ""),
        availability=_f(r.get("availability")) if _f(r.get("availability")) is not None else 1.0,
        selected_by_percent=_f(r.get("selected_by_percent")),
        photo_url=r.get("photo_url") if isinstance(r.get("photo_url"), str) else None,
        rating=_i(r.get("rating")) or 50,
        rating_source=str(r.get("rating_source") or "fplense"),
        expected=[
            schemas.GwPoints(gw=g, points=round(_f(r[c]) or 0.0, 3)) for g, c in ctx.gw_cols.items()
        ],
        p=round(_f(r["p"]) or 0.0, 3),
        P_h=round(_f(r["P_h"]) or 0.0, 3),
        actual=_i(r.get("actual")) if ctx.finished else None,
        minutes=_i(r.get("minutes")) if ctx.finished else None,
        fixtures=ticks.get(str(r["club"]), []),
    )


# --- squads -----------------------------------------------------------------------------------


def order_starters(pool: pd.DataFrame, starters: list[int]) -> list[int]:
    """GK -> FWD, keeping the given order within a position (the team-code order)."""
    return sorted(starters, key=lambda i: POS_ORDER.get(pool.at[i, "pos"], 9))


def build_squad(
    ctx: GwContext,
    ids: list[int],
    starters: list[int] | None,
    bench: list[int] | None,
    captain: int | None,
    vice: int | None,
    kind: str,
    label: str,
    source: str | None = None,
    budget: int = config.BUDGET,
    enforce_budget: bool = True,
) -> schemas.Squad:
    """A full 15 with its lineup as a response; a missing XI/captain gets the lineup helper."""
    pool = ctx.pool
    unknown = [i for i in ids if i not in pool.index]
    if unknown:
        raise BadRequest(f"unknown player ids for GW{ctx.gw}: {unknown}", "unknown")
    ids = list(dict.fromkeys(int(i) for i in ids))
    if starters is None:
        from fPLense.optimize.squad_ilp import best_lineup

        try:
            lu = best_lineup(pool.assign(P_h=pool["p"], p1=pool["p"]), ids)
        except ValueError as exc:
            raise BadRequest(str(exc), "shape") from exc
        starters, bench = lu.starters, lu.bench
        captain = captain if captain in set(starters) else lu.captain
        vice = vice if vice in set(starters) and vice != captain else lu.vice
    elif captain is None:
        captain = max(starters, key=lambda i: pool.at[i, "p"])
    starters = order_starters(pool, [int(i) for i in starters])
    start_set = set(starters)
    if bench is None:
        bench = [i for i in ids if i not in start_set]
        bench.sort(key=lambda i: (pool.at[i, "pos"] == "GK", -pool.at[i, "p"]))
    bench = [int(i) for i in bench if i not in start_set]
    if vice is None or vice == captain or vice not in start_set:
        others = [i for i in starters if i != captain]
        vice = max(others, key=lambda i: pool.at[i, "p"]) if others else captain
    problems = rule_problems(pool, ids, starters, captain, vice, budget, enforce_budget)
    order = starters + bench
    cost = int(pool.loc[ids, "price"].sum())
    p = pool["p"].astype(float)
    expected = float(p.reindex(starters).fillna(0).sum() + (p.get(captain, 0.0) or 0.0))
    horizon = [
        schemas.GwPoints(
            gw=g,
            points=round(
                float(pool.loc[starters, c].fillna(0).sum() + (pool.at[captain, c] or 0.0)), 3
            ),
        )
        for g, c in ctx.gw_cols.items()
    ]
    actual = None
    if ctx.finished and len(starters) == config.XI_SIZE:
        a = pd.DataFrame({"points": pool["actual"], "minutes": pool["minutes"]})
        actual = score_actual(pool.loc[order, "pos"], a, starters, bench, captain, vice)["points"]
    code = None
    if len(order) == 15 and len(starters) == 11 and captain in start_set and vice in start_set:
        try:
            code = team_code.encode(starters, bench, captain, vice)
        except team_code.TeamCodeError:
            code = None
    bench_order = {i: k + 1 for k, i in enumerate(bench)}
    players = [
        squad_player(pool.loc[i], i in start_set, bench_order.get(i), i == captain, i == vice, ctx)
        for i in order
    ]
    return schemas.Squad(
        kind=kind,
        gw=ctx.gw,
        label=label,
        players=players,
        starters=starters,
        bench=bench,
        captain=int(captain),
        vice=int(vice),
        cost=cost,
        bank=int(budget) - cost,
        budget=int(budget),
        expected_points=round(expected, 3),
        horizon_expected=horizon,
        actual_points=actual,
        code=code,
        source=source or ctx.source,
        problems=[schemas.Problem(**q) for q in problems],
    )


def squad_player(r: pd.Series, starter, bench_order, captain, vice, ctx) -> schemas.SquadPlayer:
    return schemas.SquadPlayer(
        id=int(r["element"]),
        code=_i(r.get("code")),
        web_name=str(r["web_name"]),
        pos=r["pos"],
        club=str(r["club"]),
        club_short=str(r["club_short"]),
        price=int(r["price"]),
        expected=_f(r.get("p")),
        P_h=_f(r.get("P_h")),
        actual=_i(r.get("actual")) if ctx.finished else None,
        minutes=_i(r.get("minutes")) if ctx.finished else None,
        starter=bool(starter),
        bench_order=bench_order,
        captain=bool(captain),
        vice=bool(vice),
        photo_url=r.get("photo_url") if isinstance(r.get("photo_url"), str) else None,
        rating=_i(r.get("rating")),
        rating_source=r.get("rating_source") if isinstance(r.get("rating_source"), str) else None,
        status=r.get("status") if isinstance(r.get("status"), str) else None,
        news=r.get("news") if isinstance(r.get("news"), str) else None,
    )


def squad_from_doc(ctx: GwContext, doc: dict, kind: str, label: str) -> schemas.Squad:
    """A published squad JSON (``squad_gwXX.json`` / ``squad_pred.json``) as a response."""
    players = doc["players"]
    ids = [q["element"] for q in players]
    starters = [q["element"] for q in players if q["starter"]]
    bench = [q["element"] for q in sorted(players, key=lambda q: q["bench_order"] or 0)]
    bench = [i for i in bench if i not in set(starters)]
    return build_squad(ctx, ids, starters, bench, doc["captain"], doc["vice"], kind, label)


def squad_from_hindsight(ctx: GwContext, doc: dict) -> schemas.Squad:
    return build_squad(
        ctx,
        doc["squad"],
        doc["starters"],
        doc["bench"],
        doc["captain"],
        doc["vice"],
        "hindsight",
        f"Hindsight best GW{ctx.gw}",
        source="hindsight",
    )


def model_pick(store: Store, gw: int | None = None) -> schemas.Squad:
    ctx = gw_context(store, gw)
    doc = None
    if ctx.source == "latest" and ctx.gw == int(store.latest()["gw"]):
        doc = store.squad_next()
    if doc is None and ctx.archive is not None:
        doc = ctx.archive["squad"]
    if not doc:
        raise NotFound(f"no model pick published for GW{ctx.gw}")
    return squad_from_doc(ctx, doc, "model_pick", f"Model pick GW{ctx.gw}")


def hindsight(store: Store, gw: int) -> schemas.Squad:
    ctx = gw_context(store, gw)
    if not ctx.finished or ctx.archive is None or not ctx.archive.get("hindsight"):
        raise NotFound(f"no hindsight-best squad for GW{gw} (only finished, archived GWs)")
    return squad_from_hindsight(ctx, ctx.archive["hindsight"])


def picks_lineup(picks: dict) -> tuple[list[int], list[int], list[int], int, int]:
    """FPL picks -> ``(ids, starters, bench, captain, vice)`` (positions 1-11 start)."""
    rows = sorted(picks["picks"], key=lambda p: p["position"])
    ids = [int(p["element"]) for p in rows]
    starters = [int(p["element"]) for p in rows if p["position"] <= 11]
    bench = [int(p["element"]) for p in rows if p["position"] > 11]
    captain = next((int(p["element"]) for p in rows if p["is_captain"]), starters[0])
    vice = next((int(p["element"]) for p in rows if p["is_vice_captain"]), starters[1])
    return ids, starters, bench, captain, vice


def decode_code(store: Store, code: str, gw: int | None = None) -> tuple[schemas.Squad, dict]:
    """Team code -> squad in GW ``gw`` (default: next). Raises ``team_code.TeamCodeError``."""
    team = team_code.decode(code)
    ctx = gw_context(store, gw)
    players = {
        int(i): {"pos": r["pos"], "club": r["club"], "price": int(r["price"])}
        for i, r in ctx.pool[["pos", "club", "price"]].iterrows()
    }
    info = team_code.validate(team, players)
    squad = build_squad(
        ctx,
        list(team.players),
        team.starters,
        team.bench,
        team.captain,
        team.vice,
        "code",
        "Pasted team",
        enforce_budget=False,
    )
    return squad, info
