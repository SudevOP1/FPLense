import { useEffect, useState } from "react";
import { useHealth } from "@/api/hooks";

const SLOW_MS = 2500;
const COLD_START_S = 60;

/**
 * Free-tier hosts sleep when idle. If /api/health is slow, say the server is waking up and show
 * rough progress over the ~30-60 s cold start.
 */
export function ServerStatus() {
  const health = useHealth();
  const [elapsed, setElapsed] = useState(0);
  const waiting = health.isPending || (health.isError && health.failureCount < 9);

  useEffect(() => {
    if (!waiting) return;
    const t0 = Date.now();
    const t = window.setInterval(() => setElapsed(Date.now() - t0), 500);
    return () => window.clearInterval(t);
  }, [waiting]);

  if (health.data?.status === "no_data")
    return (
      <div role="status" className="border-b border-warn/40 bg-warn/10 px-4 py-2 text-center text-sm text-warn">
        No predictions are published yet. Check back before the next deadline.
      </div>
    );
  if (health.isError && !waiting)
    return (
      <div role="alert" className="border-b border-bad/40 bg-bad/10 px-4 py-2 text-center text-sm text-bad">
        The FPLense server isn't answering.{" "}
        <button type="button" className="font-semibold underline" onClick={() => health.refetch()}>
          Retry
        </button>
      </div>
    );
  if (!waiting || elapsed < SLOW_MS) return null;
  const progress = Math.min(95, (elapsed / 1000 / COLD_START_S) * 100);
  return (
    <div role="status" className="border-b border-line bg-raised px-4 py-2 text-sm">
      <div className="mx-auto flex max-w-6xl items-center gap-3">
        <span>Waking up the server… free hosting sleeps when idle; this can take up to a minute.</span>
        <div className="h-1.5 w-32 shrink-0 overflow-hidden rounded-full bg-line" aria-hidden>
          <div className="h-full origin-left bg-accent transition-transform duration-slow" style={{ transform: `scaleX(${progress / 100})` }} />
        </div>
      </div>
    </div>
  );
}
