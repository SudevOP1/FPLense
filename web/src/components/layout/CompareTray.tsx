import { AnimatePresence, motion } from "framer-motion";
import { Link, useLocation } from "react-router-dom";
import { SlotBadge } from "@/components/ui/Bits";
import { compareHref, LETTERS, MAX_SLOTS, slotLabel } from "@/lib/compareSlots";
import { useCompareTray } from "@/lib/compareTray";
import { DURATION, EASE_OUT } from "@/lib/motion";

/** Bottom tray of up to 3 teams waiting to be compared. */
export function CompareTray() {
  const tray = useCompareTray();
  const { pathname } = useLocation();
  const show = tray.slots.length > 0 && pathname !== "/compare";
  return (
    <AnimatePresence>
      {show && (
        <motion.aside
          aria-label="Compare tray"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 16 }}
          transition={{ duration: DURATION.base, ease: EASE_OUT }}
          className="fixed inset-x-2 bottom-[4.5rem] z-40 mx-auto max-w-3xl rounded-xl border border-line bg-raised p-2 shadow-lg md:bottom-4"
        >
          <div className="flex flex-wrap items-center gap-2">
            <ul className="flex min-w-0 flex-1 flex-wrap gap-2">
              {tray.slots.map((s, k) => (
                <li key={k} className="flex min-w-0 items-center gap-1.5 rounded-full border border-line bg-surface py-0.5 pl-0.5 pr-1 text-sm">
                  <SlotBadge letter={LETTERS[k]} size="sm" />
                  <span className="truncate">{slotLabel(s)}</span>
                  <button
                    type="button"
                    aria-label={`Remove ${slotLabel(s)} from compare`}
                    className="flex h-7 w-7 items-center justify-center rounded-full text-muted hover:text-ink"
                    onClick={() => tray.remove(k)}
                  >
                    ×
                  </button>
                </li>
              ))}
              {tray.slots.length < MAX_SLOTS && (
                <li className="self-center text-xs text-muted">
                  {MAX_SLOTS - tray.slots.length} slot{MAX_SLOTS - tray.slots.length === 1 ? "" : "s"} free
                </li>
              )}
            </ul>
            <button type="button" className="btn-ghost min-h-[40px] text-xs" onClick={tray.clear}>
              Clear
            </button>
            <Link
              to={compareHref(tray.slots)}
              className={`btn-primary min-h-[40px] ${tray.slots.length < 2 ? "pointer-events-none opacity-50" : ""}`}
              aria-disabled={tray.slots.length < 2}
              tabIndex={tray.slots.length < 2 ? -1 : undefined}
            >
              Compare
            </Link>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
