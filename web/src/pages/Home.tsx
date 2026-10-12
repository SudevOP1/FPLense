import { Link } from "react-router-dom";
import { useBestSquad, useHistorySummary, useMeta, usePlayers } from "@/api/hooks";
import { Pitch } from "@/components/Pitch/Pitch";
import { PlayerPhoto } from "@/components/PlayerCard/PlayerPhoto";
import { Countdown } from "@/components/ui/Countdown";
import { GLOSSARY, InfoTip } from "@/components/ui/Bits";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { money, points } from "@/lib/format";
import { toPitchPlayers } from "@/lib/pitch";
import { usePlayerDrawer } from "@/lib/playerDrawer";
import { useTitle } from "@/lib/useTitle";

const ENTRY_CARDS = [
  { to: "/best", title: "See the best team", body: "The model's best £100m squad for the next gameweek.", icon: "★" },
  { to: "/me", title: "Load my team", body: "Your squad's expected points, best lineup and transfers.", icon: "☺" },
  { to: "/season", title: "Replay the season", body: "The model's pick vs the best possible team, week by week.", icon: "↺" },
];

export default function Home() {
  useTitle(null);
  const meta = useMeta();
  const best = useBestSquad();
  const players = usePlayers();
  const summary = useHistorySummary();
  const drawer = usePlayerDrawer();
  const last = summary.data?.gws.at(-1);
  const captains = [...(players.data?.players ?? [])]
    .filter((p) => p.availability > 0)
    .sort((a, b) => b.p - a.p)
    .slice(0, 5);

  return (
    <div className="flex flex-col gap-6">
      <section className="grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
        <div>
          <h1 className="text-3xl font-bold md:text-4xl">
            Your FPL edge, <span className="text-coral">explained.</span>
          </h1>
          <p className="mt-2 max-w-xl text-muted">
            Expected points for every player from a model tested week by week, and the best legal squad picked by an
            integer program. No guesswork, no paywall.
          </p>
        </div>
        <div className="card px-5 py-4 md:w-80">
          {meta.isPending ? (
            <Skeleton className="h-16 w-56" />
          ) : meta.data?.deadline ? (
            <Countdown deadline={meta.data.deadline} gw={meta.data.next_gw} />
          ) : (
            <p className="text-sm text-muted">No upcoming deadline published.</p>
          )}
        </div>
      </section>

      <ul className="grid gap-3 sm:grid-cols-3">
        {ENTRY_CARDS.map((c) => (
          <li key={c.to}>
            <Link
              to={c.to}
              className="card flex h-full min-h-[96px] items-start gap-3 p-4 transition duration-fast ease-out hover:-translate-y-0.5 hover:shadow-lg"
            >
              <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent/20 text-lg text-coral">
                {c.icon}
              </span>
              <span>
                <span className="block font-display text-lg font-semibold">{c.title}</span>
                <span className="text-sm text-muted">{c.body}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <section aria-labelledby="home-best" className="flex flex-col gap-3">
          <div className="flex items-end justify-between gap-2">
            <h2 id="home-best" className="text-xl font-semibold">
              Best XI for GW{meta.data?.next_gw ?? "…"}
            </h2>
            {best.data && (
              <span className="num text-sm text-muted">
                {points(best.data.expected_points)} pts · {money(best.data.cost)}
              </span>
            )}
          </div>
          {best.isPending && <Skeleton className="h-[480px] rounded-xl" />}
          {best.isError && <ErrorState error={best.error} onRetry={() => best.refetch()} />}
          {best.data && (
            <Pitch
              players={toPitchPlayers(best.data).filter((p) => p.starter)}
              label="Best XI"
              layoutPrefix="home"
              extras={(p) => ({ onClick: () => drawer.open(p.id) })}
            />
          )}
          <Link to="/best" className="btn-secondary self-start">
            Tweak budget, locks and bans →
          </Link>
        </section>

        <div className="flex flex-col gap-6">
          <section aria-labelledby="home-captains" className="card p-4">
            <h2 id="home-captains" className="mb-3 flex items-center gap-2 text-lg font-semibold">
              Top captain picks <InfoTip text={GLOSSARY.expected} label="About expected points" />
            </h2>
            {players.isPending && <Skeleton className="h-60" />}
            {players.isError && <ErrorState error={players.error} onRetry={() => players.refetch()} />}
            <ol className="flex flex-col gap-1">
              {captains.map((p, k) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => drawer.open(p.id)}
                    className="flex min-h-[52px] w-full items-center gap-3 rounded px-2 text-left hover:bg-line/40"
                  >
                    <span className="num w-4 text-muted">{k + 1}</span>
                    <PlayerPhoto src={p.photo_url} name={p.name} className="w-8 rounded-sm" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-semibold">{p.web_name}</span>
                      <span className="text-xs text-muted">
                        {p.club_short} · {p.fixtures.filter((f) => f.gw === players.data?.gw).map((f) => `${f.opponent} (${f.home ? "H" : "A"})`).join(", ") || "no fixture"}
                      </span>
                    </span>
                    <span className="num text-lg font-bold">{points(p.p)}</span>
                  </button>
                </li>
              ))}
            </ol>
          </section>

          <section aria-labelledby="home-recap" className="card p-4">
            <h2 id="home-recap" className="mb-2 text-lg font-semibold">
              {last ? `GW${last.gw} recap` : "Last gameweek"}
            </h2>
            {summary.isPending && <Skeleton className="h-16" />}
            {summary.data && !last && <p className="text-sm text-muted">No finished gameweek yet.</p>}
            {last && (
              <>
                <p className="num text-lg">
                  model pick <strong>{last.model_actual}</strong> · best possible <strong>{last.hindsight_points}</strong> · average{" "}
                  <strong>{last.average_entry_score ?? "–"}</strong>
                </p>
                <p className="mt-1 flex items-center gap-1 text-xs text-muted">
                  Best possible = hindsight-best £100m team <InfoTip text={GLOSSARY.hindsight} label="About hindsight best" />
                </p>
                <Link to={`/season?gw=${last.gw}`} className="mt-3 inline-block text-sm font-semibold text-coral underline-offset-2 hover:underline">
                  Replay GW{last.gw} →
                </Link>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
