"""Harmonise one season of vaastav ``merged_gw.csv`` into the lake schema.

Rules (PLAN.md §8 P1):
- 2019-20 GW 39–47 (COVID restart numbering) → 30–38.
- ``position`` and ``team`` come from ``players_raw`` / fixtures for seasons without them.
- Columns a season doesn't have (xG before 2022-23, DEFCON, ``starts``) are NaN, never 0.
- ``team_score`` / ``opp_score`` from ``was_home`` + ``team_h_score`` / ``team_a_score``.
- ``price = value / 10``.
- ``xP`` (look-ahead risk), ``mng_*``, ``kickoff_time_formatted``, ``ea_index``, ``loaned_*``
  and other one-season extras are dropped.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from fPLense import config

log = logging.getLogger(__name__)

# Ordered lake schema: (column, kind). kind: "int" = never-null integer, "float" = nullable
# numeric stored as float64, "str", "bool", "ts" (UTC timestamp).
SCHEMA: list[tuple[str, str]] = [
    ("season", "str"),
    ("element", "int"),
    ("name", "str"),
    ("position", "str"),
    ("team_id", "int"),
    ("team", "str"),
    ("opponent_team", "int"),
    ("opponent_team_name", "str"),
    ("fixture", "int"),
    ("gw", "int"),
    ("kickoff_time", "ts"),
    ("was_home", "bool"),
    ("team_h_score", "float"),
    ("team_a_score", "float"),
    ("team_score", "float"),
    ("opp_score", "float"),
    ("team_h_difficulty", "float"),
    ("team_a_difficulty", "float"),
    ("minutes", "int"),
    ("total_points", "int"),
    ("goals_scored", "float"),
    ("assists", "float"),
    ("clean_sheets", "float"),
    ("goals_conceded", "float"),
    ("own_goals", "float"),
    ("penalties_saved", "float"),
    ("penalties_missed", "float"),
    ("yellow_cards", "float"),
    ("red_cards", "float"),
    ("saves", "float"),
    ("bonus", "float"),
    ("bps", "float"),
    ("influence", "float"),
    ("creativity", "float"),
    ("threat", "float"),
    ("ict_index", "float"),
    ("starts", "float"),
    ("expected_goals", "float"),
    ("expected_assists", "float"),
    ("expected_goal_involvements", "float"),
    ("expected_goals_conceded", "float"),
    ("defensive_contribution", "float"),
    ("clearances_blocks_interceptions", "float"),
    ("recoveries", "float"),
    ("tackles", "float"),
    ("value", "int"),
    ("price", "float"),
    ("selected", "float"),
    ("transfers_in", "float"),
    ("transfers_out", "float"),
    ("transfers_balance", "float"),
]
COLUMNS = [c for c, _ in SCHEMA]

# Explicitly dropped (PLAN.md §8 P1 step 4). Anything else outside SCHEMA is dropped too.
DROP_COLUMNS = {"xP", "kickoff_time_formatted", "ea_index", "loaned_in", "loaned_out"}
DROP_PREFIXES = ("mng_",)

COVID_SEASON = "2019-20"
COVID_GW_OFFSET = 9  # GW 39..47 -> 30..38

VALID_POSITIONS = set(config.POSITIONS.values())
POSITION_ALIASES = {"GKP": "GK"}


def drop_unwanted(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in df.columns if c in DROP_COLUMNS or c.startswith(DROP_PREFIXES)]
    return df.drop(columns=cols)


def remap_gw(gw: pd.Series, season: str) -> pd.Series:
    """2019-20 resumed after COVID as GW 39–47; map those to 30–38. Other seasons unchanged."""
    gw = pd.to_numeric(gw).astype("int64")
    if season == COVID_SEASON:
        gw = gw.where(gw < 39, gw - COVID_GW_OFFSET)
    return gw


def parse_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    mapped = s.astype(str).str.strip().str.lower().map({"true": True, "false": False})
    if mapped.isna().any():
        raise ValueError(f"unparseable booleans: {s[mapped.isna()].unique()[:5]}")
    return mapped.astype(bool)


def derive_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Own-team and opponent goals from the home/away score columns."""
    h = pd.to_numeric(df["team_h_score"], errors="coerce")
    a = pd.to_numeric(df["team_a_score"], errors="coerce")
    home = df["was_home"].astype(bool)
    df["team_score"] = h.where(home, a)
    df["opp_score"] = a.where(home, h)
    return df


def fixture_sides(df: pd.DataFrame, fixtures: pd.DataFrame | None) -> pd.DataFrame:
    """One row per fixture: ``fixture, team_h, team_a`` (+ difficulty when known).

    Uses ``fixtures.csv`` when the season has it. Otherwise the sides are recovered from the
    player rows themselves: home-side rows list the away team as ``opponent_team`` and vice versa.
    """
    if fixtures is not None:
        cols = ["id", "team_h", "team_a", "team_h_difficulty", "team_a_difficulty"]
        return fixtures[cols].rename(columns={"id": "fixture"})
    opp = df[["fixture", "was_home", "opponent_team"]].drop_duplicates()
    home = opp[~opp["was_home"]].rename(columns={"opponent_team": "team_h"})  # away rows' opp
    away = opp[opp["was_home"]].rename(columns={"opponent_team": "team_a"})  # home rows' opp
    sides = home[["fixture", "team_h"]].merge(
        away[["fixture", "team_a"]], on="fixture", how="outer"
    )
    if sides["fixture"].duplicated().any():
        raise ValueError("fixture maps to more than one home/away pair")
    sides["team_h_difficulty"] = np.nan
    sides["team_a_difficulty"] = np.nan
    return sides


def add_team(df: pd.DataFrame, fixtures: pd.DataFrame | None, players_raw: pd.DataFrame):
    """Own team id per row, from the fixture's sides (correct for mid-season movers);
    falls back to ``players_raw.team`` (end-of-season club) if a side is unknown."""
    sides = fixture_sides(df, fixtures)
    df = df.merge(sides, on="fixture", how="left", validate="many_to_one")
    df["team_id"] = df["team_h"].where(df["was_home"], df["team_a"])
    fallback = df["element"].map(players_raw.set_index("id")["team"])
    n_fallback = int(df["team_id"].isna().sum())
    if n_fallback:
        log.warning("%d rows: team from players_raw (fixture side unknown)", n_fallback)
        df["team_id"] = df["team_id"].fillna(fallback)
    return df.drop(columns=["team_h", "team_a"])


def add_position(df: pd.DataFrame, players_raw: pd.DataFrame) -> pd.DataFrame:
    from_raw = df["element"].map(players_raw.set_index("id")["element_type"].map(config.POSITIONS))
    if "position" in df.columns:
        pos = df["position"].replace(POSITION_ALIASES)
        df["position"] = pos.where(pos.notna(), from_raw)
    else:
        df["position"] = from_raw
    return df


def team_names(
    master_team_list: pd.DataFrame, season: str, teams: pd.DataFrame | None = None
) -> pd.Series:
    """Team id -> name for one season: ``master_team_list.csv`` (which stops at 2023-24),
    else the season's own ``teams.csv``."""
    t = master_team_list[master_team_list["season"] == season]
    if not t.empty:
        return t.set_index("team")["team_name"]
    if teams is not None:
        return teams.set_index("id")["name"]
    raise ValueError(f"no team names for {season}: not in master_team_list, no teams.csv")


def enforce_schema(df: pd.DataFrame) -> pd.DataFrame:
    for col, kind in SCHEMA:
        if col not in df.columns:
            if kind in {"int", "bool", "ts"}:
                raise ValueError(f"required column missing: {col}")
            df[col] = np.nan if kind == "float" else None
            continue
        if kind == "int":
            df[col] = pd.to_numeric(df[col]).astype("int64")
        elif kind == "float":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        elif kind == "str":
            df[col] = df[col].astype("string")
        elif kind == "ts":
            df[col] = pd.to_datetime(df[col], utc=True)
    return df[COLUMNS]


def normalize_season(
    gw: pd.DataFrame,
    *,
    season: str,
    players_raw: pd.DataFrame,
    master_team_list: pd.DataFrame,
    fixtures: pd.DataFrame | None = None,
    teams: pd.DataFrame | None = None,
) -> pd.DataFrame:
    df = drop_unwanted(gw.copy())
    # merged_gw's own team/position are replaced by the derived ones below
    df = df.rename(columns={"GW": "gw"}).drop(columns=["team", "round"], errors="ignore")
    df["season"] = season
    df["gw"] = remap_gw(df["gw"], season)
    df["was_home"] = parse_bool(df["was_home"])
    df = add_team(df, fixtures, players_raw)
    df = add_position(df, players_raw)

    bad = ~df["position"].isin(VALID_POSITIONS)
    if bad.any():
        # 2024-25 lists assistant managers (position "AM"); they aren't players
        dropped = sorted(df.loc[bad, "position"].astype(str).unique())
        log.info("%s: dropping %d rows with position %s", season, bad.sum(), dropped)
        df = df[~bad].copy()

    names = team_names(master_team_list, season, teams)
    df["team"] = df["team_id"].map(names)
    df["opponent_team_name"] = df["opponent_team"].map(names)
    df = derive_scores(df)
    df["price"] = pd.to_numeric(df["value"]) / 10
    df = enforce_schema(df)
    return df.sort_values(["kickoff_time", "fixture", "element"], ignore_index=True)
