"""Odds → implied goals / clean-sheet probability, and the odds loader (no network)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from fPLense.etl import load_odds
from fPLense.etl.odds_features import (
    add_implied,
    calibration_table,
    devig,
    implied_mu,
    p_home_win,
    p_over_25,
    split_mu,
)

# --- de-vig / implied goals -----------------------------------------------------------------


def test_devig_sums_to_one():
    probs = devig(1.8, 3.6, 4.5)
    assert sum(probs) == pytest.approx(1.0)
    assert probs[0] > probs[1] and probs[0] > probs[2]
    assert sum(devig(1.9, 1.9)) == pytest.approx(1.0)


def test_devig_removes_margin_proportionally():
    p_home, p_draw, p_away = devig(2.0, 4.0, 4.0)  # overround 1.0 -> already fair
    assert (p_home, p_draw, p_away) == pytest.approx((0.5, 0.25, 0.25))


def test_devig_missing_price_is_nan():
    assert all(math.isnan(p) for p in devig(2.0, float("nan"), 3.0))


def test_even_over_under_gives_mu_about_2_67():
    p_over = devig(2.0, 2.0)[0]
    assert p_over == pytest.approx(0.5)
    assert implied_mu(p_over) == pytest.approx(2.674, abs=0.01)


def test_implied_mu_round_trips():
    for mu in (1.5, 2.3, 3.4):
        assert implied_mu(p_over_25(mu)) == pytest.approx(mu, abs=1e-6)


def test_implied_mu_clips_extremes():
    assert implied_mu(1e-6) == pytest.approx(0.2)
    assert implied_mu(0.9999) == pytest.approx(6.0)
    assert math.isnan(implied_mu(float("nan")))


def test_heavy_favourite_home_gets_bigger_lambda():
    p_home, _, _ = devig(1.25, 6.5, 13.0)
    mu = implied_mu(devig(1.6, 2.4)[0])
    lam_home, lam_away = split_mu(mu, p_home)
    assert lam_home > lam_away
    assert lam_home + lam_away == pytest.approx(mu)
    # the split reproduces the bookmaker's home-win probability
    assert p_home_win(lam_home / mu, mu) == pytest.approx(p_home, abs=1e-6)


def test_away_favourite_gets_bigger_away_lambda():
    p_home, _, _ = devig(7.0, 4.5, 1.45)
    lam_home, lam_away = split_mu(2.8, p_home)
    assert lam_away > lam_home


def test_add_implied_columns_and_clean_sheet():
    df = pd.DataFrame(
        {
            "odds_h": [1.5, 3.0],
            "odds_d": [4.2, 3.3],
            "odds_a": [6.5, 2.4],
            "odds_over": [1.7, 2.1],
            "odds_under": [2.2, 1.75],
        }
    )
    out = add_implied(df)
    hda = out[["p_home", "p_draw", "p_away"]].sum(axis=1)
    np.testing.assert_allclose(hda, 1.0)
    np.testing.assert_allclose(out.lam_home + out.lam_away, out.mu)
    np.testing.assert_allclose(out.p_cs_home, np.exp(-out.lam_away))
    np.testing.assert_allclose(out.p_cs_away, np.exp(-out.lam_home))
    assert out.loc[0, "lam_home"] > out.loc[0, "lam_away"]  # home favourite
    assert out.loc[1, "lam_home"] < out.loc[1, "lam_away"]  # away favourite


def test_calibration_table_deciles():
    rng = np.random.default_rng(0)
    p = pd.Series(rng.uniform(0.05, 0.6, 5000))
    cs = pd.Series(rng.uniform(size=5000) < p)
    table = calibration_table(p, cs)
    assert len(table) == 10
    assert table["n"].sum() == 5000
    np.testing.assert_allclose(table.p_mean, table.cs_rate, atol=0.06)


# --- odds loader (synthetic football-data frames) -------------------------------------------


def _fd_frame(**overrides) -> pd.DataFrame:
    """Two matches in the 2019-20+ layout, closing-odds columns included."""
    base = {
        "Div": ["E0", "E0"],
        "Date": ["09/08/2019", "10/08/2019"],
        "Time": ["20:00", "15:00"],
        "HomeTeam": ["Liverpool", "West Ham"],
        "AwayTeam": ["Norwich", "Man City"],
        "FTHG": [4, 0],
        "FTAG": [1, 5],
        "B365H": [1.14, 12.0],
        "B365D": [10.0, 6.5],
        "B365A": [19.0, 1.22],
        "AvgH": [1.15, 11.5],
        "AvgD": [9.5, 6.4],
        "AvgA": [18.0, 1.24],
        "B365>2.5": [1.4, 1.36],
        "B365<2.5": [3.0, 3.2],
        "Avg>2.5": [1.4, 1.37],
        "Avg<2.5": [2.95, 3.1],
        "AHh": [-2.25, 1.75],
        "B365AHH": [1.9, 1.93],
        "AvgAHA": [1.95, 1.9],
        # closing odds: must never survive
        "B365CH": [1.1, 13.0],
        "PSCH": [1.11, 12.5],
        "PSCD": [11.0, 6.0],
        "AvgCH": [1.12, 12.0],
        "MaxCA": [21.0, 1.3],
        "AvgC>2.5": [1.35, 1.33],
        "B365C<2.5": [3.2, 3.4],
        "AHCh": [-2.5, 2.0],
        "B365CAHH": [1.88, 1.9],
        "BFECAHA": [1.9, 1.91],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_closing_regex_flags_closing_columns_only():
    closing = ["B365CH", "PSCA", "AvgC>2.5", "MaxC<2.5", "B365CAHH", "AHCh", "BFDCD", "PCAHA"]
    pre_match = ["B365H", "PSA", "Avg>2.5", "BbAv<2.5", "BbAvAHH", "AHh", "HC", "AC", "HxG"]
    assert all(load_odds.CLOSING_RE.match(c) for c in closing)
    assert not any(load_odds.CLOSING_RE.match(c) for c in pre_match)


def test_no_closing_column_survives_load():
    raw = _fd_frame()
    assert any(load_odds.CLOSING_RE.match(c) for c in raw.columns)
    dropped = load_odds.drop_closing(raw)
    assert not [c for c in dropped.columns if load_odds.CLOSING_RE.match(c)]
    out = load_odds.clean_odds(raw)
    assert not [c for c in out.columns if load_odds.CLOSING_RE.match(c)]
    assert list(out.columns) == load_odds.LAKE_COLUMNS


def test_closing_odds_do_not_change_features():
    raw = _fd_frame()
    base = load_odds.clean_odds(raw)
    tweaked = raw.copy()
    for c in ["B365CH", "PSCH", "AvgCH", "MaxCA", "AvgC>2.5", "B365C<2.5"]:
        tweaked[c] = tweaked[c] * 3
    pd.testing.assert_frame_equal(base, load_odds.clean_odds(tweaked))


def test_market_average_preferred_then_b365():
    raw = _fd_frame(AvgH=[1.15, np.nan], **{"Avg>2.5": [np.nan, 1.37]})
    out = load_odds.clean_odds(raw)
    assert list(out.source_1x2) == ["avg", "b365"]
    assert out.loc[0, "odds_h"] == pytest.approx(1.15)
    assert out.loc[1, "odds_h"] == pytest.approx(12.0)  # B365H fallback
    assert list(out.source_ou) == ["b365", "avg"]
    assert out.loc[0, "odds_over"] == pytest.approx(1.4)  # B365>2.5 fallback


def test_betbrain_columns_used_before_2019_20():
    raw = pd.DataFrame(
        {
            "Div": ["E0"],
            "Date": ["13/08/16"],
            "HomeTeam": ["Burnley"],
            "AwayTeam": ["Swansea"],
            "FTHG": [0],
            "FTAG": [1],
            "B365H": [2.4],
            "B365D": [3.3],
            "B365A": [3.25],
            "BbAvH": [2.43],
            "BbAvD": [3.21],
            "BbAvA": [3.1],
            "BbAv>2.5": [2.3],
            "BbAv<2.5": [1.61],
            "PSCH": [2.79],
        }
    )
    out = load_odds.clean_odds(raw)
    assert out.loc[0, "source_1x2"] == "avg" and out.loc[0, "odds_h"] == pytest.approx(2.43)
    assert out.loc[0, "odds_over"] == pytest.approx(2.3)
    assert out.loc[0, "date"] == pd.Timestamp("2016-08-13")
    assert pd.isna(out.loc[0, "time"])
    assert out.loc[0, "lam_home"] > 0


def test_dates_parsed_day_first_in_both_formats():
    s = pd.Series(["13/08/16", "01/02/2019", "10/08/2018"])
    assert list(load_odds.parse_dates(s)) == [
        pd.Timestamp("2016-08-13"),
        pd.Timestamp("2019-02-01"),
        pd.Timestamp("2018-08-10"),
    ]


def test_other_divisions_and_blank_rows_dropped():
    raw = _fd_frame(Div=["E0", "E1"])
    raw.loc[2] = [None] * len(raw.columns)
    out = load_odds.clean_odds(raw)
    assert len(out) == 1 and out.loc[0, "home_team"] == "Liverpool"


def test_fd_season_code():
    from fPLense import config

    assert config.fd_season_code("2016-17") == "1617"
    assert config.fd_season_code("2026-27") == "2627"
