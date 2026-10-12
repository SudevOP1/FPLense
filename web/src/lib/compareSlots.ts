// Compare slots and how they live in the URL: /compare?a=model_pick.6&b=hindsight.5&c=entry.5.123
// (kind.gw.value; gw may be empty, e.g. code..FPLN-2627-...). A share link with ?t=<code> also
// opens as slot A. Builder drafts and other ad-hoc squads travel as team codes.

export type CompareKind = "model_pick" | "hindsight" | "entry" | "code";

export interface CompareSlot {
  kind: CompareKind;
  gw: number | null;
  value: number | string | null; // entry: team id · code: team code
  label?: string;
}

export const LETTERS = ["A", "B", "C"] as const;
export type Letter = (typeof LETTERS)[number];
export const MAX_SLOTS = 3;
const PARAMS = ["a", "b", "c"] as const;
const KINDS: CompareKind[] = ["model_pick", "hindsight", "entry", "code"];

export const KIND_LABEL: Record<CompareKind, string> = {
  entry: "My team",
  model_pick: "Model pick",
  hindsight: "Hindsight best",
  code: "Paste code",
};

export function slotToParam(slot: CompareSlot): string {
  return [slot.kind, slot.gw ?? "", slot.value ?? ""].join(".");
}

export function paramToSlot(raw: string | null): CompareSlot | null {
  if (!raw) return null;
  const [kind, gwText, ...rest] = raw.split(".");
  if (!KINDS.includes(kind as CompareKind)) return null;
  const gw = gwText ? Number(gwText) : null;
  if (gw != null && !(Number.isInteger(gw) && gw >= 1 && gw <= 38)) return null;
  const valueText = rest.join(".");
  let value: CompareSlot["value"] = null;
  if (kind === "entry") {
    const id = Number(valueText);
    value = valueText && Number.isInteger(id) && id > 0 ? id : null; // empty: waits for a team ID
  } else if (kind === "code") {
    value = valueText || null; // an empty code slot waits for a paste
  }
  return { kind: kind as CompareKind, gw, value };
}

export function slotsFromSearch(params: URLSearchParams): CompareSlot[] {
  const slots = PARAMS.map((p) => paramToSlot(params.get(p))).filter((s): s is CompareSlot => s != null);
  const t = params.get("t");
  if (t && slots.length < MAX_SLOTS) slots.unshift({ kind: "code", gw: null, value: t });
  return slots.slice(0, MAX_SLOTS);
}

export function searchFromSlots(slots: CompareSlot[]): URLSearchParams {
  const out = new URLSearchParams();
  slots.slice(0, MAX_SLOTS).forEach((s, k) => out.set(PARAMS[k], slotToParam(s)));
  return out;
}

export function compareHref(slots: CompareSlot[]): string {
  return `/compare?${searchFromSlots(slots).toString()}`;
}

export function slotLabel(slot: CompareSlot): string {
  if (slot.label) return slot.label;
  const gw = slot.gw ? ` GW${slot.gw}` : "";
  if (slot.kind === "entry") return `Team ${slot.value}${gw}`;
  if (slot.kind === "code") return `Pasted team${gw}`;
  return `${KIND_LABEL[slot.kind]}${gw}`;
}

/** The API's Slot body for /api/compare. */
export function toApiSlot(slot: CompareSlot) {
  return { kind: slot.kind, gw: slot.gw, value: slot.value, label: slot.label ?? null };
}

export function sameSlot(a: CompareSlot, b: CompareSlot): boolean {
  return a.kind === b.kind && a.gw === b.gw && String(a.value ?? "") === String(b.value ?? "");
}
