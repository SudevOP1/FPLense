"""Create the DuckDB feature store: run ``db/sql/*.sql`` in order against the Parquet lake.

The SQL files reference ``${lake}`` (the lake directory) and ``${team_names}`` (the club-name
map), substituted here, so the same views can be built over a different lake (the leakage test
builds them over a truncated copy).
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

from fPLense import config

log = logging.getLogger(__name__)


def sql_files(sql_dir: Path = config.SQL_DIR) -> list[Path]:
    return sorted(sql_dir.glob("*.sql"))


def _sql_path(path: Path) -> str:
    """Absolute POSIX path, single quotes escaped for a SQL string literal."""
    return Path(path).resolve().as_posix().replace("'", "''")


def render(sql: str, lake_dir: Path, team_names: Path) -> str:
    return sql.replace("${lake}", _sql_path(lake_dir)).replace(
        "${team_names}", _sql_path(team_names)
    )


def build(
    db_path: Path | str = config.DUCKDB_PATH,
    lake_dir: Path = config.LAKE_DIR,
    team_names: Path = config.TEAM_NAMES_PATH,
) -> duckdb.DuckDBPyConnection:
    """Run every SQL file and return the open connection (``db_path=":memory:"`` for tests)."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    for path in sql_files():
        log.info("run %s", path.name)
        con.execute(render(path.read_text(encoding="utf-8"), lake_dir, team_names))
    return con


def features(con: duckdb.DuckDBPyConnection, where: str = "") -> pd.DataFrame:
    """``v_features`` as a DataFrame, ordered by season, kickoff, fixture, element."""
    clause = f"where {where}" if where else ""
    return con.sql(
        f"select * from v_features {clause} order by season, kickoff_time, fixture, element"
    ).df()


def summary(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Row counts and coverage numbers printed by ``pipeline --build``."""

    def one(q: str) -> int:
        return int(con.sql(q).fetchone()[0])

    return {
        "v_player_match rows": one("select count(*) from v_player_match"),
        "v_team_match rows": one("select count(*) from v_team_match"),
        "fixtures": one("select count(*) from v_fixture_odds"),
        "fixtures with odds": one("select count(*) from v_fixture_odds where p_home is not null"),
        "fixtures with implied goals": one(
            "select count(*) from v_fixture_odds where lam_home is not null"
        ),
        "team rows with Elo diff": one(
            "select count(*) from v_match_odds where elo_diff is not null"
        ),
        "v_features rows": one("select count(*) from v_features"),
        "features": len(config.FEATURES),
    }
