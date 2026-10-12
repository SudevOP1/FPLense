// Motion tokens (PLAN.md §8 P7 "Motion"). Only transform and opacity are animated; nothing runs
// longer than 400 ms; nothing loops except loading shimmers. Reduced motion (system setting or
// the in-app toggle) turns every animation into an instant change.

import type { TargetAndTransition, Transition, Variants } from "framer-motion";

export const DURATION = { fast: 0.12, base: 0.2, slow: 0.32 } as const;
export const EASE_OUT: [number, number, number, number] = [0.22, 1, 0.36, 1];
export const SPRING: Transition = { type: "spring", stiffness: 400, damping: 30 };
export const DEAL_STAGGER = 0.025; // cards deal onto the pitch GK -> FWD
export const COUNT_MS = 300; // numbers count up/down
export const COPIED_MS = 1500; // copy button shows a tick

export const pageVariants: Variants = {
  hidden: { opacity: 0, y: 4 },
  shown: { opacity: 1, y: 0, transition: { duration: 0.15, ease: EASE_OUT } },
};

/** Card dealt onto the pitch; `custom` is its deal index. */
export const dealVariants: Variants = {
  hidden: { opacity: 0, y: 10, scale: 0.96 },
  shown: (i: number = 0) => ({
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { ...SPRING, delay: i * DEAL_STAGGER },
  }),
  exit: { opacity: 0, y: 12, transition: { duration: DURATION.base, ease: EASE_OUT } },
};

export const popVariants: Variants = {
  hidden: { opacity: 0, scale: 0.8 },
  shown: { opacity: 1, scale: 1, transition: { duration: DURATION.base, ease: EASE_OUT } },
};

export const fadeVariants: Variants = {
  hidden: { opacity: 0 },
  shown: { opacity: 1, transition: { duration: DURATION.base, ease: EASE_OUT } },
  exit: { opacity: 0, transition: { duration: DURATION.fast } },
};

/** Single 2-px shake when a rule chip turns red (never repeats). */
export const shake: TargetAndTransition = {
  x: [0, -2, 2, -2, 0],
  transition: { duration: DURATION.slow, ease: "easeOut" },
};

export const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";

export function systemPrefersReducedMotion(): boolean {
  try {
    return window.matchMedia?.(REDUCED_QUERY).matches ?? false;
  } catch {
    return false;
  }
}
