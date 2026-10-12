import { useEffect, useState } from "react";
import { countdownParts, deadlineText, urgency } from "@/lib/format";

const URGENCY_CLASS = {
  calm: "text-ink",
  amber: "text-warn",
  red: "text-bad",
  passed: "text-muted",
} as const;

/** Live deadline countdown: amber under 24 h, red under 1 h; local time with a relative hint. */
export function Countdown({ deadline, gw }: { deadline: string; gw: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);
  const left = new Date(deadline).getTime() - now;
  const u = urgency(left);
  const { d, h, m, s } = countdownParts(left);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    // inline-size container: the digits scale with the card instead of overflowing narrow ones
    <div className="flex min-w-0 flex-col gap-1" style={{ containerType: "inline-size" }}>
      <span className="label">GW{gw} deadline</span>
      <span
        className={`num whitespace-nowrap font-bold leading-tight ${URGENCY_CLASS[u]}`}
        style={{ fontSize: "clamp(1rem, 13cqi, 2.25rem)" }}
        aria-hidden
      >
        {u === "passed" ? "Passed" : `${d > 0 ? `${d}d ` : ""}${pad(h)}:${pad(m)}:${pad(s)}`}
      </span>
      <span className="sr-only">
        {u === "passed" ? "The deadline has passed." : `Deadline ${deadlineText(deadline, now)}`}
      </span>
      <span className="text-sm text-muted">{deadlineText(deadline, now)}</span>
    </div>
  );
}
