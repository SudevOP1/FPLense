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
