import { Link } from "react-router-dom";
import { usePlayer } from "@/api/hooks";
import { HBars, SeasonChart } from "@/components/charts/Charts";
import { Badge, GLOSSARY, InfoTip } from "@/components/ui/Bits";
import { Sheet } from "@/components/ui/Sheet";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { money, pct, points, shortDate } from "@/lib/format";
import { PlayerPhoto } from "../PlayerCard/PlayerPhoto";

/** Player drawer: expected vs actual this season, the SHAP waterfall, fixtures and news. */
export function PlayerDrawer({ playerId, onClose }: { playerId: number | null; onClose: () => void }) {
  const q = usePlayer(playerId);
  const p = q.data;
  return (
    <Sheet open={playerId != null} onClose={onClose} title={p ? p.name : "Player"}>
      {q.isPending && (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-40" />
        </div>
      )}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {p && (
        <div className="flex flex-col gap-4">
          <div className="flex gap-4">
            <PlayerPhoto src={p.photo_url} name={p.name} className="w-20 shrink-0 rounded-md" />
            <div className="flex min-w-0 flex-col gap-1 text-sm">
              <p className="text-muted">
                {p.pos} · {p.club} · <span className="num">{money(p.price)}</span>
              </p>
              <p className="flex items-center gap-1">
                Rating <strong className="num text-lg">{p.rating}</strong>
                <InfoTip text={GLOSSARY.rating} label="About the rating" />
              </p>
              <p>
                Next GW <strong className="num">{points(p.p)}</strong> · P_h <strong className="num">{points(p.P_h)}</strong>{" "}
                <InfoTip text={GLOSSARY.P_h} label="About P_h" />
              </p>
              <p className="text-muted">
                Owned by <span className="num">{p.selected_by_percent == null ? "–" : `${p.selected_by_percent.toFixed(1)}%`}</span> ·
                availability <span className="num">{pct(p.availability)}</span>
              </p>
              {p.news && <Badge tone="warn">{p.news}</Badge>}
            </div>
          </div>

          {p.season.length > 0 && (
            <SeasonChart
              title="Expected vs actual this season"
              gws={p.season.map((s) => s.gw)}
              series={[
                { key: "exp", label: "Expected", values: p.season.map((s) => (s.expected == null ? null : Number(s.expected.toFixed(1)))), token: "navy" },
                { key: "act", label: "Actual", values: p.season.map((s) => s.actual), token: "accent" },
              ]}
            />
          )}

          {p.shap.length > 0 && (
            <div className="flex flex-col gap-2">
              <HBars
                title="Why the model thinks this (next GW)"
                summary={`Starting from the average player (${points(p.shap_base_value)}), these features move the forecast to ${points(p.shap_prediction)} before availability.`}
                rows={p.shap.map((s) => ({
                  label: s.feature,
                  value: s.shap,
                  note: s.value == null ? undefined : typeof s.value === "number" ? String(Number(s.value.toFixed(2))) : s.value,
                }))}
                signedValues
                valueLabel="SHAP (points)"
              />
              <p className="text-xs text-muted">
                Base <span className="num">{points(p.shap_base_value)}</span> + contributions = <span className="num">{points(p.shap_prediction)}</span> expected
                points before availability (×{pct(p.availability)}).
              </p>
            </div>
          )}

          <div>
            <h3 className="mb-2 font-semibold">Upcoming fixtures</h3>
            <ul className="flex flex-col gap-1 text-sm">
              {p.fixtures.map((f) => (
                <li key={`${f.gw}-${f.kickoff}`} className="flex items-center justify-between gap-2">
                  <span>
                    <span className="num text-muted">GW{f.gw}</span> {f.opponent} ({f.home ? "H" : "A"})
                  </span>
                  <span className="flex items-center gap-2 text-muted">
                    {shortDate(f.kickoff)}
                    <FdrChip fdr={f.fdr} />
                  </span>
                </li>
              ))}
              {p.fixtures.length === 0 && <li className="text-muted">No fixtures in the forecast window.</li>}
            </ul>
          </div>

          <Link to={`/builder?add=${p.id}`} className="btn-primary" onClick={onClose}>
            Add to Builder
          </Link>
        </div>
      )}
    </Sheet>
  );
}

const FDR_CLASS: Record<number, string> = {
  // fixed colours (same in both themes) with AA contrast for their text
  1: "bg-[#0B6E3F] text-white",
  2: "bg-[#7BE0A6] text-[#0E1834]",
  3: "bg-[#E2E5EE] text-[#0E1834]",
  4: "bg-[#FF9D90] text-[#0E1834]",
  5: "bg-[#A11D2E] text-white",
};

/** Fixture difficulty as number + colour (never colour alone). */
export function FdrChip({ fdr }: { fdr: number | null }) {
  if (fdr == null) return <span className="num text-xs text-muted">–</span>;
  return (
    <span className={`num inline-flex h-6 min-w-6 items-center justify-center rounded-sm px-1 text-xs font-bold ${FDR_CLASS[fdr] ?? "bg-line"}`} title={`Fixture difficulty ${fdr} of 5`}>
      {fdr}
    </span>
  );
}
