"""API: /health, /meta, /model, /players and /players/{id} on the synthetic published folder."""

from __future__ import annotations

from fastapi.testclient import TestClient

from fPLense.api import schemas
from fPLense.api.main import create_app


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = schemas.Health(**r.json())
    assert body.status == "ok" and body.next_gw == 3
    assert "etag" not in r.headers  # health is never cached


def test_health_without_published_data(tmp_path):
    with TestClient(create_app(published_dir=tmp_path)) as c:
        assert c.get("/api/health").json()["status"] == "no_data"
        r = c.get("/api/meta")
        assert r.status_code == 503 and r.json()["kind"] == "not_published"


def test_meta(client):
    m = schemas.Meta(**client.get("/api/meta").json())
    assert m.next_gw == 3 and m.gws == [3, 4]
    assert m.finished_gws == [1, 2] and m.current_gw == 2
    assert m.archived_gws == [1, 2]
    assert m.backfilled_gws == [1] and m.live_gws == [2]
    assert m.headline is not None and m.headline.gain_pct == 11.4
    assert m.rating_source == "fplense"


def test_model_card(client):
    body = client.get("/api/model").json()
    assert body["headline"]["ci"] == [10.2, 12.6]


def test_players_next_gw(client):
    r = client.get("/api/players")
    assert r.status_code == 200
    out = schemas.PlayersOut(**r.json())
    assert out.gw == 3 and out.source == "latest" and not out.finished
    assert len(out.players) == 60
    p = out.players[0]
    assert [e.gw for e in p.expected] == [3, 4]
    assert p.P_h >= out.players[-1].P_h  # sorted by P_h
    assert p.photo_url.endswith(f"/{p.code}.png")
    assert 50 <= p.rating <= 99 and p.rating_source == "fplense"
    assert p.actual is None
    assert all(f.gw in (3, 4) for f in p.fixtures) and p.fixtures
    injured = next(x for x in out.players if x.status == "i")
    assert injured.availability == 0.0 and injured.p == 0.0 and injured.news == "Knee"


def test_players_finished_gw_has_actuals(client):
    out = schemas.PlayersOut(**client.get("/api/players?gw=1").json())
    assert out.finished and out.source == "backfill" and out.gws == [1]
    assert all(p.actual is not None and p.minutes is not None for p in out.players)
    assert sum(p.actual for p in out.players) > 0


def test_players_bad_gw(client):
    assert client.get("/api/players?gw=20").status_code == 404
    assert client.get("/api/players?gw=0").status_code == 422
    assert client.get("/api/players?gw=abc").status_code == 422


def test_player_detail(client):
    r = client.get("/api/players/5")
    assert r.status_code == 200
    d = schemas.PlayerDetail(**r.json())
    assert d.id == 5
    assert [g.gw for g in d.season] == [1, 2, 3, 4]
    assert d.season[0].source == "backfill" and d.season[0].actual is not None
    assert d.season[2].source == "latest" and d.season[2].actual is None
    assert d.shap and d.shap_base_value is not None
    total = d.shap_base_value + sum(s.shap for s in d.shap)
    assert abs(total - d.shap_prediction) < 1e-4  # the waterfall adds up
    assert client.get("/api/players/9999").status_code == 404
    assert client.get("/api/players/0").status_code == 422


def test_etag_and_cache_control(client):
    r = client.get("/api/players")
    etag = r.headers["etag"]
    assert r.headers["cache-control"] == "public, max-age=300"
    again = client.get("/api/players", headers={"If-None-Match": etag})
    assert again.status_code == 304 and not again.content
    assert client.get("/api/players", headers={"If-None-Match": '"stale"'}).status_code == 200


def test_store_reloads_changed_files(published_mini, make_client):
    import json
    import os

    c = make_client()
    path = published_mini / "latest.json"
    original = path.read_text(encoding="utf-8")
    try:
        doc = json.loads(original)
        doc["generated_at"] = "2026-09-04T09:00:00+00:00"
        path.write_text(json.dumps(doc), encoding="utf-8")
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
        assert c.get("/api/health").json()["published_at"] == "2026-09-04T09:00:00+00:00"
    finally:
        path.write_text(original, encoding="utf-8")
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 20_000_000))
