import { useEffect, useMemo, useRef } from "react";
import { useReducedMotion, useSettings } from "./settings";

// SVG presentation attributes can't use CSS var(), so charts read the theme tokens at runtime.
const TOKENS = ["ink", "muted", "line", "navy", "coral", "accent", "good", "bad", "warn", "slot-a", "slot-b", "slot-c"] as const;
type Token = (typeof TOKENS)[number];

const FALLBACK: Record<Token, string> = {
  ink: "14 24 52",
  muted: "84 94 124",
  line: "222 226 236",
  navy: "20 36 79",
  coral: "196 62 44",
  accent: "255 107 87",
  good: "13 122 72",
  bad: "196 40 40",
  warn: "166 82 0",
  "slot-a": "0 114 178",
  "slot-b": "190 80 0",
  "slot-c": "0 120 88",
};

export type ChartColors = Record<Token, string>;

export function useChartColors(): ChartColors {
  const { resolvedTheme } = useSettings();
  return useMemo(() => {
    // Read the tokens from a probe carrying the new theme: SettingsProvider only flips
    // <html data-theme> in an effect after this render, so the root still has the old theme here.
    const probe = document.createElement("div");
    probe.dataset.theme = resolvedTheme;
    probe.style.display = "none";
    document.body.appendChild(probe);
    const style = getComputedStyle(probe);
    const out = {} as ChartColors;
    for (const t of TOKENS) {
      const raw = style.getPropertyValue(`--${t}`).trim() || FALLBACK[t];
      out[t] = `rgb(${raw})`;
    }
    probe.remove();
    return out;
  }, [resolvedTheme]);
}

/** Lines draw once on first view, not on every re-render; never with reduced motion. */
export function useDrawOnce(): { isAnimationActive: boolean; animationDuration: number } {
  const reduced = useReducedMotion();
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
  }, []);
  return { isAnimationActive: !reduced && !mounted.current, animationDuration: 400 };
}

export const SLOT_TOKENS = ["slot-a", "slot-b", "slot-c"] as const;
export const DASHES = ["0", "6 3", "2 3", "8 3 2 3"];
