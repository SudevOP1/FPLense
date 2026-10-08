"""Live prediction path (PLAN.md §8 P5): GW sums, availability, the deadline gate, and feature
rows for upcoming fixtures built through the real DuckDB views on a synthetic current season."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fPLense import config
from fPLense.etl import elo_goals
from fPLense.etl.fetch_api import parse_fixtures
from fPLense.etl.normalize import COLUMNS, enforce_schema
from fPLense.models import predict

SEASON = config.CURRENT_SEASON

# --- gameweek sums and availability -----------------------------------------------------------


def test_gw_sum_over_double_gameweek():
    per_fixture = pd.DataFrame(
        {"element": [1, 1, 2, 1], "gw": [6, 6, 6, 7], "pred": [2.0, 3.0, 4.0, 1.5]}
    )
    wide = predict.gw_points(per_fixture, [1, 2], [6, 7])
    assert wide.loc[1, 6] == pytest.approx(5.0)  # two fixtures summed
    assert wide.loc[1, 7] == pytest.approx(1.5)


def test_blank_gameweek_is_zero():
    per_fixture = pd.DataFrame({"element": [1, 2], "gw": [6, 6], "pred": [2.0, 4.0]})
    wide = predict.gw_points(per_fixture, [1, 2, 3], [6, 7])
    assert wide.loc[2, 7] == 0.0  # no fixture in GW7
    assert (wide.loc[3] == 0.0).all()  # player with no fixture at all
    assert not wide.isna().any().any()
    assert predict.gw_points(per_fixture.iloc[:0], [1], [6]).loc[1, 6] == 0.0


def test_availability_scaling():
    players = pd.DataFrame(
        {"chance_of_playing_next_round": [75.0, 0.0, 100.0, 25.0], "status": ["d", "i", "a", "d"]}
    )
    assert predict.availability(players).tolist() == [0.75, 0.0, 1.0, 0.25]


def test_nan_availability_means_100_percent():
    players = pd.DataFrame({"chance_of_playing_next_round": [np.nan, None], "status": ["a", "a"]})
    assert predict.availability(players).tolist() == [1.0, 1.0]


def test_unavailable_status_is_zero_even_without_chance():
    players = pd.DataFrame({"chance_of_playing_next_round": [np.nan], "status": ["u"]})
    assert predict.availability(players).tolist() == [0.0]


# --- deadline gate ----------------------------------------------------------------------------

NOW = pd.Timestamp("2026-10-08T12:00:00Z")


@pytest.mark.parametrize(
    ("deadline", "published", "force", "due"),
    [
        ("2026-10-10T10:00:00Z", False, False, True),  # 46 h away, not published
        ("2026-10-10T13:00:00Z", False, False, False),  # 49 h away: too early
        ("2026-10-10T10:00:00Z", True, False, False),  # already published
        ("2026-10-08T11:00:00Z", False, False, False),  # deadline passed
        (None, False, False, False),  # season over
        ("2026-10-20T10:00:00Z", True, True, True),  # --force overrides everything
    ],
)
def test_should_refresh(deadline, published, force, due):
    ok, reason = predict.should_refresh(
        pd.Timestamp(deadline) if deadline else None, NOW, published, force
    )
    assert ok is due, reason
    assert reason


# --- synthetic current season -----------------------------------------------------------------
# Teams use real FPL names so the team-name map (and Elo club names) resolve.
TEAMS = pd.DataFrame(
    {
        "team_id": [1, 2, 3, 4],
        "team": ["Arsenal", "Chelsea", "Liverpool", "Spurs"],
        "team_short": ["ARS", "CHE", "LIV", "TOT"],
    }
)
# (fixture, gw, home, away, kickoff). GW1-3 played; GW4 upcoming; GW5: Arsenal and Chelsea play
# twice (double GW), Liverpool and Spurs blank.
SCHEDULE = [
    (1, 1, 1, 2, "2026-08-22T14:00Z"),
    (2, 1, 3, 4, "2026-08-22T16:30Z"),
    (3, 2, 2, 3, "2026-08-29T14:00Z"),
    (4, 2, 4, 1, "2026-08-29T16:30Z"),
    (5, 3, 1, 3, "2026-09-05T14:00Z"),
    (6, 3, 2, 4, "2026-09-05T16:30Z"),
    (7, 4, 3, 1, "2026-09-12T14:00Z"),
    (8, 4, 4, 2, "2026-09-12T16:30Z"),
    (9, 5, 1, 2, "2026-09-19T14:00Z"),
    (10, 5, 2, 1, "2026-09-22T19:00Z"),
]
PLAYED_GWS = {1, 2, 3}
PLAYERS = pd.DataFrame(
    {
        "element": [11, 12, 21, 22, 31, 32, 41, 42],
        "name": [f"Player {i}" for i in [11, 12, 21, 22, 31, 32, 41, 42]],
        "web_name": [f"P{i}" for i in [11, 12, 21, 22, 31, 32, 41, 42]],
        "position": ["MID", "DEF"] * 4,
        "team_id": [1, 1, 2, 2, 3, 3, 4, 4],
        "now_cost": [80, 50, 75, 45, 90, 55, 70, 40],
        "status": ["a"] * 8,
        "chance_of_playing_next_round": [np.nan] * 8,
    }
)


def fixtures_frame() -> pd.DataFrame:
    played = {f for f, gw, *_ in SCHEDULE if gw in PLAYED_GWS}
    raw = [
        {
            "id": f,
            "event": gw,
            "kickoff_time": ko,
            "team_h": h,
            "team_a": a,
            "team_h_difficulty": 3,
            "team_a_difficulty": 2,
            "team_h_score": 2 if f in played else None,
            "team_a_score": 1 if f in played else None,
            "finished": f in played,
        }
        for f, gw, h, a, ko in SCHEDULE
    ]
    return parse_fixtures(raw, TEAMS)


def history_frame(fx: pd.DataFrame) -> pd.DataFrame:
    """Played rows; player 11 scores 2, 4, 9 (GW1-3) so his form is easy to check."""
    points = {11: [2, 4, 9]}
    names = TEAMS.set_index("team_id")["team"]
    rows = []
    for f in fx[fx["finished"]].itertuples():
        for side, home in (("team_h", True), ("team_a", False)):
            team = getattr(f, side)
            opp = f.team_a if home else f.team_h
            for p in PLAYERS[PLAYERS["team_id"] == team].itertuples():
                pts = points.get(p.element, [1, 1, 1])[f.gw - 1]
                rows.append(
                    {
                        "season": SEASON,
                        "element": p.element,
                        "name": p.name,
                        "position": p.position,
                        "team_id": team,
                        "team": names[team],
                        "opponent_team": opp,
                        "opponent_team_name": names[opp],
                        "fixture": f.fixture,
                        "gw": f.gw,
                        "kickoff_time": f.kickoff_time,
                        "was_home": home,
                        "team_h_score": 2.0,
                        "team_a_score": 1.0,
                        "team_score": 2.0 if home else 1.0,
                        "opp_score": 1.0 if home else 2.0,
                        "team_h_difficulty": 3.0,
                        "team_a_difficulty": 2.0,
                        "minutes": 90,
                        "total_points": pts,
                        "bps": 10.0,
                        "value": p.now_cost,
                        "price": p.now_cost / 10,
                        "selected": 1000.0,
                        "transfers_balance": 10.0,
                    }
                )
    return enforce_schema(pd.DataFrame(rows))


def elo_frame() -> pd.DataFrame:
    dates = pd.date_range("2026-07-01", "2026-09-15", freq="SMS").date
    clubs = {"Arsenal": 1900, "Chelsea": 1800, "Liverpool": 1850, "Tottenham": 1750}
    return pd.DataFrame(
        [{"date": d, "club": c, "elo": float(e)} for d in dates for c, e in clubs.items()]
    )


ELO_MODEL = elo_goals.EloGoalModel(intercept=0.2, coef_elo_100=0.19, coef_home=0.19)


@pytest.fixture(scope="module")
def synthetic():
    fx = fixtures_frame()
    history = history_frame(fx)
    names = pd.read_csv(config.TEAM_NAMES_PATH)
    elo = elo_frame()
    gws = [4, 5]
    upcoming = fx[fx["gw"].isin(gws)]
    odds, sources = predict.upcoming_odds(upcoming, pd.DataFrame(), ELO_MODEL, elo, names)
    rows = predict.horizon_features(history, PLAYERS, fx, TEAMS, gws, odds, elo)
    return {"fx": fx, "history": history, "rows": rows, "sources": sources, "odds": odds}


def test_future_rows_blank_every_outcome():
    fx = fixtures_frame()
    fut = predict.future_rows(PLAYERS, fx[fx["gw"] == 4], TEAMS)
    assert fut.columns.tolist() == COLUMNS
    assert len(fut) == len(PLAYERS)  # 2 fixtures x 2 teams x 2 players
    assert fut[predict.OUTCOME_COLUMNS].isna().all().all()
    p11 = fut.set_index("element").loc[11]
    assert p11["opponent_team_name"] == "Liverpool" and not p11["was_home"]
    assert p11["value"] == 80 and p11["team_a_difficulty"] == 2  # pre-deadline facts kept


def test_feature_rows_cover_every_upcoming_fixture(synthetic):
    rows = synthetic["rows"]
    assert rows["y"].isna().all()
    by_gw = rows.groupby("gw").size().to_dict()
    assert by_gw == {4: 8, 5: 8}  # GW5: Arsenal and Chelsea players twice, others blank
    assert set(rows.loc[rows["gw"] == 5, "team"]) == {"Arsenal", "Chelsea"}
    assert (rows.loc[rows["gw"] == 5, "is_dgw"] == 1).all()
    assert (rows.loc[rows["gw"] == 4, "is_dgw"] == 0).all()


def test_every_horizon_gw_sees_todays_form(synthetic):
    """GW5's form must equal GW4's (form as of today), not average over blank GW4 rows."""
    p11 = synthetic["rows"][synthetic["rows"]["element"] == 11].sort_values("kickoff_time")
    assert p11["pts_last1"].tolist() == [9, 9, 9]
    assert np.allclose(p11["pts_r3"], 5.0)  # (2 + 4 + 9) / 3
    assert np.allclose(p11["pts_r5"], 5.0)
    assert np.allclose(p11["minutes_r3"], 90.0)
    assert (synthetic["rows"]["regular"]).all()


def test_days_rest_from_schedule_for_later_gws(synthetic):
    rows = synthetic["rows"].set_index(["element", "fixture"])
    assert rows.loc[(11, 7), "days_rest"] == 7  # GW4: from the last played match (view)
    assert rows.loc[(11, 9), "days_rest"] == 7  # GW5 first match: GW4 fixture on 12 Sep
    assert rows.loc[(11, 10), "days_rest"] == 3  # DGW second match, 19 -> 22 Sep


def test_upcoming_fixtures_fall_back_to_elo(synthetic):
    src = synthetic["sources"]
    assert len(src) == 4 and (src["odds_source"] == "elo").all()
    rows = synthetic["rows"]
    assert rows["team_xg_implied"].notna().all() and rows["p_clean_sheet"].notna().all()
    assert rows["elo_diff"].notna().all()
    ars_home = rows[(rows["team"] == "Arsenal") & (rows["fixture"] == 9)].iloc[0]
    assert ars_home["elo_diff"] == pytest.approx(100.0)
    assert ars_home["p_win"] > 0.5


def test_upcoming_odds_prefers_bookmaker_rows():
    fx = fixtures_frame()
    upcoming = fx[fx["gw"] == 4]
    names = pd.read_csv(config.TEAM_NAMES_PATH)
    from fPLense.etl.load_odds import clean_odds

    fd = clean_odds(
        pd.DataFrame(
            {
                "Div": ["E0"],
                "Date": ["12/09/2026"],
                "HomeTeam": ["Liverpool"],
                "AwayTeam": ["Arsenal"],
                "AvgH": [2.5],
                "AvgD": [3.4],
                "AvgA": [2.8],
                "Avg>2.5": [1.8],
                "Avg<2.5": [2.0],
            }
        )
    )
    odds, sources = predict.upcoming_odds(upcoming, fd, ELO_MODEL, elo_frame(), names)
    src = sources.set_index("fixture")["odds_source"]
    assert src[7] == "avg" and src[8] == "elo"
    assert len(odds) == 2


def test_assemble_scales_and_sums(synthetic):
    rows = synthetic["rows"].copy()
    rows["pred"] = 2.0
    players = PLAYERS.assign(
        code=0,
        team=PLAYERS["team_id"].map(TEAMS.set_index("team_id")["team"]),
        team_short=PLAYERS["team_id"].map(TEAMS.set_index("team_id")["team_short"]),
        news="",
        selected_by_percent=1.0,
        season_minutes=270,
        season_points=10,
    )
    players.loc[players["element"] == 12, "chance_of_playing_next_round"] = 50.0
    t = predict.assemble(players, rows, synthetic["fx"], TEAMS, synthetic["sources"], [4, 5])
    t = t.set_index("element")
    assert t.at[11, "p_gw04"] == pytest.approx(2.0)
    assert t.at[11, "p_gw05"] == pytest.approx(4.0)  # double GW
    assert t.at[31, "p_gw05"] == 0.0 and t.at[31, "fx_gw05"] == "blank"
    assert t.at[12, "p_gw05"] == pytest.approx(2.0)  # 4.0 x 50%
    assert t.at[11, "P_h"] == pytest.approx(2.0 + 0.9 * 4.0)
    assert t.at[11, "p1"] == t.at[11, "p_gw04"]
    assert t.at[11, "fx_gw05"] == "CHE (H), CHE (A)"
    assert t.at[11, "src_gw04"] == "elo" and t.at[11, "odds_source"] == "elo"
    assert t["price"].dtype.kind == "i"


def test_schedule_rest():
    rest = predict.schedule_rest(fixtures_frame()).set_index(["fixture", "team_id"])["days_rest"]
    assert np.isnan(rest[(1, 1)])  # first match of the season
    assert rest[(4, 1)] == 7
    assert rest[(10, 1)] == 3


def test_horizon_gws_stops_at_season_end():
    fx = pd.DataFrame({"gw": [36, 37, 38]})
    assert predict.horizon_gws(fx, 37, 5) == [37, 38]
