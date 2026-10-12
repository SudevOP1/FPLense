import { useId, useRef, type ReactNode } from "react";

/**
 * Gameweek scrubber: prev / next buttons and a slider (arrow keys work natively), plus swipe
 * left/right on touch screens.
 */
export function GwScrubber({
  gws,
  value,
  onChange,
  label = "Gameweek",
  marks,
}: {
  gws: number[];
  value: number;
  onChange: (gw: number) => void;
  label?: string;
  marks?: (gw: number) => ReactNode;
}) {
  const id = useId();
  const start = useRef<number | null>(null);
  const k = Math.max(0, gws.indexOf(value));
  const go = (d: number) => {
    const next = gws[Math.min(gws.length - 1, Math.max(0, k + d))];
    if (next !== undefined && next !== value) onChange(next);
  };
  return (
    <div
      className="card flex flex-col gap-2 px-4 py-3"
      onPointerDown={(e) => {
        if (e.pointerType === "touch") start.current = e.clientX;
      }}
      onPointerUp={(e) => {
        if (start.current == null) return;
        const dx = e.clientX - start.current;
        start.current = null;
        if (Math.abs(dx) > 48) go(dx < 0 ? 1 : -1);
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id} className="label">
          {label}
        </label>
        <span className="num text-xl font-bold" aria-live="polite">
          GW{value}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <button type="button" className="btn-secondary h-11 w-11 px-0" aria-label="Previous gameweek" disabled={k <= 0} onClick={() => go(-1)}>
          ‹
        </button>
        <input
          id={id}
          type="range"
          min={0}
          max={Math.max(0, gws.length - 1)}
          step={1}
          value={k}
          aria-valuetext={`Gameweek ${value}`}
          onChange={(e) => onChange(gws[Number(e.target.value)])}
          className="h-11 flex-1 accent-[rgb(var(--accent))]"
        />
        <button
          type="button"
          className="btn-secondary h-11 w-11 px-0"
          aria-label="Next gameweek"
          disabled={k >= gws.length - 1}
          onClick={() => go(1)}
        >
          ›
        </button>
      </div>
      {marks && (
        <div className="flex justify-between px-12 text-[10px] text-muted" aria-hidden>
          {gws.map((g) => (
            <span key={g}>{marks(g)}</span>
          ))}
        </div>
      )}
    </div>
  );
}

/** Compact GW select for per-slot pickers. */
export function GwSelect({
  gws,
  value,
  onChange,
  label,
  format = (g) => `GW${g}`,
}: {
  gws: number[];
  value: number | null;
  onChange: (gw: number) => void;
  label: string;
  format?: (gw: number) => string;
}) {
  const id = useId();
  return (
    <span className="inline-flex items-center gap-2">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <select
        id={id}
        value={value ?? ""}
        onChange={(e) => onChange(Number(e.target.value))}
        className="field min-h-[40px] w-auto py-1 pr-8 text-sm"
      >
        {value == null && <option value="">Pick a GW</option>}
        {gws.map((g) => (
          <option key={g} value={g}>
            {format(g)}
          </option>
        ))}
      </select>
    </span>
  );
}
