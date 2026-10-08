"""Elo-only goal estimate used when upcoming fixtures have no bookmaker odds."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fPLense.etl import elo_goals
from fPLense.etl.load_odds import LAKE_COLUMNS


def test_fit_recovers_known_coefficients():
    rng = np.random.default_rng(0)
    n = 20_000
    diff = rng.normal(0, 150, n)
    home = rng.integers(0, 2, n)
    lam = np.exp(0.2 + 0.19 * diff / 100 + 0.2 * home)
    model = elo_goals.fit(rng.poisson(lam), diff, home)
    assert model.intercept == pytest.approx(0.2, abs=0.03)
    assert model.coef_elo_100 == pytest.approx(0.19, abs=0.02)
    assert model.coef_home == pytest.approx(0.2, abs=0.03)
    assert model.n == n


def test_stronger_and_home_sides_expect_more_goals():
    m = elo_goals.EloGoalModel(intercept=0.2, coef_elo_100=0.19, coef_home=0.19)
    assert m.lam(100, 0) > m.lam(0, 0) > m.lam(-100, 0)
    assert m.lam(0, 1) > m.lam(0, 0)


def test_implied_probabilities_are_consistent():
    p = elo_goals.implied([1.8, 1.0], [0.9, 1.0]).iloc[0]
    assert p["p_home"] + p["p_draw"] + p["p_away"] == pytest.approx(1.0)
    assert p["p_home"] > p["p_away"]
    assert p["p_cs_home"] == pytest.approx(np.exp(-0.9))
    assert p["mu"] == pytest.approx(2.7)
    even = elo_goals.implied([1.0], [1.0]).iloc[0]
    assert even["p_home"] == pytest.approx(even["p_away"])


def test_latest_elo_is_strictly_before():
    elo = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-01", "2026-09-15"]).date,
            "club": ["Arsenal", "Arsenal"],
            "elo": [1900.0, 1950.0],
        }
    )
    assert elo_goals.latest_elo(elo, "Arsenal", "2026-09-15") == 1900.0  # same day excluded
    assert elo_goals.latest_elo(elo, "Arsenal", "2026-09-16") == 1950.0
    assert np.isnan(elo_goals.latest_elo(elo, "Arsenal", "2026-08-01"))


def test_estimate_rows_match_odds_lake_schema():
    elo = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-01"] * 2).date,
            "club": ["Arsenal", "Tottenham"],
            "elo": [1900.0, 1700.0],
        }
    )
    names = pd.DataFrame(
        {
            "fpl_name": ["Arsenal", "Spurs"],
            "fd_name": ["Arsenal", "Tottenham"],
            "clubelo_name": ["Arsenal", "Tottenham"],
        }
    )
    fx = pd.DataFrame(
        {"home": ["Spurs"], "away": ["Arsenal"], "date": [pd.Timestamp("2026-10-10")]}
    )
    m = elo_goals.EloGoalModel(intercept=0.2, coef_elo_100=0.19, coef_home=0.19)
    rows = elo_goals.estimate_rows(fx, m, elo, names)
    assert rows.columns.tolist() == LAKE_COLUMNS
    r = rows.iloc[0]
    assert r["home_team"] == "Tottenham" and r["away_team"] == "Arsenal"
    assert r["source_1x2"] == "elo" and r["source_ou"] == "elo"
    assert r["lam_home"] == pytest.approx(float(m.lam(-200, 1)))
    assert r["lam_away"] == pytest.approx(float(m.lam(200, 0)))
    assert r["p_away"] > r["p_home"]  # Arsenal 200 Elo stronger
    assert np.isnan(r["odds_h"])  # no bookmaker prices behind an Elo row
    assert elo_goals.estimate_rows(fx.iloc[:0], m, elo, names).empty
