"""Transfer planner: T = 0 holds, exactly T moves, hits, budget and squad legality."""

from __future__ import annotations

import pandas as pd
import pytest
from pools import random_pool

from fPLense import config
from fPLense.optimize.squad_ilp import check_squad, pick_squad
from fPLense.optimize.transfers import (
    best_transfers,
    options_table,
    plan_transfers,
    recommended,
)


@pytest.fixture(scope="module")
def setup():
    """A legal starting squad picked on stale predictions, then the predictions move."""
    pool = random_pool(n=200, seed=21)
    start = pick_squad(pool, budget=980)
    new = pool.copy()
    # current squad's best players get injured-ish forecasts, so moves are worth making
    for i in sorted(start.squad, key=lambda i: -pool.at[i, "P_h"])[:4]:
        new.loc[i, ["p1", "P_h"]] = [0.2, 0.5]
    return new, start.squad, 1000 - start.cost


def test_hold_returns_current_squad(setup):
    pool, s0, bank = setup
    opt = best_transfers(pool, s0, bank, free_transfers=1, n_transfers=0)
    assert sorted(opt.result.squad) == sorted(s0)
    assert opt.ins == [] and opt.outs == []
    assert opt.hits == 0
    assert opt.bank_after == bank


@pytest.mark.parametrize("t", [1, 2, 3])
def test_exactly_t_moves_and_legal(setup, t):
    pool, s0, bank = setup
    opt = best_transfers(pool, s0, bank, free_transfers=1, n_transfers=t)
    assert len(opt.ins) == t and len(opt.outs) == t
    assert not set(opt.ins) & set(s0)
    assert set(opt.outs) <= set(s0)
    assert set(opt.result.squad) == (set(s0) - set(opt.outs)) | set(opt.ins)
    budget = int(pool.loc[s0, "price"].sum()) + bank
    assert opt.result.cost <= budget
    assert opt.bank_after == budget - opt.result.cost >= 0
    assert check_squad(pool, opt.result, budget=budget) == []


@pytest.mark.parametrize("free", [0, 1, 2, 5])
def test_hits_applied(setup, free):
    pool, s0, bank = setup
    options = plan_transfers(pool, s0, bank, free_transfers=free)
    assert [o.n_transfers for o in options] == [0, 1, 2, 3]
    for o in options:
        assert o.hits == config.HIT_COST * max(0, o.n_transfers - free)
        assert o.objective == pytest.approx(o.result.objective - o.hits)
        assert o.gain_vs_hold == pytest.approx(o.objective - options[0].objective)
    assert options[0].gain_vs_hold == 0


def test_more_free_transfers_never_hurt(setup):
    pool, s0, bank = setup
    one = plan_transfers(pool, s0, bank, free_transfers=1)
    three = plan_transfers(pool, s0, bank, free_transfers=3)
    for a, b in zip(one, three, strict=True):
        assert b.objective >= a.objective - 1e-6


def test_moves_replace_the_injured(setup):
    pool, s0, bank = setup
    opt = recommended(plan_transfers(pool, s0, bank, free_transfers=2))
    assert opt.n_transfers >= 1
    assert opt.gain_vs_hold > 0
    assert all(pool.at[i, "P_h"] == 0.5 for i in opt.outs)


def test_bank_limits_upgrades():
    pool = random_pool(n=200, seed=4)
    start = pick_squad(pool, budget=1000)
    rich = best_transfers(pool, start.squad, bank=300, free_transfers=1, n_transfers=1)
    broke = best_transfers(pool, start.squad, bank=0, free_transfers=1, n_transfers=1)
    assert broke.result.cost <= start.cost
    assert rich.result.cost <= start.cost + 300
    assert rich.objective >= broke.objective - 1e-6


def test_current_players_kept_even_if_unavailable(setup):
    pool, s0, bank = setup
    pool = pool.copy()
    pool["status"] = "a"
    pool.loc[s0[0], "status"] = "u"  # can still be sold, never bought
    opts = plan_transfers(pool, s0, bank, free_transfers=1, max_transfers=1)
    assert sorted(opts[0].result.squad) == sorted(s0)


def test_missing_current_player_raises(setup):
    pool, s0, bank = setup
    with pytest.raises(ValueError, match="missing from the pool"):
        plan_transfers(pool.drop(index=s0[0]), s0, bank)


def test_wrong_squad_size_raises(setup):
    pool, s0, bank = setup
    with pytest.raises(ValueError, match="15 distinct"):
        best_transfers(pool, s0[:14], bank, 1, 1)


def test_options_table(setup):
    pool, s0, bank = setup
    names = pd.Series({i: f"P{i}" for i in pool.index})
    table = options_table(plan_transfers(pool, s0, bank, free_transfers=1), names)
    assert list(table["transfers"]) == [0, 1, 2, 3]
    assert list(table["hit"]) == [0, 0, -4, -8]
    assert table.loc[0, "net_gain"] == 0
