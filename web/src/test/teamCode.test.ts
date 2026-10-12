// The TypeScript team codes must match the Python implementation byte for byte: both run the
// shared vectors in tests/fixtures/team_code_vectors.json (made by scripts/make_team_code_vectors.py).
import { describe, expect, it } from "vitest";
import vectors from "../../../tests/fixtures/team_code_vectors.json";
import {
  ALPHABET,
  CODE_CHARS,
  crc8,
  decode,
  encode,
  extract,
  looksLikeCode,
  payload,
  TeamCodeError,
  validate,
  type CodePlayer,
} from "@/lib/teamCode";

const players = Object.fromEntries(Object.entries(vectors.players).map(([id, p]) => [Number(id), p as CodePlayer]));
const hex = (bytes: Uint8Array) => [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");

function kindOf(fn: () => unknown): string | null {
  try {
    fn();
    return null;
  } catch (e) {
    expect(e).toBeInstanceOf(TeamCodeError);
    return (e as TeamCodeError).kind;
  }
}

describe("CRC-8", () => {
  it("matches the pinned check value (0xF4 for '123456789')", () => {
    const input = new TextEncoder().encode(vectors.crc8_check.input_ascii);
    expect(crc8(input)).toBe(vectors.crc8_check.crc);
    expect(crc8(input)).toBe(0xf4);
  });
});

describe("shared vectors", () => {
  it.each(vectors.valid)("encodes $name byte for byte", (v) => {
    const code = encode(v.starters, v.bench, v.captain, v.vice);
    expect(code).toBe(v.code);
    const bytes = payload({ season: v.season, players: [...v.starters, ...v.bench], captain: v.captain, vice: v.vice });
    expect(hex(bytes)).toBe(v.bytes_hex);
  });

  it.each(vectors.valid)("decodes $name back to the same team", (v) => {
    const team = decode(v.code);
    expect(team.season).toBe(v.season);
    expect(team.players).toEqual([...v.starters, ...v.bench]);
    expect(team.captain).toBe(v.captain);
    expect(team.vice).toBe(v.vice);
    expect(validate(team, players).cost).toBeGreaterThan(0);
  });

  it.each(vectors.invalid)("rejects $name as $kind", (v) => {
    expect(kindOf(() => decode(v.input))).toBe(v.kind);
  });

  it("catches every single-character typo in every vector", () => {
    let checked = 0;
    for (const v of vectors.valid) {
      const prefix = v.code.slice(0, v.code.length - CODE_CHARS);
      const body = v.code.slice(prefix.length);
      for (let k = 0; k < body.length; k++) {
        for (const ch of ALPHABET) {
          if (ch === body[k]) continue;
          const typo = prefix + body.slice(0, k) + ch + body.slice(k + 1);
          expect(kindOf(() => decode(typo)), typo).not.toBeNull();
          checked++;
        }
      }
    }
    expect(checked).toBe(vectors.valid.length * CODE_CHARS * 31);
  });
});

describe("forgiving input", () => {
  const v = vectors.valid[0];
  it("accepts any case, whitespace and look-alike letters", () => {
    expect(decode(v.code.toLowerCase()).players).toEqual([...v.starters, ...v.bench]);
    expect(decode(`  ${v.code.slice(0, 20)} \n ${v.code.slice(20)}  `).captain).toBe(v.captain);
    const withLookalikes = v.code.replace(/1/g, "l").replace(/0/g, "O");
    expect(decode(withLookalikes.replace(/^FPLN-2627/i, "FPLN-2627")).vice).toBe(v.vice);
  });

  it("accepts a full share URL", () => {
    const url = `https://fplense.app/compare?t=${encodeURIComponent(v.code)}`;
    expect(extract(url)).toBe(v.code);
    expect(decode(url).players).toHaveLength(15);
    expect(decode(`/builder?t=${v.code}`).captain).toBe(v.captain);
    expect(looksLikeCode(url)).toBe(true);
    expect(looksLikeCode("hello world")).toBe(false);
  });

  it("gives the specific squad messages from validate()", () => {
    const team = decode(v.code);
    const missing: Record<number, CodePlayer> = { ...players };
    delete missing[v.starters[0]];
    expect(kindOf(() => validate(team, missing))).toBe("unknown");
    const sameClub = Object.fromEntries(Object.entries(players).map(([id, p]) => [id, { ...p, club: "C1" }]));
    expect(kindOf(() => validate(team, sameClub))).toBe("club");
    const allMid = Object.fromEntries(Object.entries(players).map(([id, p]) => [id, { ...p, pos: "MID" }]));
    expect(kindOf(() => validate(team, allMid))).toBe("shape");
  });

  it("refuses to encode illegal teams", () => {
    const xi = [...v.starters];
    expect(kindOf(() => encode(xi, [v.bench[0], v.bench[0], v.bench[2], v.bench[3]], v.captain, v.vice))).toBe("duplicate");
    expect(kindOf(() => encode(xi, v.bench, v.bench[0], v.vice))).toBe("captain");
  });
});
