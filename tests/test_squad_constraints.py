"""Squad ILP: every FPL rule holds on random pools, and it beats the greedy heuristic."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pools import random_pool

from fPLense import config
from fPLense.optimize import squad_ilp
from fPLense.optimize.squad_ilp import InfeasibleSquadError, check_squad, greedy_squad, pick_squad


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_random_pools_obey_every_rule(seed):
    pool = random_pool(seed=seed)
    res = pick_squad(pool)
    assert check_squad(pool, res) == []
    sq = pool.loc[res.squad]
    # budget in integer tenths
    assert res.cost == int(sq["price"].sum()) <= config.BUDGET
    assert sq["price"].dtype.kind == "i"
    # 2-5-5-3 and <= 3 per club
    assert sq["pos"].value_counts().to_dict() == config.SQUAD_QUOTAS
    assert sq["club"].value_counts().max() <= config.MAX_PER_CLUB
    # XI shape
    xi = pool.loc[res.starters, "pos"].value_counts()
    assert len(res.starters) == 11
    assert xi.get("GK", 0) == 1
    assert xi.get("DEF", 0) >= 3 and xi.get("MID", 0) >= 2 and xi.get("FWD", 0) >= 1
    # exactly one captain, who starts; vice is a different starter
    assert res.captain in res.starters
    assert res.vice in res.starters and res.vice != res.captain
    # bench = the other 4, GK last
    assert sorted(res.bench + res.starters) == sorted(res.squad)
    assert pool.at[res.bench[-1], "pos"] == "GK"


def test_tight_budget_still_respected():
    pool = random_pool(seed=7)
    res = pick_squad(pool, budget=800)
    assert res.cost <= 800
    assert check_squad(pool, res, budget=800) == []


def test_captain_is_best_p1_starter_choice():
    pool = random_pool(seed=3)
    res = pick_squad(pool)
    # the captain term is p1: no other starter has a higher p1
    assert pool.at[res.captain, "p1"] == pytest.approx(pool.loc[res.starters, "p1"].max())


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_ilp_beats_greedy_on_toy_pool(seed):
    rng = np.random.default_rng(seed)
    base = random_pool(n=400, seed=seed)
    # 25 players (enough for every quota with spares), clubs round-robin so <= 3 per club
    take = {"GK": 3, "DEF": 7, "MID": 9, "FWD": 6}
    toy = pd.concat(
        [
            base[base["pos"] == p].sample(n, random_state=int(rng.integers(1e6)))
            for p, n in take.items()
        ]
    )
    toy["club"] = [f"C{k % 10}" for k in range(len(toy))]
    assert len(toy) == 25
    # a binding budget: the cheapest legal squad plus £15m
    cheapest = sum(
        toy.loc[toy["pos"] == p, "price"].nsmallest(n).sum() for p, n in config.SQUAD_QUOTAS.items()
    )
    budget = int(cheapest) + 150
    ilp = pick_squad(toy, budget=budget)
    greedy = greedy_squad(toy, budget=budget)
    assert check_squad(toy, ilp, budget=budget) == []
    assert check_squad(toy, greedy, budget=budget) == []
    assert ilp.objective >= greedy.objective - 1e-6


def test_objective_matches_reported_value():
    pool = random_pool(seed=11)
    res = pick_squad(pool)
    assert res.objective == pytest.approx(
        squad_ilp.squad_objective(pool, res.squad, res.starters, res.captain)
    )


def test_infeasible_raises_clear_error():
    pool = random_pool(seed=0)
    with pytest.raises(InfeasibleSquadError, match="no legal squad"):
        pick_squad(pool, budget=300)
    only_two_fwd = pool[pool["pos"] != "FWD"]
    only_two_fwd = pd.concat([only_two_fwd, pool[pool["pos"] == "FWD"].head(2)])
    with pytest.raises(InfeasibleSquadError):
        pick_squad(only_two_fwd)


def test_unavailable_players_are_filtered():
    pool = random_pool(seed=5)
    best = pick_squad(pool)
    star = max(best.squad, key=lambda i: pool.at[i, "P_h"])
    pool["status"] = "a"
    pool["chance_of_playing_next_round"] = np.nan
    pool.loc[star, "status"] = "u"
    other = [i for i in best.squad if i != star][0]
    pool.loc[other, "chance_of_playing_next_round"] = 0
    res = pick_squad(pool)
    assert star not in res.squad and other not in res.squad
    # NaN chance means 100%: those players remain eligible
    assert len(squad_ilp.eligible(pool)) == len(pool) - 2


def test_prices_must_be_integer_tenths():
    pool = random_pool(seed=1)
    pool["price"] = pool["price"] / 10  # £m floats, the classic mistake
    with pytest.raises(ValueError, match="integer tenths"):
        pick_squad(pool)


def test_missing_columns_rejected():
    with pytest.raises(ValueError, match="missing columns"):
        pick_squad(random_pool().drop(columns="P_h"))


def test_discounted_sum():
    per_gw = np.array([[2.0, 2.0, 2.0], [5.0, 0.0, np.nan]])
    out = squad_ilp.discounted_sum(per_gw, discount=0.9)
    assert out == pytest.approx([2 + 1.8 + 1.62, 5.0])


def test_best_xi_is_optimal_for_formation():
    pool = random_pool(seed=2)
    res = pick_squad(pool)
    starters, captain = squad_ilp.best_xi(pool, res.squad)
    # best_xi maximises the starters' P_h alone, so it can't do worse than the ILP's XI on it
    assert pool.loc[starters, "P_h"].sum() >= pool.loc[res.starters, "P_h"].sum() - 1e-6
    assert (
        check_squad(pool, squad_ilp.result_from_selection(pool, res.squad, starters, captain)) == []
    )
    assert captain in starters


# --- P6: locks, bans, the lineup helper, the rule report, pruning -----------------------------


def test_locks_and_bans_respected():
    pool = random_pool(seed=11)
    free = pick_squad(pool)
    banned = set(free.squad[:4])
    outsiders = [i for i in pool.index if i not in free.squad and pool.at[i, "price"] <= 55]
    locked = outsiders[:2]
    res = pick_squad(pool, locked=locked, banned=banned)
    assert set(locked) <= set(res.squad)
    assert not banned & set(res.squad)
    assert check_squad(pool, res) == []
    assert res.objective <= free.objective + 1e-9


def test_locked_player_skips_availability_filter():
    pool = random_pool(seed=12).assign(status="a")
    star = pool["P_h"].idxmax()
    pool.loc[star, "status"] = "u"
    assert star not in pick_squad(pool).squad
    assert star in pick_squad(pool, locked=[star]).squad


@pytest.mark.parametrize(
    ("make_locks", "causes"),
    [
        (lambda p: list(p.index[p["pos"] == "GK"][:3]), {"quota"}),
        (lambda p: list(p.index[p["club"] == p["club"].iloc[0]][:4]), {"club limit"}),
        (lambda p: list(p.sort_values("price").index[-15:]), {"budget", "quota"}),
    ],
)
def test_infeasible_locks_name_the_cause(make_locks, causes):
    pool = random_pool(n=300, seed=13)
    with pytest.raises(InfeasibleSquadError) as err:
        pick_squad(pool, locked=make_locks(pool))
    assert err.value.cause in causes
    assert str(err.value)


def test_budget_lock_message():
    pool = random_pool(n=300, seed=14)
    dear = list(pool[pool["pos"] == "FWD"].sort_values("price").index[-3:])
    dear += list(pool[pool["pos"] == "MID"].sort_values("price").index[-5:])
    with pytest.raises(InfeasibleSquadError, match="budget") as err:
        pick_squad(pool, locked=dear, budget=900)
    assert err.value.cause == "budget"


def test_lock_and_ban_conflict():
    pool = random_pool(seed=15)
    with pytest.raises(InfeasibleSquadError) as err:
        pick_squad(pool, locked=[pool.index[0]], banned=[pool.index[0]])
    assert err.value.cause == "conflict"


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_best_lineup_is_legal_and_optimal_for_a_fixed_squad(seed):
    pool = random_pool(seed=seed)
    squad = pick_squad(pool, budget=900).squad
    res = squad_ilp.best_lineup(pool, squad)
    assert sorted(res.squad) == sorted(squad)
    assert check_squad(pool, res, budget=10_000) == []
    # the ILP objective is at least that of the formation-rule XI with its best captain
    xi, cap = squad_ilp.best_xi(pool, squad)
    rule = squad_ilp.squad_objective(pool, squad, xi, cap)
    assert res.objective >= rule - 1e-9


def test_best_lineup_rejects_incomplete_squads():
    pool = random_pool(seed=3)
    with pytest.raises(ValueError, match="2-5-5-3"):
        squad_ilp.best_lineup(pool, pick_squad(pool).squad[:14])


def test_rule_problems_on_partial_and_broken_squads():
    pool = random_pool(n=300, seed=4)
    defs = list(pool.index[pool["pos"] == "DEF"][:6])
    probs = squad_ilp.rule_problems(pool, defs)
    assert {"size", "quota"} <= {p["rule"] for p in probs}
    assert any("6 DEF" in p["message"] for p in probs)
    club = pool["club"].iloc[0]
    four = list(pool.index[pool["club"] == club][:4])
    assert any(p["rule"] == "club" for p in squad_ilp.rule_problems(pool, four))
    assert any(p["rule"] == "duplicate" for p in squad_ilp.rule_problems(pool, [defs[0]] * 2))
    assert any(p["rule"] == "unknown" for p in squad_ilp.rule_problems(pool, [999_999]))
    legal = pick_squad(pool)
    ok = squad_ilp.rule_problems(pool, legal.squad, legal.starters, legal.captain, legal.vice)
    assert ok == []
    over = squad_ilp.rule_problems(pool, legal.squad, budget=legal.cost - 1)
    assert [p["rule"] for p in over] == ["budget"]
    assert squad_ilp.rule_problems(pool, legal.squad, budget=1, enforce_budget=False) == []
    bad_xi = squad_ilp.rule_problems(pool, legal.squad, legal.bench + legal.starters[:7])
    assert any(p["rule"] == "xi" for p in bad_xi)


def test_evaluate_squad_expected_and_actual():
    pool = random_pool(seed=5)
    pool["p_a"] = pool["p1"]
    pool["p_b"] = pool["p1"] * 2
    res = pick_squad(pool)
    actual = pd.DataFrame({"points": 2, "minutes": 90}, index=pool.index)
    out = squad_ilp.evaluate_squad(
        pool, res.squad, res.starters, res.captain, res.vice, {6: "p_a", 7: "p_b"}, actual
    )
    xi = pool.loc[res.starters, "p1"].sum() + pool.at[res.captain, "p1"]
    assert out["expected"][6] == pytest.approx(xi)
    assert out["expected"][7] == pytest.approx(2 * xi)
    assert out["actual"]["points"] == 24  # 11 x 2 + the captain's 2 again
    assert out["legal"] and out["cost"] == res.cost
    auto = squad_ilp.evaluate_squad(pool, res.squad, gw_cols={6: "p_a"})
    assert len(auto["starters"]) == 11 and auto["captain"] in auto["starters"]
    partial = squad_ilp.evaluate_squad(pool, res.squad[:5], gw_cols={6: "p_a"})
    assert not partial["legal"] and partial["starters"] == []


def test_pruning_never_changes_the_optimum():
    import unittest.mock as mock

    for seed in range(4):
        pool = random_pool(n=400, seed=seed)
        assert len(squad_ilp.prune_dominated(squad_ilp.validate_pool(pool))) < len(pool)
        pruned = pick_squad(pool)
        with mock.patch.object(squad_ilp, "prune_dominated", lambda d, keep=(): d):
            raw = pick_squad(pool)
        assert pruned.objective == pytest.approx(raw.objective)


def test_pruning_keeps_protected_players():
    pool = squad_ilp.validate_pool(random_pool(n=400, seed=1))
    worst = pool["P_h"].idxmin()  # made the priciest of his position too: dominated by many
    pool.loc[worst, ["price", "p1"]] = [
        pool.loc[pool["pos"] == pool.at[worst, "pos"], "price"].max(),
        0,
    ]
    assert worst not in squad_ilp.prune_dominated(pool).index
    assert worst in squad_ilp.prune_dominated(pool, keep=[worst]).index
