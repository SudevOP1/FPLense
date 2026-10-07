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
TESTS_FIXTURES_DIR = ROOT / "tests" / "fixtures"

# --- sources -------------------------------------------------------------------------------

VAASTAV_BASE_URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
FPL_API_BASE_URL = "https://fantasy.premierleague.com/api"

# --- HTTP ----------------------------------------------------------------------------------

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 FPLense"}
REQUEST_SLEEP_S = 0.25  # pause between consecutive calls to the same host
REQUEST_TIMEOUT_S = 60
REQUEST_RETRIES = 4
REQUEST_BACKOFF_S = 1.0  # sleep = backoff * 2**attempt
