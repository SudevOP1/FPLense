"""B0 rolling-form fallback and the Ridge pipeline (pure logic, no data)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fPLense import config
from fPLense.models import baselines


def _synthetic(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({f: rng.normal(size=n) for f in config.FEATURES if f != "position"})
    df["position"] = rng.choice(["GK", "DEF", "MID", "FWD"], size=n)
    df["y"] = 2.0 + 1.5 * df["pts_r5"] + rng.normal(scale=0.5, size=n)
    return df


def test_b0_fallback_order():
    df = pd.DataFrame(
        {
            "pts_r5": [4.0, np.nan, np.nan, 0.0],
            "pts_season_avg": [1.0, 3.0, np.nan, 5.0],
        }
    )
    assert baselines.rolling_baseline(df).tolist() == [4.0, 3.0, 0.0, 0.0]


def test_b0_accepts_nullable_ints():
    df = pd.DataFrame(
        {
            "pts_r5": pd.array([2, None], dtype="Int64"),
            "pts_season_avg": pd.array([None, 6], dtype="Int64"),
        }
    )
    assert baselines.rolling_baseline(df).tolist() == [2.0, 6.0]


def test_ridge_fits_on_nan_input():
    df = _synthetic()
    df.loc[df.index[::3], "xg_r5"] = np.nan
    df["defcon_r5"] = np.nan  # an all-missing column (e.g. DEFCON before 2025-26)
    df["pts_last1"] = pd.array([None] * 50 + list(range(len(df) - 50)), dtype="Int64")
    model = baselines.fit_ridge(df)
    pred = baselines.predict_ridge(model, df)
    assert pred.shape == (len(df),)
    assert np.isfinite(pred).all()


def test_ridge_learns_signal_and_handles_unseen_position():
    df = _synthetic()
    model = baselines.fit_ridge(df)
    corr = np.corrcoef(baselines.predict_ridge(model, df), df["y"])[0, 1]
    assert corr > 0.9
    test = df.head(5).copy()
    test["position"] = "AM"  # unseen category must not crash
    assert np.isfinite(baselines.predict_ridge(model, test)).all()


def test_ridge_pipeline_steps():
    model = baselines.make_ridge()
    assert [name for name, _ in model.steps] == ["pre", "ridge"]
    num = model.named_steps["pre"].transformers[0][1]
    assert num.named_steps["impute"].add_indicator is True
    assert model.named_steps["pre"].transformers[1][2] == ["position"]


@pytest.mark.parametrize("subset", list(config.ABLATION_SETS))
def test_ablation_sets_are_nested_and_valid(subset):
    feats = config.ABLATION_SETS[subset]
    assert set(feats) <= set(config.FEATURES)
    assert len(feats) == len(set(feats))
    names = list(config.ABLATION_SETS)
    i = names.index(subset)
    if i:
        assert set(config.ABLATION_SETS[names[i - 1]]) < set(feats)


def test_ablation_ladder_ends_at_full_feature_set():
    assert set(config.ABLATION_SETS["iv_odds_elo"]) == set(config.FEATURES)
    added = set(config.ABLATION_SETS["iv_odds_elo"]) - set(config.ABLATION_SETS["iii_xg"])
    assert added == set(config.FEATURE_GROUPS["odds_elo"])
    assert not {"xg_r5", "xgi_r5"} & set(config.ABLATION_SETS["ii_fixture"])
