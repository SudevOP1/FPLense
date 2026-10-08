from __future__ import annotations

import pytest

from fPLense import config


@pytest.fixture(scope="session")
def lake_dir():
    """The downloaded Parquet lake; tests using it skip cleanly on fresh clones / CI."""
    if not config.PLAYER_MATCH_DIR.exists() or not any(config.PLAYER_MATCH_DIR.iterdir()):
        pytest.skip(
            f"data lake not found at {config.PLAYER_MATCH_DIR}; "
            "run `python -m fPLense.pipeline --refresh-history` first"
        )
    return config.PLAYER_MATCH_DIR


@pytest.fixture(scope="session")
def full_lake_dir(lake_dir):
    """The lake with odds and Elo as well; skips if P2's downloads haven't run."""
    for path, flag in [(config.ODDS_DIR, "--refresh-odds"), (config.ELO_DIR, "--refresh-elo")]:
        if not path.exists() or not any(path.iterdir()):
            pytest.skip(f"{path} not found; run `python -m fPLense.pipeline {flag}` first")
    return config.LAKE_DIR


@pytest.fixture(scope="session")
def feature_store(full_lake_dir):
    """DuckDB views over the real lake, built in memory (the on-disk file is left alone)."""
    from fPLense.db.build import build

    con = build(":memory:", lake_dir=full_lake_dir)
    yield con
    con.close()
