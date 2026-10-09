"""Hindsight-best squads: legal, never beaten by the model pick or random legal squads."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pools import random_pool

from fPLense import config
from fPLense.models import history
from fPLense.optimize.squad_ilp import check_squad, pick_squad, result_from_selection


def actual_pool(seed: int) -> pd.DataFrame:
    """A synthetic GW: prices, positions, clubs, and actual points (some players don't play)."""
    rng = np.random.default_rng(seed)
    pool = random_pool(n=250, seed=seed)
    minutes = rng.choice([0, 30, 90], size=len(pool), p=[0.3, 0.1, 0.6])
    points = np.where(minutes > 0, rng.poisson(pool["p1"].to_numpy()) + 1, 0)
    pool["points"] = points.astype(float)
    pool["minutes"] = minutes
    pool["p1"] = pool["points"]
    pool["P_h"] = pool["points"]
    return pool


def squad_doc(pool: pd.DataFrame, res) -> dict:
    bench_order = {p: k + 1 for k, p in enumerate(res.bench)}
    return {
        "captain": int(res.captain),
        "vice": int(res.vice),
        "cost": int(res.cost),
        "players": [
            {
                "element": int(i),
                "pos": pool.at[i, "pos"],
                "starter": i in set(res.starters),
                "bench_order": bench_order.get(i),
            }
            for i in res.squad
        ],
    }


def actual_of(pool: pd.DataFrame, res) -> int:
    act = pool.rename(columns={"points": "total_points"})
    return history.squad_actual(squad_doc(pool, res), act, pool["pos"])["points"]


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_hindsight_squad_is_legal_and_scores_xi_plus_captain(seed):
    pool = actual_pool(seed)
    h = history.hindsight_squad(pool)
    res = result_from_selection(pool, h["squad"], h["starters"], h["captain"], bench_w=0.0)
    assert check_squad(pool, res) == []
    assert h["cost"] <= config.BUDGET
    xi = pool.loc[h["starters"], "points"]
    assert h["points"] == int(xi.sum() + pool.at[h["captain"], "points"])
    # captain = the best actual starter
    assert pool.at[h["captain"], "points"] == xi.max()


@pytest.mark.parametrize("seed", [0, 1])
def test_hindsight_beats_model_pick_and_random_legal_squads(seed):
    pool = actual_pool(seed)
    best = history.hindsight_squad(pool)["points"]
    rng = np.random.default_rng(100 + seed)
    # the "model pick": a squad chosen on noisy forecasts, scored on actual points
    noisy = pool.assign(p1=pool["points"] + rng.normal(0, 3, len(pool)))
    model = pick_squad(noisy.assign(P_h=noisy["p1"]))
    model_points = actual_of(pool, model)
    assert best >= model_points
    capture = model_points / best
    assert 0.0 <= capture <= 1.0
    # 50 random legal squads (random objectives through the same ILP, so every one is legal)
    for k in range(50):
        r = rng.random(len(pool)) * 10
        res = pick_squad(pool.assign(p1=r, P_h=r))
        assert check_squad(pool, res) == []
        assert best >= actual_of(pool, res), f"random squad {k} beat the hindsight squad"


def test_hindsight_respects_that_gws_prices():
    pool = actual_pool(3)
    top = pool["points"].nlargest(15).index
    rich = history.hindsight_squad(pool)
    poor = history.hindsight_squad(pool.assign(price=pool["price"] + 15))
    assert poor["cost"] <= config.BUDGET
    assert poor["points"] <= rich["points"]
    assert set(top) - set(rich["squad"])  # the 15 top scorers don't fit £100m + the rules


def test_actual_pool_from_actuals_table():
    act = pd.DataFrame(
        {
            "element": [1, 2, 1],
            "gw": [3, 3, 4],
            "total_points": [5, 2, 7],
            "minutes": [90, 0, 90],
            "price": [55, 45, 56],
            "pos": ["MID", "DEF", "MID"],
            "team": ["Arsenal", "Spurs", "Arsenal"],
        }
    )
    p = history.actual_pool(act, 3)
    assert list(p.index) == [1, 2]
    assert p.at[1, "p1"] == p.at[1, "P_h"] == p.at[1, "points"] == 5.0
    assert p.at[1, "club"] == "Arsenal" and p["price"].dtype.kind == "i"
