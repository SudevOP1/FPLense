// The persistent compare tray: "Add to compare" on any team view drops it here (max 3).

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { MAX_SLOTS, sameSlot, slotLabel, type CompareSlot } from "./compareSlots";
import { load, save } from "./storage";
import { useToast } from "./toast";

interface Tray {
  slots: CompareSlot[];
  add: (slot: CompareSlot) => boolean;
  remove: (index: number) => void;
  clear: () => void;
}

const TrayContext = createContext<Tray | null>(null);

export function CompareTrayProvider({ children }: { children: ReactNode }) {
  const [slots, setSlots] = useState<CompareSlot[]>(() => load<CompareSlot[]>("tray", []).slice(0, MAX_SLOTS));
  const toast = useToast();

  const persist = useCallback((next: CompareSlot[]) => {
    setSlots(next);
    save("tray", next);
  }, []);

  const add = useCallback(
    (slot: CompareSlot) => {
      if (slots.some((s) => sameSlot(s, slot))) {
        toast.show(`${slotLabel(slot)} is already in the compare tray.`);
        return false;
      }
      if (slots.length >= MAX_SLOTS) {
        toast.show(`The compare tray holds ${MAX_SLOTS} teams. Remove one first.`, { tone: "bad" });
        return false;
      }
      persist([...slots, slot]);
      toast.show(`Added ${slotLabel(slot)} to compare.`, { tone: "good" });
      return true;
    },
    [slots, persist, toast],
  );

  const value = useMemo<Tray>(
    () => ({
      slots,
      add,
      remove: (i) => persist(slots.filter((_, k) => k !== i)),
      clear: () => persist([]),
    }),
    [slots, add, persist],
  );

  return <TrayContext.Provider value={value}>{children}</TrayContext.Provider>;
}

export function useCompareTray(): Tray {
  const ctx = useContext(TrayContext);
  if (!ctx) throw new Error("useCompareTray outside CompareTrayProvider");
  return ctx;
}
