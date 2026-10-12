import { useId, useState, type ReactNode } from "react";

export interface TableData {
  columns: string[];
  rows: (string | number)[][];
}

/**
 * Every chart gets a visually hidden summary for screen readers and a "Show as table" toggle
 * with the same numbers.
 */
export function ChartFrame({
  title,
  summary,
  table,
  children,
  height = 260,
  actions,
}: {
  title: string;
  summary: string;
  table: TableData;
  children: ReactNode;
  height?: number;
  actions?: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  const summaryId = useId();
  return (
    <figure className="card flex flex-col gap-2 p-4" aria-describedby={summaryId}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <figcaption className="font-display font-semibold">{title}</figcaption>
        <div className="flex flex-wrap items-center gap-2">
          {actions}
          <button
            type="button"
            className="btn-ghost min-h-[36px] px-2 text-xs"
            aria-pressed={asTable}
            onClick={() => setAsTable((v) => !v)}
          >
            {asTable ? "Show chart" : "Show as table"}
          </button>
        </div>
      </div>
      <p id={summaryId} className="sr-only">
        {summary}
      </p>
      {asTable ? (
        <div className="max-h-[360px] overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                {table.columns.map((c) => (
                  <th key={c} scope="col" className="border-b border-line px-2 py-1 text-left font-semibold text-muted">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r, k) => (
                <tr key={k} className="border-b border-line/60">
                  {r.map((v, j) => (
                    <td key={j} className="num px-2 py-1">
                      {v}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ height }} aria-hidden>
          {children}
        </div>
      )}
    </figure>
  );
}

export function Legend({ items }: { items: { label: string; color: string; dash?: string; letter?: string }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted" aria-hidden>
      {items.map((it) => (
        <li key={it.label} className="flex items-center gap-1.5">
          <svg width="22" height="8" aria-hidden>
            <line x1="1" y1="4" x2="21" y2="4" stroke={it.color} strokeWidth="2.5" strokeDasharray={it.dash} />
          </svg>
          {it.letter && <strong className="text-ink">{it.letter}</strong>}
          {it.label}
        </li>
      ))}
    </ul>
  );
}
