"""API: /compare, /transfers/plan and /codes/*."""

from __future__ import annotations

import json

from conftest import ENTRY_ID

from fPLense import config
from fPLense.api import schemas

# --- compare ----------------------------------------------------------------------------------


def test_compare_two_slots(client):
    body = {"slots": [{"kind": "model_pick", "gw": 1}, {"kind": "hindsight", "gw": 1}]}
    r = client.post("/api/compare", json=body)
    assert r.status_code == 200
    out = schemas.CompareOut(**r.json())
    a, b = out.slots
    assert (a.letter, b.letter) == ("A", "B")
    assert a.squad.actual_points <= b.squad.actual_points
    assert sum(x.expected for x in a.by_position) >= 0 and len(a.by_position) == 4
    shared = {s.id for s in out.shared}
    assert shared == {p.id for p in a.squad.players} & {p.id for p in b.squad.players}
    assert set(a.differentials).isdisjoint(shared) and len(a.differentials) == 15 - len(shared)
    assert [h.gw for h in out.horizon] == [1]


def test_compare_three_slots_each_with_its_own_gw(client, mini_squad):
    body = {
        "slots": [
            {"kind": "entry", "gw": 2, "value": ENTRY_ID},
            {"kind": "model_pick"},
            {"kind": "squad", "value": mini_squad, "label": "Draft"},
        ]
    }
    r = client.post("/api/compare", json=body)
    assert r.status_code == 200, r.text
    out = schemas.CompareOut(**r.json())
    assert [s.squad.gw for s in out.slots] == [2, 3, 3]
    assert out.slots[0].squad.actual_points is not None and out.slots[0].bench_actual is not None
    assert out.slots[1].squad.actual_points is None
    assert out.slots[2].squad.label == "Draft"
    # the custom squad IS the model pick: everything shared between B and C
    assert {s.id for s in out.shared if "B" in s.slots and "C" in s.slots} == set(mini_squad)
    assert [h.gw for h in out.horizon] == [2, 3, 4]
    row3 = next(h for h in out.horizon if h.gw == 3)
    # same 15 players; C gets the lineup helper's XI, picked for GW3 alone, so it can't do worse
    # in GW3 than the model pick's XI (chosen for the whole horizon)
    assert row3.points[0] is None and row3.points[2] >= row3.points[1] - 1e-9


def test_compare_rejects_one_and_four_slots(client):
    one = {"slots": [{"kind": "model_pick"}]}
    four = {"slots": [{"kind": "model_pick"}] * 4}
    assert client.post("/api/compare", json=one).status_code == 422
    assert client.post("/api/compare", json=four).status_code == 422


def test_compare_bad_code_slot(client):
    body = {"slots": [{"kind": "model_pick"}, {"kind": "code", "value": "FPLN-2627-NOPE"}]}
    r = client.post("/api/compare", json=body)
    assert r.status_code == 422 and r.json()["kind"] == "typo"
    bad = {"slots": [{"kind": "model_pick"}, {"kind": "squad", "value": [1, 2]}]}
    assert client.post("/api/compare", json=bad).status_code == 422


# --- transfers --------------------------------------------------------------------------------


def test_transfer_plan_from_an_explicit_squad(client, mini_squad):
    squad = mini_squad[:-1] + [x for x in range(1, 61) if x not in mini_squad and x % 6 == 1][:1]
    body = {"squad": squad, "bank": 20, "free_transfers": 1, "max_transfers": 5}
    r = client.post("/api/transfers/plan", json=body)
    assert r.status_code == 200, r.text
    out = schemas.TransferOut(**r.json())
    assert [o.n_transfers for o in out.options][0] == 0
    assert max(o.n_transfers for o in out.options) <= 5
    assert sum(o.recommended for o in out.options) == 1
    for o in out.options:
        assert o.hits == 4 * max(0, o.n_transfers - 1)
        assert len(o.moves) == o.n_transfers
        assert all(m.out.pos == m.into.pos for m in o.moves)
    assert out.path is not None and out.path.advice
    target = {p.id for p in out.path.target.players}
    for s in out.path.steps:
        assert all(m.into.id in target and m.out.id not in target for m in s.new_moves)
    assert "selling price" in out.caveat


def test_transfer_plan_from_a_team_id(client, mini_squad):
    r = client.post("/api/transfers/plan", json={"team_id": ENTRY_ID, "max_transfers": 2})
    assert r.status_code == 200, r.text
    out = schemas.TransferOut(**r.json())
    assert out.bank == 15  # prefilled from the picks' entry_history
    assert {p.id for p in out.current.players} == set(mini_squad)
    assert out.options[0].net_gain == 0.0


def test_transfer_plan_needs_a_squad(client):
    r = client.post("/api/transfers/plan", json={})
    assert r.status_code == 422
    assert client.post("/api/transfers/plan", json={"squad": [1, 2, 3]}).status_code == 422
    assert (
        client.post(
            "/api/transfers/plan", json={"squad": list(range(1, 16)), "free_transfers": 9}
        ).status_code
        == 422
    )


# --- team codes -------------------------------------------------------------------------------


def test_code_round_trip(client):
    best = schemas.Squad(**client.get("/api/squads/best").json())
    bench = best.bench
    body = {"starters": best.starters, "bench": bench, "captain": best.captain, "vice": best.vice}
    enc = schemas.EncodeOut(**client.post("/api/codes/encode", json=body).json())
    assert enc.code == best.code and enc.share_param == f"t={enc.code}"
    dec = schemas.DecodeOut(
        **client.post("/api/codes/decode", json={"code": f" {enc.code.lower()} "}).json()
    )
    assert dec.squad.starters == best.starters and dec.squad.captain == best.captain
    assert not dec.over_budget
    url = client.post("/api/codes/decode", json={"code": f"https://x.app/compare?t={enc.code}"})
    assert url.status_code == 200


def test_decode_errors_are_specific(client):
    vectors = json.loads((config.TESTS_FIXTURES_DIR / "team_code_vectors.json").read_text("utf-8"))
    season = next(v for v in vectors["invalid"] if v["kind"] == "season")
    r = client.post("/api/codes/decode", json={"code": season["input"]})
    assert r.status_code == 422 and r.json()["kind"] == "season" and "2025-26" in r.json()["detail"]
    r = client.post("/api/codes/decode", json={"code": "hello"})
    assert r.json()["kind"] == "junk"
    # a well-formed code whose ids aren't players of this (mini) season
    unknown = vectors["valid"][2]["code"]
    r = client.post("/api/codes/decode", json={"code": unknown})
    assert r.status_code == 422 and r.json()["kind"] == "unknown"


def test_encode_rejects_illegal_teams(client):
    best = schemas.Squad(**client.get("/api/squads/best").json())
    dup = {
        "starters": best.starters,
        "bench": best.bench[:3] + [best.starters[0]],
        "captain": best.captain,
        "vice": best.vice,
    }
    assert client.post("/api/codes/encode", json=dup).status_code == 422
    four_gk = {
        "starters": best.starters,
        "bench": best.bench,
        "captain": best.bench[0],
        "vice": best.vice,
    }
    r = client.post("/api/codes/encode", json=four_gk)
    assert r.status_code == 422 and r.json()["kind"] == "captain"
