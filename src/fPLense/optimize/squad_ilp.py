"""Squad selection as an integer linear program (PLAN.md §8 P4), solved with PuLP's bundled CBC.

The pool is a DataFrame indexed by player id with columns ``pos`` (GK/DEF/MID/FWD), ``club``,
``price`` (integer tenths of £1m, FPL ``now_cost``: 55 = £5.5m), ``p1`` (next-GW expected points)
and ``P_h`` (discounted expected points over the next N GWs). Integer prices keep the budget check
exact (no ``100.00000000000001 > 100.0`` surprises).

Objective: starters' ``P_h`` + the captain's ``p1`` (the armband doubles one GW) + ``bench_w`` x
the bench's ``P_h``. Constraints: budget, 2-5-5-3 quotas, at most 3 per club, an XI of 11 with
1 GK / >=3 DEF / >=2 MID / >=1 FWD, one captain who starts.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pulp

from fPLense import config

REQUIRED_COLUMNS = ["pos", "club", "price", "p1", "P_h"]


class InfeasibleSquadError(RuntimeError):
    """The solver found no legal squad (budget too small, too few players per position, ...).

    ``cause`` names the rule that broke when it is known: ``"budget"``, ``"quota"``,
    ``"club limit"``, ``"conflict"`` (a player both locked and banned) or ``"infeasible"``.
    """

    def __init__(self, message: str, cause: str = "infeasible"):
        super().__init__(message)
        self.cause = cause


@dataclass
class SquadResult:
    squad: list[int]  # 15 player ids, GK -> FWD
    starters: list[int]  # 11 ids
    bench: list[int]  # 4 ids in substitution order (outfield by p1, GK last)
    captain: int
    vice: int
    cost: int  # tenths of £1m
    objective: float  # value of the ILP objective
    expected_points: float  # starters' P_h + captain's p1 (no bench term)
    status: str = "Optimal"
    extra: dict = field(default_factory=dict)


# --- inputs -----------------------------------------------------------------------------------


def discounted_sum(per_gw, discount: float = config.HORIZON_DISCOUNT) -> np.ndarray:
    """``P_h``: sum over the horizon of ``discount**j`` x points in GW t+j (j = 0, 1, ...)."""
    arr = np.atleast_2d(np.asarray(per_gw, dtype=float))
    weights = discount ** np.arange(arr.shape[1])
    return np.nan_to_num(arr) @ weights


def eligible(df: pd.DataFrame) -> pd.DataFrame:
    """Drop players who can't play: status ``u`` (unavailable/left) or a 0% chance next round."""
    keep = pd.Series(True, index=df.index)
    if "status" in df:
        keep &= df["status"].astype(str) != "u"
    if "chance_of_playing_next_round" in df:
        keep &= pd.to_numeric(df["chance_of_playing_next_round"], errors="coerce").fillna(100) > 0
    return df[keep]


def prune_dominated(df: pd.DataFrame, keep: Iterable = ()) -> pd.DataFrame:
    """Drop players no optimal squad needs, so the ILP solves in a fraction of the time.

    Player ``i`` is dominated by ``j`` (same position, not in ``keep``) when ``j`` costs no more
    and has ``p1`` and ``P_h`` at least as high (one of them strictly or a lower id on ties).
    If ``i``'s dominators span at least ``quota + MAX_CLUBS_FULL`` distinct clubs, any squad with
    ``i`` can swap him for a dominator that is not already picked and whose club isn't full
    (at most 15 / 3 = 5 clubs are full, at most ``quota - 1`` dominators are picked), at no extra
    cost and with an objective at least as high. So dropping ``i`` never changes the optimum.
    ``keep`` (locked or currently owned players) is never dropped nor used as a dominator.
    """
    keep = set(keep)
    max_full = sum(config.SQUAD_QUOTAS.values()) // config.MAX_PER_CLUB
    drop = []
    for pos, g in df.groupby("pos"):
        cand = g[~g.index.isin(keep)]
        if len(cand) == 0:
            continue
        need = config.SQUAD_QUOTAS.get(pos, 0) + max_full
        price = cand["price"].to_numpy(float)
        p1 = cand["p1"].fillna(0).to_numpy(float)
        ph = cand["P_h"].fillna(0).to_numpy(float)
        ids = cand.index.to_numpy()
        club_codes, _ = pd.factorize(cand["club"].astype(str))
        for k in range(len(cand)):
            better = (price <= price[k]) & (p1 >= p1[k]) & (ph >= ph[k])
            strict = (price < price[k]) | (p1 > p1[k]) | (ph > ph[k]) | (ids < ids[k])
            dom = better & strict
            dom[k] = False
            if dom.sum() >= need and len(np.unique(club_codes[dom])) >= need:
                drop.append(ids[k])
    return df.drop(index=drop)


def validate_pool(df: pd.DataFrame) -> pd.DataFrame:
    """Check the columns and that prices are integer tenths; returns a clean copy."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df]
    if missing:
        raise ValueError(f"pool is missing columns {missing}")
    if not df.index.is_unique:
        raise ValueError("pool index (player id) must be unique")
    price = pd.to_numeric(df["price"], errors="raise")
    if not np.allclose(price, np.round(price)):
        raise ValueError("prices must be integer tenths of £1m (FPL now_cost, e.g. 55 = £5.5m)")
    unknown = set(df["pos"]) - set(config.SQUAD_QUOTAS)
    if unknown:
        raise ValueError(f"unknown positions {sorted(unknown)}")
    # only the columns the solver reads, as plain numpy/object columns: `df.at` on a wide frame
    # with Arrow string columns costs ~0.1 ms per lookup, which dominated the planner's runtime
    keep = REQUIRED_COLUMNS + [c for c in ("status", "chance_of_playing_next_round") if c in df]
    out = df[keep].copy()
    out["pos"] = out["pos"].astype(object)
    out["club"] = out["club"].astype(str).astype(object)
    if "status" in out:
        out["status"] = out["status"].astype(str).astype(object)
    out["price"] = np.round(price).astype(int)
    out["p1"] = pd.to_numeric(out["p1"]).fillna(0.0).astype(float)
    out["P_h"] = pd.to_numeric(out["P_h"]).fillna(0.0).astype(float)
    return out


# --- shared model pieces (also used by transfers.py) -----------------------------------------


def add_squad_variables(m: pulp.LpProblem, ids: list) -> tuple[dict, dict, dict]:
    x = pulp.LpVariable.dicts("squad", ids, cat="Binary")
    y = pulp.LpVariable.dicts("start", ids, cat="Binary")
    c = pulp.LpVariable.dicts("capt", ids, cat="Binary")
    return x, y, c


def squad_objective_expr(df: pd.DataFrame, x, y, c, bench_w: float):
    ids = list(df.index)
    ph, p1 = df["P_h"].to_dict(), df["p1"].to_dict()  # dict lookups: `df.at` is slow
    return pulp.lpSum(y[i] * ph[i] + c[i] * p1[i] for i in ids) + bench_w * (
        pulp.lpSum((x[i] - y[i]) * ph[i] for i in ids)
    )


def add_rule_constraints(
    m: pulp.LpProblem, df: pd.DataFrame, x, y, c, club_limit: bool = True
) -> None:
    """Quotas, club limit, XI shape and captaincy (everything except the budget)."""
    ids = list(df.index)
    pos_of = df["pos"].to_dict()
    by_pos = {p: [i for i in ids if pos_of[i] == p] for p in config.SQUAD_QUOTAS}
    for pos, n in config.SQUAD_QUOTAS.items():
        m += pulp.lpSum(x[i] for i in by_pos[pos]) == n, f"quota_{pos}"
    if club_limit:
        club_of = df["club"].astype(str).to_dict()
        clubs: dict[str, list] = {}
        for i in ids:
            clubs.setdefault(club_of[i], []).append(i)
        for k, club in enumerate(sorted(clubs)):
            m += pulp.lpSum(x[i] for i in clubs[club]) <= config.MAX_PER_CLUB, f"club_{k}"
    m += pulp.lpSum(y[i] for i in ids) == config.XI_SIZE, "xi_size"
    m += pulp.lpSum(y[i] for i in by_pos["GK"]) == config.XI_MIN["GK"], "xi_gk"
    for pos in ("DEF", "MID", "FWD"):
        m += pulp.lpSum(y[i] for i in by_pos[pos]) >= config.XI_MIN[pos], f"xi_{pos}"
    m += pulp.lpSum(c[i] for i in ids) == 1, "one_captain"
    for i in ids:
        m += y[i] <= x[i], f"start_in_squad_{i}"
        m += c[i] <= y[i], f"capt_starts_{i}"


def solve(m: pulp.LpProblem, time_limit: float | None = None) -> str:
    m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit))
    status = pulp.LpStatus[m.status]
    if status != "Optimal":
        raise InfeasibleSquadError(
            f"no legal squad: solver status {status!r} (check budget, pool size per position, "
            "club spread)"
        )
    return status


def _chosen(var: dict, ids: Iterable) -> list:
    return [i for i in ids if (var[i].value() or 0) > 0.5]


def result_from_selection(
    df: pd.DataFrame,
    squad: list,
    starters: list,
    captain,
    bench_w: float = config.BENCH_WEIGHT,
    status: str = "Optimal",
) -> SquadResult:
    """Order the squad, pick the vice and bench order, and compute the objective."""
    order = {p: k for k, p in enumerate(config.SQUAD_QUOTAS)}
    sq = df.loc[list(squad)]
    squad_sorted = sorted(sq.index, key=lambda i: (order[sq.at[i, "pos"]], -sq.at[i, "P_h"]))
    start_set = set(starters)
    others = [i for i in starters if i != captain]
    vice = max(others, key=lambda i: (df.at[i, "p1"], df.at[i, "P_h"]))
    bench = [i for i in squad_sorted if i not in start_set]
    bench.sort(key=lambda i: (df.at[i, "pos"] == "GK", -df.at[i, "p1"], -df.at[i, "P_h"]))
    expected = float(df.loc[list(starters), "P_h"].sum() + df.at[captain, "p1"])
    return SquadResult(
        squad=list(squad_sorted),
        starters=[i for i in squad_sorted if i in start_set],
        bench=bench,
        captain=captain,
        vice=vice,
        cost=int(df.loc[list(squad), "price"].sum()),
        objective=squad_objective(df, squad, starters, captain, bench_w),
        expected_points=expected,
        status=status,
    )


def squad_objective(
    df: pd.DataFrame, squad, starters, captain, bench_w: float = config.BENCH_WEIGHT
) -> float:
    """The ILP objective evaluated for any selection (used to compare with heuristics)."""
    bench = [i for i in squad if i not in set(starters)]
    return float(
        df.loc[list(starters), "P_h"].sum()
        + df.at[captain, "p1"]
        + bench_w * df.loc[bench, "P_h"].sum()
    )


# --- the squad ILP ----------------------------------------------------------------------------


def pick_squad(
    df: pd.DataFrame,
    budget: int = config.BUDGET,
    bench_w: float = config.BENCH_WEIGHT,
    filter_unavailable: bool = True,
    locked: Iterable = (),
    banned: Iterable = (),
    time_limit: float | None = None,
) -> SquadResult:
    """Best legal 15-man squad, XI and captain for the pool. Raises ``InfeasibleSquadError``.

    ``locked`` players are forced in (``x_i = 1``; they skip the availability filter) and
    ``banned`` ones forced out (``x_i = 0``). An impossible lock set raises with the broken rule
    named in the message and in ``.cause``.
    """
    locked, banned = list(dict.fromkeys(locked)), set(banned)
    unknown = [i for i in locked if i not in df.index]
    if unknown:
        raise ValueError(f"locked players not in the pool: {unknown}")
    both = sorted(set(locked) & banned)
    if both:
        raise InfeasibleSquadError(f"players {both} are both locked and banned", "conflict")
    base = eligible(df) if filter_unavailable else df
    base = pd.concat([df.loc[locked], base.drop(index=locked, errors="ignore")])
    pool = validate_pool(base.drop(index=list(banned), errors="ignore"))
    check_locks(pool, locked, budget)
    pool = prune_dominated(pool, keep=locked)
    ids = list(pool.index)
    m = pulp.LpProblem("fplense_squad", pulp.LpMaximize)
    x, y, c = add_squad_variables(m, ids)
    m += squad_objective_expr(pool, x, y, c, bench_w)
    price = pool["price"].to_dict()
    m += pulp.lpSum(price[i] * x[i] for i in ids) <= int(budget), "budget"
    add_rule_constraints(m, pool, x, y, c)
    for i in locked:
        m += x[i] == 1, f"lock_{i}"
    try:
        status = solve(m, time_limit)
    except InfeasibleSquadError as exc:
        if not locked:
            raise
        raise InfeasibleSquadError(
            f"no legal squad contains all {len(locked)} locked players: the club limit and the "
            "position quotas can't both be met within the budget",
            "infeasible",
        ) from exc
    return result_from_selection(
        pool, _chosen(x, ids), _chosen(y, ids), _chosen(c, ids)[0], bench_w, status
    )


def money(tenths: int) -> str:
    """``55`` -> ``"£5.5m"``."""
    return f"£{tenths / 10:.1f}m"


def check_locks(pool: pd.DataFrame, locked: list, budget: int = config.BUDGET) -> None:
    """Fail fast, naming the rule, when the locked players alone rule out every legal squad."""
    if not locked:
        return
    lk = pool.loc[locked]
    for pos, n in lk["pos"].value_counts().items():
        if n > config.SQUAD_QUOTAS[pos]:
            raise InfeasibleSquadError(
                f"{n} {pos} locked, but a squad holds only {config.SQUAD_QUOTAS[pos]} {pos}",
                "quota",
            )
    for club, n in lk["club"].astype(str).value_counts().items():
        if n > config.MAX_PER_CLUB:
            raise InfeasibleSquadError(
                f"{n} {club} players locked, but at most {config.MAX_PER_CLUB} per club "
                "are allowed",
                "club limit",
            )
    cost = int(lk["price"].sum())
    rest = pool.drop(index=locked)
    fill = 0
    for pos, n in config.SQUAD_QUOTAS.items():
        need = n - int((lk["pos"] == pos).sum())
        prices = rest.loc[rest["pos"] == pos, "price"].nsmallest(need)
        if len(prices) < need:
            raise InfeasibleSquadError(
                f"not enough {pos} left in the pool to fill the squad", "quota"
            )
        fill += int(prices.sum())
    if cost + fill > budget:
        raise InfeasibleSquadError(
            f"the locked players cost {money(cost)}; even with the cheapest players in the other "
            f"{sum(config.SQUAD_QUOTAS.values()) - len(locked)} slots the squad costs "
            f"{money(cost + fill)}, over the {money(budget)} budget",
            "budget",
        )


def best_lineup(df: pd.DataFrame, squad, bench_w: float = config.BENCH_WEIGHT) -> SquadResult:
    """Best XI, bench order, captain and vice for a **fixed** 15-man squad (the lineup helper).

    The squad ILP's objective with every squad variable fixed to 1 (and no budget or club limit:
    the squad is given). Pass a pool whose ``p1`` and ``P_h`` are next-GW points to optimise a
    single gameweek.
    """
    squad = list(dict.fromkeys(squad))
    pool = validate_pool(df.loc[squad])
    counts = pool["pos"].value_counts()
    if len(squad) != 15 or any(counts.get(p, 0) != n for p, n in config.SQUAD_QUOTAS.items()):
        raise ValueError("the lineup helper needs a full 2-5-5-3 squad of 15")
    ids = list(pool.index)
    m = pulp.LpProblem("fplense_lineup", pulp.LpMaximize)
    x, y, c = add_squad_variables(m, ids)
    m += squad_objective_expr(pool, x, y, c, bench_w)
    add_rule_constraints(m, pool, x, y, c, club_limit=False)
    for i in ids:
        m += x[i] == 1, f"fixed_{i}"
    status = solve(m)
    return result_from_selection(pool, ids, _chosen(y, ids), _chosen(c, ids)[0], bench_w, status)


def rule_problems(
    df: pd.DataFrame,
    squad,
    starters=None,
    captain=None,
    vice=None,
    budget: int = config.BUDGET,
    enforce_budget: bool = True,
) -> list[dict]:
    """Plain-English rule report for any (possibly partial) squad: ``[{rule, message}]``.

    Works on 0-15 players so a team builder can show it live. ``enforce_budget=False`` leaves the
    budget out (real teams can be worth more than £100m after price rises).
    """
    out: list[dict] = []
    ids = list(squad)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        out.append({"rule": "duplicate", "message": f"players picked more than once: {dupes}"})
    ids = list(dict.fromkeys(ids))
    unknown = [i for i in ids if i not in df.index]
    if unknown:
        out.append({"rule": "unknown", "message": f"unknown player ids: {unknown}"})
    ids = [i for i in ids if i in df.index]
    sq = df.loc[ids]
    size = sum(config.SQUAD_QUOTAS.values())
    if len(ids) != size:
        out.append({"rule": "size", "message": f"{len(ids)} of {size} players picked"})
    counts = sq["pos"].value_counts()
    for pos, n in config.SQUAD_QUOTAS.items():
        have = int(counts.get(pos, 0))
        if have > n:
            out.append({"rule": "quota", "message": f"{have} {pos}: a squad holds exactly {n}"})
        elif have < n and len(ids) == size:
            out.append({"rule": "quota", "message": f"{have} {pos}: a squad needs exactly {n}"})
    for club, n in sq["club"].astype(str).value_counts().items():
        if n > config.MAX_PER_CLUB:
            msg = f"{n} players from {club}: max {config.MAX_PER_CLUB} per club"
            out.append({"rule": "club", "message": msg})
    cost = int(sq["price"].sum()) if len(sq) else 0
    if enforce_budget and cost > budget:
        msg = f"costs {money(cost)}: {money(cost - budget)} over the {money(budget)} budget"
        out.append({"rule": "budget", "message": msg})
    if starters is not None:
        xi = [i for i in dict.fromkeys(starters) if i in df.index]
        if len(xi) != config.XI_SIZE or not set(xi) <= set(ids):
            out.append({"rule": "xi", "message": "the starting XI must be 11 squad players"})
        xc = df.loc[xi, "pos"].value_counts()
        if xc.get("GK", 0) != 1:
            out.append({"rule": "xi", "message": "the XI needs exactly 1 goalkeeper"})
        for pos in ("DEF", "MID", "FWD"):
            if xc.get(pos, 0) < config.XI_MIN[pos]:
                msg = f"the XI needs at least {config.XI_MIN[pos]} {pos}"
                out.append({"rule": "xi", "message": msg})
        if captain is not None and captain not in xi:
            out.append({"rule": "captain", "message": "the captain must be in the XI"})
        if vice is not None and (vice not in xi or vice == captain):
            out.append({"rule": "captain", "message": "the vice-captain must be another starter"})
    return out


SHAPE_RULES = {"size", "quota", "duplicate", "unknown"}


def evaluate_squad(
    df: pd.DataFrame,
    squad,
    starters=None,
    captain=None,
    vice=None,
    gw_cols: dict[int, str] | None = None,
    actual: pd.DataFrame | None = None,
    budget: int = config.BUDGET,
    enforce_budget: bool = True,
) -> dict:
    """Expected points per GW, cost and rule report for any squad (+ actual points if known).

    ``gw_cols`` maps GW -> the pool column holding that GW's expected points. Without
    ``starters``, a full 2-5-5-3 squad gets the lineup helper's XI (on the first GW's points).
    ``actual`` (indexed by player, columns ``points`` and ``minutes``) scores the XI with the
    backtest's simplified auto-subs and the captain doubled (the vice's if the captain didn't
    play).
    """
    squad = list(squad)
    problems = rule_problems(df, squad, starters, captain, vice, budget, enforce_budget)
    known = [i for i in dict.fromkeys(squad) if i in df.index]
    cost = int(df.loc[known, "price"].sum()) if known else 0
    gw_cols = gw_cols or {}
    first = next(iter(gw_cols.values()), "p1")
    full = not any(p["rule"] in SHAPE_RULES for p in problems)
    if starters is None and full:
        lineup = best_lineup(df.assign(P_h=df[first], p1=df[first]), known)
        starters, bench = lineup.starters, lineup.bench
        captain, vice = lineup.captain, lineup.vice
    else:
        start_set = set(starters or [])
        bench = [i for i in known if i not in start_set]
    xi = [i for i in (starters or []) if i in df.index]
    expected = {
        gw: float(df.loc[xi, col].fillna(0).sum() + (df.at[captain, col] if captain in xi else 0.0))
        for gw, col in gw_cols.items()
    }
    out = {
        "cost": cost,
        "bank": int(budget) - cost,
        "problems": problems,
        "legal": not problems,
        "starters": list(xi),
        "bench": list(bench),
        "captain": captain,
        "vice": vice,
        "expected": expected,
        "actual": None,
    }
    if actual is not None and len(xi) == config.XI_SIZE and captain is not None:
        out["actual"] = score_actual(df.loc[known, "pos"], actual, xi, bench, captain, vice)
    return out


def score_actual(pos: pd.Series, actual: pd.DataFrame, starters, bench, captain, vice) -> dict:
    """Actual points of a lineup: XI with the backtest's auto-subs, captain (or vice) doubled."""
    from types import SimpleNamespace

    from fPLense.optimize.backtest import score_gw

    ids = list(pos.index)
    a = actual.reindex(ids)[["points", "minutes"]].fillna(0)
    a["pos"] = pos
    res = SimpleNamespace(starters=list(starters), bench=list(bench), captain=captain, vice=vice)
    pts, info = score_gw(a, res)
    return {"points": int(pts), "subs": info["subs"], "armband": info["armband"]}


# --- baselines for comparison -----------------------------------------------------------------


def best_xi(df: pd.DataFrame, squad) -> tuple[list, object]:
    """Best XI of a 15-man squad by ``P_h`` and its captain (top ``p1`` starter).

    Optimal for this formation rule: fill the minimums (1 GK, 3 DEF, 2 MID, 1 FWD) with the best
    at each position, then the 4 best remaining outfielders. The squad quotas cap the rest.
    """
    sq = df.loc[list(squad)].sort_values("P_h", ascending=False)
    starters: list = []
    for pos, n in config.XI_MIN.items():
        starters += list(sq.index[sq["pos"] == pos][:n])
    rest = sq[(sq["pos"] != "GK") & ~sq.index.isin(starters)]
    starters += list(rest.index[: config.XI_SIZE - len(starters)])
    captain = max(starters, key=lambda i: (df.at[i, "p1"], df.at[i, "P_h"]))
    return starters, captain


def greedy_squad(
    df: pd.DataFrame,
    budget: int = config.BUDGET,
    bench_w: float = config.BENCH_WEIGHT,
    filter_unavailable: bool = True,
) -> SquadResult:
    """Points-per-£ heuristic: add players by ``P_h / price`` while the squad can still be filled.

    A player is added only if quota, club limit and budget hold *and* the remaining open slots can
    still be filled with the cheapest players left, so the result is always a legal squad.
    """
    pool = validate_pool(eligible(df) if filter_unavailable else df)
    ranked = pool.assign(ppp=pool["P_h"] / pool["price"].clip(lower=1)).sort_values(
        ["ppp", "P_h"], ascending=False
    )
    # unpicked players per position, cheapest first: the reserve for the slots still open
    cheapest = {
        pos: list(pool.loc[pool["pos"] == pos, "price"].sort_values().items())
        for pos in config.SQUAD_QUOTAS
    }

    def reserve(after: dict[str, int], skip) -> int:
        total = 0
        for p, n in after.items():
            prices = [price for j, price in cheapest[p] if j != skip][:n]
            total += sum(prices)
        return total

    need = dict(config.SQUAD_QUOTAS)
    clubs: dict[str, int] = {}
    squad: list = []
    spent = 0
    for i, row in ranked.iterrows():
        pos, club, price = row["pos"], str(row["club"]), int(row["price"])
        if need[pos] == 0 or clubs.get(club, 0) >= config.MAX_PER_CLUB:
            continue
        after = dict(need, **{pos: need[pos] - 1})
        if spent + price + reserve(after, i) > budget:
            continue
        squad.append(i)
        cheapest[pos] = [(j, pr) for j, pr in cheapest[pos] if j != i]
        spent += price
        need[pos] -= 1
        clubs[club] = clubs.get(club, 0) + 1
        if not any(need.values()):
            break
    if any(need.values()):
        raise InfeasibleSquadError(f"greedy heuristic could not fill {need}")
    starters, captain = best_xi(pool, squad)
    return result_from_selection(pool, squad, starters, captain, bench_w, status="Heuristic")


def check_squad(df: pd.DataFrame, res: SquadResult, budget: int = config.BUDGET) -> list[str]:
    """Rule violations of a result (empty list = legal). Used by tests and the backtest."""
    problems = []
    sq = df.loc[res.squad]
    xi = df.loc[res.starters]
    if len(set(res.squad)) != sum(config.SQUAD_QUOTAS.values()):
        problems.append(f"squad size {len(set(res.squad))}")
    if int(sq["price"].sum()) > budget:
        problems.append(f"cost {int(sq['price'].sum())} > budget {budget}")
    counts = sq["pos"].value_counts()
    for pos, n in config.SQUAD_QUOTAS.items():
        if counts.get(pos, 0) != n:
            problems.append(f"{pos}: {counts.get(pos, 0)} != {n}")
    over = sq["club"].astype(str).value_counts()
    if (over > config.MAX_PER_CLUB).any():
        problems.append(f"clubs over limit: {list(over[over > config.MAX_PER_CLUB].index)}")
    if len(set(res.starters)) != config.XI_SIZE or not set(res.starters) <= set(res.squad):
        problems.append("XI is not 11 squad players")
    xi_counts = xi["pos"].value_counts()
    if xi_counts.get("GK", 0) != 1:
        problems.append("XI needs exactly 1 GK")
    for pos in ("DEF", "MID", "FWD"):
        if xi_counts.get(pos, 0) < config.XI_MIN[pos]:
            problems.append(f"XI needs >= {config.XI_MIN[pos]} {pos}")
    if res.captain not in res.starters:
        problems.append("captain does not start")
    if res.vice not in res.starters or res.vice == res.captain:
        problems.append("vice must be another starter")
    return problems
