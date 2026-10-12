import { useModel } from "@/api/hooks";
import type { ModelStats } from "@/api/types";
import { HBars, MaeByGw } from "@/components/charts/Charts";
import { Stat } from "@/components/ui/Bits";
import { ErrorState, PageHeader, Skeleton } from "@/components/ui/States";
import { useTitle } from "@/lib/useTitle";

const MODEL_LABEL: Record<string, string> = {
  b0: "Rolling form (baseline)",
  ridge: "Ridge regression",
  lgbm: "LightGBM",
  lgbm_l1: "LightGBM (L1, median)",
};

const STEPS = [
  { t: "ETL", d: "10 seasons of FPL history + the live FPL API + bookmaker odds + Elo, into Parquet." },
  { t: "Features", d: "43 leakage-safe features as DuckDB SQL window views (each ends at the previous match)." },
  { t: "Model", d: "LightGBM, validated walk-forward like a real forecast, explained with SHAP." },
  { t: "Optimizer", d: "A PuLP integer program picks the best legal £100m squad and transfers." },
  { t: "App", d: "FastAPI serves the published predictions; this React app shows them." },
];

function fmtCi(ci?: [number, number]) {
  return ci ? `[${ci[0].toFixed(1)}, ${ci[1].toFixed(1)}]` : "–";
}

export default function ModelCard() {
  useTitle("Model Card");
  const q = useModel();
  if (q.isPending)
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-28" />
        <Skeleton className="h-72" />
      </div>
    );
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const { headline, metrics, mae_by_gw, shap_importance, backtest } = q.data;
  const reg = metrics?.walk_forward?.regulars ?? {};
  const shap = Object.entries(shap_importance?.mean_abs_shap ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Model Card" sub="How FPLense forecasts points, how well it does, and where it falls short." />

      {headline && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat label="MAE cut vs rolling form" value={`${headline.gain_pct.toFixed(1)}%`} sub={`95% CI ${fmtCi(headline.ci as [number, number])}`} />
          <Stat label="LightGBM MAE" value={headline.mae.toFixed(3)} sub={`baseline ${headline.b0_mae.toFixed(3)}`} />
          <Stat label="Rank correlation" value={headline.spearman.toFixed(2)} sub={`baseline ${headline.b0_spearman.toFixed(2)} (Spearman per GW)`} />
          <Stat label="Player-gameweeks" value={headline.n.toLocaleString("en-GB")} sub={`regulars, ${headline.season} walk-forward`} />
        </div>
      )}

      <section className="card overflow-x-auto p-4" aria-labelledby="metrics">
        <h2 id="metrics" className="mb-2 text-lg font-semibold">
          Walk-forward results (regulars)
        </h2>
        <p className="mb-3 text-sm text-muted">
          Trained only on data before each gameweek, then scored on it, for every gameweek of {metrics?.walk_forward?.target_season ?? "2025-26"}. Regulars ={" "}
          {metrics?.regulars_definition ?? "players with recent minutes"}. CIs: {metrics?.bootstrap ?? "block bootstrap"}.
        </p>
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-muted">
              <th scope="col" className="py-1 pr-2">
                Model
              </th>
              <th scope="col" className="px-2 text-right">
                MAE
              </th>
              <th scope="col" className="px-2 text-right">
                RMSE
              </th>
              <th scope="col" className="px-2 text-right">
                Spearman
              </th>
              <th scope="col" className="px-2 text-right">
                MAE cut vs baseline (95% CI)
              </th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(reg).map(([k, m]: [string, ModelStats]) => (
              <tr key={k} className={`border-b border-line/60 ${k === "lgbm" ? "font-semibold" : ""}`}>
                <th scope="row" className="py-1.5 pr-2 text-left font-medium">
                  {MODEL_LABEL[k] ?? k}
                </th>
                <td className="num px-2 text-right">{m.mae.toFixed(3)}</td>
                <td className="num px-2 text-right">{m.rmse?.toFixed(3) ?? "–"}</td>
                <td className="num px-2 text-right">{m.spearman_per_gw?.toFixed(3) ?? "–"}</td>
                <td className="num px-2 text-right">
                  {m.mae_gain_pct == null ? "baseline" : `${m.mae_gain_pct.toFixed(1)}% ${fmtCi(m.mae_gain_ci95)}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-muted">
          The L1 model has the lowest MAE because it predicts medians; the optimizer needs expected values, so the app uses the L2 LightGBM.
        </p>
      </section>

      {mae_by_gw && (
        <MaeByGw
          series={Object.entries(mae_by_gw.models).map(([k, v]) => ({ key: k, label: MODEL_LABEL[k] ?? k, gws: v.gw, mae: v.mae }))}
        />
      )}

      {shap.length > 0 && (
        <HBars
          title="What drives the forecasts (mean |SHAP|, points)"
          summary={`The most important features are ${shap
            .slice(0, 3)
            .map(([f]) => f)
            .join(", ")}.`}
          rows={shap.map(([f, v]) => ({ label: f, value: v }))}
          valueLabel="Mean |SHAP|"
        />
      )}

      {backtest && (
        <section className="card p-4" aria-labelledby="bt">
          <h2 id="bt" className="mb-2 text-lg font-semibold">
            The honest backtest
          </h2>
          <p className="text-sm">
            Playing {backtest.season} with each strategy ({backtest.rules}):{" "}
            {Object.entries(backtest.total_points)
              .map(([k, v]) => `${backtest.strategies[k] ?? k} ${v.toLocaleString("en-GB")}`)
              .join(" · ")}
            .
          </p>
          {backtest.a_minus_b != null && (
            <p className="mt-2 text-sm text-muted">
              A − B = {backtest.a_minus_b} points, 95% CI {fmtCi(backtest.a_minus_b_ci95)}: not significant. A better forecast didn't turn into more
              season points in one simulated season; week-to-week noise is large. So FPLense claims the forecast gain, not a points gain.
            </p>
          )}
        </section>
      )}

      <section className="card p-4" aria-labelledby="lim">
        <h2 id="lim" className="mb-2 text-lg font-semibold">
          Limitations
        </h2>
        <ul className="list-disc space-y-1 pl-5 text-sm">
          <li>FPL points are noisy (about 3 points of spread per appearance); even a perfect model misses most hauls.</li>
          <li>Minutes are the biggest driver and the hardest to know: rotation and late injury news aren't in the data until FPL publishes them.</li>
          <li>Past gameweeks before the live archive started are backfilled: rebuilt from earlier data, with everyone counted as fit.</li>
          <li>Selling prices aren't public, so transfer plans value your players at today's price.</li>
          <li>Promoted teams and new signings have little history (cold start).</li>
        </ul>
      </section>

      <section aria-labelledby="how" className="flex flex-col gap-3">
        <h2 id="how" className="text-lg font-semibold">
          How it works
        </h2>
        <ol className="grid gap-2 md:grid-cols-5">
          {STEPS.map((s, k) => (
            <li key={s.t} className="card relative flex flex-col gap-1 p-3">
              <span className="num text-xs font-bold text-coral">{k + 1}</span>
              <span className="font-display font-semibold">{s.t}</span>
              <span className="text-xs text-muted">{s.d}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
