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
    """The solver found no legal squad (budget too small, too few players per position, ...)."""


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
    out = df.copy()
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
    return pulp.lpSum(y[i] * df.at[i, "P_h"] + c[i] * df.at[i, "p1"] for i in ids) + bench_w * (
        pulp.lpSum((x[i] - y[i]) * df.at[i, "P_h"] for i in ids)
    )


def add_rule_constraints(m: pulp.LpProblem, df: pd.DataFrame, x, y, c) -> None:
    """Quotas, club limit, XI shape and captaincy (everything except the budget)."""
    ids = list(df.index)
    for pos, n in config.SQUAD_QUOTAS.items():
        m += pulp.lpSum(x[i] for i in ids if df.at[i, "pos"] == pos) == n, f"quota_{pos}"
    for k, club in enumerate(sorted(df["club"].astype(str).unique())):
        members = [i for i in ids if str(df.at[i, "club"]) == club]
        m += pulp.lpSum(x[i] for i in members) <= config.MAX_PER_CLUB, f"club_{k}"
    m += pulp.lpSum(y[i] for i in ids) == config.XI_SIZE, "xi_size"
    m += pulp.lpSum(y[i] for i in ids if df.at[i, "pos"] == "GK") == config.XI_MIN["GK"], "xi_gk"
    for pos in ("DEF", "MID", "FWD"):
        lo = config.XI_MIN[pos]
        m += pulp.lpSum(y[i] for i in ids if df.at[i, "pos"] == pos) >= lo, f"xi_{pos}"
    m += pulp.lpSum(c[i] for i in ids) == 1, "one_captain"
    for i in ids:
        m += y[i] <= x[i], f"start_in_squad_{i}"
        m += c[i] <= y[i], f"capt_starts_{i}"


def solve(m: pulp.LpProblem) -> str:
    m.solve(pulp.PULP_CBC_CMD(msg=False))
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
) -> SquadResult:
    """Best legal 15-man squad, XI and captain for the pool. Raises ``InfeasibleSquadError``."""
    pool = validate_pool(eligible(df) if filter_unavailable else df)
    ids = list(pool.index)
    m = pulp.LpProblem("fplense_squad", pulp.LpMaximize)
    x, y, c = add_squad_variables(m, ids)
    m += squad_objective_expr(pool, x, y, c, bench_w)
    m += pulp.lpSum(pool.at[i, "price"] * x[i] for i in ids) <= int(budget), "budget"
    add_rule_constraints(m, pool, x, y, c)
    status = solve(m)
    return result_from_selection(
        pool, _chosen(x, ids), _chosen(y, ids), _chosen(c, ids)[0], bench_w, status
    )


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
