"""No-leakage test for the DuckDB feature views (PLAN.md §8 P2).

For a gameweek k, rebuild the views from a lake truncated to the fixtures before GW k plus GW k's
own fixture rows with every outcome blanked (points, minutes, goals, xG, scores, ownership and
transfer counts: what is unknown at the FPL deadline). GW k's features must equal those from the
full build. Any window that reached the current fixture, a later fixture, or the first match of
a double gameweek would make them differ.

The synthetic mini-lake test always runs; the ``@pytest.mark.data`` test uses the real lake.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fPLense import config
from fPLense.db.build import build, features
from fPLense.etl.load_odds import clean_odds
from fPLense.etl.normalize import enforce_schema

# Everything a row learns only after the deadline. Identity, fixture, kickoff, home/away,
# FDR and price stay: they are published before it.
OUTCOME_COLUMNS = [
    "minutes",
    "total_points",
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
    "team_h_score",
    "team_a_score",
    "team_score",
    "opp_score",
    "selected",
    "transfers_in",
    "transfers_out",
    "transfers_balance",
]
NUMERIC_FEATURES = [f for f in config.FEATURES if f not in config.CATEGORICAL_FEATURES]


# --- helpers --------------------------------------------------------------------------------


def truncate(pm: pd.DataFrame, k: int) -> pd.DataFrame:
    """Rows before GW k, plus GW k's rows with every outcome blanked."""
    out = pm[pm["gw"] <= k].copy()
    out[OUTCOME_COLUMNS] = out[OUTCOME_COLUMNS].astype("float64")
    out.loc[out["gw"] == k, OUTCOME_COLUMNS] = np.nan
    return out


def write_player_match(lake: Path, pm: pd.DataFrame) -> None:
    for season, part in pm.groupby("season"):
        out = lake / "player_match" / f"season={season}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        part.drop(columns="season").to_parquet(out, index=False)


def comparable(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(config.KEY_COLUMNS).reset_index(drop=True)
    out = df[config.KEY_COLUMNS + config.CATEGORICAL_FEATURES].astype(str)
    num = df[NUMERIC_FEATURES].apply(pd.to_numeric).astype("float64")
    return pd.concat([out, num], axis=1)


def assert_same_features(full: pd.DataFrame, truncated: pd.DataFrame) -> None:
    assert len(full) > 0
    a, b = comparable(full), comparable(truncated)
    assert len(a) == len(b)
    pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-9, atol=1e-12)


def features_after_truncation(pm, season, k, tmp: Path, copy_from: Path) -> pd.DataFrame:
    """Build the views over a truncated copy of ``pm`` (odds and Elo copied unchanged)."""
    lake = tmp / f"lake_{season}_{k}"
    write_player_match(lake, truncate(pm, k))
    for sub in ("odds", "elo"):
        shutil.copytree(copy_from / sub, lake / sub)
    con = build(":memory:", lake_dir=lake)
    try:
        return features(con, f"season = '{season}' and gw = {k}")
    finally:
        con.close()


# --- synthetic mini-lake --------------------------------------------------------------------

SEASON = "2024-25"
# (team_id, FPL name, football-data name, ClubElo name); FPL names map via team_names.csv
TEAMS = [
    (1, "Arsenal", "Arsenal", "Arsenal"),
    (2, "Chelsea", "Chelsea", "Chelsea"),
    (3, "Spurs", "Tottenham", "Tottenham"),
    (4, "Man Utd", "Man United", "Man United"),
    (5, "Liverpool", "Liverpool", "Liverpool"),
    (6, "Everton", "Everton", "Everton"),
]
DGW = 6  # fixture moved from GW 8 into GW 6: those two teams play twice in GW 6, blank in GW 8
N_GW = 10


def schedule() -> list[tuple[int, int, int, pd.Timestamp]]:
    """Double round robin of 6 teams over 10 GWs, with one DGW: (gw, home, away, kickoff)."""
    ids = [t[0] for t in TEAMS]
    rounds = []
    rot = ids[:]
    for r in range(len(ids) - 1):
        pairs = [(rot[i], rot[-1 - i]) for i in range(len(ids) // 2)]
        rounds.append([(b, a) if r % 2 else (a, b) for a, b in pairs])
        rot = [rot[0], rot[-1], *rot[1:-1]]
    rounds += [[(a, h) for h, a in rnd] for rnd in rounds]
    start = pd.Timestamp("2024-08-17 11:30", tz="UTC")
    out = []
    for gw, rnd in enumerate(rounds, start=1):
        for i, (h, a) in enumerate(rnd):
            kickoff = start + pd.Timedelta(days=7 * (gw - 1), hours=2 * i)
            if gw == 8 and i == 0:  # rescheduled into GW 6's midweek
                gw_played, kickoff = DGW, start + pd.Timedelta(days=7 * (DGW - 1) + 3)
            else:
                gw_played = gw
            out.append((gw_played, h, a, kickoff))
    return out


def make_player_match(rng: np.random.Generator) -> pd.DataFrame:
    names = {t[0]: t[1] for t in TEAMS}
    rows = []
    for fixture, (gw, h, a, kickoff) in enumerate(schedule(), start=1):
        hs, as_ = rng.integers(0, 4, size=2)
        for team, opp, home in [(h, a, True), (a, h, False)]:
            for j, pos in enumerate(["GK", "DEF", "MID", "FWD"]):
                minutes = int(rng.choice([0, 30, 90]))
                played = minutes > 0
                rows.append(
                    {
                        "season": SEASON,
                        "element": team * 10 + j,
                        "name": f"p{team}{j}",
                        "position": pos,
                        "team_id": team,
                        "team": names[team],
                        "opponent_team": opp,
                        "opponent_team_name": names[opp],
                        "fixture": fixture,
                        "gw": gw,
                        "kickoff_time": kickoff,
                        "was_home": home,
                        "team_h_score": hs,
                        "team_a_score": as_,
                        "team_score": hs if home else as_,
                        "opp_score": as_ if home else hs,
                        "team_h_difficulty": int(rng.integers(2, 6)),
                        "team_a_difficulty": int(rng.integers(2, 6)),
                        "minutes": minutes,
                        "total_points": int(rng.integers(1, 13)) if played else 0,
                        "goals_scored": int(rng.integers(0, 2)) if played else 0,
                        "assists": int(rng.integers(0, 2)) if played else 0,
                        "clean_sheets": int((as_ if home else hs) == 0 and minutes >= 60),
                        "saves": int(rng.integers(0, 5)) if pos == "GK" and played else 0,
                        "bonus": int(rng.integers(0, 4)) if played else 0,
                        "bps": int(rng.integers(0, 40)) if played else 0,
                        "influence": rng.uniform(0, 60) * played,
                        "creativity": rng.uniform(0, 60) * played,
                        "threat": rng.uniform(0, 60) * played,
                        "ict_index": rng.uniform(0, 15) * played,
                        "starts": int(minutes >= 60),
                        "expected_goals": rng.uniform(0, 1) * played,
                        "expected_assists": rng.uniform(0, 1) * played,
                        "expected_goal_involvements": rng.uniform(0, 2) * played,
                        "expected_goals_conceded": rng.uniform(0, 2) * played,
                        "defensive_contribution": int(rng.integers(0, 15)) if played else 0,
                        "value": 45 + 5 * j + int(rng.integers(0, 3)),
                        "selected": int(rng.integers(1_000, 900_000)),
                        "transfers_in": int(rng.integers(0, 50_000)),
                        "transfers_out": int(rng.integers(0, 50_000)),
                        "transfers_balance": int(rng.integers(-50_000, 50_000)),
                    }
                )
    df = pd.DataFrame(rows)
    df["price"] = df["value"] / 10
    return enforce_schema(df)


def make_odds(pm: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    fd = {t[0]: t[2] for t in TEAMS}
    home = pm[pm["was_home"]].drop_duplicates("fixture")
    n = len(home)
    return clean_odds(
        pd.DataFrame(
            {
                "Div": "E0",
                "Date": home["kickoff_time"].dt.strftime("%d/%m/%Y").to_numpy(),
                "HomeTeam": home["team_id"].map(fd).to_numpy(),
                "AwayTeam": home["opponent_team"].map(fd).to_numpy(),
                "FTHG": home["team_h_score"].to_numpy(),
                "FTAG": home["team_a_score"].to_numpy(),
                "AvgH": rng.uniform(1.3, 6, n),
                "AvgD": rng.uniform(3.2, 4.5, n),
                "AvgA": rng.uniform(1.3, 6, n),
                "Avg>2.5": rng.uniform(1.5, 2.4, n),
                "Avg<2.5": rng.uniform(1.5, 2.4, n),
                "AvgCH": rng.uniform(1.3, 6, n),  # closing: dropped by clean_odds
            }
        )
    )


def make_elo(rng: np.random.Generator) -> pd.DataFrame:
    dates = pd.date_range("2024-07-01", "2025-06-01", freq="SMS").date  # 1st and 15th
    return pd.DataFrame(
        [
            {"date": d, "club": club, "elo": 1600 + 30 * i + rng.normal(0, 15)}
            for d in dates
            for i, (_, _, _, club) in enumerate(TEAMS)
        ]
    )


@pytest.fixture(scope="module")
def mini_lake(tmp_path_factory):
    rng = np.random.default_rng(7)
    root = tmp_path_factory.mktemp("mini") / "lake"
    pm = make_player_match(rng)
    write_player_match(root, pm)
    odds = root / "odds" / f"season={SEASON}" / "part.parquet"
    odds.parent.mkdir(parents=True)
    make_odds(pm, rng).to_parquet(odds, index=False)
    (root / "elo").mkdir()
    make_elo(rng).to_parquet(root / "elo" / "part.parquet", index=False)
    con = build(":memory:", lake_dir=root)
    full = features(con)
    con.close()
    return root, pm, full


def test_feature_count_is_30_plus():
    assert len(config.FEATURES) >= 30
    assert len(set(config.FEATURES)) == len(config.FEATURES)


def test_mini_lake_views_expose_every_feature(mini_lake):
    _, pm, full = mini_lake
    assert len(full) == len(pm)
    assert set(config.FEATURES) <= set(full.columns)
    # odds and Elo joined for every row; the DGW exists
    assert full[["team_xg_implied", "p_clean_sheet", "elo_diff"]].notna().all().all()
    assert full.loc[full.gw == DGW, "is_dgw"].max() == 1
    assert full.loc[full.gw != DGW, "is_dgw"].max() == 0


@pytest.mark.parametrize("k", range(2, N_GW + 1))
def test_mini_lake_no_leakage(mini_lake, tmp_path, k):
    root, pm, full = mini_lake
    truncated = features_after_truncation(pm, SEASON, k, tmp_path, root)
    assert truncated["y"].isna().all()  # GW k's targets really were blanked
    assert_same_features(full[full.gw == k], truncated)


def test_dgw_second_fixture_sees_only_earlier_gameweeks(mini_lake):
    _, _, full = mini_lake
    dgw = full[(full.gw == DGW) & (full.is_dgw == 1)].sort_values("kickoff_time")
    first, second = dgw.groupby("element").nth(0), dgw.groupby("element").nth(1)
    # player and own-team form; opponent form legitimately differs (two different opponents)
    cols = [
        c
        for c in NUMERIC_FEATURES
        if c.endswith(("_r3", "_r5", "_last1", "_avg")) and not c.startswith("opp_")
    ]
    a = first.set_index("element")[cols]
    b = second.set_index("element")[cols].loc[a.index]
    pd.testing.assert_frame_equal(a, b)


def test_leakage_check_is_sensitive_to_history(mini_lake, tmp_path):
    """Changing a GW k-1 outcome must change GW k features (the test isn't vacuous)."""
    root, pm, full = mini_lake
    k = 5
    changed = pm.copy()
    hit = (changed.gw == k - 1) & (changed.element == 10)
    changed.loc[hit, "total_points"] += 20
    truncated = features_after_truncation(changed, SEASON, k, tmp_path, root)
    with pytest.raises(AssertionError):
        assert_same_features(full[full.gw == k], truncated)


def test_rolling_windows_end_at_previous_fixture(mini_lake):
    _, pm, full = mini_lake
    p = pm[pm.element == 21].sort_values(["gw", "kickoff_time"])
    f = full[full.element == 21].sort_values(["gw", "kickoff_time"]).reset_index(drop=True)
    pts = p["total_points"].to_numpy(dtype=float)
    assert pd.isna(f.loc[0, "pts_last1"])  # first fixture of the season: no history
    for i in range(1, len(f)):
        assert f.loc[i, "pts_last1"] == pts[i - 1]
        assert f.loc[i, "pts_r5"] == pytest.approx(pts[max(0, i - 5) : i].mean())
        assert f.loc[i, "pts_season_avg"] == pytest.approx(pts[:i].mean())


# --- real lake ------------------------------------------------------------------------------


@pytest.mark.data
def test_real_lake_no_leakage(feature_store, full_lake_dir, tmp_path):
    from fPLense.etl.load_history import read_player_match

    rng = np.random.default_rng(2026)
    gws = feature_store.sql(
        "select season, gw, max(is_dgw) as dgw from v_features where gw >= 5 group by all"
    ).df()
    gws["season"] = gws["season"].astype(str)
    picks = gws.sample(3, random_state=rng.integers(1 << 31))
    dgw_pick = gws[(gws.dgw == 1) & ~gws.index.isin(picks.index)].sample(1, random_state=1)
    picks = pd.concat([picks, dgw_pick])
    for season, k in picks[["season", "gw"]].itertuples(index=False):
        full = features(feature_store, f"season = '{season}' and gw = {k}")
        pm = read_player_match([season])
        truncated = features_after_truncation(pm, season, int(k), tmp_path, full_lake_dir)
        assert truncated["y"].isna().all()
        assert_same_features(full, truncated)
