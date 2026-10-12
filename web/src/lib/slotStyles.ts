import type { Letter } from "./compareSlots";

// Full class names (not built from strings) so Tailwind's scanner keeps them.
const SLOT_RING: Record<Letter, string> = { A: "ring-slotA", B: "ring-slotB", C: "ring-slotC" };
const SLOT_BORDER: Record<Letter, string> = { A: "border-slotA", B: "border-slotB", C: "border-slotC" };

export const slotRing = (l: Letter) => SLOT_RING[l];
export const slotBorder = (l: Letter) => SLOT_BORDER[l];
