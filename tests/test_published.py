"""Pure helpers in `fPLense.published` (reused by the FastAPI backend)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from pools import random_pool

from fPLense import config, published
from fPLense.optimize.squad_ilp import check_squad, pick_squad

LATEST = {"gws": [6, 7, 8], "discount": 0.9}
NOW = pd.Timestamp("2026-10-08T12:00:00Z")


def table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "element": [1, 2, 3, 4],
            "web_name": ["Haaland", "Saka", "Gabriel", "Raya"],
            "name": ["Erling Haaland", "Bukayo Saka", "Gabriel dos Santos", "David Raya"],
            "pos": ["FWD", "MID", "DEF", "GK"],
            "club": ["Man City", "Arsenal", "Arsenal", "Arsenal"],
            "price": [150, 100, 60, 55],
            "minutes_r3": [90.0, 75.0, np.nan, 90.0],
            "p_gw06": [5.0, 4.0, 3.0, 2.0],
            "p_gw07": [6.0, 0.0, 3.0, 2.0],
            "p_gw08": [4.0, 4.0, 3.0, 2.0],
        }
    )


def test_with_horizon_recomputes_p_h():
    out = published.with_horizon(table(), LATEST, 2)
    assert out.loc[0, "P_h"] == pytest.approx(5.0 + 0.9 * 6.0)
    assert out.loc[1, "P_h"] == pytest.approx(4.0)  # blank GW7
    assert (out["p1"] == out["p_gw06"]).all()
    one = published.with_horizon(table(), LATEST, 1)
    assert (one["P_h"] == one["p_gw06"]).all()


def test_filter_projections():
    df = table()
    f = published.filter_projections
    assert f(df, positions=["MID", "FWD"])["element"].tolist() == [1, 2]
    assert f(df, clubs=["Arsenal"])["element"].tolist() == [2, 3, 4]
    assert f(df, price_range=(5.5, 10.0))["element"].tolist() == [2, 3, 4]
    assert f(df, min_minutes_r3=80)["element"].tolist() == [1, 4]  # NaN minutes count as 0
    assert f(df, search="dos")["element"].tolist() == [3]  # matches the full name too
    assert len(f(df)) == 4


def test_waterfall_data_sums_to_prediction():
    row = pd.Series(
        {
            "element": 1,
            "base_value": 1.2,
            **{f"shap_f{i}": v for i, v in enumerate([0.5, -0.3, 0.05, 0.02, -0.01])},
            "val_f0": 90.0,
        }
    )
    wf = published.waterfall_data(row, k=2)
    assert wf["feature"].tolist() == ["f0", "f1", "3 other features"]
    assert wf["shap"].sum() == pytest.approx(0.5 - 0.3 + 0.05 + 0.02 - 0.01)
    assert wf.loc[0, "value"] == 90.0


def test_time_helpers():
    assert published.time_until("2026-10-10T10:00:00Z", NOW) == "1d 22h"
    assert published.time_until("2026-10-08T13:30:00Z", NOW) == "1h 30m"
    assert published.time_until("2026-10-08T11:00:00Z", NOW) == "passed"
    assert published.time_until(None, NOW) == "n/a"
    assert published.age("2026-10-08T09:00:00+00:00", NOW) == "3h ago"
    assert published.age("2026-10-05T12:00:00+00:00", NOW) == "3d ago"


def test_squad_table_and_pitch_lines():
    pool = random_pool(200, seed=3)
    pool = pool.assign(web_name=[f"p{i}" for i in pool.index], club_short=pool["club"])
    res = pick_squad(pool)
    assert check_squad(pool, res) == []
    t = published.squad_table(pool, res)
    assert len(t) == 15 and t["starter"].sum() == 11
    assert t["captain"].sum() == 1 and t["vice"].sum() == 1
    lines = published.pitch_lines(t)
    assert sum(len(lines[p]) for p in published.POSITIONS) == 11
    assert len(lines["GK"]) == 1
    assert [p["bench"] for p in lines["bench"]] == [1, 2, 3, 4]
    assert lines["bench"][-1]["pos"] == "GK"


def test_squad_pool_from_predictions():
    df = table().assign(
        p1=1.0, P_h=2.0, status="a", chance_of_playing_next_round=np.nan, club_short="X"
    )
    pool = published.squad_pool(df)
    assert pool.index.tolist() == [1, 2, 3, 4]
    assert pool["price"].dtype.kind == "i"


def test_picks_summary_marks_unknown_players():
    df = table().assign(p1=1.0, P_h=2.0, status="a", club_short="X")
    picks = {"squad": [1, 2, 999]}
    s = published.picks_summary(picks, df)
    assert s["name"].tolist() == ["Haaland", "Saka", "999"]
    assert np.isnan(s.loc[2, "p1"])


def test_metrics_rows_and_headline_from_published_metrics():
    path = config.METRICS_PATH
    if not path.exists():
        pytest.skip("data/published/metrics.json not built")
    metrics = json.loads(path.read_text(encoding="utf-8"))
    rows = published.metrics_rows(metrics)
    assert rows["model"].tolist()[0] == "B0 rolling form"
    assert rows.loc[0, "gain vs B0"] == "baseline"
    head = published.headline(metrics)
    lgbm = metrics["walk_forward"]["regulars"]["lgbm"]
    assert head["gain_pct"] == lgbm["mae_gain_pct"]
    assert head["ci"][0] <= head["gain_pct"] <= head["ci"][1]
    assert published.headline(None) is None
