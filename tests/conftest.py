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


# --- API fixtures (P6): a synthetic published folder and a mocked FPL API --------------------

ENTRY_ID = 6740613  # the developer's own team (samples saved with consent)
MISSING_ID = 999
UPDATING_ID = 503


@pytest.fixture(scope="session")
def published_mini(tmp_path_factory):
    from published_mini import build

    return build(tmp_path_factory.mktemp("published_mini"))


@pytest.fixture(scope="session")
def mini_squad(published_mini):
    """The mini folder's model pick for GW3 as ordered ids (11 starters GK -> FWD, then bench)."""
    import json

    doc = json.loads((published_mini / "squad_gw03.json").read_text(encoding="utf-8"))
    starters = [p["element"] for p in doc["players"] if p["starter"]]
    bench = sorted((p for p in doc["players"] if not p["starter"]), key=lambda p: p["bench_order"])
    return starters + [p["element"] for p in bench]


class FakeFpl:
    """``httpx.MockTransport`` handler standing in for fantasy.premierleague.com."""

    def __init__(self, squad: list[int]):
        import json

        self.squad = squad
        self.calls: list[str] = []
        fx = config.TESTS_FIXTURES_DIR
        self.entry = json.loads((fx / "entry_sample.json").read_text(encoding="utf-8"))
        self.entry["current_event"] = 2
        self.history = json.loads((fx / "entry_history_sample.json").read_text(encoding="utf-8"))

    def __call__(self, request):
        import re

        import httpx
        from published_mini import picks_json

        path = request.url.path.removeprefix("/api")
        self.calls.append(path)
        m = re.fullmatch(r"/entry/(\d+)/(?:(history)/|event/(\d+)/picks/)?", path)
        if not m:
            return httpx.Response(404, json={"detail": "Not found."})
        team = int(m.group(1))
        if team == UPDATING_ID:
            return httpx.Response(503, text="The game is being updated.")
        if team != ENTRY_ID:
            return httpx.Response(404, json={"detail": "No Entry matches the given query."})
        if m.group(2):
            return httpx.Response(200, json=self.history)
        if m.group(3):
            gw = int(m.group(3))
            if gw > 2:
                return httpx.Response(404, json={"detail": "Not found."})
            return httpx.Response(200, json=picks_json(self.squad, gw))
        return httpx.Response(200, json=self.entry)


@pytest.fixture
def fake_fpl(mini_squad):
    return FakeFpl(mini_squad)


@pytest.fixture
def make_client(published_mini, fake_fpl):
    """``make_client(**create_app kwargs)`` -> a TestClient on the mini folder and fake FPL."""
    import httpx
    from fastapi.testclient import TestClient

    from fPLense.api.fpl_proxy import FplProxy
    from fPLense.api.main import create_app

    clients = []

    async def no_sleep(_):
        return None

    def make(**kwargs):
        proxy = FplProxy(transport=httpx.MockTransport(fake_fpl), sleep=no_sleep, backoff=0)
        kwargs.setdefault("rate_capacity", 1000)
        app = create_app(published_dir=published_mini, proxy=proxy, **kwargs)
        client = TestClient(app)
        clients.append(client)
        return client

    yield make
    for c in clients:
        c.close()


@pytest.fixture
def client(make_client):
    return make_client()
