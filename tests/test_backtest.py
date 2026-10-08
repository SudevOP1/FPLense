"""Backtest building blocks: the GW pool (no look-ahead), auto-subs, captaincy and a tiny run."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fPLense.optimize import backtest
from fPLense.optimize.squad_ilp import SquadResult


def _season(n_gws: int = 6, seed: int = 0):
    """6 clubs x 15 players (2-5-5-3 each; 3-per-club needs >= 5 clubs), one fixture per club/GW,
    except club C3 blanks in GW4 and C0 has a double in GW5; player 999 leaves after GW2."""
    rng = np.random.default_rng(seed)
    clubs = [f"C{k}" for k in range(6)]
    shape = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    players = [
        (100 * k + j, f"p{100 * k + j}", pos, club)
        for k, club in enumerate(clubs)
        for j, pos in enumerate(shape)
    ] + [(999, "leaver", "MID", "C1")]
    rows = []
    fixture = 0
    for gw in range(1, n_gws + 1):
        for club in clubs:
            n_fix = 0 if (club == "C3" and gw == 4) else 2 if (club == "C0" and gw == 5) else 1
            for f in range(n_fix):
                fixture += 1
                for el, name, pos, c in players:
                    if c != club or (el == 999 and gw > 2):
                        continue
                    rows.append(
                        {
                            "season": "2025-26",
                            "gw": gw,
                            "element": el,
                            "name": name,
                            "position": pos,
                            "team": club,
                            "fixture": fixture * 10 + f,
                            "minutes": int(rng.choice([0, 90])),
                            "total_points": int(rng.integers(0, 10)),
                            "value": 45 + (el % 100) % 7 * 5,
                        }
                    )
    actual = pd.DataFrame(rows)
    preds = actual.rename(columns={"total_points": "y"})[
        ["season", "gw", "element", "fixture", "y"]
    ].copy()
    preds["pred_lgbm"] = rng.uniform(0, 6, len(preds))
    preds["pred_b0"] = rng.uniform(0, 6, len(preds))
    return preds, actual


def test_pool_uses_only_the_schedule_ahead():
    preds, actual = _season()
    pg = backtest.player_gw_table(preds, actual)
    tf = backtest.team_fixture_counts(actual)
    assert tf.loc["C3", 4] == 0 and tf.loc["C0", 5] == 2

    pool = backtest.gw_pool(pg, tf, 3, "pred_lgbm", horizon=3, discount=0.9)
    el = 101  # C1 player
    now = pg[(pg.gw == 3) & (pg.element == el)].iloc[0]
    rate = now["pred_lgbm"] / now["n_fix"]
    # GW4 one fixture, GW5 one fixture for C1
    assert pool.at[el, "p1"] == pytest.approx(now["pred_lgbm"])
    assert pool.at[el, "P_h"] == pytest.approx(now["pred_lgbm"] + 0.9 * rate + 0.81 * rate)

    c3 = 301  # blanks in GW4
    now3 = pg[(pg.gw == 3) & (pg.element == c3)].iloc[0]
    assert pool.at[c3, "P_h"] == pytest.approx(now3["pred_lgbm"] * (1 + 0.81))

    c0 = 1  # double in GW5
    now0 = pg[(pg.gw == 3) & (pg.element == c0)].iloc[0]
    assert pool.at[c0, "P_h"] == pytest.approx(now0["pred_lgbm"] * (1 + 0.9 + 0.81 * 2))

    # changing a later GW's prediction can't change this pool (no look-ahead)
    preds2 = preds.copy()
    preds2.loc[preds2.gw >= 4, "pred_lgbm"] += 100
    pool2 = backtest.gw_pool(
        backtest.player_gw_table(preds2, actual), tf, 3, "pred_lgbm", horizon=3, discount=0.9
    )
    pd.testing.assert_series_equal(pool["P_h"], pool2["P_h"])


def test_blank_player_stays_active_and_leaver_is_unavailable():
    preds, actual = _season()
    pg = backtest.player_gw_table(preds, actual)
    tf = backtest.team_fixture_counts(actual)
    pool = backtest.gw_pool(pg, tf, 4, "pred_lgbm")
    assert pool.at[301, "status"] == "a" and pool.at[301, "p1"] == 0
    assert pool.at[999, "status"] == "u" and pool.at[999, "P_h"] == 0


def _pool_and_squad():
    ids = list(range(1, 16))
    pos = ["GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    pool = pd.DataFrame(
        {"pos": pos, "minutes": 90, "points": 2, "club": "X", "price": 50, "p1": 1.0, "P_h": 1.0},
        index=ids,
    )
    # XI: GK 1, DEF 3-6 (4), MID 8-11 (4), FWD 13-14 (2); bench: MID 12, DEF 7, FWD 15, GK 2
    starters = [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14]
    res = SquadResult(
        squad=ids,
        starters=starters,
        bench=[12, 7, 15, 2],
        captain=13,
        vice=8,
        cost=750,
        objective=0,
        expected_points=0,
    )
    return pool, res


def test_score_with_captain_doubled():
    pool, res = _pool_and_squad()
    pool.loc[13, "points"] = 10
    pts, info = backtest.score_gw(pool, res)
    assert pts == 2 * 10 + 10 + 10 and info["armband"] == 13 and info["subs"] == []


def test_auto_subs_keep_formation_and_bench_order():
    pool, res = _pool_and_squad()
    pool.loc[[3], "minutes"] = 0  # a DEF misses out: 4 -> 3 DEF is still legal
    pool.loc[12, "points"] = 7  # first on the bench comes on
    pts, info = backtest.score_gw(pool, res)
    assert info["subs"] == [(3, 12)]
    assert pts == 2 * 10 + 7 + 2  # 10 others at 2, the sub's 7, captain's 2 doubled

    pool, res = _pool_and_squad()
    pool.loc[[3, 4], "minutes"] = 0  # two DEF out: the second must be replaced by a DEF
    _, info = backtest.score_gw(pool, res)
    assert info["subs"] == [(3, 12), (4, 7)]

    pool, res = _pool_and_squad()
    pool.loc[1, "minutes"] = 0  # GK only swaps with the bench GK
    _, info = backtest.score_gw(pool, res)
    assert info["subs"] == [(1, 2)]


def test_vice_takes_the_armband():
    pool, res = _pool_and_squad()
    pool.loc[13, "minutes"] = 0
    pool.loc[8, "points"] = 6
    pts, info = backtest.score_gw(pool, res)
    assert info["armband"] == 8
    # 13 replaced by bench MID 12 (2 pts); vice 8 doubled
    assert pts == 9 * 2 + 6 + 2 + 6


def test_tiny_backtest_runs_legally():
    preds, actual = _season(n_gws=6)
    result = backtest.run_backtest(season="2025-26", start_gw=3, horizon=2, inputs=(preds, actual))
    per = result.per_gw
    assert set(per["strategy"]) == {"lgbm", "b0", "greedy"}
    assert (
        per.groupby("strategy")["gw"].apply(list)
        == pd.Series([[3, 4, 5, 6]] * 3, index=["b0", "greedy", "lgbm"])
    ).all()
    assert (per["transfers"] <= 1).all()
    assert (per["bank"] >= 0).all()
    s = result.summary
    assert s["total_points"]["lgbm"] == int(per[per.strategy == "lgbm"]["points"].sum())
    lo, hi = s["a_minus_b_ci95"]
    assert lo <= hi
