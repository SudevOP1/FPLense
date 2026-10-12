import { useId, useState, type ReactNode } from "react";
import { signed, tone } from "@/lib/format";
import type { Letter } from "@/lib/compareSlots";

const TONE_CLASS = { good: "text-good", bad: "text-bad", neutral: "text-muted" } as const;

/** "+2.4" green / "−4" red: the sign is always shown, so colour is never the only cue. */
export function Delta({ value, digits = 1, className = "" }: { value: number; digits?: number; className?: string }) {
  return <span className={`num ${TONE_CLASS[tone(value, digits)]} ${className}`}>{signed(value, digits)}</span>;
}

const SLOT_BG: Record<Letter, string> = { A: "bg-slotA", B: "bg-slotB", C: "bg-slotC" };

/** Compare slot letter: colour-blind-safe colour plus the letter itself. */
export function SlotBadge({ letter, size = "md" }: { letter: Letter; size?: "sm" | "md" }) {
  const dims = size === "sm" ? "h-5 w-5 text-[11px]" : "h-7 w-7 text-sm";
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-full font-display font-bold text-on-slot ${SLOT_BG[letter]} ${dims}`}
      aria-label={`Team ${letter}`}
    >
      {letter}
    </span>
  );
}

export function Badge({ children, tone: t = "neutral", title }: { children: ReactNode; tone?: "neutral" | "warn" | "good" | "bad" | "accent"; title?: string }) {
  const cls = {
    neutral: "border-line bg-raised text-muted",
    warn: "border-warn/40 bg-warn/10 text-warn",
    good: "border-good/40 bg-good/10 text-good",
    bad: "border-bad/40 bg-bad/10 text-bad",
    accent: "border-accent/50 bg-accent/15 text-coral",
  }[t];
  return (
    <span className={`chip ${cls}`} title={title}>
      {children}
    </span>
  );
}

/** One-line jargon explainer: a small "?" button that shows its text on hover or focus. */
export function InfoTip({ text, label = "What's this?" }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="relative inline-flex align-middle">
      <button
        type="button"
        aria-label={label}
        aria-describedby={open ? id : undefined}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-line text-[11px] font-bold text-muted hover:text-ink"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((o) => !o)}
      >
        ?
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute bottom-full left-1/2 z-50 mb-2 w-64 -translate-x-1/2 rounded-md border border-line bg-raised px-3 py-2 text-left text-xs font-normal normal-case tracking-normal text-ink shadow-lg"
        >
          {text}
        </span>
      )}
    </span>
  );
}

export const GLOSSARY = {
  P_h: "P_h: expected points over the next few gameweeks, later weeks weighted a little less.",
  capture:
    "Capture ratio: the model pick's actual points divided by the hindsight-best team's points that week.",
  hindsight:
    "Hindsight best: the best legal £100m squad on that week's actual points (budget, 2-5-5-3, max 3 per club). Not FPL's Dream Team, which ignores budget.",
  backfilled:
    "Backfilled: rebuilt after the fact using only data from before that gameweek. Injury news wasn't known, so everyone counts as fit.",
  rating: "FPLense rating: 50-99, from expected points ranked within the player's position. Ours, not EA FC's.",
  expected: "Expected points: the model's forecast before the deadline.",
} as const;

export function Stat({ label, value, sub, tip }: { label: string; value: ReactNode; sub?: ReactNode; tip?: string }) {
  return (
    <div className="card flex flex-col gap-1 px-4 py-3">
      <span className="label flex items-center gap-1">
        {label}
        {tip && <InfoTip text={tip} label={`About ${label}`} />}
      </span>
      <span className="num text-2xl font-bold">{value}</span>
      {sub && <span className="text-xs text-muted">{sub}</span>}
    </div>
  );
}

/** Segmented control (a radio group). */
export function Segmented<T extends string | number>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded border border-line bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={`min-h-[36px] rounded-sm px-3 text-xs font-semibold transition duration-fast ${
            o.value === value ? "bg-navy text-surface" : "text-muted hover:text-ink"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
