// TypeScript port of src/fPLense/team_code.py. Both run the same vectors
// (tests/fixtures/team_code_vectors.json), so Python and TypeScript agree byte for byte.
//
// Payload (35 bytes, big-endian): version u8 | season u16 | 15 player ids u16 (11 starters
// GK -> FWD, then the bench in order) | captain_idx << 4 | vice_idx | CRC-8 (poly 0x07, init 0),
// encoded as Crockford base32 (56 chars) behind "FPLN-<season>-".

export const VERSION = 1;
export const PREFIX = "FPLN";
export const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
export const N_PLAYERS = 15;
export const N_STARTERS = 11;
export const PAYLOAD_BYTES = 1 + 2 + 2 * N_PLAYERS + 1 + 1; // 35
export const CODE_CHARS = (PAYLOAD_BYTES * 8) / 5; // 56
export const CURRENT_SEASON = "2026-27";

const DECODE: Record<string, number> = Object.fromEntries([
  ...[...ALPHABET].map((ch, k) => [ch, k] as const),
  ["I", 1],
  ["L", 1],
  ["O", 0],
]);

const SQUAD_QUOTAS = { GK: 2, DEF: 5, MID: 5, FWD: 3 } as const;
const XI_MIN = { DEF: 3, MID: 2, FWD: 1 } as const;
const MAX_PER_CLUB = 3;
const BUDGET = 1000;

export type TeamCodeErrorKind =
  | "junk"
  | "typo"
  | "version"
  | "season"
  | "duplicate"
  | "captain"
  | "unknown"
  | "shape"
  | "club";

export class TeamCodeError extends Error {
  kind: TeamCodeErrorKind;

  constructor(kind: TeamCodeErrorKind, message: string) {
    super(message);
    this.name = "TeamCodeError";
    this.kind = kind;
  }
}

export interface TeamCode {
  season: number; // e.g. 2627
  players: number[]; // 11 starters then 4 bench
  captain: number;
  vice: number;
}

/** "2026-27" -> 2627 */
export function seasonNumber(season: string = CURRENT_SEASON): number {
  return Number(season.slice(2, 4) + season.slice(5, 7));
}

/** 2526 -> "2025-26" */
export function seasonLabel(n: number): string {
  const s = String(n).padStart(4, "0");
  return `20${s.slice(0, 2)}-${s.slice(2)}`;
}

/** CRC-8/SMBUS: polynomial x^8 + x^2 + x + 1, init 0, no reflection, no final xor. */
export function crc8(data: Uint8Array, poly = 0x07, init = 0x00): number {
  let crc = init;
  for (const byte of data) {
    crc ^= byte;
    for (let k = 0; k < 8; k++) crc = crc & 0x80 ? ((crc << 1) ^ poly) & 0xff : (crc << 1) & 0xff;
  }
  return crc;
}

export function b32encode(data: Uint8Array): string {
  let bits = 0n;
  for (const byte of data) bits = (bits << 8n) | BigInt(byte);
  const n = Math.floor((data.length * 8) / 5);
  let out = "";
  for (let k = 0; k < n; k++) out += ALPHABET[Number((bits >> BigInt(5 * (n - 1 - k))) & 31n)];
  return out;
}

export function b32decode(text: string, nBytes: number): Uint8Array {
  let bits = 0n;
  for (const ch of text) bits = (bits << 5n) | BigInt(DECODE[ch]);
  const out = new Uint8Array(nBytes);
  for (let k = nBytes - 1; k >= 0; k--) {
    out[k] = Number(bits & 0xffn);
    bits >>= 8n;
  }
  return out;
}

/** The 35 raw bytes of a code (checksum included). */
export function payload(team: TeamCode): Uint8Array {
  const ids = team.players;
  if (ids.length !== N_PLAYERS)
    throw new TeamCodeError("shape", `a team code needs ${N_PLAYERS} players, got ${ids.length}`);
  if (new Set(ids).size !== N_PLAYERS)
    throw new TeamCodeError("duplicate", "a player appears twice in the team");
  if (ids.some((i) => !(Number.isInteger(i) && i > 0 && i < 2 ** 16)))
    throw new TeamCodeError("unknown", "player ids must be between 1 and 65535");
  const xi = ids.slice(0, N_STARTERS);
  if (!xi.includes(team.captain) || !xi.includes(team.vice) || team.captain === team.vice)
    throw new TeamCodeError("captain", "captain and vice-captain must be two different starters");
  const out = new Uint8Array(PAYLOAD_BYTES);
  const view = new DataView(out.buffer);
  view.setUint8(0, VERSION);
  view.setUint16(1, team.season);
  ids.forEach((id, k) => view.setUint16(3 + 2 * k, id));
  view.setUint8(33, (xi.indexOf(team.captain) << 4) | xi.indexOf(team.vice));
  view.setUint8(34, crc8(out.subarray(0, 34)));
  return out;
}

/** "FPLN-2627-<56 chars>". Starters should already be in GK -> FWD order. */
export function encode(
  xi: number[],
  benchIds: number[],
  captain: number,
  vice: number,
  season = CURRENT_SEASON,
): string {
  const number = seasonNumber(season);
  const team: TeamCode = {
    season: number,
    players: [...xi, ...benchIds].map(Number),
    captain,
    vice,
  };
  return `${PREFIX}-${String(number).padStart(4, "0")}-${b32encode(payload(team))}`;
}

/** Pull the code out of whatever was pasted: a bare code, any case, or a share URL. */
export function extract(text: string): string {
  let raw = (text ?? "").trim();
  const lower = raw.toLowerCase();
  const urlish =
    raw.includes("?") ||
    lower.startsWith("http://") ||
    lower.startsWith("https://") ||
    raw.startsWith("/");
  if (urlish) {
    try {
      const t = new URL(raw, "http://x").searchParams.get("t");
      if (t) raw = t;
    } catch {
      // not a URL after all: keep the raw text
    }
  }
  return raw.replace(/\s+/g, "").toUpperCase();
}

/** Does this text look like a team code (or a share URL carrying one)? Used for paste detection. */
export function looksLikeCode(text: string): boolean {
  return /^FPLN-?\d{4}-?[0-9A-Z]{20,}$/.test(extract(text));
}

/** Parse and check a code (form and checksum only; see validate() for the squad). */
export function decode(text: string, season = CURRENT_SEASON): TeamCode {
  const code = extract(text);
  const m = /^FPLN-?(\d{4})-?([0-9A-Z]+)$/.exec(code);
  if (!m)
    throw new TeamCodeError("junk", "That isn't a FPLense team code (they start with FPLN-).");
  const prefixSeason = Number(m[1]);
  const body = m[2];
  if ([...body].some((ch) => !(ch in DECODE)) || body.length !== CODE_CHARS)
    throw new TeamCodeError("typo", "This code looks like a typo: check it was copied in full.");
  const raw = b32decode(body, PAYLOAD_BYTES);
  if (crc8(raw.subarray(0, PAYLOAD_BYTES - 1)) !== raw[PAYLOAD_BYTES - 1])
    throw new TeamCodeError("typo", "This code looks like a typo: the checksum doesn't match.");
  const view = new DataView(raw.buffer);
  const version = view.getUint8(0);
  const number = view.getUint16(1);
  const ids = Array.from({ length: N_PLAYERS }, (_, k) => view.getUint16(3 + 2 * k));
  const armbands = view.getUint8(33);
  if (version !== VERSION)
    throw new TeamCodeError(
      "version",
      `This code was made by a newer FPLense (format v${version}).`,
    );
  if (number !== prefixSeason)
    throw new TeamCodeError("typo", "This code looks like a typo: its season label was changed.");
  if (number !== seasonNumber(season))
    throw new TeamCodeError(
      "season",
      `This code is from ${seasonLabel(number)}; player ids change every season, so it can't be loaded in ${season}.`,
    );
  if (new Set(ids).size !== N_PLAYERS)
    throw new TeamCodeError("duplicate", "This code lists the same player twice.");
  const cap = armbands >> 4;
  const vice = armbands & 0x0f;
  if (cap >= N_STARTERS || vice >= N_STARTERS || cap === vice)
    throw new TeamCodeError("captain", "This code's captain or vice-captain isn't a starter.");
  return { season: number, players: ids, captain: ids[cap], vice: ids[vice] };
}

export interface CodePlayer {
  pos: string;
  club: string;
  price: number;
}

/** Check a decoded team against the season's players. Budget is reported, never enforced. */
export function validate(
  team: TeamCode,
  players: Record<number, CodePlayer>,
): { cost: number; overBudget: boolean } {
  const unknown = team.players.filter((i) => !(i in players));
  if (unknown.length)
    throw new TeamCodeError(
      "unknown",
      `This code has ${unknown.length} player(s) we don't know: [${unknown.join(", ")}].`,
    );
  const pos = team.players.map((i) => players[i].pos);
  for (const [p, n] of Object.entries(SQUAD_QUOTAS)) {
    const have = pos.filter((x) => x === p).length;
    if (have !== n)
      throw new TeamCodeError("shape", `This team has ${have} ${p}; a squad needs exactly ${n}.`);
  }
  const xi = pos.slice(0, N_STARTERS);
  const count = (p: string) => xi.filter((x) => x === p).length;
  const short = (Object.keys(XI_MIN) as (keyof typeof XI_MIN)[]).some((p) => count(p) < XI_MIN[p]);
  if (count("GK") !== 1 || short)
    throw new TeamCodeError(
      "shape",
      "This team's XI isn't legal (1 GK, at least 3 DEF, 2 MID and 1 FWD).",
    );
  const clubs = new Map<string, number>();
  for (const i of team.players) {
    const c = String(players[i].club);
    clubs.set(c, (clubs.get(c) ?? 0) + 1);
  }
  const over = [...clubs]
    .filter(([, n]) => n > MAX_PER_CLUB)
    .map(([c]) => c)
    .sort();
  if (over.length)
    throw new TeamCodeError(
      "club",
      `This team has more than ${MAX_PER_CLUB} players from ${over.join(", ")}.`,
    );
  const cost = team.players.reduce((s, i) => s + Number(players[i].price), 0);
  return { cost, overBudget: cost > BUDGET };
}

/** Share URL for a route carrying a code, e.g. shareUrl("/builder", code). */
export function shareUrl(route: string, code: string, origin = window.location.origin): string {
  return `${origin}${route}?t=${encodeURIComponent(code)}`;
}
