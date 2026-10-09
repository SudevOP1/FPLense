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
    pair_moves,
    path_to_target,
    plan,
    plan_transfers,
    recommend_text,
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


# --- P6: T up to 5 and the path to a target squad ---------------------------------------------


def test_plan_goes_up_to_five(setup):
    pool, s0, bank = setup
    out = plan(pool, s0, bank, free_transfers=2, max_transfers=5)
    assert [o.n_transfers for o in out["options"]] == [0, 1, 2, 3, 4, 5]
    for o in out["options"]:
        assert check_squad(pool, o.result, budget=10_000) == []
        assert o.hits == 4 * max(0, o.n_transfers - 2)
    assert out["recommended"] in out["options"]
    assert out["path"] is None


@pytest.fixture(scope="module")
def target_setup(setup):
    pool, s0, bank = setup
    return pool, s0, bank, pick_squad(pool, budget=1000).squad


def test_target_mode_only_buys_from_target_and_sells_the_rest(target_setup):
    pool, s0, bank, target = target_setup
    steps = path_to_target(pool, s0, target, bank, free_transfers=1)
    assert steps, "the stale squad should have moves towards the best squad"
    buys, sells = set(target) - set(s0), set(s0) - set(target)
    for s in steps:
        assert set(s.option.ins) <= buys
        assert set(s.option.outs) <= sells
        assert len(s.option.ins) == len(s.option.outs) == s.n_moves
        assert pool.at[s.new_out, "pos"] == pool.at[s.new_in, "pos"]
        assert check_squad(pool, s.option.result, budget=10_000) == []
    for a, b in zip(steps, steps[1:], strict=False):  # nested: earlier moves are kept
        assert set(a.option.ins) <= set(b.option.ins)
        assert b.n_moves == a.n_moves + 1


def test_target_path_gain_never_falls_with_more_free_moves(target_setup):
    pool, s0, bank, target = target_setup
    by_free = {f: path_to_target(pool, s0, target, bank, free_transfers=f) for f in (0, 1, 3, 5)}
    for t in range(len(by_free[0])):
        gains = [by_free[f][t].net_gain for f in (0, 1, 3, 5)]
        assert gains == sorted(gains)
        for f in (0, 1, 3, 5):
            assert by_free[f][t].hits == 4 * max(0, by_free[f][t].n_moves - f)


def test_recommend_text(target_setup):
    pool, s0, bank, target = target_setup
    steps = path_to_target(pool, s0, target, bank, free_transfers=1)
    n, text = recommend_text(steps, 1)
    best = max(steps, key=lambda s: s.net_gain)
    assert n == (best.n_moves if best.net_gain > 0 else 0)
    assert text.startswith("Make" if n else "Hold")
    assert recommend_text([], 1)[0] == 0


def test_plan_with_target_returns_a_path(target_setup):
    pool, s0, bank, target = target_setup
    out = plan(pool, s0, bank, free_transfers=1, max_transfers=2, target=target)
    assert out["path"]["steps"] and out["path"]["advice"]


def test_pair_moves_like_for_like(setup):
    pool, s0, bank = setup
    opt = best_transfers(pool, s0, bank, free_transfers=3, n_transfers=3)
    pairs = pair_moves(pool, opt.outs, opt.ins)
    assert len(pairs) == 3
    assert all(pool.at[o, "pos"] == pool.at[i, "pos"] for o, i in pairs)
