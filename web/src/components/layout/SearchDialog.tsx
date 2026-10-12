import { useEffect, useId, useMemo, useRef, useState } from "react";
import { usePlayers } from "@/api/hooks";
import { Sheet } from "@/components/ui/Sheet";
import { money, points } from "@/lib/format";
import { usePlayerDrawer } from "@/lib/playerDrawer";

function normalise(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

/** Global player search (press "/" or Ctrl/⌘ K). Enter opens the top hit's drawer. */
export function SearchDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const players = usePlayers();
  const drawer = usePlayerDrawer();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();

  useEffect(() => {
    if (open) {
      setQ("");
      setActive(0);
      window.setTimeout(() => input.current?.focus(), 0);
    }
  }, [open]);

  const hits = useMemo(() => {
    const all = players.data?.players ?? [];
    const n = normalise(q.trim());
    if (!n) return [...all].sort((a, b) => b.P_h - a.P_h).slice(0, 8);
    return all
      .filter((p) => normalise(`${p.name} ${p.web_name} ${p.club} ${p.club_short}`).includes(n))
      .sort((a, b) => b.P_h - a.P_h)
      .slice(0, 12);
  }, [players.data, q]);

  const choose = (id: number) => {
    onClose();
    drawer.open(id);
  };

  return (
    <Sheet open={open} onClose={onClose} title="Find a player" side="center">
      <div className="flex flex-col gap-3">
        <input
          ref={input}
          type="search"
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={hits[active] ? `${listId}-${hits[active].id}` : undefined}
          aria-label="Search players by name or club"
          placeholder="Search players by name or club…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setActive(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(hits.length - 1, a + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(0, a - 1));
            } else if (e.key === "Enter" && hits[active]) {
              choose(hits[active].id);
            }
          }}
          className="field"
        />
        <ul id={listId} role="listbox" aria-label="Players" className="flex flex-col">
          {hits.map((p, k) => (
            <li
              key={p.id}
              id={`${listId}-${p.id}`}
              role="option"
              aria-selected={k === active}
              onClick={() => choose(p.id)}
              onKeyDown={() => undefined}
              onMouseEnter={() => setActive(k)}
              className={`flex min-h-[44px] cursor-pointer items-center justify-between gap-2 rounded px-2 text-sm ${k === active ? "bg-line/50" : ""}`}
            >
              <span className="truncate">
                <strong>{p.web_name}</strong> <span className="text-muted">{p.pos} · {p.club_short}</span>
              </span>
              <span className="num shrink-0 text-muted">
                {money(p.price)} · {points(p.P_h)}
              </span>
            </li>
          ))}
          {players.data && hits.length === 0 && <li className="px-2 py-3 text-sm text-muted">No player matches “{q}”.</li>}
        </ul>
        <p className="text-xs text-muted">↑ ↓ to move, Enter to open, Esc to close.</p>
      </div>
    </Sheet>
  );
}
