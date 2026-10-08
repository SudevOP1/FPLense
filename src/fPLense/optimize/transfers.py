"""Transfer planner (PLAN.md §8 P4): the best T = 0..3 transfers for an existing squad.

Same objective and rules as the squad ILP, but the new squad must come from the current one:
``x_i = s0_i - out_i + in_i`` with ``in_i`` only for players outside S0 and ``out_i`` only for
players in it, ``sum(in) = sum(out) = T``. Transfers beyond the free ones cost ``HIT_COST`` points
each (``h >= T - F``, ``h >= 0``). Budget: ``sum(price_i * x_i) <= value(S0) + bank``.

**Caveat:** the public FPL API doesn't expose selling prices (you keep only half of any rise), so
the current squad is valued at ``now_cost``; the user can correct the bank by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pulp

from fPLense import config
from fPLense.optimize.squad_ilp import (
    InfeasibleSquadError,
    SquadResult,
    _chosen,
    add_rule_constraints,
    add_squad_variables,
    eligible,
    result_from_selection,
    solve,
    squad_objective_expr,
    validate_pool,
)


@dataclass
class TransferOption:
    n_transfers: int
    ins: list[int]
    outs: list[int]
    hits: int  # points deducted
    result: SquadResult  # the squad after the moves (objective excludes the hit)
    objective: float  # ILP objective net of hits
    gain_vs_hold: float  # objective - objective of T = 0
    bank_after: int  # tenths of £1m


def _pool_for(df: pd.DataFrame, current: list[int], filter_unavailable: bool) -> pd.DataFrame:
    missing = [i for i in current if i not in df.index]
    if missing:
        raise ValueError(f"current squad players missing from the pool: {missing}")
    if not filter_unavailable:
        return validate_pool(df)
    # never drop the current squad (they must be sellable); filter only the buy candidates
    buyable = eligible(df.drop(index=current))
    return validate_pool(pd.concat([df.loc[current], buyable]))


def best_transfers(
    df: pd.DataFrame,
    current: list[int],
    bank: int,
    free_transfers: int,
    n_transfers: int,
    bench_w: float = config.BENCH_WEIGHT,
    filter_unavailable: bool = True,
    _pool: pd.DataFrame | None = None,
) -> TransferOption:
    """Best squad reachable with exactly ``n_transfers`` moves. Raises if none is legal."""
    if len(set(current)) != sum(config.SQUAD_QUOTAS.values()):
        raise ValueError(f"current squad must have 15 distinct players, got {len(set(current))}")
    pool = _pool if _pool is not None else _pool_for(df, current, filter_unavailable)
    ids = list(pool.index)
    s0 = set(current)
    t = int(n_transfers)

    m = pulp.LpProblem(f"fplense_transfers_{t}", pulp.LpMaximize)
    x, y, c = add_squad_variables(m, ids)
    tin = pulp.LpVariable.dicts("in", [i for i in ids if i not in s0], cat="Binary")
    tout = pulp.LpVariable.dicts("out", [i for i in ids if i in s0], cat="Binary")
    h = pulp.LpVariable("hits", lowBound=0, cat="Integer")

    m += squad_objective_expr(pool, x, y, c, bench_w) - config.HIT_COST * h
    for i in ids:
        if i in s0:
            m += x[i] == 1 - tout[i], f"keep_or_sell_{i}"
        else:
            m += x[i] == tin[i], f"buy_{i}"
    m += pulp.lpSum(tin.values()) == t, "n_in"
    m += pulp.lpSum(tout.values()) == t, "n_out"
    m += h >= t - int(free_transfers), "hits"
    value_s0 = int(pool.loc[list(s0), "price"].sum())
    m += pulp.lpSum(pool.at[i, "price"] * x[i] for i in ids) <= value_s0 + int(bank), "budget"
    add_rule_constraints(m, pool, x, y, c)
    status = solve(m)

    squad = _chosen(x, ids)
    res = result_from_selection(pool, squad, _chosen(y, ids), _chosen(c, ids)[0], bench_w, status)
    hits = config.HIT_COST * int(round(h.value() or 0))
    return TransferOption(
        n_transfers=t,
        ins=[i for i in squad if i not in s0],
        outs=[i for i in current if i not in set(squad)],
        hits=hits,
        result=res,
        objective=res.objective - hits,
        gain_vs_hold=0.0,
        bank_after=value_s0 + int(bank) - res.cost,
    )


def plan_transfers(
    df: pd.DataFrame,
    current: list[int],
    bank: int,
    free_transfers: int = 1,
    max_transfers: int = config.MAX_TRANSFERS_PLANNED,
    bench_w: float = config.BENCH_WEIGHT,
    filter_unavailable: bool = True,
) -> list[TransferOption]:
    """Options for T = 0..max_transfers, each with its net gain vs holding (T = 0).

    Options the budget can't reach are left out. ``free_transfers`` is clipped to 0..5.
    """
    free = max(0, min(int(free_transfers), config.MAX_FREE_TRANSFERS))
    pool = _pool_for(df, current, filter_unavailable)
    options: list[TransferOption] = []
    for t in range(max_transfers + 1):
        try:
            options.append(
                best_transfers(df, current, bank, free, t, bench_w, filter_unavailable, pool)
            )
        except InfeasibleSquadError:
            if t == 0:
                raise
    hold = options[0].objective
    for opt in options:
        opt.gain_vs_hold = opt.objective - hold
    return options


def recommended(options: list[TransferOption], min_gain: float = 0.0) -> TransferOption:
    """The option with the largest net gain; ties go to fewer transfers."""
    best = options[0]
    for opt in options[1:]:
        if opt.gain_vs_hold > best.gain_vs_hold + 1e-9 and opt.gain_vs_hold > min_gain:
            best = opt
    return best


def options_table(options: list[TransferOption], names: pd.Series | None = None) -> pd.DataFrame:
    """One row per option, for the app and notebooks."""

    def label(ids):
        return ", ".join(str(names.get(i, i)) if names is not None else str(i) for i in ids)

    return pd.DataFrame(
        {
            "transfers": [o.n_transfers for o in options],
            "out": [label(o.outs) for o in options],
            "in": [label(o.ins) for o in options],
            "hit": [-o.hits for o in options],
            "expected_points": [round(o.result.expected_points, 2) for o in options],
            "net_gain": [round(o.gain_vs_hold, 2) for o in options],
            "bank_after": [o.bank_after / 10 for o in options],
        }
    )
