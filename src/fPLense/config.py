"""Project-wide settings: seasons, paths, data sources and HTTP request settings."""

from __future__ import annotations

from pathlib import Path

# --- seasons -------------------------------------------------------------------------------

SEASONS: list[str] = [
    "2016-17",
    "2017-18",
    "2018-19",
    "2019-20",
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
    "2025-26",
]
CURRENT_SEASON = "2026-27"

# vaastav has no fixtures.csv (hence no FDR) before this season
FIRST_SEASON_WITH_FIXTURES = "2018-19"
# per-season teams.csv exists from here (needed: master_team_list.csv stops at 2023-24)
FIRST_SEASON_WITH_TEAMS = "2019-20"

# Expected merged_gw.csv row counts, verified 2026-10-07 (PLAN.md §3a). Sanity checks, not inputs.
EXPECTED_ROWS: dict[str, int] = {
    "2016-17": 23_679,
    "2017-18": 22_467,
    "2018-19": 21_790,
    "2019-20": 22_560,
    "2020-21": 24_365,
    "2021-22": 25_447,
    "2022-23": 26_505,
    "2023-24": 29_725,
    "2024-25": 27_605,
    "2025-26": 29_757,
}

POSITIONS: dict[int, str] = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

# --- paths ---------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
LAKE_DIR = DATA_DIR / "lake"
PUBLISHED_DIR = DATA_DIR / "published"
DUCKDB_PATH = DATA_DIR / "fplense.duckdb"
MANIFEST_PATH = RAW_DIR / "manifest.json"
PLAYER_MATCH_DIR = LAKE_DIR / "player_match"
ODDS_DIR = LAKE_DIR / "odds"
ELO_DIR = LAKE_DIR / "elo"
TESTS_FIXTURES_DIR = ROOT / "tests" / "fixtures"
DOCS_IMG_DIR = ROOT / "docs" / "img"
PACKAGE_DIR = Path(__file__).resolve().parent
TEAM_NAMES_PATH = PACKAGE_DIR / "etl" / "team_names.csv"
SQL_DIR = PACKAGE_DIR / "db" / "sql"

# --- sources -------------------------------------------------------------------------------

VAASTAV_BASE_URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
FPL_API_BASE_URL = "https://fantasy.premierleague.com/api"

# football-data.co.uk Premier League CSVs: <base>/<code>/E0.csv, code "1617" = 2016-17
FOOTBALL_DATA_BASE_URL = "https://www.football-data.co.uk/mmz4281"
FOOTBALL_DATA_FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
MATCHES_PER_SEASON = 380

# Kaggle dataset with ClubElo snapshots (MIT). Token setup: PLAN.md §0.2.
ELO_KAGGLE_DATASET = "adamgbor/club-football-match-data-2000-2025"
ELO_KAGGLE_FILE = "EloRatings.csv"
ELO_COUNTRY = "ENG"
ELO_START_DATE = "2016-07-01"


def fd_season_code(season: str) -> str:
    """``"2016-17"`` -> ``"1617"`` (football-data.co.uk's folder name)."""
    return season[2:4] + season[5:7]


# --- HTTP ----------------------------------------------------------------------------------

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 FPLense"}
REQUEST_SLEEP_S = 0.25  # pause between consecutive calls to the same host
REQUEST_TIMEOUT_S = 60
REQUEST_RETRIES = 4
REQUEST_BACKOFF_S = 1.0  # sleep = backoff * 2**attempt

# --- features (PLAN.md §8 P2) --------------------------------------------------------------
# Built by db/sql/06_v_features.sql. Every rolling window ends at the previous gameweek.

FEATURE_GROUPS: dict[str, list[str]] = {
    "form": [
        "pts_last1",
        "pts_r3",
        "pts_r5",
        "pts_season_avg",
        "pts_per90_season",
        "bps_r5",
        "bonus_r5",
        "ict_r5",
    ],
    "minutes": ["minutes_r3", "minutes_r5", "played60_r5", "days_rest"],
    "attacking": [
        "xg_r5",
        "xa_r5",
        "xgi_r5",
        "goals_r5",
        "assists_r5",
        "threat_r5",
        "creativity_r5",
        "influence_r5",
    ],
    "defensive": ["xgc_r5", "cs_r5", "saves_r5", "defcon_r5"],
    "market": ["price", "price_change_3", "log_selected_lag1", "transfers_balance_lag1"],
    "fixture": [
        "was_home",
        "fdr",
        "opp_gf_r5",
        "opp_ga_r5",
        "opp_xga_r5",
        "team_gf_r5",
        "team_xgf_r5",
        "is_dgw",
    ],
    "odds_elo": ["team_xg_implied", "opp_xg_implied", "p_clean_sheet", "p_win", "elo_diff"],
    "categorical": ["position", "gw"],
}
FEATURES: list[str] = [f for group in FEATURE_GROUPS.values() for f in group]
CATEGORICAL_FEATURES: list[str] = ["position"]
TARGET = "y"
KEY_COLUMNS: list[str] = ["season", "element", "fixture"]
