"""Club-name map between FPL, football-data.co.uk and ClubElo.

Pure tests check the CSV itself and the 2026-27 FPL clubs (saved from bootstrap-static).
``@pytest.mark.data`` tests check the real joins: all 3,800 historical fixtures must match.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from fPLense import config
from fPLense.etl import load_odds


@pytest.fixture(scope="module")
def names() -> pd.DataFrame:
    return pd.read_csv(config.TEAM_NAMES_PATH, dtype=str)


@pytest.fixture(scope="module")
def clubs_2026_27() -> list[str]:
    data = json.loads((config.TESTS_FIXTURES_DIR / "teams_2026_27.json").read_text("utf-8"))
    return [t["name"] for t in data["teams"]]


def test_map_columns_and_no_blanks(names):
    assert list(names.columns) == ["fpl_name", "fd_name", "clubelo_name"]
    assert not names.isna().any().any()
    assert (names.apply(lambda s: s.str.strip()) == names).all().all()


def test_fpl_names_unique(names):
    assert names["fpl_name"].is_unique


def test_fd_and_elo_names_agree(names):
    # one football-data name never maps to two different ClubElo names (and vice versa)
    assert (names.groupby("fd_name")["clubelo_name"].nunique() == 1).all()
    assert (names.groupby("clubelo_name")["fd_name"].nunique() == 1).all()


def test_every_2026_27_club_maps(names, clubs_2026_27):
    assert len(clubs_2026_27) == 20
    missing = sorted(set(clubs_2026_27) - set(names.fpl_name))
    assert not missing, f"2026-27 clubs missing from team_names.csv: {missing}"
    assert "Coventry City" in clubs_2026_27  # promoted club


# --- real data ------------------------------------------------------------------------------


@pytest.mark.data
def test_every_lake_team_maps(feature_store, names):
    teams = {r[0] for r in feature_store.sql("select distinct team from v_team_match").fetchall()}
    assert len(teams) == 34
    assert not sorted(teams - set(names.fpl_name))


@pytest.mark.data
def test_all_3800_historical_fixtures_match_odds(feature_store):
    seasons = ", ".join(f"'{s}'" for s in config.SEASONS)
    total, matched = feature_store.sql(
        f"""select count(*), count(p_home) from v_fixture_odds where season in ({seasons})"""
    ).fetchone()
    assert total == 3_800
    assert matched == 3_800, f"{total - matched} fixtures unmatched"


@pytest.mark.data
def test_odds_join_orientation_matches_scores(feature_store):
    # football-data's full-time score must equal FPL's for the same (season, home, away)
    bad = feature_store.sql(
        """
        select count(*) from v_fixture_odds f
        join v_team_match h on h.season = f.season and h.fixture = f.fixture and h.is_home
        where f.fthg <> h.goals_for or f.ftag <> h.goals_against
        """
    ).fetchone()[0]
    assert bad == 0


@pytest.mark.data
def test_odds_lake_rows_unique_per_home_away(feature_store):
    dupes = feature_store.sql(
        "select count(*) from (select season, home_team, away_team, count(*) n from v_odds "
        "group by all having n > 1)"
    ).fetchone()[0]
    assert dupes == 0


@pytest.mark.data
def test_every_team_fixture_has_elo(feature_store):
    total, with_elo, stale = feature_store.sql(
        """
        select count(*), count(elo_diff),
               count(*) filter (where gw_start_date - elo_date > 31)
        from v_match_odds join (
            select season, gw, cast(timezone('UTC', min(kickoff_time)) as date) gw_start_date
            from v_team_match group by all
        ) using (season, gw)
        """
    ).fetchone()
    assert total == 7_600
    assert with_elo == 7_600
    assert stale == 0  # snapshots are semimonthly: never more than a month old


@pytest.mark.data
def test_2026_27_clubs_in_football_data_and_elo(feature_store, names, clubs_2026_27):
    mapped = names.set_index("fpl_name").loc[clubs_2026_27]
    path = load_odds.raw_path(config.CURRENT_SEASON)
    if path.exists():
        fd = load_odds.clean_odds(load_odds.read_csv(path))
        fd_teams = set(fd.home_team) | set(fd.away_team)
        assert fd_teams <= set(mapped.fd_name), sorted(fd_teams - set(mapped.fd_name))
    latest = {
        r[0]
        for r in feature_store.sql(
            "select club from v_elo where date = (select max(date) from v_elo)"
        ).fetchall()
    }
    assert not sorted(set(mapped.clubelo_name) - latest)
