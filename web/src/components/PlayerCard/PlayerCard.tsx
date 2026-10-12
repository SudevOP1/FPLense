import { motion } from "framer-motion";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { money, points, ratingTier, type RatingTier } from "@/lib/format";
import { popVariants } from "@/lib/motion";
import { useEntrance } from "@/lib/settings";
import { PlayerPhoto } from "./PlayerPhoto";

export interface CardPlayer {
  id: number;
  web_name: string;
  name?: string;
  pos: string;
  club?: string;
  club_short: string;
  price: number;
  photo_url?: string | null;
  rating?: number | null;
  rating_source?: string | null;
  expected?: number | null;
  actual?: number | null;
  captain?: boolean;
  vice?: boolean;
  status?: string | null;
  news?: string | null;
}

export interface MenuItem {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
}

const STATUS_FLAG: Record<string, { label: string; cls: string }> = {
  d: { label: "Doubtful", cls: "bg-warn text-on-accent" },
  i: { label: "Injured", cls: "bg-bad text-white" },
  s: { label: "Suspended", cls: "bg-bad text-white" },
  u: { label: "Unavailable", cls: "bg-bad text-white" },
  n: { label: "Not available", cls: "bg-bad text-white" },
};

// Fixed mid-tone hues, not theme tokens: the band should read the same in light and dark. The
// number sits straight on the photo, so a thin shadow keeps it legible over any background.
const RATING_TEXT: Record<RatingTier, string> = {
  elite: "text-[#2563eb]",
  great: "text-[#16a34a]",
  good: "text-[#ca8a04]",
  fair: "text-[#ea580c]",
  poor: "text-[#dc2626]",
};

const MENU_WIDTH = 176;

/**
 * Action menu. The list is portalled to <body> with fixed positioning so the card's and the
 * pitch's overflow-hidden can't clip it; it closes on outside tap, Escape, scroll and resize.
 */
function CardMenu({ items, name }: { items: MenuItem[]; name: string }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!open || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const left = Math.min(Math.max(8, r.right - MENU_WIDTH), window.innerWidth - MENU_WIDTH - 8);
    setPos({ top: r.bottom + 4, left });
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!ref.current?.contains(t) && !listRef.current?.contains(t)) close();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);
  return (
    <div ref={ref} className="absolute right-0.5 top-0.5 z-10">
      <button
        type="button"
        aria-label={`Actions for ${name}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="relative flex h-6 w-6 items-center justify-center rounded-full bg-surface/90 text-sm font-bold text-ink shadow-sm before:absolute before:-inset-2 before:content-[''] hover:bg-surface"
      >
        ⋯
      </button>
      {open &&
        createPortal(
          <div
            ref={listRef}
            role="menu"
            style={{ top: pos?.top ?? 0, left: pos?.left ?? 0, width: MENU_WIDTH, visibility: pos ? "visible" : "hidden" }}
            className="fixed z-50 rounded-md border border-line bg-raised py-1 text-left shadow-lg"
          >
            {items.map((it) => (
              <button
                key={it.label}
                type="button"
                role="menuitem"
                disabled={it.disabled}
                className="block min-h-[40px] w-full px-3 text-left text-sm hover:bg-line/40 disabled:opacity-50"
                onClick={() => {
                  setOpen(false);
                  it.onSelect();
                }}
              >
                {it.label}
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}

/**
 * Mini FUT-style card: photo, rating badge (FPLense rating, coloured by band),
 * name, price and a points chip (expected for future GWs, actual for finished ones; both in the
 * tooltip). The photo is cropped to head and shoulders to keep cards short, so the captain / vice
 * armband and the availability flag (with the news text) sit beside the name.
 */
export function PlayerCard({
  player,
  mode = "expected",
  onClick,
  menu,
  ring,
  badge,
  ghost = false,
  dimmed = false,
  selected = false,
  extra,
}: {
  player: CardPlayer;
  mode?: "expected" | "actual";
  onClick?: () => void;
  menu?: MenuItem[];
  ring?: string;
  badge?: ReactNode;
  ghost?: boolean;
  dimmed?: boolean;
  selected?: boolean;
  extra?: ReactNode;
}) {
  const entrance = useEntrance();
  const flag = player.status ? STATUS_FLAG[player.status] : undefined;
  const fullName = player.name ?? player.web_name;
  const shown = mode === "actual" ? points(player.actual, "actual") : points(player.expected);
  const tip = [
    fullName,
    `${player.pos} · ${player.club ?? player.club_short} · ${money(player.price)}`,
    `Expected ${points(player.expected)}${player.actual != null ? ` · actual ${points(player.actual, "actual")}` : ""}`,
    player.news ? `News: ${player.news}` : "",
  ]
    .filter(Boolean)
    .join("\n");

  const body = (
    <>
      <div className="relative">
        <PlayerPhoto src={player.photo_url} name={fullName} face className="mx-auto w-[78%]" />
        {player.rating != null && (
          <span
            className={`num absolute left-1 top-1 text-base font-extrabold leading-none [text-shadow:0_0_2px_rgb(var(--surface)),0_1px_1px_rgb(0_0_0/0.25)] ${RATING_TEXT[ratingTier(player.rating)]}`}
            title="FPLense rating"
            aria-label={`FPLense rating ${player.rating}`}
          >
            {player.rating}
          </span>
        )}
      </div>
      <div className="flex flex-col items-center gap-0.5 border-t border-line px-1 pb-1.5 pt-1">
        <span className="flex w-full items-center justify-center gap-1">
          {(player.captain || player.vice) && (
            <motion.span
              {...entrance}
              variants={popVariants}
              className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                (player.captain || player.vice) && "bg-accent text-on-accent"
              }`}
              aria-label={player.captain ? "Captain" : "Vice-captain"}
            >
              <span className="translate-y-[1px]">{player.captain ? "C" : "V"}</span>
            </motion.span>
          )}
          <span className="min-w-0 truncate text-[12px] font-semibold leading-tight" title={fullName}>
            {player.web_name}
          </span>
          {flag && (
            <span
              className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${flag.cls}`}
              title={player.news || flag.label}
            >
              !<span className="sr-only">{`${flag.label}${player.news ? `: ${player.news}` : ""}`}</span>
            </span>
          )}
        </span>
        <span className="flex w-full items-center justify-between gap-1 text-[11px]">
          <span className="num text-muted">{money(player.price)}</span>
          <span
            className={`num rounded-sm px-1 font-bold ${mode === "actual" ? "bg-navy text-surface" : "bg-accent/20 text-ink"}`}
            aria-label={`${mode === "actual" ? "actual" : "expected"} points ${shown}`}
          >
            {shown}
          </span>
        </span>
      </div>
    </>
  );

  return (
    <div
      title={tip}
      data-player={player.id}
      className={`group relative w-full overflow-hidden rounded-md border bg-surface shadow transition duration-fast ease-out ${
        ring ? `ring-2 ${ring}` : ""
      } ${selected ? "border-accent ring-2 ring-accent" : "border-line"} ${ghost ? "border-dashed opacity-70" : ""} ${
        dimmed ? "opacity-50" : ""
      } hover:-translate-y-0.5 hover:shadow-lg`}
    >
      {onClick ? (
        <button
          type="button"
          onClick={onClick}
          className="block w-full text-left"
          aria-label={`${fullName}, ${player.pos}, ${money(player.price)}, ${shown} points`}
        >
          {body}
        </button>
      ) : (
        body
      )}
      {menu && menu.length > 0 && <CardMenu items={menu} name={fullName} />}
      {badge && <div className="pointer-events-none absolute right-1 top-7">{badge}</div>}
      {extra}
    </div>
  );
}
