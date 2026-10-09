"""Season-history archive: write-once folders, as-of backfill = features from the truncated
lake, the refusal when the model saw the season, source labels, actuals and summaries."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from test_predict import ELO_MODEL, PLAYERS, SEASON, TEAMS, elo_frame, fixtures_frame, history_frame

from fPLense import config
from fPLense.db.build import build, features
from fPLense.models import history, predict

FEATURES_NO_GW = [f for f in config.FEATURES]


def archive_table(gw: int = 6) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "element": [1, 2],
            "code": [11, 22],
            "web_name": ["A", "B"],
            "pos": ["MID", "DEF"],
            "club": ["Arsenal", "Spurs"],
            "club_short": ["ARS", "TOT"],
            "price": [80, 45],
            f"p_gw{gw:02d}": [5.0, 2.0],
            "P_h": [20.0, 8.0],
            "availability": [1.0, 0.5],
        }
    )


SQUAD = {"gw": 6, "gws": [6, 7], "captain": 1, "vice": 2, "cost": 125, "players": []}
MODEL_META = {"model_sha256": "abc", "train_max_season": "2025-26"}


# --- write-once archive -----------------------------------------------------------------------


def test_archive_is_write_once(tmp_path):
    frame = history.archive_frame(archive_table(), 6)
    meta = {"made_at": "2026-10-08T16:45:00+00:00", "source": "live"}
    d = history.write_archive(6, frame, SQUAD, meta, tmp_path)
    assert (d / "predictions.parquet").exists() and (d / "squad_pred.json").exists()
    with pytest.raises(history.ArchiveExistsError):
        history.write_archive(6, frame.assign(p=99.0), SQUAD, meta, tmp_path)
    assert history.read_archive(6, tmp_path)["predictions"]["p"].tolist() == [5.0, 2.0]
    history.write_archive(6, frame.assign(p=99.0), SQUAD, meta, tmp_path, force=True)
    assert history.read_archive(6, tmp_path)["predictions"]["p"].tolist() == [99.0, 99.0]
    assert history.archived_gws(tmp_path) == [6]


def test_archive_live_never_overwrites(tmp_path):
    first = history.archive_live(archive_table(), SQUAD, 6, "t1", MODEL_META, tmp_path)
    assert first is not None
    again = history.archive_live(
        archive_table().assign(p_gw06=0.0), SQUAD, 6, "t2", MODEL_META, tmp_path
    )
    assert again is None
    a = history.read_archive(6, tmp_path)
    assert a["meta"]["made_at"] == "t1" and a["meta"]["source"] == "live"
    assert a["meta"]["model_train_max_season"] == "2025-26"
    assert a["predictions"]["p"].tolist() == [5.0, 2.0]


def test_source_label_is_checked(tmp_path):
    frame = history.archive_frame(archive_table(), 6)
    with pytest.raises(ValueError, match="source"):
        history.write_archive(6, frame, SQUAD, {"source": "guess"}, tmp_path)
    with pytest.raises(ValueError, match="missing"):
        history.write_archive(6, frame.drop(columns="code"), SQUAD, {"source": "live"}, tmp_path)


def test_backfill_refused_when_the_model_saw_the_season():
    history.check_backfill_allowed("2025-26")
    for season in ("2026-27", "2027-28"):
        with pytest.raises(history.BackfillRefusedError, match="seen"):
            history.check_backfill_allowed(season)


def test_model_meta_must_match_the_model(tmp_path):
    model = tmp_path / "model.txt"
    model.write_text("tree 1")
    meta = tmp_path / "model_meta.json"
    history.write_model_meta("2025-26", model, meta, trees=1)
    assert history.read_model_meta(model, meta)["train_max_season"] == "2025-26"
    model.write_text("tree 2")  # retrained without updating the meta
    with pytest.raises(RuntimeError, match="different model"):
        history.read_model_meta(model, meta)
    with pytest.raises(FileNotFoundError):
        history.read_model_meta(model, tmp_path / "nope.json")


# --- as-of backfill ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def season():
    fx = fixtures_frame()
    return {
        "fx": fx,
        "history": history_frame(fx),
        "names": pd.read_csv(config.TEAM_NAMES_PATH),
        "elo": elo_frame(),
        "players": PLAYERS.assign(
            code=PLAYERS["element"] + 1000,
            team=PLAYERS["team_id"].map(TEAMS.set_index("team_id")["team"]),
            team_short=PLAYERS["team_id"].map(TEAMS.set_index("team_id")["team_short"]),
            news="",
            selected_by_percent=1.0,
            season_minutes=270,
            season_points=10,
        ),
    }


def backfill_rows(s, history_rows: pd.DataFrame, gw: int, played_odds=None) -> pd.DataFrame:
    inp = history.backfill_inputs(
        history_rows, s["fx"], played_odds, s["elo"], s["names"], ELO_MODEL, gw, [gw]
    )
    players = history.players_at(s["players"], history_rows, TEAMS, gw)
    return predict.horizon_features(
        inp["history"], players, s["fx"], TEAMS, [gw], inp["odds"], inp["elo"]
    ).sort_values(["fixture", "element"], ignore_index=True)


def full_lake_rows(s, tmp_path, gw: int) -> pd.DataFrame:
    """``v_features`` for GW ``gw`` from the lake with every played GW in it (no truncation)."""
    played = s["fx"][s["fx"]["finished"]]
    odds, _ = predict.upcoming_odds(played, pd.DataFrame(), ELO_MODEL, s["elo"], s["names"])
    root = predict.write_temp_lake(tmp_path, s["history"], s["history"].iloc[:0], odds, s["elo"])
    con = build(":memory:", lake_dir=root)
    try:
        rows = features(con, f"season = '{SEASON}' and gw = {gw}")
    finally:
        con.close()
    return rows.sort_values(["fixture", "element"], ignore_index=True)


@pytest.mark.parametrize("gw", [2, 3])
def test_backfill_equals_features_of_the_full_lake(season, tmp_path, gw):
    """The as-of rebuild (lake truncated before GW k + GW k's fixtures blanked) gives exactly
    the features the full lake gives for GW k: the backfill sees what the model would have."""
    back = backfill_rows(season, season["history"], gw)
    full = full_lake_rows(season, tmp_path, gw)
    assert len(back) == len(full) > 0
    assert back["y"].isna().all() and full["y"].notna().all()
    for f in config.FEATURES:
        a, b = back[f], full[f]
        if f == "position":
            assert a.astype(str).tolist() == b.astype(str).tolist()
        else:
            np.testing.assert_allclose(
                pd.to_numeric(a, errors="coerce").astype(float),
                pd.to_numeric(b, errors="coerce").astype(float),
                equal_nan=True,
                err_msg=f,
            )


def test_backfill_ignores_later_outcomes_but_not_earlier_ones(season):
    base = backfill_rows(season, season["history"], 3)
    later = season["history"].copy()
    later.loc[later["gw"] >= 3, "total_points"] = 50  # what happened in GW3 itself
    assert backfill_rows(season, later, 3)[config.FEATURES].equals(base[config.FEATURES])
    earlier = season["history"].copy()
    earlier.loc[earlier["gw"] == 2, "total_points"] = 50
    changed = backfill_rows(season, earlier, 3)
    assert not changed["pts_last1"].equals(base["pts_last1"])


def test_backfill_odds_only_for_the_gws_own_round(season):
    fx = season["fx"]
    from fPLense.etl.load_odds import clean_odds

    fd = clean_odds(
        pd.DataFrame(
            {
                "Div": ["E0", "E0"],
                "Date": ["05/09/2026", "12/09/2026"],
                "HomeTeam": ["Arsenal", "Liverpool"],  # GW3 fixture 5 and GW4 fixture 7
                "AwayTeam": ["Liverpool", "Arsenal"],
                "AvgH": [2.0, 2.5],
                "AvgD": [3.4, 3.4],
                "AvgA": [3.6, 2.8],
                "Avg>2.5": [1.8, 1.8],
                "Avg<2.5": [2.0, 2.0],
            }
        )
    )
    inp = history.backfill_inputs(
        season["history"], fx, fd, season["elo"], season["names"], ELO_MODEL, 3, [3, 4]
    )
    src = inp["sources"].set_index("fixture")["odds_source"]
    assert src[5] == "avg"  # GW3's own round: bookmaker odds known before the deadline
    assert src[7] == "elo"  # GW4: its odds weren't published yet at the GW3 deadline
    cutoff = history.gw_start_date(fx, 3)
    assert (pd.to_datetime(inp["elo"]["date"]) < cutoff).all()
    assert inp["history"]["gw"].max() == 2


def test_players_at_takes_club_and_price_from_that_gw(season):
    h = season["history"].copy()
    h.loc[(h["element"] == 11) & (h["gw"] == 2), "value"] = 85
    h = h[~((h["element"] == 42) & (h["gw"] < 3))]  # player 42 only appears from GW3
    p = history.players_at(season["players"], h, TEAMS, 2).set_index("element")
    assert p.at[11, "now_cost"] == 85 and p.at[11, "team"] == "Arsenal"
    assert 42 not in p.index
    assert (p["status"] == "a").all() and p["chance_of_playing_next_round"].isna().all()


# --- actuals, summaries -----------------------------------------------------------------------


def test_actuals_sum_a_double_gameweek():
    h = pd.DataFrame(
        {
            "element": [1, 1, 2],
            "gw": [5, 5, 5],
            "fixture": [9, 10, 9],
            "kickoff_time": pd.to_datetime(["2026-09-19", "2026-09-22", "2026-09-19"], utc=True),
            "total_points": [6, 2, 0],
            "minutes": [90, 0, 0],
            "value": [80, 81, 45],
            "position": ["MID", "MID", "DEF"],
            "team_id": [1, 1, 2],
            "team": ["Arsenal", "Arsenal", "Chelsea"],
        }
    )
    a = history.actuals(h).set_index("element")
    assert a.at[1, "total_points"] == 8 and a.at[1, "fixtures"] == 2
    assert a.at[1, "fixtures_played"] == 1 and a.at[1, "price"] == 80
    assert a.at[2, "fixtures_played"] == 0


def test_summary_row_and_capture_ratio():
    players = [
        {
            "element": i,
            "pos": "GK" if i in (1, 2) else "DEF" if i < 8 else "MID" if i < 13 else "FWD",
            "starter": i not in (2, 7, 12, 15),
            "bench_order": None,
        }
        for i in range(1, 16)
    ]
    for k, i in enumerate((12, 15, 7, 2)):
        players[i - 1]["bench_order"] = k + 1
    squad = {"captain": 13, "vice": 14, "cost": 990, "players": players}
    act = pd.DataFrame(
        {
            "element": range(1, 16),
            "gw": 4,
            "total_points": [2] * 15,
            "minutes": [90] * 15,
            "pos": [p["pos"] for p in players],
        }
    )
    act.loc[act["element"] == 3, ["total_points", "minutes"]] = [0, 0]  # sub comes on
    preds = pd.DataFrame({"element": range(1, 16), "p": [1.0] * 15})
    archive = {"squad": squad, "predictions": preds, "meta": {"source": "backfill"}}
    hind = {"points": 40, "cost": 1000, "squad": list(range(1, 16))}
    row = history.summary_row(
        4, archive, hind, act, {"average_entry_score": 50, "highest_score": 120}
    )
    assert row["model_actual"] == 2 * 10 + 2 + 2  # 10 starters + 1 auto-sub, captain doubled
    assert row["model_expected"] == pytest.approx(12.0)  # 11 x 1.0 + captain 1.0
    assert row["capture_ratio"] == pytest.approx(24 / 40)
    assert row["source"] == "backfill" and row["shared_players"] == 15


def test_season_and_fixtures_docs():
    bootstrap = json.loads(
        (config.TESTS_FIXTURES_DIR / "bootstrap_static_sample.json").read_text(encoding="utf-8")
    )
    doc = history.season_doc(bootstrap)
    assert doc["events"] and all("average_entry_score" in e for e in doc["events"])
    fx = fixtures_frame()
    fdoc = history.fixtures_doc(fx, TEAMS)
    assert len(fdoc["fixtures"]) == len(fx)
    first = fdoc["fixtures"][0]
    assert first["team_h_short"] == "ARS" and first["team_h_difficulty"] == 3.0
    assert fdoc["fixtures"][-1]["team_h_score"] is None
