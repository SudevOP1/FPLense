"""FPL API parsing and schema checks against the saved samples in tests/fixtures/ (no network)."""

from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest
import requests

from fPLense import config
from fPLense.etl import fetch_api
from fPLense.etl.normalize import COLUMNS

FIX = config.TESTS_FIXTURES_DIR


def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bootstrap():
    return load("bootstrap_static_sample.json")


@pytest.fixture(scope="module")
def raw_fixtures():
    return load("fixtures_sample.json")


@pytest.fixture(scope="module")
def summary():
    return load("element_summary_sample.json")


@pytest.fixture(scope="module")
def teams(bootstrap):
    return fetch_api.parse_teams(bootstrap)


# --- fake HTTP session ------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int, payload=None):
        self.status_code = status
        self._payload = payload
        self.content = json.dumps(payload).encode()

    def json(self):
        return self._payload


class FakeSession:
    """Returns the queued responses in order and records the URLs requested."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.urls: list[str] = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def no_sleep(_):
    return None


# --- schema checks ----------------------------------------------------------------------------


def test_saved_samples_pass_schema_checks(bootstrap, raw_fixtures, summary):
    fetch_api.check_fields(bootstrap, fetch_api.BOOTSTRAP_KEYS, "bootstrap")
    fetch_api.check_records(bootstrap["elements"], fetch_api.ELEMENT_KEYS, "elements")
    fetch_api.check_records(bootstrap["teams"], fetch_api.TEAM_KEYS, "teams")
    fetch_api.check_records(bootstrap["events"], fetch_api.EVENT_KEYS, "events")
    fetch_api.check_records(raw_fixtures, fetch_api.FIXTURE_KEYS, "fixtures")
    fetch_api.check_summary(summary, summary["history"][0]["element"])
    fetch_api.check_picks(load("picks_sample.json"))


def test_missing_field_raises_schema_error(bootstrap):
    broken = copy.deepcopy(bootstrap)
    del broken["elements"][0]["now_cost"]
    session = FakeSession([FakeResponse(200, broken)])
    with pytest.raises(fetch_api.SchemaError, match="now_cost"):
        fetch_api.fetch_bootstrap(session, sleep=no_sleep)


def test_fixtures_must_be_a_list():
    session = FakeSession([FakeResponse(200, {"oops": 1})])
    with pytest.raises(fetch_api.SchemaError):
        fetch_api.fetch_fixtures(session, sleep=no_sleep)


def test_fetch_retries_then_succeeds(bootstrap):
    session = FakeSession(
        [FakeResponse(503), requests.ConnectionError("reset"), FakeResponse(200, bootstrap)]
    )
    data = fetch_api.fetch_bootstrap(session, sleep=no_sleep)
    assert len(data["elements"]) == len(bootstrap["elements"])
    assert len(session.urls) == 3
    assert session.urls[0] == f"{config.FPL_API_BASE_URL}/bootstrap-static/"


def test_fetch_fixtures_event_query(raw_fixtures):
    session = FakeSession([FakeResponse(200, raw_fixtures)])
    fetch_api.fetch_fixtures(session, event=6, sleep=no_sleep)
    assert session.urls[0].endswith("/fixtures/?event=6")


def test_element_summary_cache(tmp_path, summary):
    element = summary["history"][0]["element"]
    session = FakeSession([FakeResponse(200, summary)])
    first = fetch_api.fetch_element_summary(element, session, cache_dir=tmp_path, sleep=no_sleep)
    again = fetch_api.fetch_element_summary(element, session, cache_dir=tmp_path, sleep=no_sleep)
    assert first == again
    assert len(session.urls) == 1  # second call served from disk
    assert (tmp_path / f"{element}.json").exists()


# --- parsing ----------------------------------------------------------------------------------


def test_parse_players(bootstrap):
    p = fetch_api.parse_players(bootstrap)
    assert len(p) == len(bootstrap["elements"])
    assert set(p["position"]) <= {"GK", "DEF", "MID", "FWD"}
    assert p["now_cost"].dtype == np.int64
    assert np.allclose(p["price"], p["now_cost"] / 10)
    haaland = p.set_index("element").loc[411]
    assert haaland["name"] == "Erling Haaland" and haaland["web_name"] == "Haaland"
    assert haaland["position"] == "FWD" and haaland["team"] == "Man City"
    # null chance of playing stays NaN (= 100% downstream), not 0
    assert np.isnan(haaland["chance_of_playing_next_round"])


def test_parse_players_drops_non_players(bootstrap):
    b = copy.deepcopy(bootstrap)
    b["elements"][0]["element_type"] = 5  # assistant-manager style element
    assert len(fetch_api.parse_players(b)) == len(bootstrap["elements"]) - 1


def test_events_next_and_last_finished(bootstrap):
    b = copy.deepcopy(bootstrap)
    for e in b["events"]:  # the saved sample is GW1-5, all finished; make GW4 current, GW5 next
        e["finished"] = e["id"] <= 4
        e["is_current"] = e["id"] == 4
        e["is_next"] = e["id"] == 5
    ev = fetch_api.parse_events(b)
    assert ev["deadline_time"].dt.tz is not None
    gw, deadline = fetch_api.next_event(ev)
    assert gw == 5
    assert deadline == pd.Timestamp(b["events"][4]["deadline_time"])
    assert fetch_api.last_finished_gw(ev) == 4
    # without an is_next flag, the first unfinished non-current GW is next
    assert fetch_api.next_event(ev.assign(is_next=False))[0] == 5
    # season over: every GW finished
    assert fetch_api.next_event(fetch_api.parse_events(bootstrap)) is None


def test_parse_fixtures(raw_fixtures, teams):
    fx = fetch_api.parse_fixtures(raw_fixtures, teams)
    assert len(fx) == len(raw_fixtures)
    assert fx["gw"].dtype == np.int64
    assert fx["team_h_name"].notna().all() and fx["team_a_name"].notna().all()
    unscheduled = copy.deepcopy(raw_fixtures)
    unscheduled[0]["event"] = None
    assert len(fetch_api.parse_fixtures(unscheduled, teams)) == len(raw_fixtures) - 1


def _fixtures_for(history, teams, finished=True):
    """A fixtures frame covering a player's history rows (sample fixtures don't include them)."""
    rows = []
    for h in history:
        other = h["opponent_team"]
        own = 15  # Man City in the 2026-27 sample
        home, away = (own, other) if h["was_home"] else (other, own)
        rows.append(
            {
                "id": h["fixture"],
                "event": h["round"],
                "kickoff_time": h["kickoff_time"],
                "team_h": home,
                "team_a": away,
                "team_h_difficulty": 2,
                "team_a_difficulty": 4,
                "team_h_score": h["team_h_score"],
                "team_a_score": h["team_a_score"],
                "finished": finished,
            }
        )
    return fetch_api.parse_fixtures(rows, teams)


def test_history_rows_match_lake_schema(summary, bootstrap, teams):
    players = fetch_api.parse_players(bootstrap).set_index("element")
    player = {"name": players.at[411, "name"], "position": "FWD"}
    fx = _fixtures_for(summary["history"], teams)
    rows = fetch_api.history_rows(summary["history"], player, fx, teams)
    assert rows.columns.tolist() == COLUMNS
    assert len(rows) == len(summary["history"])
    assert (rows["team"] == "Man City").all()
    assert (rows["season"] == config.CURRENT_SEASON).all()
    first = rows.iloc[0]
    h0 = summary["history"][0]
    assert first["gw"] == h0["round"] and first["total_points"] == h0["total_points"]
    assert first["expected_goals"] == pytest.approx(float(h0["expected_goals"]))  # "0.74" parsed
    assert first["price"] == pytest.approx(h0["value"] / 10)
    # own/opponent score from the home/away scores and venue
    assert first["team_score"] == (h0["team_h_score"] if h0["was_home"] else h0["team_a_score"])
    # FDR comes from the fixture's own side
    assert first["team_h_difficulty"] == 2 and first["team_a_difficulty"] == 4


def test_history_rows_skip_unfinished_fixtures(summary, teams):
    fx = _fixtures_for(summary["history"], teams, finished=False)
    rows = fetch_api.history_rows(summary["history"], {"name": "x", "position": "FWD"}, fx, teams)
    assert rows.empty


def test_zero_rows_for_players_without_minutes(teams):
    players = pd.DataFrame(
        {
            "element": [900, 901],
            "name": ["A Keeper", "B Back"],
            "position": ["GK", "DEF"],
            "team_id": [1, 7],
            "now_cost": [40, 45],
            "selected": [1000.0, np.nan],
        }
    )
    fx = fetch_api.parse_fixtures(
        [
            {
                "id": 1,
                "event": 1,
                "kickoff_time": "2026-08-21T19:00:00Z",
                "team_h": 1,
                "team_a": 7,
                "team_h_difficulty": 2,
                "team_a_difficulty": 4,
                "team_h_score": 3,
                "team_a_score": 0,
                "finished": True,
            },
            {
                "id": 2,
                "event": 2,
                "kickoff_time": "2026-08-28T19:00:00Z",
                "team_h": 7,
                "team_a": 3,
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
                "team_h_score": None,
                "team_a_score": None,
                "finished": False,
            },
        ],
        teams,
    )
    rows = fetch_api.zero_rows(players, fx, teams)
    assert rows.columns.tolist() == COLUMNS
    assert len(rows) == 2  # one finished fixture each; the unfinished one is skipped
    assert (rows["minutes"] == 0).all() and (rows["total_points"] == 0).all()
    assert (rows["bps"] == 0).all() and (rows["expected_goals"] == 0).all()
    assert rows["transfers_balance"].isna().all()  # unknown, not 0
    gk = rows.set_index("element").loc[900]
    assert bool(gk["was_home"]) and gk["team_score"] == 3 and gk["opp_score"] == 0
    assert gk["value"] == 40 and gk["price"] == pytest.approx(4.0)


def test_history_past_cold_start(summary):
    row = fetch_api.history_past_row(411, summary["history_past"])
    last = next(p for p in summary["history_past"] if p["season_name"] == "2025/26")
    assert row["prev_season_pts_per90"] == pytest.approx(
        last["total_points"] * 90 / last["minutes"]
    )
    assert np.isnan(fetch_api.history_past_row(1, [])["prev_season_pts_per90"])
    assert fetch_api.prev_season_name("2026-27") == "2025/26"


def test_parse_picks():
    picks = fetch_api.parse_picks(load("picks_sample.json"))
    assert len(picks["squad"]) == 15 and len(set(picks["squad"])) == 15
    assert isinstance(picks["bank"], int) and picks["bank"] >= 0
    assert picks["captain"] in picks["squad"]


def test_parse_picks_rejects_short_squad():
    data = load("picks_sample.json")
    data["picks"] = data["picks"][:14]
    with pytest.raises(fetch_api.SchemaError, match="15"):
        fetch_api.parse_picks(data)


def test_fetch_picks_url():
    session = FakeSession([FakeResponse(200, load("picks_sample.json"))])
    fetch_api.fetch_picks(123, 5, session, sleep=no_sleep)
    assert session.urls[0] == f"{config.FPL_API_BASE_URL}/entry/123/event/5/picks/"
