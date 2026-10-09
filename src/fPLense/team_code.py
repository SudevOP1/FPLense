"""Shareable copy-paste team codes (PLAN.md §8 P6), e.g. ``FPLN-2627-0G2Q...``.

Payload (35 bytes, big-endian):

    version (1 byte) | season (uint16, 2627 = 2026-27) | 15 player ids (uint16 each:
    the 11 starters GK -> FWD, then the 4 bench slots in bench order) |
    captain index << 4 | vice index (1 byte, both 0..10) | CRC-8 of everything before it

encoded as **Crockford base32** (digits + letters without I, L, O, U; case-insensitive) behind a
readable prefix ``FPLN-<season>-``. 35 bytes = 280 bits = exactly 56 characters, no padding.
CRC-8 (polynomial 0x07) catches every error burst of up to 8 bits, so any single mistyped
character (5 bits) is detected.

``decode`` is forgiving about the *form* of the input (whitespace, any case, ``I/L`` for ``1`` and
``O`` for ``0``, a full share URL with ``?t=<code>``) and strict about the *content*: a bad
checksum, another season, duplicates, unknown players or an illegal squad each get their own
message. The budget is reported, never enforced (real teams can be worth more than £100m).

The same test vectors (``tests/fixtures/team_code_vectors.json``) run in pytest and in the P7
TypeScript implementation, so both agree byte for byte.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from fPLense import config

VERSION = 1
PREFIX = "FPLN"
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32
_DECODE = {ch: k for k, ch in enumerate(ALPHABET)} | {"I": 1, "L": 1, "O": 0}
N_PLAYERS = 15
N_STARTERS = 11
PAYLOAD_BYTES = 1 + 2 + 2 * N_PLAYERS + 1 + 1
CODE_CHARS = PAYLOAD_BYTES * 8 // 5  # 56


def season_number(season: str = config.CURRENT_SEASON) -> int:
    """``"2026-27"`` -> ``2627``."""
    return int(season[2:4] + season[5:7])


def season_label(number: int) -> str:
    """``2526`` -> ``"2025-26"``."""
    s = f"{int(number):04d}"
    return f"20{s[:2]}-{s[2:]}"


class TeamCodeError(ValueError):
    """A code that can't be used. ``kind`` is one of ``junk``, ``typo``, ``version``,
    ``season``, ``duplicate``, ``captain``, ``unknown``, ``shape``, ``club``."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class TeamCode:
    season: int  # e.g. 2627
    players: tuple[int, ...]  # 11 starters (GK -> FWD) then 4 bench in order
    captain: int  # player id
    vice: int  # player id

    @property
    def starters(self) -> list[int]:
        return list(self.players[:N_STARTERS])

    @property
    def bench(self) -> list[int]:
        return list(self.players[N_STARTERS:])


# --- checksum and base32 ----------------------------------------------------------------------


def crc8(data: bytes, poly: int = 0x07, init: int = 0x00) -> int:
    """CRC-8 (SMBus: polynomial x^8 + x^2 + x + 1, init 0, no reflection, no final xor)."""
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def b32encode(data: bytes) -> str:
    bits = int.from_bytes(data, "big")
    n = len(data) * 8 // 5
    return "".join(ALPHABET[(bits >> (5 * (n - 1 - k))) & 31] for k in range(n))


def b32decode(text: str, n_bytes: int) -> bytes:
    bits = 0
    for ch in text:
        bits = (bits << 5) | _DECODE[ch]
    return bits.to_bytes(n_bytes, "big")


# --- encode / decode --------------------------------------------------------------------------


def payload(team: TeamCode) -> bytes:
    """The 35 raw bytes of a code (checksum included)."""
    ids = list(team.players)
    if len(ids) != N_PLAYERS:
        raise TeamCodeError("shape", f"a team code needs {N_PLAYERS} players, got {len(ids)}")
    if len(set(ids)) != N_PLAYERS:
        raise TeamCodeError("duplicate", "a player appears twice in the team")
    if any(not 0 < i < 2**16 for i in ids):
        raise TeamCodeError("unknown", "player ids must be between 1 and 65535")
    starters = ids[:N_STARTERS]
    if team.captain not in starters or team.vice not in starters or team.captain == team.vice:
        raise TeamCodeError("captain", "captain and vice-captain must be two different starters")
    armbands = (starters.index(team.captain) << 4) | starters.index(team.vice)
    body = struct.pack(f">BH{N_PLAYERS}HB", VERSION, team.season, *ids, armbands)
    return body + bytes([crc8(body)])


def encode(
    starters: list[int],
    bench: list[int],
    captain: int,
    vice: int,
    season: str = config.CURRENT_SEASON,
) -> str:
    """``FPLN-2627-<56 chars>``. ``starters`` should already be in GK -> FWD order."""
    number = season_number(season)
    team = TeamCode(number, tuple(int(i) for i in [*starters, *bench]), int(captain), int(vice))
    return f"{PREFIX}-{number:04d}-{b32encode(payload(team))}"


def extract(text: str) -> str:
    """Pull the code out of whatever was pasted: a bare code, any case, or a share URL."""
    raw = (text or "").strip()
    if "?" in raw or raw.lower().startswith(("http://", "https://", "/")):
        query = parse_qs(urlparse(raw).query)
        if query.get("t"):
            raw = query["t"][0]
    return re.sub(r"\s+", "", raw).upper()


def decode(text: str, season: str = config.CURRENT_SEASON) -> TeamCode:
    """Parse and check a code (form and checksum only; see :func:`validate` for the squad)."""
    code = extract(text)
    m = re.fullmatch(r"FPLN-?(\d{4})-?([0-9A-Z]+)", code)
    if not m:
        raise TeamCodeError("junk", "That isn't a FPLense team code (they start with FPLN-).")
    prefix_season, body = int(m.group(1)), m.group(2)
    if any(ch not in _DECODE for ch in body) or len(body) != CODE_CHARS:
        raise TeamCodeError("typo", "This code looks like a typo: check it was copied in full.")
    raw = b32decode(body, PAYLOAD_BYTES)
    if crc8(raw[:-1]) != raw[-1]:
        raise TeamCodeError("typo", "This code looks like a typo: the checksum doesn't match.")
    version, number, *rest = struct.unpack(f">BH{N_PLAYERS}HB", raw[:-1])
    ids, armbands = rest[:N_PLAYERS], rest[N_PLAYERS]
    if version != VERSION:
        raise TeamCodeError(
            "version", f"This code was made by a newer FPLense (format v{version})."
        )
    if number != prefix_season:
        raise TeamCodeError("typo", "This code looks like a typo: its season label was changed.")
    if number != season_number(season):
        raise TeamCodeError(
            "season",
            f"This code is from {season_label(number)}; player ids change every season, so it "
            f"can't be loaded in {season}.",
        )
    if len(set(ids)) != N_PLAYERS:
        raise TeamCodeError("duplicate", "This code lists the same player twice.")
    cap, vice = armbands >> 4, armbands & 0x0F
    if cap >= N_STARTERS or vice >= N_STARTERS or cap == vice:
        raise TeamCodeError("captain", "This code's captain or vice-captain isn't a starter.")
    return TeamCode(number, tuple(ids), ids[cap], ids[vice])


def validate(team: TeamCode, players: dict[int, dict]) -> dict:
    """Check a decoded team against the season's players (``id -> {pos, club, price}``).

    Raises ``TeamCodeError`` for unknown ids, a broken 2-5-5-3 squad, a broken XI shape or more
    than 3 players from one club. Returns ``{"cost", "over_budget"}``: the budget is reported,
    not enforced.
    """
    unknown = [i for i in team.players if i not in players]
    if unknown:
        raise TeamCodeError(
            "unknown", f"This code has {len(unknown)} player(s) we don't know: {unknown}."
        )
    pos = [players[i]["pos"] for i in team.players]
    for p, n in config.SQUAD_QUOTAS.items():
        if pos.count(p) != n:
            raise TeamCodeError(
                "shape", f"This team has {pos.count(p)} {p}; a squad needs exactly {n}."
            )
    xi = pos[:N_STARTERS]
    if xi.count("GK") != 1 or any(xi.count(p) < config.XI_MIN[p] for p in ("DEF", "MID", "FWD")):
        raise TeamCodeError(
            "shape", "This team's XI isn't legal (1 GK, at least 3 DEF, 2 MID and 1 FWD)."
        )
    clubs: dict[str, int] = {}
    for i in team.players:
        c = str(players[i]["club"])
        clubs[c] = clubs.get(c, 0) + 1
    over = sorted(c for c, n in clubs.items() if n > config.MAX_PER_CLUB)
    if over:
        raise TeamCodeError(
            "club", f"This team has more than {config.MAX_PER_CLUB} players from {', '.join(over)}."
        )
    cost = sum(int(players[i]["price"]) for i in team.players)
    return {"cost": cost, "over_budget": cost > config.BUDGET}
