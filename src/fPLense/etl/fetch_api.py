"""Live data for the current season from the official FPL API (PLAN.md §3b, §8 P5).

- ``bootstrap-static/`` (players, teams, gameweeks) and ``fixtures/`` are fetched on every refresh.
- ``element-summary/{id}/`` is fetched for each player with minutes > 0 this season; its
  ``history`` becomes lake rows in the same schema as the 10 historical seasons. Responses are
  cached on disk per finished gameweek (a finished GW's history doesn't change).
- Players with 0 minutes all season get synthesized 0-minute rows for their club's finished
  fixtures (what vaastav's ``merged_gw`` has for them), so the model doesn't treat them as
  cold-start rows.
- ``history_past`` gives the cold-start column ``prev_season_pts_per90`` (published for context;
  not a model feature).
- ``fetch_picks`` loads a public team's 15 picks for the transfer planner.

Every call goes through :mod:`fPLense.etl.net` (browser-like User-Agent, 0.25 s pause, retries
with backoff) and every response is checked for the fields the code reads (``SchemaError``).
The API is unofficial; use it politely, for personal and non-commercial purposes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from fPLense import config
from fPLense.etl import net
from fPLense.etl.normalize import COLUMNS, derive_scores, enforce_schema

log = logging.getLogger(__name__)

# Fields the code reads from each response (checked on every call).
BOOTSTRAP_KEYS = {"elements", "teams", "events"}
ELEMENT_KEYS = {
    "id",
    "code",
    "first_name",
    "second_name",
    "web_name",
    "team",
    "element_type",
    "now_cost",
    "status",
    "chance_of_playing_next_round",
    "selected_by_percent",
    "news",
    "minutes",
    "total_points",
}
TEAM_KEYS = {"id", "name", "short_name"}
EVENT_KEYS = {"id", "deadline_time", "finished", "is_current", "is_next"}
FIXTURE_KEYS = {
    "id",
    "event",
    "kickoff_time",
    "team_h",
    "team_a",
    "team_h_difficulty",
    "team_a_difficulty",
    "team_h_score",
    "team_a_score",
    "finished",
}
SUMMARY_KEYS = {"history", "history_past"}
HISTORY_KEYS = {
    "element",
    "fixture",
    "opponent_team",
    "total_points",
    "was_home",
    "kickoff_time",
    "round",
    "minutes",
    "value",
    "selected",
    "transfers_balance",
}
HISTORY_PAST_KEYS = {"season_name", "total_points", "minutes"}
PICKS_KEYS = {"picks", "entry_history"}
PICK_KEYS = {"element", "position", "is_captain", "is_vice_captain"}
ENTRY_HISTORY_KEYS = {"event", "bank", "value"}

# Lake columns that are counts/stats: 0 on a synthesized 0-minute row.
ZERO_STAT_COLUMNS = [
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "own_goals",
    "penalties_saved",
    "penalties_missed",
    "yellow_cards",
    "red_cards",
    "saves",
    "bonus",
    "bps",
    "influence",
    "creativity",
    "threat",
    "ict_index",
    "starts",
    "expected_goals",
    "expected_assists",
    "expected_goal_involvements",
    "expected_goals_conceded",
    "defensive_contribution",
    "clearances_blocks_interceptions",
    "recoveries",
    "tackles",
]


class SchemaError(ValueError):
    """An FPL API response is missing fields this code depends on (the API changed)."""


def check_fields(record: Mapping, required: Iterable[str], where: str) -> None:
    missing = sorted(set(required) - set(record))
    if missing:
        raise SchemaError(f"{where}: missing fields {missing} (has the FPL API changed?)")


def check_records(records: Iterable[Mapping], required: Iterable[str], where: str) -> None:
    for k, rec in enumerate(records):
        check_fields(rec, required, f"{where}[{k}]")


# --- fetching ---------------------------------------------------------------------------------


def api_url(path: str) -> str:
    return f"{config.FPL_API_BASE_URL}/{path.strip('/')}/"


def fetch_bootstrap(session=None, **kwargs) -> dict:
    data = net.get_json(api_url("bootstrap-static"), session, **kwargs)
    check_fields(data, BOOTSTRAP_KEYS, "bootstrap-static")
    check_records(data["elements"], ELEMENT_KEYS, "bootstrap-static.elements")
    check_records(data["teams"], TEAM_KEYS, "bootstrap-static.teams")
    check_records(data["events"], EVENT_KEYS, "bootstrap-static.events")
    return data


def fetch_fixtures(session=None, event: int | None = None, **kwargs) -> list[dict]:
    url = api_url("fixtures") + (f"?event={int(event)}" if event is not None else "")
    data = net.get_json(url, session, **kwargs)
    if not isinstance(data, list):
        raise SchemaError("fixtures: expected a list")
    check_records(data, FIXTURE_KEYS, "fixtures")
    return data


def check_summary(data: Mapping, element: int) -> None:
    where = f"element-summary/{element}"
    check_fields(data, SUMMARY_KEYS, where)
    check_records(data["history"], HISTORY_KEYS, f"{where}.history")
    check_records(data["history_past"], HISTORY_PAST_KEYS, f"{where}.history_past")


def fetch_element_summary(
    element: int, session=None, cache_dir: Path | None = None, **kwargs
) -> dict:
    """One player's summary; read from / written to ``cache_dir/<id>.json`` when given."""
    cache = Path(cache_dir) / f"{int(element)}.json" if cache_dir is not None else None
    if cache is not None and cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
    else:
        data = net.get_json(api_url(f"element-summary/{int(element)}"), session, **kwargs)
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
    check_summary(data, element)
    return data


def fetch_picks(team_id: int, gw: int, session=None, **kwargs) -> dict:
    """A public team's picks for one gameweek (``entry/{id}/event/{gw}/picks/``)."""
    data = net.get_json(api_url(f"entry/{int(team_id)}/event/{int(gw)}/picks"), session, **kwargs)
    check_picks(data)
    return data


def check_picks(data: Mapping) -> None:
    check_fields(data, PICKS_KEYS, "picks")
    check_records(data["picks"], PICK_KEYS, "picks.picks")
    check_fields(data["entry_history"], ENTRY_HISTORY_KEYS, "picks.entry_history")


def parse_picks(data: Mapping) -> dict[str, Any]:
    """``{"squad": [15 ids], "bank": tenths, "value": tenths, "captain": id, "gw": n}``."""
    check_picks(data)
    picks = sorted(data["picks"], key=lambda p: p["position"])
    squad = [int(p["element"]) for p in picks]
    if len(set(squad)) != sum(config.SQUAD_QUOTAS.values()):
        raise SchemaError(f"picks: expected 15 distinct players, got {len(set(squad))}")
    eh = data["entry_history"]
    captain = next((int(p["element"]) for p in picks if p["is_captain"]), None)
    return {
        "squad": squad,
        "bank": int(eh["bank"]),
        "value": int(eh["value"]),
        "captain": captain,
        "gw": int(eh["event"]),
    }


# --- parsing ----------------------------------------------------------------------------------


def parse_teams(bootstrap: Mapping) -> pd.DataFrame:
    teams = pd.DataFrame(bootstrap["teams"])[["id", "name", "short_name"]]
    return teams.rename(columns={"id": "team_id", "name": "team", "short_name": "team_short"})


def parse_events(bootstrap: Mapping) -> pd.DataFrame:
    ev = pd.DataFrame(bootstrap["events"])[
        ["id", "deadline_time", "finished", "is_current", "is_next"]
    ]
    ev = ev.rename(columns={"id": "gw"})
    ev["deadline_time"] = pd.to_datetime(ev["deadline_time"], utc=True)
    for c in ("finished", "is_current", "is_next"):
        ev[c] = ev[c].astype(bool)
    return ev.sort_values("gw", ignore_index=True)


def next_event(events: pd.DataFrame) -> tuple[int, pd.Timestamp] | None:
    """``(gw, deadline)`` of the next gameweek, or ``None`` once the season is over."""
    nxt = events[events["is_next"]]
    if nxt.empty:
        nxt = events[~events["finished"] & ~events["is_current"]]
    if nxt.empty:
        return None
    row = nxt.iloc[0]
    return int(row["gw"]), row["deadline_time"]


def last_finished_gw(events: pd.DataFrame) -> int:
    done = events.loc[events["finished"], "gw"]
    return int(done.max()) if len(done) else 0


def parse_players(bootstrap: Mapping) -> pd.DataFrame:
    """One row per player: identity, club, position, price (``now_cost`` tenths), availability."""
    el = pd.DataFrame(bootstrap["elements"])
    teams = parse_teams(bootstrap).set_index("team_id")
    out = pd.DataFrame(
        {
            "element": el["id"].astype("int64"),
            "code": el["code"].astype("int64"),
            "web_name": el["web_name"].astype(str),
            "name": (el["first_name"].astype(str) + " " + el["second_name"].astype(str)),
            "team_id": el["team"].astype("int64"),
            "position": el["element_type"].map(config.POSITIONS),
            "now_cost": el["now_cost"].astype("int64"),
            "status": el["status"].astype(str),
            "chance_of_playing_next_round": pd.to_numeric(
                el["chance_of_playing_next_round"], errors="coerce"
            ).astype(float),
            "news": el["news"].fillna("").astype(str),
            "selected_by_percent": pd.to_numeric(el["selected_by_percent"], errors="coerce"),
            "season_minutes": el["minutes"].astype("int64"),
            "season_points": el["total_points"].astype("int64"),
        }
    )
    if out["position"].isna().any():
        bad = sorted(el.loc[out["position"].isna(), "element_type"].unique())
        log.info(
            "dropping %d non-player elements (element_type %s)", out["position"].isna().sum(), bad
        )
        out = out[out["position"].notna()].copy()
    out["team"] = out["team_id"].map(teams["team"])
    out["team_short"] = out["team_id"].map(teams["team_short"])
    total = bootstrap.get("total_players")
    out["selected"] = out["selected_by_percent"] / 100 * total if total else np.nan
    out["price"] = out["now_cost"] / 10
    return out.reset_index(drop=True)


def parse_fixtures(fixtures: list[Mapping], teams: pd.DataFrame) -> pd.DataFrame:
    """One row per fixture: GW, kick-off, sides, FDR, scores; unscheduled ones (no GW) dropped."""
    fx = pd.DataFrame(fixtures)
    names = teams.set_index("team_id")
    out = pd.DataFrame(
        {
            "fixture": fx["id"].astype("int64"),
            "gw": pd.to_numeric(fx["event"], errors="coerce").astype("Int64"),
            "kickoff_time": pd.to_datetime(fx["kickoff_time"], utc=True),
            "team_h": fx["team_h"].astype("int64"),
            "team_a": fx["team_a"].astype("int64"),
            "team_h_difficulty": pd.to_numeric(fx["team_h_difficulty"]).astype(float),
            "team_a_difficulty": pd.to_numeric(fx["team_a_difficulty"]).astype(float),
            "team_h_score": pd.to_numeric(fx["team_h_score"], errors="coerce").astype(float),
            "team_a_score": pd.to_numeric(fx["team_a_score"], errors="coerce").astype(float),
            "finished": fx["finished"].astype(bool),
        }
    )
    out["team_h_name"] = out["team_h"].map(names["team"])
    out["team_a_name"] = out["team_a"].map(names["team"])
    out = out[out["gw"].notna() & out["kickoff_time"].notna()].copy()
    out["gw"] = out["gw"].astype("int64")
    return out.sort_values(["kickoff_time", "fixture"], ignore_index=True)


def _finish_rows(df: pd.DataFrame, season: str, fixtures: pd.DataFrame, teams: pd.DataFrame):
    """Add own team (from the fixture's side), names, FDR, scores and price; lake schema."""
    sides = fixtures[
        ["fixture", "team_h", "team_a", "team_h_difficulty", "team_a_difficulty", "kickoff_time"]
    ].rename(columns={"kickoff_time": "_ko"})
    # history rows carry the scores; synthesized rows take them from the fixture
    scores = [c for c in ("team_h_score", "team_a_score") if c not in df]
    sides = sides.join(fixtures[scores])
    df = df.merge(sides, on="fixture", how="inner", validate="many_to_one")
    df["kickoff_time"] = df["kickoff_time"].where(df["kickoff_time"].notna(), df["_ko"])
    df["team_id"] = df["team_h"].where(df["was_home"], df["team_a"])
    df["opponent_team"] = df["team_a"].where(df["was_home"], df["team_h"])
    names = teams.set_index("team_id")["team"]
    df["team"] = df["team_id"].map(names)
    df["opponent_team_name"] = df["opponent_team"].map(names)
    df["season"] = season
    df = derive_scores(df)
    df["price"] = pd.to_numeric(df["value"]) / 10
    return df.drop(columns=["team_h", "team_a", "_ko"])


def history_rows(
    history: list[Mapping],
    player: Mapping,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    season: str = config.CURRENT_SEASON,
) -> pd.DataFrame:
    """``element-summary`` history → lake rows (finished fixtures only)."""
    if not history:
        return _empty()
    df = pd.DataFrame(history).rename(columns={"round": "gw"})
    df = df.drop(columns=["modified"], errors="ignore")
    df["kickoff_time"] = pd.to_datetime(df["kickoff_time"], utc=True)
    df["was_home"] = df["was_home"].astype(bool)
    df["name"] = player["name"]
    df["position"] = player["position"]
    finished = fixtures[fixtures["finished"]]
    df = df[df["fixture"].isin(finished["fixture"])]
    if df.empty:
        return _empty()
    return enforce_schema(_finish_rows(df, season, finished, teams))


def zero_rows(
    players: pd.DataFrame,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    season: str = config.CURRENT_SEASON,
) -> pd.DataFrame:
    """0-minute rows for players who haven't played: one per finished fixture of their club.

    Points/minutes/stats are 0 (as in vaastav's ``merged_gw``); ``value`` is today's price and
    ``selected`` today's ownership (the API has no per-GW history without a per-player call);
    transfer counts are unknown (NaN).
    """
    finished = fixtures[fixtures["finished"]]
    parts = []
    for side, home in (("team_h", True), ("team_a", False)):
        f = finished[["fixture", "gw", "kickoff_time", side]].rename(columns={side: "team_id"})
        p = players.merge(f, on="team_id")
        p["was_home"] = home
        parts.append(p)
    df = pd.concat(parts, ignore_index=True)
    if df.empty:
        return _empty()
    df = df[
        [
            "element",
            "name",
            "position",
            "fixture",
            "gw",
            "kickoff_time",
            "was_home",
            "now_cost",
            "selected",
        ]
    ]
    df = df.rename(columns={"now_cost": "value"})
    df["minutes"] = 0
    df["total_points"] = 0
    for c in ZERO_STAT_COLUMNS:
        df[c] = 0.0
    return enforce_schema(_finish_rows(df, season, finished, teams))


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def prev_season_name(season: str = config.CURRENT_SEASON) -> str:
    """``"2026-27"`` -> ``"2025/26"`` (``history_past.season_name`` format)."""
    start = int(season[:4]) - 1
    return f"{start}/{str(start + 1)[2:]}"


def history_past_row(element: int, past: list[Mapping], season: str = config.CURRENT_SEASON):
    """Last season's totals for the cold-start column (NaN if the player wasn't in the league)."""
    prev = next((p for p in past if p["season_name"] == prev_season_name(season)), None)
    minutes = float(prev["minutes"]) if prev else np.nan
    points = float(prev["total_points"]) if prev else np.nan
    per90 = points * 90.0 / minutes if prev and minutes > 0 else np.nan
    return {
        "element": int(element),
        "prev_season_minutes": minutes,
        "prev_season_points": points,
        "prev_season_pts_per90": per90,
    }


# --- refresh ----------------------------------------------------------------------------------


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def refresh_live(
    *, session=None, bootstrap: dict | None = None, live_dir: Path = config.LIVE_DIR
) -> dict[str, Any]:
    """Fetch bootstrap + fixtures + element summaries and write the live lake (``data/lake/live``).

    ``bootstrap`` can be passed in when the caller already fetched it. Returns a summary dict
    (also written to ``meta.json``).
    """
    session = session or net.make_session()
    bootstrap = bootstrap if bootstrap is not None else fetch_bootstrap(session)
    raw_fixtures = fetch_fixtures(session)
    _write_json(config.API_CACHE_DIR / "bootstrap-static.json", bootstrap)
    _write_json(config.API_CACHE_DIR / "fixtures.json", raw_fixtures)

    teams = parse_teams(bootstrap)
    events = parse_events(bootstrap)
    players = parse_players(bootstrap)
    fixtures = parse_fixtures(raw_fixtures, teams)
    last_gw = last_finished_gw(events)
    cache_dir = config.API_CACHE_DIR / "element-summary" / f"gw{last_gw:02d}"

    played = players[players["season_minutes"] > 0]
    log.info("element-summary for %d players with minutes > 0 (cache %s)", len(played), cache_dir)
    rows, past = [], []
    for k, p in enumerate(played.itertuples(index=False), start=1):
        data = fetch_element_summary(p.element, session, cache_dir=cache_dir)
        rows.append(history_rows(data["history"], p._asdict(), fixtures, teams))
        past.append(history_past_row(p.element, data["history_past"]))
        if k % 100 == 0:
            log.info("  %d / %d", k, len(played))
    rows.append(zero_rows(players[players["season_minutes"] == 0], fixtures, teams))
    history = pd.concat([r for r in rows if len(r)], ignore_index=True)
    history = history.sort_values(["kickoff_time", "fixture", "element"], ignore_index=True)

    hist_path = live_dir / "player_match" / f"season={config.CURRENT_SEASON}" / "part.parquet"
    hist_path.parent.mkdir(parents=True, exist_ok=True)
    history.drop(columns="season").to_parquet(hist_path, index=False)
    players.to_parquet(live_dir / config.LIVE_PLAYERS_PATH.name, index=False)
    fixtures.to_parquet(live_dir / config.LIVE_FIXTURES_PATH.name, index=False)

    past_df = pd.DataFrame(past, columns=list(history_past_row(0, []).keys()))
    past_path = live_dir / config.LIVE_HISTORY_PAST_PATH.name
    if (
        past_path.exists()
    ):  # once per season: keep earlier rows, add players seen for the first time
        old = pd.read_parquet(past_path)
        past_df = pd.concat([old, past_df[~past_df["element"].isin(old["element"])]])
    past_df.to_parquet(past_path, index=False)

    nxt = next_event(events)
    meta = {
        "season": config.CURRENT_SEASON,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "last_finished_gw": last_gw,
        "next_gw": nxt[0] if nxt else None,
        "next_deadline": nxt[1].isoformat() if nxt else None,
        "players": len(players),
        "players_fetched": len(played),
        "history_rows": len(history),
        "zero_minute_players": int((players["season_minutes"] == 0).sum()),
        "fixtures": len(fixtures),
    }
    _write_json(live_dir / config.LIVE_META_PATH.name, meta)
    return meta
