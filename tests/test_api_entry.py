"""API: /entry/* through the FPL proxy (mocked with httpx.MockTransport; no network)."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from conftest import ENTRY_ID, MISSING_ID, UPDATING_ID

from fPLense.api import schemas
from fPLense.api.fpl_proxy import FplNotFound, FplProxy, FplUnavailable, FplUpstreamError


def test_entry_joins_the_season_summary(client):
    r = client.get(f"/api/entry/{ENTRY_ID}")
    assert r.status_code == 200
    e = schemas.Entry(**r.json())
    assert e.id == ENTRY_ID and e.team_name and e.manager_name
    assert [g.gw for g in e.history] == [1, 2, 3, 4, 5]
    gw1 = e.history[0]
    assert gw1.model_pick_points is not None and gw1.hindsight_points is not None
    assert gw1.average_entry_score == 51
    assert e.history[3].model_pick_points is None  # GW4 isn't archived in the mini folder
    assert "cache-control" not in r.headers  # live FPL data: no shared caching


def test_unknown_team_is_a_friendly_404(client):
    r = client.get(f"/api/entry/{MISSING_ID}")
    assert r.status_code == 404
    assert r.json()["detail"] == f"No FPL team with ID {MISSING_ID}."


def test_fpl_updating_is_a_503_with_retry_hint(client):
    r = client.get(f"/api/entry/{UPDATING_ID}")
    assert r.status_code == 503
    assert "try again" in r.json()["detail"] and r.headers["retry-after"]


def test_team_id_validated(client):
    assert client.get("/api/entry/0").status_code == 422
    assert client.get("/api/entry/-4").status_code == 422
    assert client.get("/api/entry/abc").status_code == 422


def test_entry_gw_resolves_picks_with_points_and_lineup(client, mini_squad):
    r = client.get(f"/api/entry/{ENTRY_ID}/gw/2")
    assert r.status_code == 200
    out = schemas.EntryGwOut(**r.json())
    assert out.gw == 2 and out.predict_gw == 2
    assert {p.id for p in out.squad.players} == set(mini_squad)
    assert out.squad.actual_points is not None
    assert all(p.expected is not None for p in out.squad.players)  # from the frozen archive
    assert out.lineup is not None and len(out.lineup.starters) == 11
    assert set(out.lineup_changes) <= set(out.lineup.starters)
    nxt = schemas.EntryGwOut(**client.get(f"/api/entry/{ENTRY_ID}/gw/2?predict_gw=3").json())
    assert nxt.predict_gw == 3 and nxt.lineup.gw == 3


def test_picks_before_the_deadline_404(client):
    r = client.get(f"/api/entry/{ENTRY_ID}/gw/3")
    assert r.status_code == 404 and "GW3" in r.json()["detail"]


def test_finished_gw_picks_are_cached(client, fake_fpl):
    client.get(f"/api/entry/{ENTRY_ID}/gw/1")
    client.get(f"/api/entry/{ENTRY_ID}/gw/1")
    picks_calls = [c for c in fake_fpl.calls if c.endswith("/event/1/picks/")]
    assert len(picks_calls) == 1
    client.get(f"/api/entry/{ENTRY_ID}")
    client.get(f"/api/entry/{ENTRY_ID}")
    assert fake_fpl.calls.count(f"/entry/{ENTRY_ID}/") == 1  # 10-minute TTL


def test_rate_limit_429_with_retry_after(make_client):
    c = make_client(rate_capacity=2, rate_refill=0.01)
    assert c.get(f"/api/entry/{ENTRY_ID}").status_code == 200
    assert c.get(f"/api/entry/{ENTRY_ID}").status_code == 200
    r = c.get(f"/api/entry/{ENTRY_ID}")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert c.get("/api/players").status_code == 200  # published data isn't rate-limited


# --- the proxy on its own ---------------------------------------------------------------------


def run(coro):
    return asyncio.run(coro)


def make_proxy(handler, **kw):
    sleeps: list[float] = []

    async def sleep(s):
        sleeps.append(s)

    clock = iter(float(k) for k in range(10_000))
    proxy = FplProxy(
        transport=httpx.MockTransport(handler), sleep=sleep, clock=lambda: next(clock), **kw
    )
    return proxy, sleeps


def test_proxy_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(502)
        return httpx.Response(200, json={"current": [], "chips": []})

    proxy, sleeps = make_proxy(handler, retries=3, backoff=0.5)
    assert run(proxy.history(1)) == {"current": [], "chips": []}
    assert calls["n"] == 3 and 0.5 in sleeps and 1.0 in sleeps


def test_proxy_errors():
    proxy, _ = make_proxy(lambda r: httpx.Response(404, json={}), retries=1)
    with pytest.raises(FplNotFound):
        run(proxy.entry(5))
    proxy, _ = make_proxy(lambda r: httpx.Response(503), retries=1, backoff=0)
    with pytest.raises(FplUnavailable):
        run(proxy.entry(5))
    proxy, _ = make_proxy(lambda r: httpx.Response(200, json={"id": 1}), retries=0)
    with pytest.raises(FplUpstreamError, match="unexpected"):  # schema check
        run(proxy.entry(5))
    proxy, _ = make_proxy(lambda r: httpx.Response(403), retries=2)
    with pytest.raises(FplUpstreamError, match="403"):
        run(proxy.entry(5))


def test_proxy_spaces_calls():
    proxy, sleeps = make_proxy(lambda r: httpx.Response(404), retries=0, min_interval=5.0)

    async def two():
        for team in (1, 2):
            with pytest.raises(FplNotFound):
                await proxy.entry(team)

    run(two())
    assert any(s > 0 for s in sleeps)  # the second call waited for the limiter
    assert proxy.upstream_calls == 2


def test_proxy_lru_evicts_oldest_finished_picks():
    from published_mini import picks_json

    def handler(request):
        gw = int(request.url.path.split("/")[-3])
        return httpx.Response(200, json=picks_json(list(range(1, 16)), gw))

    proxy, _ = make_proxy(handler, lru_size=2)
    for gw in (1, 2, 3, 1):
        run(proxy.picks(7, gw, finished=True))
    assert proxy.upstream_calls == 4  # GW1 was evicted by GW3, so fetched again
    run(proxy.picks(7, 3, finished=True))
    assert proxy.upstream_calls == 4


def test_proxy_survives_a_new_event_loop():
    """The httpx client is bound to the running loop: a second loop gets a fresh client instead
    of reusing connections tied to a closed one (seen with a real connection pool)."""
    proxy, _ = make_proxy(lambda r: httpx.Response(200, json={"current": [], "chips": []}))

    async def call():
        await proxy.history(1)
        return proxy._client

    first = run(call())
    proxy._ttl_cache.clear()
    second = run(call())
    assert first is not second and proxy.upstream_calls == 2
