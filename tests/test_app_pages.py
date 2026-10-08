"""Smoke tests: every Streamlit page runs headless (``AppTest``, no server) on the committed
``data/published/`` files without raising. The Transfer Planner is driven with the saved picks
sample in session state, so no network call is made."""

from __future__ import annotations

import json

import pytest

from fPLense import config
from fPLense.etl.fetch_api import parse_picks

APP = config.ROOT / "app"
PAGES = [
    "Home.py",
    "pages/1_Projections.py",
    "pages/2_Optimal_Squad.py",
    "pages/3_Transfer_Planner.py",
    "pages/4_Model_Card.py",
]


@pytest.fixture(scope="module", autouse=True)
def published():
    if not config.LATEST_PATH.exists():
        pytest.skip("no published predictions (run the --refresh --predict pipeline)")


def run(page: str, session: dict | None = None):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP / page), default_timeout=120)
    for k, v in (session or {}).items():
        at.session_state[k] = v
    return at.run()


@pytest.mark.parametrize("page", PAGES)
def test_page_runs(page):
    at = run(page)
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def test_optimal_squad_shows_a_legal_squad():
    at = run("pages/2_Optimal_Squad.py")
    labels = [m.label for m in at.metric]
    assert any(label.startswith("Expected points") for label in labels)
    cost = next(m.value for m in at.metric if m.label == "Squad cost")
    assert float(cost.strip("£m")) <= config.BUDGET / 10


def test_transfer_planner_with_saved_picks():
    raw = json.loads((config.TESTS_FIXTURES_DIR / "picks_sample.json").read_text("utf-8"))
    at = run("pages/3_Transfer_Planner.py", {"picks": parse_picks(raw), "team_id": 1})
    assert not at.exception, [e.value for e in at.exception]
    assert at.success and "Recommendation" in at.success[0].value
    assert len(at.dataframe) >= 1
