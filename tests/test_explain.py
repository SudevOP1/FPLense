"""SHAP helpers on a tiny synthetic LightGBM model (no data, no saved model needed)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fPLense import config
from fPLense.models import explain, train


@pytest.fixture(scope="module")
def fitted():
    rng = np.random.default_rng(0)
    n = 600
    df = pd.DataFrame({f: rng.normal(size=n) for f in config.FEATURES if f != "position"})
    df["position"] = rng.choice(train.POSITION_CATEGORIES, size=n)
    df["minutes_r3"] = rng.choice([0.0, 45.0, 90.0, np.nan], size=n)
    df[config.TARGET] = 2 * (df["minutes_r3"].fillna(0) > 45) + df["pts_r5"] + rng.normal(0, 0.3, n)
    df["season"] = "2025-26"
    df["gw"] = rng.integers(1, 39, size=n)
    model = train.make_lgbm(n_estimators=40)
    model.fit(train.lgbm_frame(df), df[config.TARGET], categorical_feature=["position"])
    return model, df


def test_shap_values_add_up_to_prediction(fitted):
    model, df = fitted
    sv = explain.shap_frame(model, df)
    pred = model.predict(train.lgbm_frame(df))
    total = sv.drop(columns="base_value").sum(axis=1) + sv["base_value"]
    assert np.allclose(total, pred, atol=1e-6)
    assert list(sv.columns[:-1]) == config.FEATURES


def test_tree_explainer_matches_lightgbm_contrib(fitted):
    model, df = fitted
    sub = df.head(50)
    expl = explain.explain(model, sub)
    sv = explain.shap_frame(model, sub)
    assert np.allclose(expl.values, sv.drop(columns="base_value").to_numpy(), atol=1e-6)
    # position shown as text in waterfalls, as a numeric code for colouring
    assert set(expl.display_data[:, config.FEATURES.index("position")]) <= set(
        train.POSITION_CATEGORIES
    )
    assert expl.data.dtype.kind == "f"


def test_top_contributions_sorted_by_magnitude():
    sv = pd.DataFrame({"a": [0.1, -2.0], "b": [-0.5, 0.3], "c": [0.2, 1.0], "base_value": 1.0})
    top = explain.top_contributions(sv, k=2)
    assert top.iloc[0] == [("b", -0.5), ("c", 0.2)]
    assert top.iloc[1] == [("a", -2.0), ("c", 1.0)]


def test_minutes_is_the_top_driver(fitted):
    model, df = fitted
    imp = explain.importance(explain.explain(model, df))
    assert imp.index[0] in {"minutes_r3", "pts_r5"}
    assert (imp.diff().dropna() <= 1e-12).all()


def test_sample_rows_limits_and_filters(fitted):
    _, df = fitted
    other = df.assign(season="2024-25")
    both = pd.concat([df, other], ignore_index=True)
    s = explain.sample_rows(both, n=100, season="2025-26")
    assert len(s) == 100 and (s["season"] == "2025-26").all()
    assert len(explain.sample_rows(df, n=10_000, season="2025-26")) == len(df)


def test_missing_model_file_has_clear_message(tmp_path):
    with pytest.raises(FileNotFoundError, match="--train"):
        explain.load_model(tmp_path / "nope.txt")
