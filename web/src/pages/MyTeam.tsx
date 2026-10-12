import { useEffect, useId, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useEntry, useEntryGw, useMeta } from "@/api/hooks";
import type { EntryGwOut, SquadPlayer } from "@/api/types";
import { SeasonChart } from "@/components/charts/Charts";
import { GwSelect } from "@/components/GwPicker/GwPicker";
import { Pitch } from "@/components/Pitch/Pitch";
import { SquadView } from "@/components/SquadView";
import { Badge, Segmented, Stat } from "@/components/ui/Bits";
import { Confetti } from "@/components/ui/Motion";
import { ErrorState, PageHeader, Skeleton } from "@/components/ui/States";
import { Tabs } from "@/components/ui/Tabs";
import { compareHref } from "@/lib/compareSlots";
import { money, points, rank } from "@/lib/format";
import { usePlayerDrawer } from "@/lib/playerDrawer";
import { load, save } from "@/lib/storage";
import { useTitle } from "@/lib/useTitle";
import { TransfersPanel } from "./Transfers";

function TeamIdForm({ initial }: { initial?: string }) {
  const navigate = useNavigate();
  const [text, setText] = useState(initial ?? "");
  const [error, setError] = useState<string | null>(null);
  const [help, setHelp] = useState(false);
  const id = useId();
  const last = load<number | null>("teamId", null);
  return (
    <form
      className="card flex flex-col gap-3 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        const n = Number(text.trim());
        if (!Number.isInteger(n) || n <= 0) {
          setError("A team ID is a whole number, like 1234567.");
          return;
        }
        setError(null);
        navigate(`/me/${n}`);
      }}
    >
      <label htmlFor={id} className="font-semibold">
        Your FPL team ID
      </label>
      <div className="flex gap-2">
        <input
          id={id}
          inputMode="numeric"
          autoComplete="off"
          placeholder="e.g. 1234567"
          value={text}
          aria-invalid={error ? true : undefined}
          onChange={(e) => setText(e.target.value)}
          className="field num max-w-xs"
        />
        <button type="submit" className="btn-primary">
          Load team
        </button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-bad">
          {error}
        </p>
      )}
      <button
        type="button"
        className="self-start text-sm font-semibold text-coral underline-offset-2 hover:underline"
        aria-expanded={help}
        onClick={() => setHelp((h) => !h)}
      >
        Where do I find my ID?
      </button>
      {help && (
        <div className="rounded-md border border-line bg-raised p-3 text-sm">
          <p>
            Open the{" "}
            <a
              href="https://fantasy.premierleague.com"
              target="_blank"
              rel="noopener noreferrer"
              className="text-coral underline-offset-2 hover:underline"
            >
              FPL site
            </a>
            , go to <strong>Points</strong>, and look at the address bar. Your ID is the number after <code>/entry/</code>:
          </p>
          <p className="num mt-2 break-all rounded bg-surface px-2 py-1">
            fantasy.premierleague.com/entry/<mark className="rounded bg-accent/30 px-0.5 text-ink">1234567</mark>/event/6
          </p>
        </div>
      )}
      {last && !initial && (
        <Link to={`/me/${last}`} className="text-sm text-muted underline-offset-2 hover:underline">
          Load team {last} again
        </Link>
      )}
    </form>
  );
}

/** Your 15 with next-GW expected points, or the lineup helper's suggestion with changes highlighted. */
function LineupSection({ data, nextGw }: { data: EntryGwOut; nextGw: number }) {
  const drawer = usePlayerDrawer();
  const [view, setView] = useState<"yours" | "suggested">("yours");
  const lineup = data.lineup;
  const nextExpected = useMemo(() => new Map((lineup?.players ?? []).map((p) => [p.id, p.expected])), [lineup]);
  const yours: SquadPlayer[] = data.squad.players.map((p) => ({
    ...p,
    expected: nextExpected.get(p.id) ?? p.expected,
    actual: null,
  }));
  const changes = new Set(data.lineup_changes);
  const capChanged = lineup && lineup.captain !== data.squad.captain;
  const shown = view === "suggested" && lineup ? lineup.players : yours;
  return (
    <section aria-labelledby="lineup" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="lineup" className="text-lg font-semibold">
          Your squad for GW{nextGw}
        </h2>
        {lineup && (
          <Segmented
            label="Lineup view"
            value={view}
            onChange={setView}
            options={[
              { value: "yours", label: "Your XI" },
              { value: "suggested", label: "Suggested XI" },
            ]}
          />
        )}
      </div>
      {lineup && (
        <p className="text-sm" aria-live="polite">
          <strong>Lineup helper:</strong>{" "}
          {changes.size === 0 && !capChanged
            ? "your XI and captain already look best."
            : `${changes.size ? `start ${[...changes].map((id) => lineup.players.find((p) => p.id === id)?.web_name).join(", ")}` : "keep your XI"}${
                capChanged ? `; captain ${lineup.players.find((p) => p.id === lineup.captain)?.web_name}` : ""
              }.`}{" "}
          <span className="num text-muted">
            ({points(lineup.expected_points)} expected vs{" "}
            {points(
              yours.filter((p) => p.starter).reduce((a, p) => a + (p.expected ?? 0), 0) +
                (yours.find((p) => p.captain)?.expected ?? 0),
            )}
            )
          </span>
        </p>
      )}
      <Pitch
        players={shown}
        label={view === "suggested" ? "Suggested lineup" : "Your lineup"}
        layoutPrefix="me-lineup"
        extras={(p) => ({
          onClick: () => drawer.open(p.id),
          ring: view === "suggested" && changes.has(p.id) ? "ring-accent" : undefined,
          badge: view === "suggested" && changes.has(p.id) ? <Badge tone="accent">IN</Badge> : undefined,
        })}
      />
    </section>
  );
}

function PastGw({
  teamId,
  gws,
  defaultGw,
  modelPoints,
}: {
  teamId: number;
  gws: number[];
  defaultGw: number;
  modelPoints: Map<number, number | null>;
}) {
  const [gw, setGw] = useState(defaultGw);
  const q = useEntryGw(teamId, gw);
  const beat = q.data?.points != null && (modelPoints.get(gw) ?? Infinity) < q.data.points;
  return (
    <section aria-labelledby="past" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="past" className="text-lg font-semibold">
          A past gameweek
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <GwSelect gws={gws} value={gw} onChange={setGw} label="Pick a past gameweek" />
          <Link
            className="btn-primary"
            to={compareHref([
              { kind: "entry", gw, value: teamId },
              { kind: "model_pick", gw, value: null },
              { kind: "hindsight", gw, value: null },
            ])}
          >
            Compare this week
          </Link>
        </div>
      </div>
      {q.isPending && <Skeleton className="h-[460px] rounded-xl" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {q.data && (
        <>
          {beat && (
            <p className="card border-good/40 px-4 py-2 text-sm font-semibold text-good">
              You beat the model pick in GW{gw}: {q.data.points} vs {modelPoints.get(gw)}.
            </p>
          )}
          <Confetti event={`beat-model-${teamId}-${gw}`} fire={beat} />
          <SquadView
            squad={q.data.squad}
            slot={{ kind: "entry", gw, value: teamId }}
            layoutPrefix={`me-past-${gw}`}
            badges={q.data.active_chip ? <Badge tone="accent">{q.data.active_chip}</Badge> : undefined}
            compact
          />
          {q.data.automatic_subs.length > 0 && (
            <p className="text-sm text-muted">
              Auto-subs:{" "}
              {q.data.automatic_subs
                .map(
                  (s) =>
                    `${q.data!.squad.players.find((p) => p.id === s.into)?.web_name} for ${q.data!.squad.players.find((p) => p.id === s.out)?.web_name}`,
                )
                .join(", ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

export default function MyTeam({ tab = "squad" }: { tab?: "squad" | "transfers" }) {
  const params = useParams();
  const navigate = useNavigate();
  const teamId = params.teamId && /^\d+$/.test(params.teamId) ? Number(params.teamId) : null;
  const meta = useMeta();
  const entry = useEntry(teamId);
  const e = entry.data;
  useTitle(e ? `${e.team_name} · My Team` : "My Team");
  const currentGw = e?.current_event ?? null;
  const nextGw = meta.data?.next_gw;
  const current = useEntryGw(teamId, currentGw, nextGw);

  useEffect(() => {
    if (teamId && e) save("teamId", teamId);
  }, [teamId, e]);

  if (!teamId)
    return (
      <div className="flex flex-col gap-5">
        <PageHeader
          title="My Team"
          sub="Load your FPL team to see its expected points, the best lineup and the best transfers."
        />
        <TeamIdForm initial={params.teamId} />
      </div>
    );

  const finished = new Set(meta.data?.finished_gws ?? []);
  const history = e?.history ?? [];
  const pastGws = history.map((h) => h.gw).filter((g) => finished.has(g));
  const modelPoints = new Map(history.map((h) => [h.gw, h.model_pick_points]));

  return (
    <div className="flex flex-col gap-5">
      {entry.isPending && (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-10 w-72" />
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {[0, 1, 2, 3].map((k) => (
              <Skeleton key={k} className="h-20" />
            ))}
          </div>
        </div>
      )}
      {entry.isError && (
        <>
          <ErrorState title="Couldn't load that team" error={entry.error} onRetry={() => entry.refetch()} />
          <TeamIdForm />
        </>
      )}
      {e && (
        <>
          <PageHeader
            title={e.team_name}
            sub={`${e.manager_name} · team ${e.id}`}
            actions={
              <button type="button" className="btn-ghost" onClick={() => navigate("/me")}>
                Change team
              </button>
            }
          />
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Stat label="Overall rank" value={rank(e.overall_rank)} />
            <Stat label="Points" value={e.overall_points ?? "–"} />
            <Stat label="Team value" value={money(e.value)} />
            <Stat label="Bank" value={money(e.bank)} />
          </div>
          <Tabs
            label="My Team sections"
            value={tab}
            onChange={(t) => navigate(t === "transfers" ? `/me/${teamId}/transfers` : `/me/${teamId}`)}
            tabs={[
              { value: "squad", label: "Squad & season" },
              { value: "transfers", label: "Transfers" },
            ]}
          />
          {tab === "transfers" ? (
            <TransfersPanel teamId={teamId} bank={e.bank} />
          ) : (
            <>
              {current.isPending && currentGw && <Skeleton className="h-[480px] rounded-xl" />}
              {current.isError && <ErrorState error={current.error} onRetry={() => current.refetch()} />}
              {current.data && nextGw && <LineupSection data={current.data} nextGw={nextGw} />}
              {!currentGw && <p className="text-sm text-muted">This team hasn't played a gameweek yet.</p>}
              {history.length > 0 && (
                <SeasonChart
                  title="Your season"
                  gws={history.map((h) => h.gw)}
                  series={[
                    { key: "you", label: "You", values: history.map((h) => h.points), token: "slot-a" },
                    { key: "model", label: "Model pick", values: history.map((h) => h.model_pick_points), token: "navy" },
                    { key: "best", label: "Hindsight best", values: history.map((h) => h.hindsight_points), token: "accent" },
                    { key: "avg", label: "Average", values: history.map((h) => h.average_entry_score), token: "muted" },
                  ]}
                  rankValues={history.map((h) => h.overall_rank)}
                  chips={[
                    ...e.chips,
                    ...history
                      .filter((h) => h.chip && !e.chips.some((c) => c.gw === h.gw))
                      .map((h) => ({ gw: h.gw, name: h.chip! })),
                  ]}
                />
              )}
              {pastGws.length > 0 && (
                <PastGw teamId={teamId} gws={pastGws} defaultGw={pastGws[pastGws.length - 1]} modelPoints={modelPoints} />
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
