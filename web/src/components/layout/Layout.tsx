import { motion } from "framer-motion";
import { Suspense, useEffect, useState } from "react";
import { NavLink, Outlet, ScrollRestoration, useLocation } from "react-router-dom";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { Segmented } from "@/components/ui/Bits";
import { Sheet } from "@/components/ui/Sheet";
import { Skeleton } from "@/components/ui/States";
import { pageVariants } from "@/lib/motion";
import { PlayerDrawerProvider } from "@/lib/playerDrawer";
import { useEntrance, useSettings, type ThemePref } from "@/lib/settings";
import { CompareTray } from "./CompareTray";
import { SearchDialog } from "./SearchDialog";
import { ServerStatus } from "./ServerStatus";
import { Tour } from "./Tour";

const MAIN = [
  { to: "/", label: "Home", icon: "⌂", end: true },
  { to: "/best", label: "Best Team", icon: "★" },
  { to: "/season", label: "Season", icon: "↺" },
  { to: "/me", label: "My Team", icon: "☺" },
  { to: "/compare", label: "Compare", icon: "⇄" },
];
const MORE = [
  { to: "/builder", label: "Builder" },
  { to: "/players", label: "Players" },
  { to: "/model", label: "Model" },
];

function SettingsPanel() {
  const s = useSettings();
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <span className="label">Theme</span>
        <Segmented<ThemePref>
          label="Theme"
          value={s.theme}
          onChange={s.setTheme}
          options={[
            { value: "system", label: "System" },
            { value: "light", label: "Light" },
            { value: "dark", label: "Dark" },
          ]}
        />
      </div>
      <label className="flex min-h-[44px] items-center justify-between gap-3 text-sm">
        <span>
          Reduce motion
          <span className="block text-xs text-muted">Turns animations into instant changes.</span>
        </span>
        <input
          type="checkbox"
          className="h-5 w-5 accent-[rgb(var(--accent))]"
          checked={s.reduceMotionPref}
          onChange={(e) => s.setReduceMotionPref(e.target.checked)}
        />
      </label>
    </div>
  );
}

function PageFallback() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading page">
      <Skeleton className="h-9 w-56" />
      <Skeleton className="h-[420px] w-full rounded-xl" />
    </div>
  );
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  `relative rounded px-3 py-2 text-sm font-semibold transition-colors duration-fast ${
    isActive ? "text-ink" : "text-muted hover:text-ink"
  }`;

export function Layout() {
  const location = useLocation();
  const entrance = useEntrance();
  const [search, setSearch] = useState(false);
  const [settings, setSettings] = useState(false);
  const [more, setMore] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement | null)?.closest("input, textarea, select, [contenteditable='true']");
      if ((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        setSearch(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <PlayerDrawerProvider>
    <div className="flex min-h-dvh flex-col">
      <a href="#main" className="sr-only-focusable fixed left-2 top-2 z-[80] rounded bg-surface px-3 py-2 shadow">
        Skip to content
      </a>
      <ServerStatus />
      <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4">
          <NavLink to="/" className="mr-2 flex items-center gap-2 font-display text-lg font-bold" aria-label="FPLense home">
            <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width={28} height={28} className="rounded-md" />
            FPL<span className="text-coral">ense</span>
          </NavLink>
          <nav aria-label="Main" className="hidden flex-1 items-center gap-1 md:flex">
            {[...MAIN.slice(1), ...MORE].map((n) => (
              <NavLink key={n.to} to={n.to} className={navClass}>
                {({ isActive }) => (
                  <>
                    {n.label}
                    {isActive && <motion.span layoutId="nav-underline" className="absolute inset-x-3 -bottom-[9px] h-0.5 rounded-full bg-accent" />}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              className="btn-ghost px-3"
              onClick={() => setSearch(true)}
              aria-label="Search players"
              title="Search players (/ or Ctrl+K)"
            >
              <span aria-hidden>⌕</span>
              <span className="hidden text-muted lg:inline">Search</span>
              <kbd className="hidden rounded border border-line px-1.5 text-[10px] text-muted lg:inline">Ctrl K</kbd>
            </button>
            <button type="button" className="btn-ghost px-3" onClick={() => setSettings(true)} aria-label="Settings" title="Theme and motion">
              <span aria-hidden>⚙</span>
            </button>
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 pb-36 pt-5 md:pb-24">
        <ErrorBoundary resetKey={location.pathname}>
          <Suspense fallback={<PageFallback />}>
            <motion.div key={location.pathname} variants={pageVariants} {...entrance}>
              <Outlet />
            </motion.div>
          </Suspense>
        </ErrorBoundary>
      </main>

      <footer className="hidden border-t border-line py-6 text-center text-xs text-muted md:block">
        FPLense · not affiliated with the Premier League · player photos © Premier League (hotlinked) · not betting advice ·{" "}
        <a className="underline" href="https://github.com/SudevOP1/FPLense">source</a>
      </footer>

      <nav aria-label="Tabs" className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        <ul className="grid grid-cols-6">
          {MAIN.map((n) => (
            <li key={n.to}>
              <NavLink
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `flex min-h-[56px] flex-col items-center justify-center gap-0.5 text-[11px] font-semibold ${isActive ? "text-coral" : "text-muted"}`
                }
              >
                <span aria-hidden className="text-base leading-none">
                  {n.icon}
                </span>
                {n.label}
              </NavLink>
            </li>
          ))}
          <li>
            <button
              type="button"
              className="flex min-h-[56px] w-full flex-col items-center justify-center gap-0.5 text-[11px] font-semibold text-muted"
              onClick={() => setMore(true)}
              aria-haspopup="dialog"
            >
              <span aria-hidden className="text-base leading-none">
                ⋯
              </span>
              More
            </button>
          </li>
        </ul>
      </nav>

      <CompareTray />
      <SearchDialog open={search} onClose={() => setSearch(false)} />
      <Sheet open={settings} onClose={() => setSettings(false)} title="Settings" side="center">
        <SettingsPanel />
      </Sheet>
      <Sheet open={more} onClose={() => setMore(false)} title="More">
        <ul className="flex flex-col gap-1">
          {MORE.map((n) => (
            <li key={n.to}>
              <NavLink to={n.to} onClick={() => setMore(false)} className="flex min-h-[48px] items-center rounded px-3 font-semibold hover:bg-line/40">
                {n.label}
              </NavLink>
            </li>
          ))}
          <li>
            <button
              type="button"
              className="flex min-h-[48px] w-full items-center rounded px-3 text-left font-semibold hover:bg-line/40"
              onClick={() => {
                setMore(false);
                setSettings(true);
              }}
            >
              Settings
            </button>
          </li>
        </ul>
      </Sheet>
      <Tour />
      <ScrollRestoration />
    </div>
    </PlayerDrawerProvider>
  );
}
