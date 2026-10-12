import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { COUNT_MS, EASE_OUT } from "@/lib/motion";
import { useReducedMotion } from "@/lib/settings";

/**
 * Number that counts to its new value over 300 ms (tabular figures, so digits don't jitter).
 * With reduced motion it shows the final value immediately.
 */
export function AnimatedNumber({
  value,
  format = (v) => v.toFixed(1),
  className = "",
}: {
  value: number | null | undefined;
  format?: (v: number) => string;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState<number | null>(value ?? null);
  const from = useRef<number | null>(value ?? null);

  useEffect(() => {
    if (value == null) {
      setShown(null);
      from.current = null;
      return;
    }
    const start = from.current;
    if (reduced || start == null || start === value || typeof requestAnimationFrame === "undefined") {
      setShown(value);
      from.current = value;
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const k = Math.min(1, (now - t0) / COUNT_MS);
      const eased = 1 - (1 - k) ** 3;
      setShown(start + (value - start) * eased);
      if (k < 1) raf = requestAnimationFrame(tick);
      else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      from.current = value;
    };
  }, [value, reduced]);

  return <span className={`num ${className}`}>{shown == null ? "–" : format(shown)}</span>;
}

const COLOURS = ["rgb(var(--accent))", "rgb(var(--navy))", "rgb(var(--good))", "rgb(var(--slot-a))", "#FFD166"];

/**
 * The one celebratory moment: a small confetti burst. Shown at most once per session per `event`
 * and never with reduced motion.
 */
export function Confetti({ event, fire }: { event: string; fire: boolean }) {
  const reduced = useReducedMotion();
  const [active, setActive] = useState(false);

  useEffect(() => {
    if (!fire || reduced) return;
    const key = `fplense:confetti:${event}`;
    try {
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, "1");
    } catch {
      // storage blocked: still fine to celebrate once per mount
    }
    setActive(true);
    // not cleared on cleanup: StrictMode re-runs the effect, which returns early above
    window.setTimeout(() => setActive(false), 500);
  }, [fire, reduced, event]);

  if (reduced) return null;
  return (
    <AnimatePresence>
      {active && (
        <div aria-hidden data-testid="confetti" className="pointer-events-none fixed inset-0 z-[70] flex items-center justify-center">
          {Array.from({ length: 28 }, (_, i) => {
            const angle = (i / 28) * Math.PI * 2;
            const dist = 120 + (i % 5) * 28;
            return (
              <motion.span
                key={i}
                className="absolute h-2 w-1.5 rounded-sm"
                style={{ background: COLOURS[i % COLOURS.length] }}
                initial={{ x: 0, y: 0, opacity: 1, rotate: 0 }}
                animate={{ x: Math.cos(angle) * dist, y: Math.sin(angle) * dist + 60, opacity: 0, rotate: 200 }}
                transition={{ duration: 0.4, ease: EASE_OUT }}
              />
            );
          })}
        </div>
      )}
    </AnimatePresence>
  );
}
