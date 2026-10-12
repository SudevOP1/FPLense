import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { asApiError, useBestSquad, useMeta, useOptimize, usePlayers } from "@/api/hooks";
import type { OptimizeIn } from "@/api/types";
import { MiniBars } from "@/components/charts/Charts";
import { SquadView } from "@/components/SquadView";
import { Badge, GLOSSARY, InfoTip } from "@/components/ui/Bits";
import { Sheet } from "@/components/ui/Sheet";
import { ErrorState, PageHeader, Skeleton, Spinner } from "@/components/ui/States";
import type { CompareSlot } from "@/lib/compareSlots";
import { money, points } from "@/lib/format";
import { usePlayerDrawer } from "@/lib/playerDrawer";
import { useTitle } from "@/lib/useTitle";

const DEFAULTS = { budget: 1000, horizon: 5, bench_weight: 0.1 };

function ids(raw: string | null): number[] {
  return (raw ?? "")
    .split(",")
    .map(Number)
    .filter((n) => Number.isInteger(n) && n > 0);
}

export default function BestTeam() {
  useTitle("Best Team");
  const [params, setParams] = useSearchParams();
  const [controls, setControls] = useState(false);
  const meta = useMeta();
  const players = usePlayers();
  const drawer = usePlayerDrawer();

  const budget = Number(params.get("budget") ?? DEFAULTS.budget);
  const horizon = Number(params.get("h") ?? DEFAULTS.horizon);
  const benchWeight = Number(params.get("bw") ?? DEFAULTS.bench_weight);
  const locked = ids(params.get("lock"));
  const banned = ids(params.get("ban"));
  const custom =
    budget !== DEFAULTS.budget || horizon !== DEFAULTS.horizon || benchWeight !== DEFAULTS.bench_weight || locked.length > 0 || banned.length > 0;

  const body = useMemo<OptimizeIn | null>(
    () => (custom ? { budget, horizon, bench_weight: benchWeight, locked, banned } : null),
    // ids() builds new arrays each render; the URL string is the real dependency
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [custom, budget, horizon, benchWeight, params.get("lock"), params.get("ban")],
  );
  const best = useBestSquad(undefined, !custom);
  const optimized = useOptimize(body);
  const q = custom ? optimized : best;
  const squad = q.data;
  const err = asApiError(q.error);

  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v == null || v === "") next.delete(k);
      else next.set(k, v);
    }
    setParams(next, { replace: true });
  };
  const toggle = (key: "lock" | "ban", id: number) => {
    const cur = key === "lock" ? locked : banned;
    const other = key === "lock" ? banned : locked;
    const next = cur.includes(id) ? cur.filter((i) => i !== id) : [...cur, id];
    set({ [key]: next.join(","), [key === "lock" ? "ban" : "lock"]: other.filter((i) => i !== id).join(",") });
  };

  const byId = useMemo(() => new Map((players.data?.players ?? []).map((p) => [p.id, p])), [players.data]);
  const name = (id: number) => byId.get(id)?.web_name ?? `#${id}`;
  const slot: CompareSlot | undefined = squad
    ? custom && squad.code
      ? { kind: "code", gw: null, value: squad.code, label: "Custom best team" }
      : { kind: "model_pick", gw: squad.gw, value: null }
    : undefined;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Best Team"
        sub={
          <>
            The best legal squad for GW{meta.data?.next_gw ?? "…"}: {money(budget)} budget, 2-5-5-3, max 3 per club, maximizing
            expected points over the next {horizon} GW{horizon === 1 ? "" : "s"}.
          </>
        }
        actions={
          <>
            {custom && (
              <button type="button" className="btn-ghost" onClick={() => setParams(new URLSearchParams(), { replace: true })}>
                Reset
              </button>
            )}
            <button type="button" className="btn-primary" onClick={() => setControls(true)}>
              Settings, locks & bans
            </button>
          </>
        }
      />

      {(locked.length > 0 || banned.length > 0) && (
        <div className="flex flex-wrap gap-2" aria-label="Locks and bans">
          {locked.map((id) => (
            <button key={`l${id}`} type="button" className="chip border-good/40 bg-good/10 text-good" onClick={() => toggle("lock", id)}>
              🔒 {name(id)} <span aria-hidden>×</span>
              <span className="sr-only">(remove lock)</span>
            </button>
          ))}
          {banned.map((id) => (
            <button key={`b${id}`} type="button" className="chip border-bad/40 bg-bad/10 text-bad" onClick={() => toggle("ban", id)}>
              ⊘ {name(id)} <span aria-hidden>×</span>
              <span className="sr-only">(remove ban)</span>
            </button>
          ))}
        </div>
      )}

      {q.isPending && !squad && <Skeleton className="h-[560px] rounded-xl" />}
      {err && err.status === 422 && (
        <div role="alert" className="card border-bad/40 px-4 py-3 text-sm">
          <strong className="text-bad">Can't build a legal squad with those settings.</strong> {err.message}
          {locked.length > 0 && (
            <button type="button" className="ml-2 font-semibold underline" onClick={() => toggle("lock", locked[locked.length - 1])}>
              Undo the last lock
            </button>
          )}
        </div>
      )}
      {q.isError && (!err || err.status !== 422) && <ErrorState error={q.error} onRetry={() => q.refetch()} />}

      {squad && (
        <div className="relative">
          {q.isFetching && (
            <div className="absolute inset-0 z-10 flex items-start justify-center rounded-xl bg-bg/40 pt-24" aria-live="polite">
              <span className="card flex items-center gap-2 px-4 py-2 text-sm font-semibold">
                <Spinner label="Re-solving" /> Re-solving…
              </span>
            </div>
          )}
          <SquadView
            squad={squad}
            slot={slot}
            badges={custom ? <Badge tone="accent">Custom settings</Badge> : <Badge>Model pick</Badge>}
            layoutPrefix="best"
            extras={(p) => ({
              onClick: () => drawer.open(p.id),
              ring: locked.includes(p.id) ? "ring-good" : undefined,
              menu: [
                { label: "Player details", onSelect: () => drawer.open(p.id) },
                { label: locked.includes(p.id) ? "Unlock" : "Lock in", onSelect: () => toggle("lock", p.id) },
                { label: "Ban from the team", onSelect: () => toggle("ban", p.id) },
              ],
            })}
          />
        </div>
      )}

      {squad && (
        <section className="card p-4" aria-labelledby="per-gw">
          <h2 id="per-gw" className="mb-3 flex items-center gap-2 font-semibold">
            Expected points per GW <InfoTip text={GLOSSARY.P_h} label="About P_h" />
          </h2>
          <ul className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {squad.players.map((sp) => {
              const p = byId.get(sp.id);
              return (
                <li key={sp.id} className="flex items-center justify-between gap-2 text-sm">
                  <span className="min-w-0 truncate">
                    <strong>{sp.web_name}</strong> <span className="text-muted">{sp.pos}</span>
                    {!sp.starter && <span className="text-muted"> · bench</span>}
                  </span>
                  <span className="flex items-center gap-3">
                    {p && <MiniBars values={p.expected} label={`${sp.web_name} expected points`} />}
                    <span className="num w-10 text-right text-muted">{points(sp.P_h)}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <Sheet open={controls} onClose={() => setControls(false)} title="Optimizer settings">
        <form className="flex flex-col gap-5" onSubmit={(e) => e.preventDefault()}>
          <label className="flex flex-col gap-2 text-sm">
            <span className="flex justify-between">
              Budget <strong className="num">{money(budget)}</strong>
            </span>
            <input
              type="range"
              min={800}
              max={1200}
              step={5}
              value={budget}
              onChange={(e) => set({ budget: e.target.value === "1000" ? null : e.target.value })}
              className="accent-[rgb(var(--accent))]"
            />
          </label>
          <label className="flex flex-col gap-2 text-sm">
            <span className="flex justify-between">
              Horizon <strong className="num">{horizon} GW{horizon === 1 ? "" : "s"}</strong>
            </span>
            <input
              type="range"
              min={1}
              max={meta.data?.horizon_max ?? 5}
              step={1}
              value={horizon}
              onChange={(e) => set({ h: e.target.value === "5" ? null : e.target.value })}
              className="accent-[rgb(var(--accent))]"
            />
          </label>
          <label className="flex flex-col gap-2 text-sm">
            <span className="flex justify-between">
              Bench weight <strong className="num">{benchWeight.toFixed(2)}</strong>
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={benchWeight}
              onChange={(e) => set({ bw: Number(e.target.value) === 0.1 ? null : e.target.value })}
              className="accent-[rgb(var(--accent))]"
            />
            <span className="text-xs text-muted">How much bench points count (0 = ignore the bench, 1 = like starters).</span>
          </label>
          <p className="text-xs text-muted">
            Lock or ban players from the ⋯ menu on any card. Changes re-solve the integer program on the server (about a second).
          </p>
          <button type="button" className="btn-primary" onClick={() => setControls(false)}>
            Done
          </button>
        </form>
      </Sheet>
    </div>
  );
}
