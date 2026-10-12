// Theme (system / light / dark) and the in-app "Reduce motion" toggle, remembered locally.

import { MotionConfig } from "framer-motion";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { REDUCED_QUERY, systemPrefersReducedMotion } from "./motion";
import { load, save } from "./storage";

export type ThemePref = "system" | "light" | "dark";

interface Settings {
  theme: ThemePref;
  resolvedTheme: "light" | "dark";
  setTheme: (t: ThemePref) => void;
  reduceMotionPref: boolean;
  setReduceMotionPref: (v: boolean) => void;
  /** true when either the system asks for reduced motion or the toggle is on */
  reducedMotion: boolean;
}

const SettingsContext = createContext<Settings | null>(null);

function useMedia(query: string, initial: () => boolean): boolean {
  const [matches, setMatches] = useState(initial);
  useEffect(() => {
    let mql: MediaQueryList | undefined;
    try {
      mql = window.matchMedia?.(query);
    } catch {
      mql = undefined;
    }
    if (!mql) return;
    const onChange = () => setMatches(mql!.matches);
    onChange();
    mql.addEventListener?.("change", onChange);
    return () => mql!.removeEventListener?.("change", onChange);
  }, [query]);
  return matches;
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemePref>(() => load<ThemePref>("theme", "system"));
  const [reduceMotionPref, setReducePref] = useState<boolean>(() => load("reduceMotion", false));
  const systemDark = useMedia("(prefers-color-scheme: dark)", () => {
    try {
      return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
    } catch {
      return false;
    }
  });
  const systemReduced = useMedia(REDUCED_QUERY, systemPrefersReducedMotion);
  const resolvedTheme = theme === "system" ? (systemDark ? "dark" : "light") : theme;
  const reducedMotion = reduceMotionPref || systemReduced;

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = resolvedTheme;
    root.style.colorScheme = resolvedTheme;
    root.classList.toggle("reduce-motion", reducedMotion);
  }, [resolvedTheme, reducedMotion]);

  const value = useMemo<Settings>(
    () => ({
      theme,
      resolvedTheme,
      setTheme: (t) => {
        setThemeState(t);
        save("theme", t);
      },
      reduceMotionPref,
      setReduceMotionPref: (v) => {
        setReducePref(v);
        save("reduceMotion", v);
      },
      reducedMotion,
    }),
    [theme, resolvedTheme, reduceMotionPref, reducedMotion],
  );

  return (
    <SettingsContext.Provider value={value}>
      <MotionConfig reducedMotion={reducedMotion ? "always" : "never"}>{children}</MotionConfig>
    </SettingsContext.Provider>
  );
}

export function useSettings(): Settings {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings outside SettingsProvider");
  return ctx;
}

/** Reduced motion from settings; safe outside the provider (falls back to the system query). */
export function useReducedMotion(): boolean {
  const ctx = useContext(SettingsContext);
  return ctx ? ctx.reducedMotion : systemPrefersReducedMotion();
}

/**
 * Framer props for an entrance animation: with reduced motion the element mounts in its final
 * state (initial={false}), so nothing animates.
 */
export function useEntrance(): { initial: "hidden" | false; animate: "shown" } {
  const reduced = useReducedMotion();
  return { initial: reduced ? false : "hidden", animate: "shown" };
}
