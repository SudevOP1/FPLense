import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Segmented } from "@/components/ui/Bits";
import { DASHES, SLOT_TOKENS, useChartColors, useDrawOnce } from "@/lib/chartColors";
import { pct, points, rank, signed } from "@/lib/format";
import { ChartFrame, Legend } from "./ChartFrame";

const AXIS = { fontSize: 11 };

// The tooltip is HTML, so it uses the CSS tokens directly: they resolve against the nearest
// data-theme ancestor at paint time, never a stale JS snapshot.
function tooltipStyle() {
  return {
    contentStyle: {
      background: "rgb(var(--raised))",
      border: "1px solid rgb(var(--line))",
      borderRadius: 8,
      fontSize: 12,
      color: "rgb(var(--ink))",
    },
    labelStyle: { color: "rgb(var(--ink))", fontWeight: 600 },
    itemStyle: { color: "rgb(var(--ink))" },
  };
}

// --- season lines ------------------------------------------------------------------------------

export interface SeasonSeries {
  key: string;
  label: string;
  values: (number | null)[];
  token?: "navy" | "accent" | "muted" | "good" | "slot-a" | "slot-b" | "slot-c" | "warn";
}

/**
 * Points per GW (or cumulative) for several series: model pick, hindsight best, average, highest,
 * and optionally your team with your overall rank on a second axis and chip weeks marked.
 */
export function SeasonChart({
  title,
  gws,
  series,
  onSelectGw,
  selectedGw,
  rankValues,
  chips = [],
}: {
  title: string;
  gws: number[];
  series: SeasonSeries[];
  onSelectGw?: (gw: number) => void;
  selectedGw?: number | null;
  rankValues?: (number | null)[];
  chips?: { gw: number; name: string }[];
}) {
  const c = useChartColors();
  const draw = useDrawOnce();
  const [mode, setMode] = useState<"gw" | "cum">("gw");
  const data = gws.map((gw, k) => {
    const row: Record<string, number | null> = { gw };
    for (const s of series) {
      if (mode === "gw") row[s.key] = s.values[k];
      else row[s.key] = s.values.slice(0, k + 1).reduce<number>((a, v) => a + (v ?? 0), 0);
    }
    if (rankValues) row.rank = rankValues[k];
    return row;
  });
  const colour = (s: SeasonSeries, k: number) => c[s.token ?? (["navy", "accent", "muted", "good"] as const)[k % 4]];
  const best = series.map((s) => `${s.label} ${s.values.reduce<number>((a, v) => a + (v ?? 0), 0)} in total`).join(", ");
  return (
    <ChartFrame
      title={title}
      summary={`${title}, gameweeks ${gws[0]} to ${gws[gws.length - 1]}: ${best}.`}
      table={{
        columns: ["GW", ...series.map((s) => s.label), ...(rankValues ? ["Overall rank"] : [])],
        rows: gws.map((gw, k) => [
          gw,
          ...series.map((s) => points(s.values[k], "actual")),
          ...(rankValues ? [rank(rankValues[k])] : []),
        ]),
      }}
      actions={
        <Segmented
          label="Points per gameweek or cumulative"
          value={mode}
          onChange={setMode}
          options={[
            { value: "gw", label: "Per GW" },
            { value: "cum", label: "Cumulative" },
          ]}
        />
      }
    >
      <div className="flex h-full flex-col gap-2">
        <Legend
          items={[
            ...series.map((s, k) => ({ label: s.label, color: colour(s, k), dash: DASHES[k % DASHES.length] })),
            ...(rankValues ? [{ label: "Your rank (right axis)", color: c.warn, dash: "1 3" }] : []),
          ]}
        />
        <div className="min-h-0 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={data}
              margin={{ top: 8, right: rankValues ? 8 : 12, bottom: 0, left: -12 }}
              onClick={(e) => {
                const gw = Number(e?.activeLabel);
                if (onSelectGw && Number.isFinite(gw)) onSelectGw(gw);
              }}
              style={{ cursor: onSelectGw ? "pointer" : undefined }}
            >
              <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="gw" tick={{ ...AXIS, fill: c.muted }} stroke={c.line} tickFormatter={(g) => `GW${g}`} />
              <YAxis yAxisId="pts" tick={{ ...AXIS, fill: c.muted }} stroke={c.line} />
              {rankValues && (
                <YAxis
                  yAxisId="rank"
                  orientation="right"
                  reversed
                  tick={{ ...AXIS, fill: c.muted }}
                  stroke={c.line}
                  tickFormatter={(v) => (v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${Math.round(v / 1e3)}k` : v)}
                />
              )}
              <Tooltip {...tooltipStyle()} labelFormatter={(g) => `GW${g}`} />
              {selectedGw != null && <ReferenceLine yAxisId="pts" x={selectedGw} stroke={c.accent} strokeWidth={2} />}
              {chips.map((ch) => (
                <ReferenceLine
                  key={`${ch.gw}-${ch.name}`}
                  yAxisId="pts"
                  x={ch.gw}
                  stroke={c.warn}
                  strokeDasharray="2 2"
                  label={{ value: ch.name, position: "top", fill: c.warn, fontSize: 10 }}
                />
              ))}
              {series.map((s, k) => (
                <Line
                  key={s.key}
                  yAxisId="pts"
                  dataKey={s.key}
                  name={s.label}
                  stroke={colour(s, k)}
                  strokeWidth={2.25}
                  strokeDasharray={DASHES[k % DASHES.length]}
                  dot={{ r: 2.5 }}
                  connectNulls
                  {...draw}
                />
              ))}
              {rankValues && (
                <Line yAxisId="rank" dataKey="rank" name="Overall rank" stroke={c.warn} strokeDasharray="1 3" dot={false} {...draw} />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    </ChartFrame>
  );
}

// --- capture ratio ------------------------------------------------------------------------------

export function CaptureBars({
  rows,
  selectedGw,
  onSelectGw,
}: {
  rows: { gw: number; capture: number | null }[];
  selectedGw?: number | null;
  onSelectGw?: (gw: number) => void;
}) {
  const c = useChartColors();
  const draw = useDrawOnce();
  const mean = rows.filter((r) => r.capture != null).reduce((a, r, _, all) => a + (r.capture ?? 0) / all.length, 0);
  return (
    <ChartFrame
      title="Capture ratio per gameweek"
      summary={`Model pick points as a share of the hindsight-best team, per gameweek; average ${pct(mean)}.`}
      table={{ columns: ["GW", "Capture ratio"], rows: rows.map((r) => [r.gw, pct(r.capture)]) }}
      height={200}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={rows.map((r) => ({ gw: r.gw, capture: r.capture == null ? null : r.capture * 100 }))}
          margin={{ top: 8, right: 8, bottom: 0, left: -16 }}
          onClick={(e) => {
            const gw = Number(e?.activeLabel);
            if (onSelectGw && Number.isFinite(gw)) onSelectGw(gw);
          }}
        >
          <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="gw" tick={{ ...AXIS, fill: c.muted }} stroke={c.line} tickFormatter={(g) => `GW${g}`} />
          <YAxis domain={[0, 100]} tick={{ ...AXIS, fill: c.muted }} stroke={c.line} unit="%" />
          <Tooltip {...tooltipStyle()} labelFormatter={(g) => `GW${g}`} formatter={(v: number) => [`${v.toFixed(0)}%`, "Capture"]} />
          <Bar dataKey="capture" radius={[4, 4, 0, 0]} style={{ cursor: onSelectGw ? "pointer" : undefined }} {...draw}>
            {rows.map((r) => (
              <Cell key={r.gw} fill={r.gw === selectedGw ? c.accent : c.navy} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}

// --- transfers: net gain by number of transfers -----------------------------------------------

export function NetGainChart({
  options,
}: {
  options: { n: number; gain: number; hits: number; net: number; recommended: boolean }[];
}) {
  const c = useChartColors();
  const draw = useDrawOnce();
  const best = options.find((o) => o.recommended);
  return (
    <ChartFrame
      title="Net gain by number of transfers"
      summary={`Expected gain after hit costs for 0 to ${options.length - 1} transfers; the recommended option is ${best?.n ?? 0} transfer(s) for ${signed(best?.net ?? 0)} points.`}
      table={{
        columns: ["Transfers", "Gain before hits", "Hit cost", "Net gain"],
        rows: options.map((o) => [o.n, signed(o.gain), o.hits ? `${-o.hits}` : "0", signed(o.net)]),
      }}
      height={220}
    >
      <div className="flex h-full flex-col gap-2">
        <Legend
          items={[
            { label: "Net gain", color: c.navy },
            { label: "Hit cost", color: c.bad, dash: "6 3" },
            { label: "Break-even (0)", color: c.muted, dash: "2 3" },
          ]}
        />
        <div className="min-h-0 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={options} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="n" tick={{ ...AXIS, fill: c.muted }} stroke={c.line} />
              <YAxis tick={{ ...AXIS, fill: c.muted }} stroke={c.line} />
              <Tooltip {...tooltipStyle()} labelFormatter={(n) => `${n} transfer(s)`} />
              <ReferenceLine y={0} stroke={c.muted} strokeDasharray="2 3" />
              <Bar dataKey="net" name="Net gain" radius={[4, 4, 0, 0]} {...draw}>
                {options.map((o) => (
                  <Cell key={o.n} fill={o.recommended ? c.accent : c.navy} />
                ))}
              </Bar>
              <Line dataKey={(o: { hits: number }) => -o.hits} name="Hit cost" stroke={c.bad} strokeDasharray="6 3" dot={false} {...draw} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    </ChartFrame>
  );
}

// --- compare --------------------------------------------------------------------------------------

export function GroupedBars({
  title,
  categories,
  slots,
  unit = "pts",
}: {
  title: string;
  categories: string[];
  slots: { letter: string; values: (number | null)[] }[];
  unit?: string;
}) {
  const c = useChartColors();
  const draw = useDrawOnce();
  const data = categories.map((cat, k) => {
    const row: Record<string, string | number | null> = { cat };
    for (const s of slots) row[s.letter] = s.values[k];
    return row;
  });
  return (
    <ChartFrame
      title={title}
      summary={`${title}: ${categories
        .map((cat, k) => `${cat} ${slots.map((s) => `${s.letter} ${points(s.values[k])}`).join(", ")}`)
        .join("; ")}.`}
      table={{ columns: ["", ...slots.map((s) => `Team ${s.letter}`)], rows: categories.map((cat, k) => [cat, ...slots.map((s) => points(s.values[k]))]) }}
      height={220}
    >
      <div className="flex h-full flex-col gap-2">
        <Legend items={slots.map((s, k) => ({ label: `Team ${s.letter}`, color: c[SLOT_TOKENS[k]], letter: s.letter }))} />
        <div className="min-h-0 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="cat" tick={{ ...AXIS, fill: c.muted }} stroke={c.line} />
              <YAxis tick={{ ...AXIS, fill: c.muted }} stroke={c.line} unit={unit === "pts" ? "" : unit} />
              <Tooltip {...tooltipStyle()} formatter={(v: number, name) => [points(v), `Team ${name}`]} />
              {slots.map((s, k) => (
                <Bar key={s.letter} dataKey={s.letter} fill={c[SLOT_TOKENS[k]]} radius={[3, 3, 0, 0]} {...draw} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </ChartFrame>
  );
}

export function HorizonLines({ gws, slots }: { gws: number[]; slots: { letter: string; values: (number | null)[] }[] }) {
  const c = useChartColors();
  const draw = useDrawOnce();
  const data = gws.map((gw, k) => {
    const row: Record<string, number | null> = { gw };
    for (const s of slots) row[s.letter] = s.values[k];
    return row;
  });
  return (
    <ChartFrame
      title="Expected points per upcoming gameweek"
      summary={`Expected points per gameweek for each team: ${slots
        .map((s) => `${s.letter}: ${s.values.map((v) => points(v)).join(", ")}`)
        .join("; ")}.`}
      table={{ columns: ["GW", ...slots.map((s) => `Team ${s.letter}`)], rows: gws.map((gw, k) => [gw, ...slots.map((s) => points(s.values[k]))]) }}
      height={220}
    >
      <div className="flex h-full flex-col gap-2">
        <Legend items={slots.map((s, k) => ({ label: `Team ${s.letter}`, color: c[SLOT_TOKENS[k]], dash: DASHES[k], letter: s.letter }))} />
        <div className="min-h-0 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="gw" tick={{ ...AXIS, fill: c.muted }} stroke={c.line} tickFormatter={(g) => `GW${g}`} />
              <YAxis tick={{ ...AXIS, fill: c.muted }} stroke={c.line} />
              <Tooltip {...tooltipStyle()} labelFormatter={(g) => `GW${g}`} formatter={(v: number, name) => [points(v), `Team ${name}`]} />
              {slots.map((s, k) => (
                <Line key={s.letter} dataKey={s.letter} stroke={c[SLOT_TOKENS[k]]} strokeWidth={2.25} strokeDasharray={DASHES[k]} dot={{ r: 3 }} {...draw} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </ChartFrame>
  );
}

/** Expected vs actual per team: a dumbbell (two dots joined by a line) per slot. */
export function Dumbbell({ rows }: { rows: { letter: string; expected: number | null; actual: number | null }[] }) {
  const max = Math.max(1, ...rows.flatMap((r) => [r.expected ?? 0, r.actual ?? 0]));
  const colours = ["bg-slotA", "bg-slotB", "bg-slotC"];
  return (
    <ChartFrame
      title="Expected vs actual points"
      summary={rows.map((r) => `Team ${r.letter}: expected ${points(r.expected)}, actual ${points(r.actual, "actual")}`).join("; ")}
      table={{ columns: ["Team", "Expected", "Actual"], rows: rows.map((r) => [r.letter, points(r.expected), points(r.actual, "actual")]) }}
      height={40 + rows.length * 44}
    >
      <ul className="flex flex-col gap-4 pt-2">
        {rows.map((r, k) => {
          const e = ((r.expected ?? 0) / max) * 100;
          const a = ((r.actual ?? 0) / max) * 100;
          return (
            <li key={r.letter} className="flex items-center gap-3">
              <span className="w-5 font-display font-bold">{r.letter}</span>
              <div className="relative h-3 flex-1 rounded-full bg-line/50">
                {r.actual != null && (
                  <span
                    className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-muted"
                    style={{ left: `${Math.min(e, a)}%`, width: `${Math.abs(a - e)}%` }}
                  />
                )}
                <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink bg-surface" style={{ left: `${e}%` }} />
                {r.actual != null && (
                  <span className={`absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full ${colours[k]}`} style={{ left: `${a}%` }} />
                )}
              </div>
              <span className="num w-24 text-right text-xs text-muted">
                {points(r.expected)} → {r.actual == null ? "–" : points(r.actual, "actual")}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs text-muted">Hollow dot: expected. Filled dot: actual.</p>
    </ChartFrame>
  );
}

// --- model card / player drawer -------------------------------------------------------------------

export function MaeByGw({ series }: { series: { key: string; label: string; gws: number[]; mae: number[] }[] }) {
  const c = useChartColors();
  const draw = useDrawOnce();
  const gws = series[0]?.gws ?? [];
  const data = gws.map((gw, k) => {
    const row: Record<string, number> = { gw };
    for (const s of series) row[s.key] = s.mae[k];
    return row;
  });
  const tokens = ["muted", "navy", "accent"] as const;
  return (
    <ChartFrame
      title="MAE by gameweek (regulars, 2025-26 walk-forward)"
      summary={`Mean absolute error per gameweek for ${series.map((s) => s.label).join(", ")}; lower is better.`}
      table={{ columns: ["GW", ...series.map((s) => s.label)], rows: gws.map((gw, k) => [gw, ...series.map((s) => s.mae[k].toFixed(3))]) }}
    >
      <div className="flex h-full flex-col gap-2">
        <Legend items={series.map((s, k) => ({ label: s.label, color: c[tokens[k % 3]], dash: DASHES[k] }))} />
        <div className="min-h-0 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
              <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="gw" tick={{ ...AXIS, fill: c.muted }} stroke={c.line} />
              <YAxis domain={["auto", "auto"]} tick={{ ...AXIS, fill: c.muted }} stroke={c.line} />
              <Tooltip {...tooltipStyle()} labelFormatter={(g) => `GW${g}`} formatter={(v: number) => v.toFixed(3)} />
              {series.map((s, k) => (
                <Line key={s.key} dataKey={s.key} name={s.label} stroke={c[tokens[k % 3]]} strokeDasharray={DASHES[k]} strokeWidth={2} dot={false} {...draw} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </ChartFrame>
  );
}

/** Horizontal bars (SHAP importance, or a waterfall's signed contributions). */
export function HBars({
  title,
  summary,
  rows,
  signedValues = false,
  valueLabel = "Value",
}: {
  title: string;
  summary: string;
  rows: { label: string; value: number; note?: string }[];
  signedValues?: boolean;
  valueLabel?: string;
}) {
  const max = Math.max(1e-9, ...rows.map((r) => Math.abs(r.value)));
  const fmt = (v: number) => (signedValues ? signed(v, 2) : v.toFixed(3));
  return (
    <ChartFrame
      title={title}
      summary={summary}
      table={{ columns: ["Feature", valueLabel, ...(rows.some((r) => r.note) ? ["Value"] : [])], rows: rows.map((r) => [r.label, fmt(r.value), ...(r.note ? [r.note] : [])]) }}
      height={Math.max(120, rows.length * 26 + 8)}
    >
      <ul className="flex flex-col gap-1.5">
        {rows.map((r) => {
          const w = (Math.abs(r.value) / max) * (signedValues ? 50 : 100);
          return (
            <li key={r.label} className="grid grid-cols-[minmax(0,9rem)_1fr_3.5rem] items-center gap-2 text-xs">
              <span className="truncate text-muted" title={r.note ? `${r.label} = ${r.note}` : r.label}>
                {r.label}
              </span>
              <span className="relative h-3">
                {signedValues && <span className="absolute inset-y-0 left-1/2 w-px bg-line" />}
                <span
                  className={`absolute inset-y-0 rounded-sm ${!signedValues ? "bg-navy" : r.value >= 0 ? "bg-good" : "bg-bad"}`}
                  style={
                    signedValues
                      ? r.value >= 0
                        ? { left: "50%", width: `${w}%` }
                        : { right: "50%", width: `${w}%` }
                      : { left: 0, width: `${w}%` }
                  }
                />
              </span>
              <span className="num text-right">{fmt(r.value)}</span>
            </li>
          );
        })}
      </ul>
    </ChartFrame>
  );
}

/** Tiny per-GW expected points bars (no axes) for cards and lists. */
export function MiniBars({ values, label }: { values: { gw: number; points: number }[]; label: string }) {
  const max = Math.max(1, ...values.map((v) => v.points));
  return (
    <span className="inline-flex h-6 items-end gap-0.5" role="img" aria-label={`${label}: ${values.map((v) => `GW${v.gw} ${v.points.toFixed(1)}`).join(", ")}`}>
      {values.map((v) => (
        <span key={v.gw} className="w-1.5 rounded-t-sm bg-accent" style={{ height: `${Math.max(8, (v.points / max) * 100)}%` }} title={`GW${v.gw}: ${v.points.toFixed(1)}`} />
      ))}
    </span>
  );
}
