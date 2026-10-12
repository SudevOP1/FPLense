// One app-wide player drawer: any card or row can open it. The drawer (and the charts library it
// uses) is a lazy chunk, loaded the first time someone opens a player, not on first paint.

import { createContext, lazy, Suspense, useContext, useMemo, useState, type ReactNode } from "react";

const PlayerDrawer = lazy(() =>
  import("@/components/PlayerDrawer/PlayerDrawer").then((m) => ({ default: m.PlayerDrawer })),
);

const DrawerContext = createContext<{ open: (id: number) => void } | null>(null);

export function PlayerDrawerProvider({ children }: { children: ReactNode }) {
  const [id, setId] = useState<number | null>(null);
  const [used, setUsed] = useState(false);
  const api = useMemo(
    () => ({
      open: (next: number) => {
        setUsed(true);
        setId(next);
      },
    }),
    [],
  );
  return (
    <DrawerContext.Provider value={api}>
      {children}
      {used && (
        <Suspense fallback={null}>
          <PlayerDrawer playerId={id} onClose={() => setId(null)} />
        </Suspense>
      )}
    </DrawerContext.Provider>
  );
}

export function usePlayerDrawer(): { open: (id: number) => void } {
  return useContext(DrawerContext) ?? { open: () => undefined };
}
