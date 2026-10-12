// Display formatting shared by every page. Prices are integer tenths of £1m (55 = £5.5m).

export const MINUS = "−"; // a real minus sign, so "−4" lines up with "+2.4"

/** 55 -> "£5.5m"; always one decimal. */
export function money(tenths: number | null | undefined): string {
  if (tenths == null || Number.isNaN(tenths)) return "–";
  const sign = tenths < 0 ? MINUS : "";
  return `${sign}£${(Math.abs(tenths) / 10).toFixed(1)}m`;
}

/** Expected points get 1 decimal, actual points are integers. */
export function points(
  value: number | null | undefined,
  kind: "expected" | "actual" = "expected",
): string {
  if (value == null || Number.isNaN(value)) return "–";
  const text = kind === "actual" ? String(Math.round(value)) : value.toFixed(1);
  return text.replace("-", MINUS);
}

/** Signed delta with the sign always shown: "+2.4", "−4", "0.0". */
export function signed(value: number, digits = 1): string {
  const rounded = Number(value.toFixed(digits));
  if (rounded === 0) return (0).toFixed(digits);
  const body = Math.abs(rounded).toFixed(digits);
  return rounded > 0 ? `+${body}` : `${MINUS}${body}`;
}

export type Tone = "good" | "bad" | "neutral";

export function tone(value: number | null | undefined, digits = 1): Tone {
  if (value == null) return "neutral";
  const rounded = Number(value.toFixed(digits));
  return rounded > 0 ? "good" : rounded < 0 ? "bad" : "neutral";
}

export function pct(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "–";
  return `${(value * 100).toFixed(digits)}%`;
}

export function rank(value: number | null | undefined): string {
  if (value == null) return "–";
  return new Intl.NumberFormat("en-GB").format(value);
}

const DAY = 86_400_000;
const HOUR = 3_600_000;
const MINUTE = 60_000;

/** "in 2 days", "in 5 hours", "in 35 minutes", "now", "3 hours ago". */
export function relative(iso: string, now: number = Date.now()): string {
  const diff = new Date(iso).getTime() - now;
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const abs = Math.abs(diff);
  if (abs < MINUTE) return "now";
  if (abs < HOUR) return rtf.format(Math.round(diff / MINUTE), "minute");
  if (abs < DAY) return rtf.format(Math.round(diff / HOUR), "hour");
  return rtf.format(Math.round(diff / DAY), "day");
}

/** "Sat 11:00 · in 2 days" in the viewer's timezone (or the one given, for tests). */
export function deadlineText(iso: string, now: number = Date.now(), timeZone?: string): string {
  const when = new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  }).format(new Date(iso));
  return `${when} · ${relative(iso, now)}`;
}

/** "Sat 4 Oct" in the viewer's timezone. */
export function shortDate(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone,
  }).format(new Date(iso));
}

export type Urgency = "calm" | "amber" | "red" | "passed";

/** Deadline colour: amber under 24 h, red under 1 h. */
export function urgency(msLeft: number): Urgency {
  if (msLeft <= 0) return "passed";
  if (msLeft < HOUR) return "red";
  if (msLeft < DAY) return "amber";
  return "calm";
}

export type RatingTier = "elite" | "great" | "good" | "fair" | "poor";

/** Card rating colour band on the 50-99 FPLense scale: blue 90+, green 80+, yellow 70+, orange 60+, red. */
export function ratingTier(rating: number): RatingTier {
  if (rating >= 90) return "elite";
  if (rating >= 80) return "great";
  if (rating >= 70) return "good";
  if (rating >= 60) return "fair";
  return "poor";
}

export function countdownParts(msLeft: number): { d: number; h: number; m: number; s: number } {
  const t = Math.max(0, Math.floor(msLeft / 1000));
  return {
    d: Math.floor(t / 86400),
    h: Math.floor((t % 86400) / 3600),
    m: Math.floor((t % 3600) / 60),
    s: t % 60,
  };
}

export const POSITIONS = ["GK", "DEF", "MID", "FWD"] as const;
export type Pos = (typeof POSITIONS)[number];

export const POS_LABEL: Record<Pos, string> = {
  GK: "Goalkeepers",
  DEF: "Defenders",
  MID: "Midfielders",
  FWD: "Forwards",
};
