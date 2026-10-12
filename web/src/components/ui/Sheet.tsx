import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { DURATION, EASE_OUT } from "@/lib/motion";

/**
 * Modal drawer (right side on desktop, bottom sheet on phones). Escape or the backdrop closes it;
 * focus moves in on open, is trapped while open and returns to the opener on close.
 */
export function Sheet({
  open,
  onClose,
  title,
  children,
  side = "right",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  side?: "right" | "center";
}) {
  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key !== "Tab" || !panel.current) return;
      const focusable = panel.current.querySelectorAll<HTMLElement>(
        'a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])',
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      (opener.current as HTMLElement | null)?.focus?.();
    };
  }, [open, onClose]);

  const placement =
    side === "right"
      ? "inset-x-0 bottom-0 max-h-[88dvh] rounded-t-xl md:inset-y-0 md:left-auto md:right-0 md:max-h-none md:w-[440px] md:rounded-none md:rounded-l-xl"
      : "inset-x-4 top-[10vh] mx-auto max-h-[80dvh] max-w-xl rounded-xl";

  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50">
          <motion.div
            className="absolute inset-0 bg-ink/40"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: DURATION.base }}
            onClick={onClose}
            aria-hidden
          />
          <motion.div
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            className={`absolute flex flex-col overflow-hidden border border-line bg-surface shadow-lg outline-none ${placement}`}
            initial={{ opacity: 0, y: side === "right" ? 24 : 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: side === "right" ? 24 : 8 }}
            transition={{ duration: DURATION.slow, ease: EASE_OUT }}
          >
            <div className="flex items-center justify-between gap-2 border-b border-line px-5 py-3">
              <h2 id={titleId} className="truncate text-lg font-semibold">
                {title}
              </h2>
              <button type="button" className="btn-ghost h-11 w-11 px-0" aria-label="Close" onClick={onClose}>
                ×
              </button>
            </div>
            <div className="overflow-y-auto px-5 py-4">{children}</div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
