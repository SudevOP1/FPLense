"""API: /squads/best, /squads/optimize, /squads/evaluate, /history/*."""

from __future__ import annotations

from fPLense import config
from fPLense.api import schemas


def legal(sq: schemas.Squad) -> None:
    by_id = {p.id: p for p in sq.players}
    assert len(sq.players) == 15 and len(sq.starters) == 11 and len(sq.bench) == 4
    pos = [p.pos for p in sq.players]
    assert {q: pos.count(q) for q in config.SQUAD_QUOTAS} == config.SQUAD_QUOTAS
    clubs = [p.club for p in sq.players]
    assert max(clubs.count(c) for c in clubs) <= 3
    xi = [by_id[i].pos for i in sq.starters]
    assert xi.count("GK") == 1 and xi.count("DEF") >= 3 and xi.count("MID") >= 2
    assert sq.captain in sq.starters and sq.vice in sq.starters and sq.captain != sq.vice
    assert sq.cost == sum(p.price for p in sq.players)
    assert [by_id[i].pos for i in sq.starters] == sorted(xi, key=list(config.SQUAD_QUOTAS).index)


def test_best_next_gw(client):
    sq = schemas.Squad(**client.get("/api/squads/best").json())
    legal(sq)
    assert sq.kind == "model_pick" and sq.gw == 3 and sq.actual_points is None
    assert sq.cost <= 1000 and sq.code.startswith("FPLN-2627-")
    assert [h.gw for h in sq.horizon_expected] == [3, 4]


def test_best_past_gw_is_the_frozen_archive(client):
    sq = schemas.Squad(**client.get("/api/squads/best?gw=1").json())
    legal(sq)
    assert sq.gw == 1 and sq.source == "backfill" and sq.actual_points is not None
    assert all(p.actual is not None for p in sq.players)
    assert client.get("/api/squads/best?gw=4").status_code == 404  # no pick made for GW4 yet


def test_optimize_default_and_settings(client):
    r = client.post("/api/squads/optimize", json={})
    assert r.status_code == 200
    sq = schemas.Squad(**r.json())
    legal(sq)
    assert sq.kind == "optimized" and sq.problems == []
    cheap = schemas.Squad(**client.post("/api/squads/optimize", json={"budget": 850}).json())
    assert cheap.cost <= 850 and cheap.budget == 850
    one = schemas.Squad(**client.post("/api/squads/optimize", json={"horizon": 1}).json())
    assert [h.gw for h in one.horizon_expected] == [3]


def test_optimize_locks_and_bans(client):
    base = schemas.Squad(**client.post("/api/squads/optimize", json={}).json())
    banned = base.starters[:3]
    outside = [i for i in range(1, 60) if i not in base.starters + base.bench][:1]
    sq = schemas.Squad(
        **client.post("/api/squads/optimize", json={"locked": outside, "banned": banned}).json()
    )
    ids = {p.id for p in sq.players}
    assert set(outside) <= ids and not set(banned) & ids


def test_optimize_impossible_locks_name_the_rule(client):
    gks = [1, 7, 13]  # three goalkeepers (club layout: GK first of every 6)
    r = client.post("/api/squads/optimize", json={"locked": gks})
    assert r.status_code == 422
    assert r.json()["kind"] == "quota" and "GK" in r.json()["detail"]
    club_a = [2, 3, 4, 5]  # four players from Club A
    r = client.post("/api/squads/optimize", json={"locked": club_a})
    assert r.status_code == 422 and r.json()["kind"] == "club limit"
    r = client.post("/api/squads/optimize", json={"locked": [4242]})
    assert r.status_code == 422 and r.json()["kind"] == "unknown"
    assert client.post("/api/squads/optimize", json={"budget": 10}).status_code == 422
    assert client.post("/api/squads/optimize", json={"horizon": 9}).status_code == 422


def test_evaluate_partial_and_full(client, mini_squad):
    r = client.post("/api/squads/evaluate", json={"players": mini_squad[:5]})
    out = schemas.EvaluateOut(**r.json())
    assert not out.legal and any(p.rule == "size" for p in out.problems)
    full = schemas.EvaluateOut(
        **client.post("/api/squads/evaluate", json={"players": mini_squad}).json()
    )
    assert full.legal and len(full.starters) == 11 and full.captain in full.starters
    assert [h.gw for h in full.horizon_expected] == [3, 4]
    assert full.expected_points == full.horizon_expected[0].points


def test_evaluate_finished_gw_scores_actuals(client, mini_squad):
    out = schemas.EvaluateOut(
        **client.post("/api/squads/evaluate", json={"players": mini_squad, "gw": 2}).json()
    )
    assert out.finished and out.actual_points is not None and out.gw == 2


def test_evaluate_reports_club_and_budget(client):
    r = client.post("/api/squads/evaluate", json={"players": [2, 3, 4, 5]})
    rules = {p["rule"] for p in r.json()["problems"]}
    assert "club" in rules
    assert (
        client.post("/api/squads/evaluate", json={"players": list(range(1, 17))}).status_code == 422
    )


def test_history_summary(client):
    s = schemas.HistorySummary(**client.get("/api/history/summary").json())
    assert [r.gw for r in s.gws] == [1, 2]
    for r in s.gws:
        assert 0 <= r.capture_ratio <= 1
        assert r.hindsight_points >= r.model_actual
    assert [e.gw for e in s.events] == [1, 2, 3, 4]


def test_history_gw(client):
    h = schemas.HistoryGw(**client.get("/api/history/1").json())
    assert h.source == "backfill" and h.caveat
    legal(h.model_pick)
    legal(h.hindsight)
    assert h.hindsight.actual_points >= h.model_pick.actual_points
    assert h.summary.model_actual == h.model_pick.actual_points
    assert h.summary.hindsight_points == h.hindsight.actual_points
    live = schemas.HistoryGw(**client.get("/api/history/2").json())
    assert live.source == "live"
    assert client.get("/api/history/9").status_code == 404
    assert client.get("/api/history/0").status_code == 422
