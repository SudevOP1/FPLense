"""ETL schema tests.

Pure-logic tests run on small in-memory frames. ``@pytest.mark.data`` tests check the real lake
built by ``python -m fPLense.pipeline --refresh-history`` and skip when it's absent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fPLense import config
from fPLense.etl import load_history
from fPLense.etl.normalize import (
    COLUMNS,
    derive_scores,
    normalize_season,
    parse_bool,
    remap_gw,
)

# --- synthetic season ----------------------------------------------------------------------
# Two teams (1 = Arsenal, 2 = Burnley), two fixtures: fixture 1 Arsenal (h) v Burnley in GW 29,
# fixture 2 Burnley (h) v Arsenal in GW 39 (COVID numbering). Element 11 ends the season at
# Burnley in players_raw but played fixture 1 for Arsenal, so team must come from the fixture.


def _rows():
    base = {
        "kickoff_time_formatted": "x",
        "ea_index": 0,
        "loaned_in": 0,
        "loaned_out": 0,
        "xP": 3.2,
        "mng_win": 0,
        "round": 0,
        "bonus": 0,
        "bps": 5,
        "selected": 1000,
        "transfers_in": 1,
        "transfers_out": 2,
        "transfers_balance": -1,
    }
    rows = []
    # fixture 1: Arsenal 2-1 Burnley
    for el, home in [(10, "True"), (11, "True"), (20, "False"), (21, "False")]:
        rows.append(
            {
                **base,
                "name": f"p{el}",
                "element": el,
                "fixture": 1,
                "was_home": home,
                "opponent_team": 2 if home == "True" else 1,
                "team_h_score": 2,
                "team_a_score": 1,
                "kickoff_time": "2020-03-01T15:00:00Z",
                "GW": 29,
                "minutes": 90,
                "total_points": 6,
                "value": 55,
            }
        )
    # fixture 2: Burnley 0-3 Arsenal, numbered GW 39
    for el, home in [(10, "False"), (20, "True"), (21, "True")]:
        rows.append(
            {
                **base,
                "name": f"p{el}",
                "element": el,
                "fixture": 2,
                "was_home": home,
                "opponent_team": 2 if home == "False" else 1,
                "team_h_score": 0,
                "team_a_score": 3,
                "kickoff_time": "2020-06-20T15:00:00Z",
                "GW": 39,
                "minutes": 0,
                "total_points": 0,
                "value": 60,
            }
        )
    return pd.DataFrame(rows)


PLAYERS_RAW = pd.DataFrame(
    {"id": [10, 11, 20, 21], "element_type": [1, 3, 2, 4], "team": [1, 2, 2, 2]}
)
MASTER = pd.DataFrame(
    {
        "season": ["2019-20", "2019-20"],
        "team": [1, 2],
        "team_name": ["Arsenal", "Burnley"],
    }
)


@pytest.fixture
def season_df():
    return normalize_season(
        _rows(), season="2019-20", players_raw=PLAYERS_RAW, master_team_list=MASTER
    )


def test_remap_gw_covid_season():
    gw = pd.Series(list(range(1, 30)) + list(range(39, 48)))
    out = remap_gw(gw, "2019-20")
    assert out.tolist() == list(range(1, 39))


def test_remap_gw_other_seasons_unchanged():
    gw = pd.Series([1, 29, 38])
    assert remap_gw(gw, "2020-21").tolist() == [1, 29, 38]


def test_gw_remapped_in_normalized_frame(season_df):
    assert season_df.loc[season_df["fixture"] == 2, "gw"].unique().tolist() == [30]
    assert season_df["gw"].between(1, 38).all()


def test_missing_columns_are_nan_not_zero(season_df):
    for col in [
        "expected_goals",
        "expected_assists",
        "expected_goal_involvements",
        "expected_goals_conceded",
        "starts",
        "defensive_contribution",
        "clearances_blocks_interceptions",
        "recoveries",
        "tackles",
        "team_h_difficulty",
        "team_a_difficulty",
    ]:
        assert season_df[col].isna().all(), col
        assert season_df[col].dtype == np.float64, col


def test_present_zero_stays_zero(season_df):
    # bonus exists in the source with value 0: must stay 0, not become NaN
    assert (season_df["bonus"] == 0).all()


def test_derive_scores():
    df = pd.DataFrame({"was_home": [True, False], "team_h_score": [2, 2], "team_a_score": [1, 1]})
    out = derive_scores(df)
    assert out["team_score"].tolist() == [2, 1]
    assert out["opp_score"].tolist() == [1, 2]


def test_scores_in_normalized_frame(season_df):
    f2 = season_df[season_df["fixture"] == 2].set_index("element")
    assert f2.loc[10, "team_score"] == 3 and f2.loc[10, "opp_score"] == 0  # Arsenal away
    assert f2.loc[20, "team_score"] == 0 and f2.loc[20, "opp_score"] == 3  # Burnley home


def test_dropped_columns(season_df):
    for col in ["xP", "mng_win", "kickoff_time_formatted", "ea_index", "loaned_in", "loaned_out"]:
        assert col not in season_df.columns
    assert season_df.columns.tolist() == COLUMNS


def test_position_and_team_joined(season_df):
    by_el = season_df.drop_duplicates("element").set_index("element")
    assert by_el["position"].to_dict() == {10: "GK", 11: "MID", 20: "DEF", 21: "FWD"}
    # element 11 was Arsenal's (home side) in fixture 1, though players_raw says Burnley
    assert by_el.loc[11, "team"] == "Arsenal"
    assert by_el.loc[20, "team"] == "Burnley"
    assert by_el.loc[20, "opponent_team_name"] == "Arsenal"


def test_team_from_fixtures_csv():
    fixtures = pd.DataFrame(
        {
            "id": [1, 2],
            "team_h": [1, 2],
            "team_a": [2, 1],
            "team_h_difficulty": [2, 4],
            "team_a_difficulty": [3, 2],
        }
    )
    df = normalize_season(
        _rows(),
        season="2019-20",
        players_raw=PLAYERS_RAW,
        master_team_list=MASTER,
        fixtures=fixtures,
    )
    f1 = df[df["fixture"] == 1].set_index("element")
    assert f1.loc[11, "team"] == "Arsenal" and f1.loc[20, "team"] == "Burnley"
    assert f1["team_h_difficulty"].eq(2).all()


def test_team_names_fall_back_to_teams_csv():
    teams = pd.DataFrame({"id": [1, 2], "name": ["Arsenal", "Burnley"]})
    df = normalize_season(
        _rows(),
        season="2025-26",
        players_raw=PLAYERS_RAW,
        master_team_list=MASTER,  # has no 2025-26 rows
        teams=teams,
    )
    assert set(df["team"]) == {"Arsenal", "Burnley"}


def test_non_player_positions_dropped():
    rows = _rows()
    rows["position"] = ["GK", "MID", "AM", "FWD", "GKP", "AM", "FWD"]
    df = normalize_season(rows, season="2019-20", players_raw=PLAYERS_RAW, master_team_list=MASTER)
    assert len(df) == 5
    assert set(df["position"]) <= {"GK", "DEF", "MID", "FWD"}
    assert (df.loc[df["element"] == 10, "position"] == "GK").all()  # GKP alias


def test_price_is_value_over_ten(season_df):
    assert np.allclose(season_df["price"], season_df["value"] / 10)
    assert season_df["value"].dtype == np.int64


def test_was_home_parsed_from_strings():
    assert parse_bool(pd.Series(["True", "false", " TRUE "])).tolist() == [True, False, True]
    with pytest.raises(ValueError):
        parse_bool(pd.Series(["maybe"]))


def test_kickoff_is_utc_timestamp(season_df):
    assert str(season_df["kickoff_time"].dt.tz) == "UTC"


def test_season_files():
    assert load_history.season_files("2016-17") == ["gws/merged_gw.csv", "players_raw.csv"]
    assert "fixtures.csv" in load_history.season_files("2018-19")
    assert "teams.csv" in load_history.season_files("2025-26")


# --- real lake -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lake(lake_dir):
    return load_history.read_player_match()


@pytest.mark.data
@pytest.mark.parametrize("season", config.SEASONS)
def test_raw_row_counts_match_plan(lake_dir, season):
    raw = load_history.read_csv(load_history.raw_path(season, "gws/merged_gw.csv"))
    assert len(raw) == config.EXPECTED_ROWS[season]


@pytest.mark.data
def test_raw_total_rows(lake_dir):
    total = sum(
        len(load_history.read_csv(load_history.raw_path(s, "gws/merged_gw.csv")))
        for s in config.SEASONS
    )
    assert total == 253_900


@pytest.mark.data
def test_lake_has_all_seasons(lake):
    assert sorted(lake["season"].unique()) == config.SEASONS


@pytest.mark.data
def test_lake_rows_are_raw_minus_non_players(lake):
    # only 2024-25 assistant-manager rows (position "AM") are removed
    counts = lake["season"].value_counts()
    for season in config.SEASONS:
        expected = config.EXPECTED_ROWS[season] - (322 if season == "2024-25" else 0)
        assert counts[season] == expected, season
    assert len(lake) >= 250_000


@pytest.mark.data
def test_lake_required_columns(lake):
    assert set(COLUMNS) <= set(lake.columns)


@pytest.mark.data
def test_lake_positions_valid(lake):
    assert lake["position"].notna().all()
    assert set(lake["position"].astype(str).unique()) == {"GK", "DEF", "MID", "FWD"}


@pytest.mark.data
def test_lake_gw_range(lake):
    assert lake["gw"].between(1, 38).all()
    # every GW has fixtures except 2022-23 GW7 (whole round postponed after the Queen's death)
    for season, gws in lake.groupby("season")["gw"]:
        missing = set(range(1, 39)) - set(gws)
        assert missing == ({7} if season == "2022-23" else set()), season


@pytest.mark.data
def test_lake_380_fixtures_per_season(lake):
    assert lake.groupby("season")["fixture"].nunique().eq(380).all()


@pytest.mark.data
def test_lake_teams_known(lake):
    assert lake["team"].notna().all()
    assert lake["opponent_team_name"].notna().all()
    assert lake.groupby("season")["team"].nunique().eq(20).all()


@pytest.mark.data
def test_lake_missing_stats_nan_in_old_seasons(lake):
    old = lake[lake["season"] < "2022-23"]
    assert old["expected_goals"].isna().all()
    new = lake[lake["season"] >= "2022-23"]
    assert new["expected_goals"].notna().all()
    assert lake.loc[lake["season"] < "2025-26", "defensive_contribution"].isna().all()


@pytest.mark.data
def test_lake_two_sides_per_fixture(lake):
    sides = lake.groupby(["season", "fixture"])["team"].nunique()
    assert sides.eq(2).all()


def test_read_csv_handles_utf8_and_latin1(tmp_path):
    utf8 = tmp_path / "utf8.csv"
    utf8.write_bytes("name\nJosé\n".encode())
    latin = tmp_path / "latin.csv"
    latin.write_bytes("name\nJosé\n".encode("latin-1"))
    assert load_history.read_csv(utf8)["name"].tolist() == ["José"]
    assert load_history.read_csv(latin)["name"].tolist() == ["José"]
