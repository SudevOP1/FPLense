// Builder draft: 11 XI slots + 4 bench slots, each with a fixed position that travels with its
// player when XI and bench swap (so the squad is always 2-5-5-3 and the XI shape is checked on
// every swap). Pure functions so the page, undo/redo and tests share one implementation.

import type { Pos } from "./format";
import { placeProblem, xiShapeProblem, type RulePlayer } from "./squadRules";

export interface BSlot {
  pos: Pos;
  id: number | null;
}

export interface Draft {
  xi: BSlot[];
  bench: BSlot[];
  captain: number | null;
  vice: number | null;
}

export type Zone = "xi" | "bench";
export interface SlotRef {
  zone: Zone;
  index: number;
}

const ORDER: Record<Pos, number> = { GK: 0, DEF: 1, MID: 2, FWD: 3 };

export function emptyDraft(): Draft {
  const xi: Pos[] = ["GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD"];
  const bench: Pos[] = ["GK", "DEF", "MID", "FWD"];
  return {
    xi: xi.map((pos) => ({ pos, id: null })),
    bench: bench.map((pos) => ({ pos, id: null })),
    captain: null,
    vice: null,
  };
}

export const slotKey = (r: SlotRef) => `${r.zone}-${r.index}`;
export function parseSlotKey(key: string): SlotRef | null {
  const m = /^(xi|bench)-(\d+)$/.exec(key);
  return m ? { zone: m[1] as Zone, index: Number(m[2]) } : null;
}

export function getSlot(d: Draft, r: SlotRef): BSlot {
  return d[r.zone][r.index];
}

export function pickedIds(d: Draft): number[] {
  return [...d.xi, ...d.bench].map((s) => s.id).filter((i): i is number => i != null);
}

export function isComplete(d: Draft): boolean {
  return pickedIds(d).length === 15 && d.captain != null && d.vice != null;
}

/** XI ids GK -> FWD (stable within a position) and bench ids in order, for codes and the API. */
export function ordered(d: Draft): { starters: number[]; bench: number[] } {
  const starters = d.xi
    .map((s, k) => ({ s, k }))
    .sort((a, b) => ORDER[a.s.pos] - ORDER[b.s.pos] || a.k - b.k)
    .map(({ s }) => s.id)
    .filter((i): i is number => i != null);
  return { starters, bench: d.bench.map((s) => s.id).filter((i): i is number => i != null) };
}

function fixArmbands(d: Draft): Draft {
  const xi = new Set(d.xi.map((s) => s.id).filter((i) => i != null));
  let { captain, vice } = d;
  if (captain != null && !xi.has(captain)) captain = null;
  if (vice != null && (!xi.has(vice) || vice === captain)) vice = null;
  return { ...d, captain, vice };
}

function withSlot(d: Draft, r: SlotRef, slot: BSlot): Draft {
  const zone = d[r.zone].map((s, k) => (k === r.index ? slot : s));
  return fixArmbands({ ...d, [r.zone]: zone });
}

export type Result = { draft: Draft; error: null } | { draft: null; error: string };

/** Put a player into a slot (replacing whoever is there). */
export function place(d: Draft, r: SlotRef, player: RulePlayer, all: Map<number, RulePlayer>): Result {
  const slot = getSlot(d, r);
  const squad = pickedIds(d).map((i) => all.get(i)!).filter(Boolean);
  const problem = placeProblem(squad, player, slot.pos, slot.id);
  if (problem) return { draft: null, error: problem };
  return { draft: withSlot(d, r, { pos: slot.pos, id: player.id }), error: null };
}

/** First empty slot for a position (XI first), or null. */
export function firstEmpty(d: Draft, pos: Pos): SlotRef | null {
  for (const zone of ["xi", "bench"] as Zone[]) {
    const index = d[zone].findIndex((s) => s.pos === pos && s.id == null);
    if (index >= 0) return { zone, index };
  }
  return null;
}

export function removeAt(d: Draft, r: SlotRef): Draft {
  const slot = getSlot(d, r);
  return withSlot(d, r, { pos: slot.pos, id: null });
}

/** Swap two slots (XI <-> bench substitution, or reordering). Checks the XI shape. */
export function swap(d: Draft, a: SlotRef, b: SlotRef): Result {
  if (a.zone === b.zone && a.index === b.index) return { draft: d, error: null };
  const sa = getSlot(d, a);
  const sb = getSlot(d, b);
  if (a.zone !== b.zone && (sa.pos === "GK") !== (sb.pos === "GK"))
    return { draft: null, error: "Goalkeepers can only swap with goalkeepers." };
  const next: Draft = { ...d, xi: [...d.xi], bench: [...d.bench] };
  next[a.zone][a.index] = sb;
  next[b.zone][b.index] = sa;
  const shape = xiShapeProblem(next.xi.map((s) => s.pos));
  if (shape) return { draft: null, error: shape };
  return { draft: fixArmbands(next), error: null };
}

export function setArmband(d: Draft, id: number, which: "captain" | "vice"): Result {
  if (!d.xi.some((s) => s.id === id)) return { draft: null, error: "Only starters can wear the armband." };
  if (which === "captain") return { draft: { ...d, captain: id, vice: d.vice === id ? d.captain : d.vice }, error: null };
  return { draft: { ...d, vice: id, captain: d.captain === id ? d.vice : d.captain }, error: null };
}

/** Build a draft from an API squad (starters, bench in order, captain, vice). */
export function fromSquad(s: { players: { id: number; pos: string }[]; starters: number[]; bench: number[]; captain: number | null; vice: number | null }): Draft {
  const pos = new Map(s.players.map((p) => [p.id, p.pos as Pos]));
  return {
    xi: s.starters.map((id) => ({ pos: pos.get(id)!, id })),
    bench: s.bench.map((id) => ({ pos: pos.get(id)!, id })),
    captain: s.captain,
    vice: s.vice,
  };
}

/** Undo/redo history. */
export interface History {
  past: Draft[];
  present: Draft;
  future: Draft[];
}

export function commit(h: History, next: Draft): History {
  if (next === h.present) return h;
  return { past: [...h.past.slice(-49), h.present], present: next, future: [] };
}

export function undo(h: History): History {
  if (!h.past.length) return h;
  return { past: h.past.slice(0, -1), present: h.past[h.past.length - 1], future: [h.present, ...h.future] };
}

export function redo(h: History): History {
  if (!h.future.length) return h;
  return { past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1) };
}
