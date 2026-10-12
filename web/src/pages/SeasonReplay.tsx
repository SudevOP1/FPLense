import { AnimatePresence, motion } from "framer-motion";
import { useSearchParams } from "react-router-dom";
import { useHistoryGw, useHistorySummary } from "@/api/hooks";
import { CaptureBars, SeasonChart } from "@/components/charts/Charts";
import { GwScrubber } from "@/components/GwPicker/GwPicker";
import { SquadView } from "@/components/SquadView";
import { Badge, GLOSSARY, InfoTip, Stat } from "@/components/ui/Bits";
import { EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui/States";
import { pct } from "@/lib/format";
import { fadeVariants } from "@/lib/motion";
import { usePlayerDrawer } from "@/lib/playerDrawer";
import { useEntrance } from "@/lib/settings";
import { useTitle } from "@/lib/useTitle";

export default function SeasonReplay() {
  useTitle("Season Replay");
  const [params, setParams] = useSearchParams();
  const summary = useHistorySummary();
  const drawer = usePlayerDrawer();
  const entrance = useEntrance();
  const gws = summary.data?.gws.map((g) => g.gw) ?? [];
  const asked = Number(params.get("gw"));
  const gw = gws.includes(asked) ? asked : (gws.at(-1) ?? null);
  const detail = useHistoryGw(gw);
  const setGw = (g: number) => setParams({ gw: String(g) }, { replace: true });
  const row = summary.data?.gws.find((g) => g.gw === gw);
  const d = detail.data;
  const shared = new Set(
    d && d.hindsight ? d.model_pick.players.map((p) => p.id).filter((id) => d.hindsight!.players.some((h) => h.id === id)) : [],
  );

  if (summary.isPending)
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-24" />
        <Skeleton className="h-[520px] rounded-xl" />
      </div>
    );
  if (summary.isError) return <ErrorState error={summary.error} onRetry={() => summary.refetch()} />;
  if (!gws.length || gw == null)
    return <EmptyState title="No finished gameweek yet" body="The replay starts once GW1 is over. Check back after the first deadline." />;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Season Replay"
        sub="What the model picked before each deadline, next to the best team anyone could have picked with hindsight."
      />
      <GwScrubber gws={gws} value={gw} onChange={setGw} />

      {row && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat label="Model pick" value={row.model_actual} sub={`expected ${row.model_expected.toFixed(1)}`} />
          <Stat label="Hindsight best" value={row.hindsight_points} tip={GLOSSARY.hindsight} />
          <Stat label="Average manager" value={row.average_entry_score ?? "–"} sub={`highest ${row.highest_score ?? "–"}`} />
          <Stat label="Capture ratio" value={pct(row.capture_ratio)} tip={GLOSSARY.capture} sub={`${row.shared_players} shared players`} />
        </div>
      )}

      {detail.isError && <ErrorState error={detail.error} onRetry={() => detail.refetch()} />}
      {!d && detail.isPending && <Skeleton className="h-[520px] rounded-xl" />}
      <AnimatePresence mode="wait">
        {d && (
          <motion.div key={d.gw} variants={fadeVariants} {...entrance} exit="exit" className="grid gap-6 lg:grid-cols-2">
            <SquadView
              squad={d.model_pick}
              title={`Model pick · GW${d.gw}`}
              slot={{ kind: "model_pick", gw: d.gw, value: null }}
              layoutPrefix={`replay-model-${d.gw}`}
              badges={
                d.source === "backfill" ? (
                  <span className="inline-flex items-center gap-1">
                    <Badge tone="warn" title={d.caveat ?? undefined}>
                      Backfilled
                    </Badge>
                    <InfoTip text={GLOSSARY.backfilled} label="About backfilled" />
                  </span>
                ) : (
                  <Badge tone="good">Picked before the deadline</Badge>
                )
              }
              extras={(p) => ({
                onClick: () => drawer.open(p.id),
                ring: shared.has(p.id) ? "ring-accent" : undefined,
              })}
              compact
            />
            {d.hindsight ? (
              <SquadView
                squad={d.hindsight}
                title={
                  <span className="inline-flex items-center gap-1">
                    Hindsight best · GW{d.gw} <InfoTip text={GLOSSARY.hindsight} label="About hindsight best" />
                  </span>
                }
                slot={{ kind: "hindsight", gw: d.gw, value: null }}
                layoutPrefix={`replay-best-${d.gw}`}
                extras={(p) => ({
                  onClick: () => drawer.open(p.id),
                  ring: shared.has(p.id) ? "ring-accent" : undefined,
                })}
                compact
              />
            ) : (
              <EmptyState title="No hindsight team for this GW" body="It's computed once the gameweek's points are final." />
            )}
          </motion.div>
        )}
      </AnimatePresence>
      {shared.size > 0 && (
        <p className="text-sm text-muted">
          <span className="mr-1 inline-block h-3 w-3 rounded-sm ring-2 ring-accent" aria-hidden /> Coral ring: in both teams ({shared.size}{" "}
          shared).
        </p>
      )}

      <SeasonChart
        title="Points per gameweek"
        gws={gws}
        selectedGw={gw}
        onSelectGw={setGw}
        series={[
          { key: "model", label: "Model pick", values: summary.data.gws.map((g) => g.model_actual), token: "navy" },
          { key: "best", label: "Hindsight best", values: summary.data.gws.map((g) => g.hindsight_points), token: "accent" },
          { key: "avg", label: "Average manager", values: summary.data.gws.map((g) => g.average_entry_score), token: "muted" },
          { key: "top", label: "Highest", values: summary.data.gws.map((g) => g.highest_score), token: "good" },
        ]}
      />
      <CaptureBars rows={summary.data.gws.map((g) => ({ gw: g.gw, capture: g.capture_ratio }))} selectedGw={gw} onSelectGw={setGw} />
      <p className="text-xs text-muted">{summary.data.note}</p>
    </div>
  );
}
