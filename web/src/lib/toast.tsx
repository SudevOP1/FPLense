// Toasts: short confirmations ("Team code copied") announced politely to screen readers.

import { AnimatePresence, motion } from "framer-motion";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { fadeVariants } from "./motion";

type ToastTone = "info" | "good" | "bad";

interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
  action?: { label: string; onClick: () => void };
}

interface ToastApi {
  show: (message: string, opts?: { tone?: ToastTone; action?: Toast["action"]; ms?: number }) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);

  const dismiss = useCallback((id: number) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);

  const show = useCallback<ToastApi["show"]>(
    (message, opts = {}) => {
      const id = next.current++;
      setToasts((ts) => [...ts.slice(-2), { id, message, tone: opts.tone ?? "info", action: opts.action }]);
      window.setTimeout(() => dismiss(id), opts.ms ?? (opts.action ? 8000 : 3200));
    },
    [dismiss],
  );

  const api = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        role="status"
        className="pointer-events-none fixed inset-x-0 bottom-24 z-[60] flex flex-col items-center gap-2 px-4 md:bottom-6"
      >
        <AnimatePresence initial={false}>
          {toasts.map((t) => (
            <motion.div
              key={t.id}
              variants={fadeVariants}
              initial="hidden"
              animate="shown"
              exit="exit"
              className={`pointer-events-auto flex max-w-md items-center gap-3 rounded-lg border px-4 py-3 text-sm font-medium shadow-lg ${
                t.tone === "bad"
                  ? "border-bad/40 bg-surface text-bad"
                  : t.tone === "good"
                    ? "border-good/40 bg-surface text-ink"
                    : "border-line bg-surface text-ink"
              }`}
            >
              <span>{t.message}</span>
              {t.action && (
                <button
                  type="button"
                  className="rounded px-2 py-1 font-semibold text-coral hover:bg-line/40"
                  onClick={() => {
                    t.action!.onClick();
                    dismiss(t.id);
                  }}
                >
                  {t.action.label}
                </button>
              )}
              <button
                type="button"
                aria-label="Dismiss"
                className="ml-1 rounded px-1 text-muted hover:text-ink"
                onClick={() => dismiss(t.id)}
              >
                ×
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast outside ToastProvider");
  return ctx;
}
