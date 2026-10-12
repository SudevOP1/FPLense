import { useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Squad } from "@/api/types";
import { CodeBox } from "@/components/CodeBox/CodeBox";
import { Pitch, type CardExtras, type PitchPlayer } from "@/components/Pitch/Pitch";
import { AnimatedNumber } from "@/components/ui/Motion";
import { Badge, GLOSSARY, InfoTip } from "@/components/ui/Bits";
import { useCompareTray } from "@/lib/compareTray";
import type { CompareSlot } from "@/lib/compareSlots";
import { money, points } from "@/lib/format";
import { toPitchPlayers } from "@/lib/pitch";
import { usePlayerDrawer } from "@/lib/playerDrawer";
import { useToast } from "@/lib/toast";

const SILHOUETTE =
  "data:image/svg+xml;utf8," +
  encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 110 140"><rect width="110" height="140" fill="#dde2ee"/><circle cx="55" cy="52" r="24" fill="#9aa6c4"/><path d="M14 140c4-34 20-50 41-50s37 16 41 50z" fill="#9aa6c4"/></svg>');

/** "Save as image": renders the pitch to a PNG. Cross-origin photos become silhouettes. */
function SaveImageButton({ target, name }: { target: React.RefObject<HTMLDivElement | null>; name: string }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      className="btn-secondary"
      disabled={busy}
      onClick={async () => {
        if (!target.current) return;
        setBusy(true);
        try {
          const { toPng } = await import("html-to-image");
          const url = await toPng(target.current, {
            pixelRatio: 2,
            imagePlaceholder: SILHOUETTE,
            backgroundColor: getComputedStyle(document.body).backgroundColor,
          });
          const a = document.createElement("a");
          a.href = url;
          a.download = `${name.replace(/[^\w-]+/g, "_")}.png`;
          a.click();
          toast.show("Image saved", { tone: "good" });
        } catch {
          toast.show("Couldn't create the image in this browser.", { tone: "bad" });
        } finally {
          setBusy(false);
        }
      }}
    >
      Save as image
    </button>
  );
}

/**
 * A squad with its summary (expected / actual points, cost, money left), the pitch and the share
 * actions: copy code, share link, add to compare, open in Builder, save as image.
 */
export function SquadView({
  squad,
  slot,
  extras,
  title,
  badges,
  actions,
  showCode = true,
  layoutPrefix,
  compact = false,
}: {
  squad: Squad;
  slot?: CompareSlot;
  extras?: (p: PitchPlayer) => CardExtras;
  title?: ReactNode;
  badges?: ReactNode;
  actions?: ReactNode;
  showCode?: boolean;
  layoutPrefix?: string;
  compact?: boolean;
}) {
  const tray = useCompareTray();
  const drawer = usePlayerDrawer();
  const pitchRef = useRef<HTMLDivElement>(null);
  const finished = squad.actual_points != null;
  const defaultExtras = (p: PitchPlayer): CardExtras => ({ onClick: () => drawer.open(p.id) });
  return (
    <section className="flex flex-col gap-3" aria-label={squad.label}>
      {(title || badges) && (
        <div className="flex flex-wrap items-center gap-2">
          {title && <h2 className="text-lg font-semibold">{title}</h2>}
          {badges}
        </div>
      )}
      <dl className={`grid gap-2 ${compact ? "grid-cols-2" : "grid-cols-2 sm:grid-cols-4"}`}>
        <div className="card px-3 py-2">
          <dt className="label flex items-center gap-1">
            Expected <InfoTip text={GLOSSARY.expected} label="About expected points" />
          </dt>
          <dd className="text-xl font-bold" aria-live="polite">
            <AnimatedNumber value={squad.expected_points} />
          </dd>
        </div>
        {finished ? (
          <div className="card px-3 py-2">
            <dt className="label">Actual</dt>
            <dd className="text-xl font-bold">
              <AnimatedNumber value={squad.actual_points} format={(v) => points(v, "actual")} />
            </dd>
          </div>
        ) : (
          <div className="card px-3 py-2">
            <dt className="label">Next {squad.horizon_expected.length} GWs</dt>
            <dd className="text-xl font-bold">
              <AnimatedNumber value={squad.horizon_expected.reduce((a, h) => a + h.points, 0)} />
            </dd>
          </div>
        )}
        <div className="card px-3 py-2">
          <dt className="label">Cost</dt>
          <dd className="text-xl font-bold">
            <AnimatedNumber value={squad.cost} format={(v) => money(Math.round(v))} />
          </dd>
        </div>
        <div className="card px-3 py-2">
          <dt className="label">Money left</dt>
          <dd className="text-xl font-bold">
            <AnimatedNumber value={squad.bank} format={(v) => money(Math.round(v))} />
          </dd>
        </div>
      </dl>
      {squad.problems.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {squad.problems.map((p) => (
            <Badge key={p.message} tone="bad">
              {p.message}
            </Badge>
          ))}
        </div>
      )}
      <Pitch
        ref={pitchRef}
        players={toPitchPlayers(squad)}
        mode={finished ? "actual" : "expected"}
        label={squad.label}
        extras={extras ?? defaultExtras}
        layoutPrefix={layoutPrefix ?? `${squad.kind}-${squad.gw}`}
      />
      <div className="flex flex-wrap gap-2">
        {slot && (
          <button type="button" className="btn-secondary" onClick={() => tray.add(slot)}>
            Add to compare
          </button>
        )}
        {squad.code && (
          <Link className="btn-secondary" to={`/builder?t=${encodeURIComponent(squad.code)}`}>
            Open in Builder
          </Link>
        )}
        <SaveImageButton target={pitchRef} name={squad.label} />
        {actions}
      </div>
      {showCode && squad.code && <CodeBox code={squad.code} />}
    </section>
  );
}
