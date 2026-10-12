// Pitch layout helpers: formation rows from the XI and the bench in order.

import { POSITIONS, type Pos } from "./format";
import { formation } from "./squadRules";

export interface LineupPlayer {
  id: number;
  pos: string;
  starter: boolean;
  bench_order: number | null;
}

export interface Lineup<T extends LineupPlayer> {
  rows: { pos: Pos; players: T[] }[];
  bench: T[];
  formation: string;
}

/** XI rows GK -> FWD (keeping the given order within a row) and the bench by bench order. */
export function lineup<T extends LineupPlayer>(players: T[]): Lineup<T> {
  const xi = players.filter((p) => p.starter);
  const rows = POSITIONS.map((pos) => ({ pos, players: xi.filter((p) => p.pos === pos) }));
  const bench = players
    .filter((p) => !p.starter)
    .sort((a, b) => (a.bench_order ?? 99) - (b.bench_order ?? 99));
  return { rows, bench, formation: formation(xi.map((p) => p.pos as Pos)) };
}

/** Deal order (GK -> FWD, then the bench) used for the card stagger. */
export function dealOrder<T extends LineupPlayer>(l: Lineup<T>): Map<number, number> {
  const order = new Map<number, number>();
  let k = 0;
  for (const row of l.rows) for (const p of row.players) order.set(p.id, k++);
  for (const p of l.bench) order.set(p.id, k++);
  return order;
}

/** API squad players -> pitch players (cards + lineup info). */
export function toPitchPlayers<T extends LineupPlayer>(squad: { players: T[] }): T[] {
  return squad.players;
}
