import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { useTransferPlan } from "@/api/hooks";
import type { Move, Squad, TransferIn, TransferOut } from "@/api/types";
import { NetGainChart } from "@/components/charts/Charts";
import { CodeBox } from "@/components/CodeBox/CodeBox";
import { Pitch } from "@/components/Pitch/Pitch";
import { PlayerPhoto } from "@/components/PlayerCard/PlayerPhoto";
import { Badge, Delta } from "@/components/ui/Bits";
import { Confetti } from "@/components/ui/Motion";
import { ErrorState, Skeleton, Spinner } from "@/components/ui/States";
import { useCompareTray } from "@/lib/compareTray";
import { money, points, signed } from "@/lib/format";
import { toPitchPlayers } from "@/lib/pitch";

function MoveRow({ move }: { move: Move }) {
  return (
    <li className="flex items-center gap-2 text-sm">
      <span className="flex min-w-0 flex-1 items-center gap-2">
        <PlayerPhoto src={move.out.photo_url} name={move.out.web_name} className="w-7 shrink-0 rounded-sm" />
        <span className="min-w-0">
          <span className="block truncate font-semibold">
            <span className="sr-only">Out: </span>
            {move.out.web_name}
          </span>
          <span className="num text-xs text-muted">
            {move.out.pos} · {money(move.out.price)}
          </span>
        </span>
      </span>
      <span aria-hidden className="text-muted">
        →
      </span>
      <span className="flex min-w-0 flex-1 items-center gap-2">
        <PlayerPhoto src={move.into.photo_url} name={move.into.web_name} className="w-7 shrink-0 rounded-sm" />
        <span className="min-w-0">
          <span className="block truncate font-semibold">
            <span className="sr-only">In: </span>
            {move.into.web_name}
          </span>
          <span className="num text-xs text-muted">
            {move.into.club_short} · {money(move.into.price)}
          </span>
        </span>
      </span>
      <Delta value={move.gain} className="w-12 text-right" />
    </li>
  );
}

/** The plan's result as ghost cards: incoming players dashed, on top of the current squad. */
function Preview({ current, target }: { current: Squad; target: Squad }) {
  const owned = new Set(current.players.map((p) => p.id));
  return (
    <Pitch
      players={toPitchPlayers(target)}
      label="Squad after the plan"
      layoutPrefix="transfer-preview"
      extras={(p) => ({ ghost: !owned.has(p.id), badge: !owned.has(p.id) ? <Badge tone="accent">IN</Badge> : undefined })}
    />
  );
}

export function TransfersPanel({ teamId, bank }: { teamId: number; bank: number | null }) {
  const [form, setForm] = useState({ bank: bank ?? 0, free: 1, max: 5 });
  const [body, setBody] = useState<TransferIn | null>(null);
  const [preview, setPreview] = useState(false);
  const plan = useTransferPlan(body);
  const tray = useCompareTray();
  const ids = { bank: useId(), free: useId(), max: useId(), freeHint: useId() };
  const data: TransferOut | undefined = plan.data;

  return (
    <div className="flex flex-col gap-5">
      <form
        className="card grid gap-4 p-4 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          setPreview(false);
          setBody({ team_id: teamId, bank: form.bank, free_transfers: form.free, max_transfers: form.max, horizon: 5, path: true });
        }}
      >
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.bank} className="label">
            Bank (£m)
          </label>
          <input
            id={ids.bank}
            type="number"
            min={0}
            max={100}
            step={0.1}
            value={(form.bank / 10).toFixed(1)}
            onChange={(e) => setForm({ ...form, bank: Math.max(0, Math.round(Number(e.target.value) * 10)) })}
            className="field num"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.free} className="label">
            Free transfers
          </label>
          <input
            id={ids.free}
            type="number"
            min={0}
            max={5}
            value={form.free}
            aria-describedby={ids.freeHint}
            onChange={(e) => setForm({ ...form, free: Math.min(5, Math.max(0, Number(e.target.value))) })}
            className="field num"
          />
          <span id={ids.freeHint} className="text-xs text-muted">
            FPL shows this on its Transfers page.
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={ids.max} className="label">
            Max transfers
          </label>
          <select id={ids.max} value={form.max} onChange={(e) => setForm({ ...form, max: Number(e.target.value) })} className="field">
            {[0, 1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className="btn-primary" disabled={plan.isFetching}>
          {plan.isFetching ? <Spinner label="Planning" /> : null}
          {data ? "Re-plan" : "Plan transfers"}
        </button>
      </form>

      {plan.isPending && body && <Skeleton className="h-64" />}
      {plan.isError && <ErrorState error={plan.error} onRetry={() => plan.refetch()} />}

      {data && (
        <>
          <p className="card border-warn/40 bg-warn/5 px-4 py-3 text-sm">
            <strong>Selling prices:</strong> {data.caveat}
          </p>
          <section aria-labelledby="opts" className="flex flex-col gap-3">
            <h3 id="opts" className="text-lg font-semibold">
              Options for GW{data.gw}
            </h3>
            <ol className="grid gap-3 md:grid-cols-2">
              {data.options.map((o) => (
                <li
                  key={o.n_transfers}
                  data-recommended={o.recommended}
                  aria-label={`${o.n_transfers} transfer${o.n_transfers === 1 ? "" : "s"}${o.recommended ? " (recommended)" : ""}`}
                  className={`card flex flex-col gap-2 p-4 ${o.recommended ? "border-accent ring-2 ring-accent" : ""}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-display font-semibold">
                      {o.n_transfers === 0 ? "Roll the transfer" : `${o.n_transfers} transfer${o.n_transfers === 1 ? "" : "s"}`}
                    </span>
                    {o.recommended && <Badge tone="accent">Recommended</Badge>}
                  </div>
                  {o.moves.length > 0 ? (
                    <ul className="flex flex-col gap-2">
                      {o.moves.map((m) => (
                        <MoveRow key={`${m.out.id}-${m.into.id}`} move={m} />
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted">Keep your squad; save the free transfer.</p>
                  )}
                  <dl className="mt-1 grid grid-cols-3 gap-2 border-t border-line pt-2 text-sm">
                    <div>
                      <dt className="label">Hit cost</dt>
                      <dd className={`num font-semibold ${o.hits ? "text-bad" : ""}`}>{o.hits ? signed(-o.hits, 0) : "0"}</dd>
                    </div>
                    <div>
                      <dt className="label">Net gain</dt>
                      <dd className="font-semibold">
                        <Delta value={o.net_gain} />
                      </dd>
                    </div>
                    <div>
                      <dt className="label">Bank after</dt>
                      <dd className="num font-semibold">{money(o.bank_after)}</dd>
                    </div>
                  </dl>
                </li>
              ))}
            </ol>
          </section>

          <NetGainChart
            options={data.options.map((o) => ({
              n: o.n_transfers,
              net: Number(o.net_gain.toFixed(2)),
              hits: o.hits,
              gain: o.net_gain + o.hits,
              recommended: o.recommended,
            }))}
          />

          {data.path && (
            <section aria-labelledby="path" className="flex flex-col gap-3">
              <h3 id="path" className="text-lg font-semibold">
                Path to the best team
              </h3>
              <p className="text-sm">{data.path.advice}</p>
              {data.path.steps.length > 0 ? (
                <ol aria-label="Path steps" className="flex flex-col gap-2">
                  {data.path.steps.map((s) => (
                    <li
                      key={s.n_moves}
                      data-testid="path-step"
                      className={`card flex flex-col gap-2 p-3 ${s.n_moves <= data.path!.make_now ? "border-accent" : ""}`}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                        <span className="flex items-center gap-2 font-semibold">
                          <span className="num flex h-7 w-7 items-center justify-center rounded-full bg-navy text-surface">{s.n_moves}</span>
                          {s.n_moves <= data.path!.make_now ? "Make now" : "Later, with free transfers"}
                        </span>
                        <span className="num text-muted">
                          total {signed(s.gain_before_hits)} · hits {s.hits ? signed(-s.hits, 0) : "0"} · net <Delta value={s.net_gain} />
                        </span>
                      </div>
                      <ul>
                        {s.new_moves.map((m) => (
                          <MoveRow key={`${m.out.id}-${m.into.id}`} move={m} />
                        ))}
                      </ul>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm text-muted">Nothing to do: you already own the best team (or the budget can't reach it).</p>
              )}
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn-primary" onClick={() => setPreview((v) => !v)} aria-pressed={preview}>
                  {preview ? "Hide preview" : "Preview the target squad"}
                </button>
                {data.path.target.code && (
                  <>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => tray.add({ kind: "code", gw: null, value: data.path!.target.code!, label: "Transfer target" })}
                    >
                      Add to compare
                    </button>
                    <Link className="btn-secondary" to={`/builder?t=${encodeURIComponent(data.path.target.code)}`}>
                      Open in Builder
                    </Link>
                  </>
                )}
              </div>
              <Confetti event="plan-preview" fire={preview && data.path.steps.length > 0} />
              {preview && (
                <div className="flex flex-col gap-3">
                  <p className="text-sm text-muted">
                    Dashed cards are the players you'd bring in. Expected {points(data.path.target.expected_points)} next GW vs{" "}
                    {points(data.current.expected_points)} now.
                  </p>
                  <Preview current={data.current} target={data.path.target} />
                  {data.path.target.code && <CodeBox code={data.path.target.code} route="/builder" />}
                </div>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
