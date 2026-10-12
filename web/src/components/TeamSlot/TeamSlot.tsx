import { useDraggable, useDroppable } from "@dnd-kit/core";
import { motion } from "framer-motion";
import type { Pos } from "@/lib/format";
import { SPRING } from "@/lib/motion";
import { useReducedMotion } from "@/lib/settings";
import { PlayerCard, type CardPlayer, type MenuItem } from "../PlayerCard/PlayerCard";

/**
 * One Builder slot: a drop target (drag a player from the list, or another slot to swap) and a
 * tap target (tap a slot, then a player; or tap two slots to swap). The tap path is also the
 * keyboard / screen-reader path.
 */
export function TeamSlot({
  slotKey,
  pos,
  player,
  selected,
  onTap,
  menu,
  benchLabel,
}: {
  slotKey: string;
  pos: Pos;
  player: CardPlayer | null;
  selected: boolean;
  onTap: () => void;
  menu?: MenuItem[];
  benchLabel?: string;
}) {
  const reduced = useReducedMotion();
  const drop = useDroppable({ id: slotKey });
  const drag = useDraggable({ id: `slot:${slotKey}`, disabled: !player });
  const over = drop.isOver;
  return (
    <div ref={drop.setNodeRef} className="flex flex-col items-center gap-1" data-slot={slotKey}>
      {benchLabel && <span className="num text-xs font-bold text-muted">{benchLabel}</span>}
      {player ? (
        <motion.div
          ref={drag.setNodeRef}
          layoutId={`builder-${player.id}`}
          transition={reduced ? { duration: 0 } : SPRING}
          className={`w-full ${drag.isDragging ? "opacity-40" : ""} ${over ? "scale-105" : ""}`}
          // pointer drag only: keyboard users swap with taps (no nested interactive roles)
          {...drag.listeners}
        >
          <PlayerCard
            player={player}
            onClick={onTap}
            selected={selected}
            menu={menu}
            ring={over ? "ring-accent" : undefined}
          />
        </motion.div>
      ) : (
        // roughly the height of a filled card (face-cropped photo + name row), so an empty
        // pitch stays inside the pitch image
        <button
          type="button"
          onClick={onTap}
          aria-pressed={selected}
          aria-label={`Empty ${pos} slot${selected ? " (selected: now pick a player)" : ""}`}
          className={`flex aspect-square min-h-[64px] w-full flex-col items-center justify-center gap-1 rounded-md border-2 border-dashed text-xs font-bold transition duration-fast ${
            selected ? "border-accent bg-accent/25 text-ink" : over ? "border-accent bg-surface/30 text-white" : "border-white/60 bg-surface/15 text-white"
          }`}
        >
          <span className="text-lg leading-none" aria-hidden>
            +
          </span>
          {pos}
        </button>
      )}
    </div>
  );
}
