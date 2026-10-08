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

# --- modelling (PLAN.md §8 P3) -------------------------------------------------------------

EVAL_DIR = DATA_DIR / "eval"  # walk-forward predictions (gitignored; summarised in metrics.json)
METRICS_PATH = PUBLISHED_DIR / "metrics.json"
MODEL_PATH = PUBLISHED_DIR / "model.txt"

# Walk-forward: for each k in EVAL_GWS train on everything before (TARGET_SEASON, k), predict k.
TARGET_SEASON = "2025-26"
EVAL_GWS: list[int] = list(range(5, 39))
# Second view: one fit on seasons before HOLDOUT_SEASON, scored on HOLDOUT_SEASON GW5+.
HOLDOUT_SEASON = "2024-25"

# "Regulars" = lagged minutes only (never actual minutes), so the subset is known pre-deadline.
REGULAR_MIN_MINUTES_R3 = 45
TOP_K = 20
BOOTSTRAP_REPS = 1_000
EARLY_STOPPING_GWS = 3  # last N gameweeks of each training window are the early-stopping set
EARLY_STOPPING_ROUNDS = 100
RANDOM_STATE = 42

LGBM_PARAMS: dict[str, object] = {
    "objective": "regression",
    "n_estimators": 2000,
    "learning_rate": 0.03,
    "num_leaves": 31,
    "min_child_samples": 50,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
}

# Ablation ladder: each step adds a block of features to the previous one.
_XG_FEATURES = ["xg_r5", "xa_r5", "xgi_r5", "xgc_r5", "opp_xga_r5", "team_xgf_r5"]
_FORM_ONLY = [
    f
    for g in ("form", "minutes", "attacking", "defensive", "market", "categorical")
    for f in FEATURE_GROUPS[g]
    if f not in _XG_FEATURES
]
_FIXTURE = [f for f in FEATURE_GROUPS["fixture"] if f not in _XG_FEATURES]
ABLATION_SETS: dict[str, list[str]] = {
    "i_form": _FORM_ONLY,
    "ii_fixture": _FORM_ONLY + _FIXTURE,
    "iii_xg": _FORM_ONLY + _FIXTURE + _XG_FEATURES,
    "iv_odds_elo": FEATURES,
}
XG_FIRST_SEASON = "2022-23"

# --- explainability (PLAN.md §8 P4) --------------------------------------------------------

SHAP_SAMPLE_ROWS = 5_000
SHAP_SAMPLE_SEASON = TARGET_SEASON  # every feature (xG, DEFCON) is populated in this season
SHAP_DEPENDENCE_FEATURES: list[str] = ["minutes_r3", "xgi_r5", "fdr"]
SHAP_TOP_K = 5  # top contributions per row written next to published predictions (P5)
SHAP_IMPORTANCE_PATH = PUBLISHED_DIR / "shap_importance.json"

# --- game rules for the optimizer (PLAN.md §3c) --------------------------------------------
# Prices are integer tenths of £1m (FPL now_cost: 55 = £5.5m), so budget checks are exact.

BUDGET = 1000
SQUAD_QUOTAS: dict[str, int] = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
XI_SIZE = 11
XI_MIN: dict[str, int] = {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}  # GK is exactly 1
MAX_PER_CLUB = 3
HIT_COST = 4  # points per transfer beyond the free ones
MAX_FREE_TRANSFERS = 5
MAX_TRANSFERS_PLANNED = 3
HORIZON = 3  # default number of gameweeks the optimizer looks ahead
HORIZON_DISCOUNT = 0.9  # weight of GW t+j is 0.9**j
BENCH_WEIGHT = 0.1

# --- optimizer backtest (PLAN.md §8 P4) ----------------------------------------------------

BACKTEST_SEASON = TARGET_SEASON
BACKTEST_START_GW = 5
BACKTEST_PATH = PUBLISHED_DIR / "backtest.json"

# --- live path: FPL API -> predictions (PLAN.md §8 P5) -------------------------------------
# The in-progress season lives apart from the 10-season training lake (data/lake/player_match/),
# so the historical row counts and the training set stay fixed.

LIVE_DIR = LAKE_DIR / "live"
LIVE_HISTORY_PATH = LIVE_DIR / "player_match" / f"season={CURRENT_SEASON}" / "part.parquet"
LIVE_PLAYERS_PATH = LIVE_DIR / "players.parquet"  # bootstrap-static elements, parsed
LIVE_FIXTURES_PATH = LIVE_DIR / "fixtures.parquet"  # every fixture of the season, parsed
LIVE_UPCOMING_ODDS_PATH = LIVE_DIR / "upcoming_odds.parquet"  # fixtures.csv E0 rows (next round)
LIVE_HISTORY_PAST_PATH = LIVE_DIR / "history_past.parquet"  # cold-start info, once per season
LIVE_META_PATH = LIVE_DIR / "meta.json"
API_CACHE_DIR = RAW_DIR / "fpl_api"  # raw JSON; element-summary cached per finished GW

PREDICT_HORIZON_MAX = 5  # the app's horizon slider goes up to this
REFRESH_WINDOW_HOURS = 48  # --refresh/--predict only run when the next deadline is this close
PUBLISHED_IMG_DIR = PUBLISHED_DIR / "img"  # model-card images the app shows
LATEST_PATH = PUBLISHED_DIR / "latest.json"  # pointer to the newest predictions + metadata
MAE_BY_GW_PATH = PUBLISHED_DIR / "mae_by_gw.json"
PUBLISHED_IMAGES: list[str] = [
    "mae_by_gw.png",
    "metrics_table.png",
    "shap_beeswarm.png",
    "shap_waterfall_premium_fwd.png",
    "shap_waterfall_budget_def.png",
    "backtest_cumulative.png",
    "odds_cs_calibration.png",
]
REPO_URL = "https://github.com/SudevOP1/FPLense"


def predictions_path(gw: int) -> Path:
    return PUBLISHED_DIR / f"predictions_gw{gw:02d}.parquet"


def shap_path(gw: int) -> Path:
    return PUBLISHED_DIR / f"shap_gw{gw:02d}.parquet"


def squad_path(gw: int) -> Path:
    return PUBLISHED_DIR / f"squad_gw{gw:02d}.json"
