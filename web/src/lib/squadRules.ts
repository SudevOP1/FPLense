// Client-side squad rules: instant checks for the Builder's rule chips (same frame as the click).
// The server (/api/squads/evaluate, optimize/squad_ilp.rule_problems) stays the source of truth;
// ruleProblems() mirrors its messages so both read the same.

import { money, type Pos } from "./format";

export const BUDGET = 1000;
export const SQUAD_QUOTAS: Record<Pos, number> = { GK: 2, DEF: 5, MID: 5, FWD: 3 };
export const XI_MIN: Record<Pos, number> = { GK: 1, DEF: 3, MID: 2, FWD: 1 };
export const XI_MAX: Record<Pos, number> = { GK: 1, DEF: 5, MID: 5, FWD: 3 };
export const MAX_PER_CLUB = 3;
export const SQUAD_SIZE = 15;
export const XI_SIZE = 11;

export interface RulePlayer {
  id: number;
  pos: Pos;
  club: string;
  price: number;
  web_name?: string;
}

export interface Problem {
  rule: string;
  message: string;
}

function countBy<T>(items: T[], key: (t: T) => string): Map<string, number> {
  const out = new Map<string, number>();
  for (const it of items) out.set(key(it), (out.get(key(it)) ?? 0) + 1);
  return out;
}

/** Same report as the Python rule_problems for a (possibly partial) squad. */
export function ruleProblems(
  squad: RulePlayer[],
  opts: {
    starters?: number[];
    captain?: number | null;
    vice?: number | null;
    budget?: number;
    enforceBudget?: boolean;
  } = {},
): Problem[] {
  const { budget = BUDGET, enforceBudget = true } = opts;
  const out: Problem[] = [];
  const ids = squad.map((p) => p.id);
  const dupes = [...new Set(ids.filter((i, k) => ids.indexOf(i) !== k))].sort((a, b) => a - b);
  if (dupes.length)
    out.push({ rule: "duplicate", message: `players picked more than once: [${dupes.join(", ")}]` });
  const unique = squad.filter((p, k) => ids.indexOf(p.id) === k);
  if (unique.length !== SQUAD_SIZE)
    out.push({ rule: "size", message: `${unique.length} of ${SQUAD_SIZE} players picked` });
  const byPos = countBy(unique, (p) => p.pos);
  for (const [pos, n] of Object.entries(SQUAD_QUOTAS)) {
    const have = byPos.get(pos) ?? 0;
    if (have > n) out.push({ rule: "quota", message: `${have} ${pos}: a squad holds exactly ${n}` });
    else if (have < n && unique.length === SQUAD_SIZE)
      out.push({ rule: "quota", message: `${have} ${pos}: a squad needs exactly ${n}` });
  }
  for (const [club, n] of countBy(unique, (p) => p.club)) {
    if (n > MAX_PER_CLUB)
      out.push({ rule: "club", message: `${n} players from ${club}: max ${MAX_PER_CLUB} per club` });
  }
  const cost = unique.reduce((s, p) => s + p.price, 0);
  if (enforceBudget && cost > budget)
    out.push({
      rule: "budget",
      message: `costs ${money(cost)}: ${money(cost - budget)} over the ${money(budget)} budget`,
    });
  if (opts.starters) {
    const known = new Map(unique.map((p) => [p.id, p]));
    const xi = [...new Set(opts.starters)].filter((i) => known.has(i));
    if (xi.length !== XI_SIZE || !xi.every((i) => known.has(i)))
      out.push({ rule: "xi", message: "the starting XI must be 11 squad players" });
    const xc = countBy(xi, (i) => known.get(i)!.pos);
    if ((xc.get("GK") ?? 0) !== 1)
      out.push({ rule: "xi", message: "the XI needs exactly 1 goalkeeper" });
    for (const pos of ["DEF", "MID", "FWD"] as const) {
      if ((xc.get(pos) ?? 0) < XI_MIN[pos])
        out.push({ rule: "xi", message: `the XI needs at least ${XI_MIN[pos]} ${pos}` });
    }
    if (opts.captain != null && !xi.includes(opts.captain))
      out.push({ rule: "captain", message: "the captain must be in the XI" });
    if (opts.vice != null && (!xi.includes(opts.vice) || opts.vice === opts.captain))
      out.push({ rule: "captain", message: "the vice-captain must be another starter" });
  }
  return out;
}

/** Why `player` can't go into the squad (replacing `replacing`, if any), or null if it can. */
export function placeProblem(
  squad: RulePlayer[],
  player: RulePlayer,
  slotPos: Pos,
  replacing: number | null = null,
): string | null {
  const name = player.web_name ?? "This player";
  if (player.pos !== slotPos) return `${name} is a ${player.pos}; this is a ${slotPos} slot.`;
  const rest = squad.filter((p) => p.id !== replacing);
  if (rest.some((p) => p.id === player.id)) return `${name} is already in your squad.`;
  const sameClub = rest.filter((p) => p.club === player.club).length;
  if (sameClub >= MAX_PER_CLUB)
    return `You already have ${MAX_PER_CLUB} ${player.club} players (max ${MAX_PER_CLUB} per club).`;
  return null;
}

/** Problems with an XI's shape given its positions (11 or fewer filled slots). */
export function xiShapeProblem(positions: Pos[]): string | null {
  const c = (p: Pos) => positions.filter((x) => x === p).length;
  if (c("GK") !== 1) return "The XI needs exactly 1 goalkeeper.";
  for (const pos of ["DEF", "MID", "FWD"] as const) {
    if (c(pos) < XI_MIN[pos]) return `The XI needs at least ${XI_MIN[pos]} ${pos}.`;
  }
  return null;
}

/** "3-5-2" from the XI's positions. */
export function formation(positions: Pos[]): string {
  return (["DEF", "MID", "FWD"] as const)
    .map((p) => positions.filter((x) => x === p).length)
    .join("-");
}

export interface Chip {
  id: "budget" | "quota" | "club";
  ok: boolean;
  label: string;
  message: string;
}

/** The Builder's three live rule chips: money left, 2-5-5-3 and max 3 per club. */
export function ruleChips(squad: RulePlayer[], budget = BUDGET): Chip[] {
  const cost = squad.reduce((s, p) => s + p.price, 0);
  const left = budget - cost;
  const byPos = countBy(squad, (p) => p.pos);
  const counts = (Object.keys(SQUAD_QUOTAS) as Pos[]).map((p) => byPos.get(p) ?? 0);
  const full = squad.length === SQUAD_SIZE;
  const quotaOk = counts.every((n, k) => n <= Object.values(SQUAD_QUOTAS)[k]);
  const clubs = [...countBy(squad, (p) => p.club)].filter(([, n]) => n > MAX_PER_CLUB);
  return [
    {
      id: "budget",
      ok: left >= 0,
      label: left >= 0 ? `${money(left)} left` : `${money(-left)} over`,
      message:
        left >= 0
          ? `${money(left)} left of your ${money(budget)} budget.`
          : `Your squad costs ${money(cost)}: ${money(-left)} over the ${money(budget)} budget.`,
    },
    {
      id: "quota",
      ok: quotaOk,
      label: counts.join("-"),
      message: full
        ? "2 GK, 5 DEF, 5 MID and 3 FWD: squad complete."
        : `${SQUAD_SIZE - squad.length} of ${SQUAD_SIZE} slots still empty (a squad is 2 GK, 5 DEF, 5 MID, 3 FWD).`,
    },
    {
      id: "club",
      ok: clubs.length === 0,
      label: clubs.length ? `${clubs[0][1]} from ${clubs[0][0]}` : `Max ${MAX_PER_CLUB} per club`,
      message: clubs.length
        ? `${clubs.map(([c, n]) => `${n} players from ${c}`).join(", ")}: max ${MAX_PER_CLUB} per club.`
        : `No club has more than ${MAX_PER_CLUB} players.`,
    },
  ];
}
