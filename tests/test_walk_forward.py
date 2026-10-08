"""Walk-forward folds, early-stopping split, metrics and bootstrap (synthetic frames, no data)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fPLense import config
from fPLense.models import evaluate, train, walk_forward

SEASONS = ["2023-24", "2024-25", "2025-26"]


def _synthetic(n_players: int = 30, n_gws: int = 10, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for season in SEASONS:
        for gw in range(1, n_gws + 1):
            for element in range(1, n_players + 1):
                rows.append({"season": season, "gw": gw, "element": element})
    df = pd.DataFrame(rows)
    df["fixture"] = df["gw"] * 100 + df["element"] % 10
    df["name"] = "p" + df["element"].astype(str)
    df["team"] = "T" + (df["element"] % 10).astype(str)
    df["position"] = np.array(["GK", "DEF", "MID", "FWD"])[df["element"] % 4]
    for f in config.FEATURES:
        if f not in ("position", "gw"):
            df[f] = rng.normal(size=len(df))
    df["minutes_r3"] = rng.choice([0.0, 30.0, 90.0, np.nan], size=len(df))
    df["y"] = np.clip(2 + 2 * df["pts_r5"] + rng.normal(size=len(df)), 0, None).round()
    return train.add_regular_flag(df)


def _key(season: str, gw: int) -> int:
    return int(season[:4]) * 100 + gw


# --- folds ----------------------------------------------------------------------------------


def test_every_training_fold_is_strictly_before_the_test_gw():
    df = _synthetic()
    seen = []
    for k, train_mask, test_mask in walk_forward.folds(df, "2025-26", list(range(5, 11))):
        tr, te = df[train_mask], df[test_mask]
        assert set(te["season"]) == {"2025-26"} and set(te["gw"]) == {k}
        assert train.gw_order(tr).max() < _key("2025-26", k)
        # expanding window: every earlier season plus all target-season GWs before k
        assert set(tr["season"]) == set(SEASONS)
        assert set(tr.loc[tr.season == "2025-26", "gw"]) == set(range(1, k))
        assert not (train_mask & test_mask).any()
        seen.append(k)
    assert seen == list(range(5, 11))


def test_folds_step_and_train_from():
    df = _synthetic()
    ks = [k for k, _, _ in walk_forward.folds(df, "2025-26", list(range(5, 11)), step=2)]
    assert ks == [5, 7, 9]
    for _, train_mask, _ in walk_forward.folds(df, "2025-26", [6], train_from="2024-25"):
        assert set(df.loc[train_mask, "season"]) == {"2024-25", "2025-26"}


def test_folds_skip_missing_gw():
    df = _synthetic()
    df = df[~((df.season == "2025-26") & (df.gw == 7))]  # e.g. 2022-23 had no GW7
    assert 7 not in [k for k, _, _ in walk_forward.folds(df, "2025-26", list(range(5, 11)))]


def test_early_stopping_set_is_last_gws_of_window():
    df = _synthetic()
    window = df[train.gw_order(df) < _key("2025-26", 3)]
    fit, valid = train.split_early_stopping(window, n_gws=3)
    assert set(zip(valid.season, valid.gw, strict=True)) == {
        ("2024-25", 10),
        ("2025-26", 1),
        ("2025-26", 2),
    }
    assert train.gw_order(fit).max() < train.gw_order(valid).min()
    assert len(fit) + len(valid) == len(window)


def test_walk_forward_predictions_end_to_end():
    df = _synthetic(n_players=40)
    preds = walk_forward.run_walk_forward(
        df, models=("b0", "ridge", "lgbm"), target_season="2025-26", gws=[8, 9]
    )
    assert set(preds["gw"]) == {8, 9}
    assert {"pred_b0", "pred_ridge", "pred_lgbm", "train_last"} <= set(preds.columns)
    assert preds.loc[preds.gw == 8, "train_last"].iloc[0] == "2025-26 GW7"
    assert preds[["pred_ridge", "pred_lgbm"]].notna().all().all()


def test_walk_forward_checkpoints_resume(tmp_path, monkeypatch):
    df = _synthetic()
    first = walk_forward.run_walk_forward(
        df, models=("b0",), target_season="2025-26", gws=[6, 7], checkpoint_dir=tmp_path
    )
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gw06.parquet", "gw07.parquet"]

    def boom(*args, **kwargs):
        raise AssertionError("fold recomputed despite checkpoint")

    monkeypatch.setattr(walk_forward, "predict_fold", boom)
    again = walk_forward.run_walk_forward(
        df, models=("b0",), target_season="2025-26", gws=[6, 7], checkpoint_dir=tmp_path
    )
    pd.testing.assert_frame_equal(first, again)


def test_regular_flag_uses_lagged_minutes_and_nan_is_false():
    df = pd.DataFrame({"minutes_r3": [90.0, 45.0, 44.9, np.nan]})
    assert train.add_regular_flag(df)["regular"].tolist() == [True, True, False, False]


def test_lgbm_frame_position_codes_are_fixed():
    a = train.lgbm_frame(pd.DataFrame({"position": ["FWD", "GK"]}), ["position"])
    b = train.lgbm_frame(pd.DataFrame({"position": ["MID"]}), ["position"])
    assert list(a["position"].cat.categories) == list(b["position"].cat.categories)
    assert a["position"].cat.codes.tolist() == [3, 0]


# --- metrics --------------------------------------------------------------------------------


def test_top_k_precision_known_example():
    y = np.array([10, 9, 8, 1, 0, 0])
    pred = np.array([5.0, 0.1, 4.0, 3.0, 0.0, 0.0])
    # predicted top 3 = idx 0, 2, 3 -> actual 10, 8, 1; actual top-3 threshold = 8 -> 2/3
    assert evaluate.top_k_precision(y, pred, k=3) == pytest.approx(2 / 3)
    assert evaluate.top_k_precision(y, y.astype(float), k=3) == 1.0


def test_top_k_precision_counts_ties_at_threshold():
    y = np.array([6, 2, 2, 2, 0])
    pred = np.array([1.0, 0.9, 0.0, 0.0, 0.8])  # picks 6, 2, 0; threshold (2nd best) = 2
    assert evaluate.top_k_precision(y, pred, k=2) == 1.0
    assert evaluate.top_k_precision(y, pred, k=3) == pytest.approx(2 / 3)


def test_bootstrap_ci_contains_point_estimate():
    rng = np.random.default_rng(1)
    n = 3000
    df = pd.DataFrame(
        {
            "season": "2025-26",
            "gw": rng.integers(5, 39, size=n),
            "y": rng.poisson(3, size=n).astype(float),
        }
    )
    df["pred_b0"] = df["y"] + rng.normal(scale=2.0, size=n)
    df["pred_m"] = df["y"] + rng.normal(scale=1.8, size=n)
    point, lo, hi = evaluate.bootstrap_gain_ci(df, "pred_m", n_reps=500)
    assert lo <= point <= hi
    expected = evaluate.gain_pct(evaluate.mae(df.y, df.pred_b0), evaluate.mae(df.y, df.pred_m))
    assert point == pytest.approx(expected)
    assert lo > 0  # a clearly better model has a CI above 0


def test_bootstrap_identical_models_give_zero():
    df = pd.DataFrame({"season": "s", "gw": [1, 1, 2, 2], "y": [1.0, 2, 3, 4]})
    df["pred_b0"] = df["pred_m"] = [0.0, 1, 1, 2]
    assert evaluate.bootstrap_gain_ci(df, "pred_m", n_reps=50) == (0.0, 0.0, 0.0)


def test_player_gw_sums_double_gameweek():
    preds = pd.DataFrame(
        {
            "season": "2025-26",
            "gw": [5, 5, 5],
            "element": [1, 1, 2],
            "fixture": [10, 11, 12],
            "position": ["MID", "MID", "DEF"],
            "regular": [True, True, False],
            "y": [3.0, 7.0, 1.0],
            "pred_b0": [2.0, 2.0, 1.0],
        }
    )
    out = evaluate.to_player_gw(preds).set_index("element")
    assert out.loc[1, "y"] == 10.0 and out.loc[1, "pred_b0"] == 4.0
    assert out.loc[1, "n_fixtures"] == 2 and out.loc[2, "n_fixtures"] == 1


def test_summarise_structure():
    df = _synthetic()
    df["pred_b0"] = df["pts_r5"]
    df["pred_lgbm"] = 2 + 2 * df["pts_r5"]
    s = evaluate.summarise(evaluate.to_player_gw(df))
    assert {"all", "regulars", "regulars_by_position"} <= set(s)
    assert "mae_gain_pct" not in s["regulars"]["b0"]
    lo, hi = s["regulars"]["lgbm"]["mae_gain_ci95"]
    assert lo <= s["regulars"]["lgbm"]["mae_gain_pct"] <= hi
    assert s["regulars"]["lgbm"]["mae"] < s["regulars"]["b0"]["mae"]
    assert set(s["regulars_by_position"]) == {"GK", "DEF", "MID", "FWD"}
    table = evaluate.metrics_table(s)
    assert len(table) == 4


def test_calibration_deciles():
    df = pd.DataFrame({"y": np.arange(100.0), "pred": np.arange(100.0)})
    cal = evaluate.calibration(df, "pred")
    assert len(cal) == 10 and cal["n"].sum() == 100
    assert np.allclose(cal["mean_pred"], cal["mean_actual"])


# --- real lake ------------------------------------------------------------------------------


@pytest.mark.data
def test_real_walk_forward_folds(feature_store):
    df = train.load_features(feature_store)
    assert len(df) == 253_578
    assert df["regular"].dtype == bool
    ks = []
    for k, train_mask, test_mask in walk_forward.folds(df):
        assert train.gw_order(df[train_mask]).max() < _key(config.TARGET_SEASON, k)
        assert set(df.loc[test_mask, "gw"]) == {k}
        ks.append(k)
    assert ks == config.EVAL_GWS
