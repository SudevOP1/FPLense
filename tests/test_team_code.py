"""Team codes: round trips, the shared vectors, typo detection and specific error messages."""

from __future__ import annotations

import json

import numpy as np
import pytest
from pools import random_pool

from fPLense import config, team_code
from fPLense.optimize.squad_ilp import pick_squad

VECTORS = json.loads((config.TESTS_FIXTURES_DIR / "team_code_vectors.json").read_text("utf-8"))
PLAYERS = {int(k): v for k, v in VECTORS["players"].items()}


def test_crc8_standard_check_value():
    # CRC-8/SMBUS check value for "123456789" is 0xF4: pins the polynomial and init value
    assert team_code.crc8(b"123456789") == 0xF4 == VECTORS["crc8_check"]["crc"]


@pytest.mark.parametrize("v", VECTORS["valid"], ids=lambda v: v["name"])
def test_shared_vectors_byte_for_byte(v):
    team = team_code.TeamCode(
        v["season"], tuple(v["starters"] + v["bench"]), v["captain"], v["vice"]
    )
    assert team_code.payload(team).hex() == v["bytes_hex"]
    assert team_code.encode(v["starters"], v["bench"], v["captain"], v["vice"]) == v["code"]
    back = team_code.decode(v["code"])
    assert back.starters == v["starters"] and back.bench == v["bench"]
    assert (back.captain, back.vice) == (v["captain"], v["vice"])
    info = team_code.validate(back, PLAYERS)
    assert info["cost"] == sum(PLAYERS[i]["price"] for i in back.players)


@pytest.mark.parametrize("v", VECTORS["invalid"], ids=lambda v: v["name"])
def test_shared_invalid_vectors(v):
    with pytest.raises(team_code.TeamCodeError) as err:
        team_code.decode(v["input"])
    assert err.value.kind == v["kind"]


def test_code_length_and_alphabet():
    code = VECTORS["valid"][0]["code"]
    assert len(code) == len("FPLN-2627-") + team_code.CODE_CHARS == 66
    assert not set(code.split("-")[-1]) & set("ILOU")


@pytest.mark.parametrize("seed", range(8))
def test_round_trip_random_legal_squads(seed):
    pool = random_pool(n=300, seed=seed)
    res = pick_squad(pool)
    starters = sorted(
        res.starters, key=lambda i: list(config.SQUAD_QUOTAS).index(pool.at[i, "pos"])
    )
    code = team_code.encode(starters, res.bench, res.captain, res.vice)
    back = team_code.decode(code)
    assert back.starters == starters and back.bench == res.bench
    assert back.captain == res.captain and back.vice == res.vice
    players = {i: {"pos": r.pos, "club": r.club, "price": r.price} for i, r in pool.iterrows()}
    assert team_code.validate(back, players)["cost"] == res.cost


@pytest.mark.parametrize("v", VECTORS["valid"], ids=lambda v: v["name"])
def test_every_single_character_typo_is_caught(v):
    prefix, body = v["code"][: -team_code.CODE_CHARS], v["code"][-team_code.CODE_CHARS :]
    caught = 0
    for k, ch in enumerate(body):
        for other in team_code.ALPHABET:
            if other == ch:
                continue
            typo = prefix + body[:k] + other + body[k + 1 :]
            with pytest.raises(team_code.TeamCodeError) as err:
                team_code.decode(typo)
            assert err.value.kind in {"typo", "version", "season", "duplicate", "captain"}
            caught += 1
    assert caught == len(body) * (len(team_code.ALPHABET) - 1)
    # a typo in the season label is caught too
    for k in range(5, 9):
        for d in "0123456789":
            if d == v["code"][k]:
                continue
            with pytest.raises(team_code.TeamCodeError):
                team_code.decode(v["code"][:k] + d + v["code"][k + 1 :])


def test_checksum_flags_body_typos_as_typos():
    # substitutions never pass the CRC: the error is always the checksum one or a format one
    code = VECTORS["valid"][0]["code"]
    rng = np.random.default_rng(0)
    for k in rng.choice(team_code.CODE_CHARS, size=20, replace=False):
        pos = len(code) - team_code.CODE_CHARS + int(k)
        other = "Z" if code[pos] != "Z" else "Y"
        with pytest.raises(team_code.TeamCodeError) as err:
            team_code.decode(code[:pos] + other + code[pos + 1 :])
        assert err.value.kind == "typo"


@pytest.mark.parametrize(
    "transform",
    [
        str.lower,
        lambda c: f"  {c}\n",
        lambda c: c.replace("-", ""),
        lambda c: f"https://fplense.app/compare?t={c}",
        lambda c: f"/builder?x=1&t={c.lower()}",
        lambda c: c.replace("1", "I").replace("0", "O"),  # Crockford aliases
        lambda c: c[:20] + " " + c[20:],  # whitespace inside (chat apps wrap)
    ],
)
def test_forgiving_input_forms(transform):
    v = VECTORS["valid"][0]
    back = team_code.decode(transform(v["code"]))
    assert back.starters == v["starters"]


def test_specific_messages():
    v = VECTORS["valid"][0]
    with pytest.raises(team_code.TeamCodeError, match="2025-26"):
        team_code.decode(next(x for x in VECTORS["invalid"] if x["kind"] == "season")["input"])
    with pytest.raises(team_code.TeamCodeError, match="typo"):
        team_code.decode(v["code"][:-1] + ("A" if v["code"][-1] != "A" else "B"))
    with pytest.raises(team_code.TeamCodeError, match="FPLN"):
        team_code.decode("")


def test_validate_rejects_unknown_shape_and_club():
    v = VECTORS["valid"][0]
    team = team_code.decode(v["code"])
    missing = dict(PLAYERS)
    missing.pop(v["starters"][3])
    with pytest.raises(team_code.TeamCodeError) as err:
        team_code.validate(team, missing)
    assert err.value.kind == "unknown"

    swapped = dict(PLAYERS)
    swapped[v["starters"][1]] = {**PLAYERS[v["starters"][1]], "pos": "MID"}  # 4 DEF, 6 MID
    with pytest.raises(team_code.TeamCodeError, match="DEF") as err:
        team_code.validate(team, swapped)
    assert err.value.kind == "shape"

    one_club = {i: {**p, "club": "C0"} if i in v["starters"][:4] else p for i, p in PLAYERS.items()}
    with pytest.raises(team_code.TeamCodeError, match="C0") as err:
        team_code.validate(team, one_club)
    assert err.value.kind == "club"


def test_illegal_xi_shape():
    v = VECTORS["valid"][0]
    # 2 GK in the XI: swap the bench GK with a starting DEF
    starters = [v["bench"][3], *v["starters"][:1], *v["starters"][2:]]
    bench = [*v["bench"][:3], v["starters"][1]]
    team = team_code.decode(team_code.encode(starters, bench, v["captain"], v["vice"]))
    with pytest.raises(team_code.TeamCodeError, match="XI") as err:
        team_code.validate(team, PLAYERS)
    assert err.value.kind == "shape"


def test_budget_reported_not_enforced():
    v = VECTORS["valid"][0]
    rich = {i: {**p, "price": 100} for i, p in PLAYERS.items()}  # 15 x £10.0m = £150m
    info = team_code.validate(team_code.decode(v["code"]), rich)
    assert info == {"cost": 1500, "over_budget": True}


def test_encode_refuses_bad_teams():
    v = VECTORS["valid"][0]
    with pytest.raises(team_code.TeamCodeError) as err:
        team_code.encode(
            v["starters"], v["bench"][:3] + [v["starters"][0]], v["captain"], v["vice"]
        )
    assert err.value.kind == "duplicate"
    with pytest.raises(team_code.TeamCodeError) as err:
        team_code.encode(v["starters"], v["bench"], v["bench"][0], v["vice"])
    assert err.value.kind == "captain"
