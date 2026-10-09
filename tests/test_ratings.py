"""Card ratings: the FPLense rating (EA FC ratings were dropped on 2026-10-09) and photo URLs."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from fPLense import config
from fPLense.etl import ratings


def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "element": [1, 2, 3, 4, 5, 6, 7],
            "code": [101, 102, 103, 104, 105, 106, 107],
            "pos": ["MID", "MID", "MID", "MID", "DEF", "DEF", "MID"],
            "P_h": [20.0, 10.0, 5.0, 0.0, 3.0, 9.0, 30.0],
            "status": ["a", "a", "a", "a", "a", "a", "i"],
            "availability": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0],
        }
    )


def test_rating_is_percentile_within_position():
    r = ratings.fplense_rating(frame())
    # available MIDs (1-4): ranks 0..3 of 3 -> 50 + 49 * {1, 2/3, 1/3, 0}
    assert r.tolist()[:4] == [99, 83, 66, 50]
    assert r[4] == 50 and r[5] == 99  # DEF ranked among DEFs only


def test_unavailable_player_placed_on_the_available_scale():
    r = ratings.fplense_rating(frame())
    assert r[6] == 99  # best P_h of all MIDs, injured: still rated against available MIDs
    low = frame().assign(P_h=[20.0, 10.0, 5.0, 0.0, 3.0, 9.0, 7.0])
    # 7.0 sits above 2 of the 3 others (0, 5): same 2/3 percentile as the 10.0 player
    assert ratings.fplense_rating(low)[6] == 83


def test_rating_range_and_ties():
    df = pd.DataFrame({"pos": ["FWD"] * 4, "P_h": [4.0, 4.0, 4.0, 1.0]})
    r = ratings.fplense_rating(df)
    assert r.between(50, 99).all()
    assert r[0] == r[1] == r[2] > r[3] == 50


def test_single_player_position_and_nan():
    df = pd.DataFrame({"pos": ["GK", "GK"], "P_h": [np.nan, 2.0], "status": ["a", "u"]})
    r = ratings.fplense_rating(df)
    assert r.dtype.kind == "i" and r.between(50, 99).all()


def test_photo_url_uses_code_not_id():
    url = ratings.photo_url(154561)
    assert url.endswith("/154561.png") and url.startswith("https://resources.premierleague.com/")
    assert ratings.photo_url(None) is None and ratings.photo_url(float("nan")) is None


def test_ratings_table_and_publish(tmp_path):
    df = frame()
    t = ratings.ratings_table(df)
    assert (t["rating_source"] == "fplense").all()
    assert t["photo_url"].str.contains("103.png").any()
    doc = ratings.publish_ratings(df, 6, tmp_path)
    saved = json.loads((tmp_path / config.RATINGS_PATH.name).read_text(encoding="utf-8"))
    assert saved == doc and saved["source"] == "fplense" and "not used" in saved["ea_fc"]
    assert saved["players"]["1"] == {"code": 101, "rating": 99}
