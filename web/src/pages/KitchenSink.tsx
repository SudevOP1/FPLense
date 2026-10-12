// Dev-only consistency audit (/dev/kitchen-sink): every component in every state, light and dark
// side by side. Not part of production builds (see routes.tsx).
import type { CompareOut, Squad } from "@/api/types";
import { CaptureBars, Dumbbell, HBars, MiniBars, NetGainChart, SeasonChart } from "@/components/charts/Charts";
import { CodeBox, PasteCodeField } from "@/components/CodeBox/CodeBox";
import { GwScrubber } from "@/components/GwPicker/GwPicker";
import { Pitch } from "@/components/Pitch/Pitch";
import { PlayerCard } from "@/components/PlayerCard/PlayerCard";
import { Badge, Delta, InfoTip, Segmented, SlotBadge, Stat } from "@/components/ui/Bits";
import { Countdown } from "@/components/ui/Countdown";
import { AnimatedNumber } from "@/components/ui/Motion";
import { RuleChips } from "@/components/ui/RuleChips";
import { EmptyState, ErrorState, Skeleton, Spinner } from "@/components/ui/States";
import { Tabs } from "@/components/ui/Tabs";
import { ApiError } from "@/api/client";
import { ruleChips } from "@/lib/squadRules";
import { toPitchPlayers } from "@/lib/pitch";
import { useState } from "react";
import squadJson from "@/test/fixtures/squad_best.json";
import compareJson from "@/test/fixtures/compare.json";

const squad = squadJson as unknown as Squad;
const compare = compareJson as unknown as CompareOut;

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="label">{title}</h2>
      {children}
    </section>
  );
}

function Sink() {
  const [tab, setTab] = useState<"a" | "b">("a");
  const [seg, setSeg] = useState<"gw" | "cum">("gw");
  const [gw, setGw] = useState(2);
  const p = squad.players[4];
  const fullChips = ruleChips(squad.players.map((x) => ({ id: x.id, pos: x.pos, club: x.club, price: x.price })));
  const badChips = ruleChips([...squad.players.slice(0, 10), ...squad.players.slice(0, 6)].map((x, k) => ({ id: k, pos: x.pos, club: "Club A", price: x.price + 30 })));
  return (
    <div className="flex flex-col gap-6 bg-bg p-4 text-ink">
      <Block title="Buttons (hover / focus / active / disabled)">
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-primary">Primary</button>
          <button type="button" className="btn-secondary">Secondary</button>
          <button type="button" className="btn-ghost">Ghost</button>
          <button type="button" className="btn-primary" disabled>Disabled</button>
          <button type="button" className="btn-secondary"><Spinner /> Loading</button>
        </div>
      </Block>
      <Block title="Badges, deltas, slots, tooltips">
        <div className="flex flex-wrap items-center gap-2">
          <Badge>Neutral</Badge><Badge tone="warn">Backfilled</Badge><Badge tone="good">Live</Badge><Badge tone="bad">Over budget</Badge><Badge tone="accent">Recommended</Badge>
          <Delta value={2.4} /><Delta value={-4} digits={0} /><Delta value={0} />
          <SlotBadge letter="A" /><SlotBadge letter="B" /><SlotBadge letter="C" />
          <InfoTip text="One-line explainer for jargon." />
        </div>
      </Block>
      <Block title="Stats, numbers, countdown">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat label="Expected" value={<AnimatedNumber value={54.3} />} sub="next GW" tip="Tooltip" />
          <Stat label="Cost" value="£99.8m" />
          <div className="card p-3"><Countdown deadline={new Date(Date.now() + 30 * 3600e3).toISOString()} gw={7} /></div>
          <div className="card p-3"><Countdown deadline={new Date(Date.now() + 20 * 60e3).toISOString()} gw={7} /></div>
        </div>
      </Block>
      <Block title="Tabs, segmented, scrubber">
        <Tabs label="Demo" value={tab} onChange={setTab} tabs={[{ value: "a", label: "Squad" }, { value: "b", label: "Transfers" }]} />
        <Segmented label="Demo" value={seg} onChange={setSeg} options={[{ value: "gw", label: "Per GW" }, { value: "cum", label: "Cumulative" }]} />
        <GwScrubber gws={[1, 2, 3, 4, 5]} value={gw} onChange={setGw} />
      </Block>
      <Block title="Rule chips (ok / violated)">
        <RuleChips chips={fullChips} />
        <RuleChips chips={badChips} />
      </Block>
      <Block title="Player cards (expected / actual / captain / vice / flagged / no photo / long name / selected / ghost)">
        <div className="grid w-full max-w-3xl grid-cols-5 gap-2 sm:grid-cols-9">
          <PlayerCard player={p} />
          <PlayerCard player={{ ...p, actual: 12 }} mode="actual" />
          <PlayerCard player={{ ...p, captain: true }} />
          <PlayerCard player={{ ...p, vice: true }} />
          <PlayerCard player={{ ...p, status: "d", news: "Knock - 75% chance of playing" }} />
          <PlayerCard player={{ ...p, photo_url: null }} />
          <PlayerCard player={{ ...p, web_name: "Alexander-Arnold-Longname", photo_url: null }} />
          <PlayerCard player={p} selected />
          <PlayerCard player={p} ghost />
        </div>
      </Block>
      <Block title="Pitch">
        <div className="max-w-xl">
          <Pitch players={toPitchPlayers(squad)} label="Kitchen sink" layoutPrefix="ks" />
        </div>
      </Block>
      <Block title="Code box + paste field">
        <CodeBox code={squad.code ?? "FPLN-2627-…"} />
        <PasteCodeField onLoad={() => undefined} serverError="This code is from 2025-26; player ids change every season." />
      </Block>
      <Block title="States: loading / empty / error">
        <div className="grid gap-2 md:grid-cols-3">
          <Skeleton className="h-32" />
          <EmptyState title="Nothing here yet" body="Friendly line plus the next action." action={<button type="button" className="btn-secondary">Do it</button>} />
          <ErrorState error={new ApiError(429, "Too many", null, 12)} onRetry={() => undefined} />
        </div>
      </Block>
      <Block title="Charts">
        <SeasonChart title="Points per gameweek" gws={[1, 2, 3, 4, 5]} series={[{ key: "a", label: "Model pick", values: [31, 116, 62, 49, 29] }, { key: "b", label: "Hindsight", values: [165, 166, 142, 163, 167] }]} />
        <CaptureBars rows={[{ gw: 1, capture: 0.19 }, { gw: 2, capture: 0.7 }, { gw: 3, capture: 0.44 }]} selectedGw={2} />
        <NetGainChart options={[0, 1, 2, 3].map((n) => ({ n, gain: n * 2, hits: Math.max(0, n - 1) * 4, net: n * 2 - Math.max(0, n - 1) * 4, recommended: n === 1 }))} />
        <Dumbbell rows={compare.slots.map((s) => ({ letter: s.letter, expected: s.squad.expected_points, actual: s.squad.actual_points }))} />
        <HBars title="SHAP waterfall" summary="demo" rows={[{ label: "minutes_r3", value: 1.27 }, { label: "fdr", value: -0.15 }]} signedValues />
        <MiniBars values={[{ gw: 6, points: 5.2 }, { gw: 7, points: 6.6 }, { gw: 8, points: 5.3 }]} label="demo" />
      </Block>
    </div>
  );
}

export default function KitchenSink() {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <div data-theme="light" className="rounded-xl border border-line">
        <Sink />
      </div>
      <div data-theme="dark" className="rounded-xl border border-line">
        <Sink />
      </div>
    </div>
  );
}
