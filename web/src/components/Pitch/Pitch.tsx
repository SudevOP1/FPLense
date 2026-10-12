import { AnimatePresence, LayoutGroup, motion } from "framer-motion";
import { forwardRef, type ReactNode } from "react";
import { POS_LABEL } from "@/lib/format";
import { dealVariants } from "@/lib/motion";
import { dealOrder, lineup, type LineupPlayer } from "@/lib/pitch";
import { useReducedMotion } from "@/lib/settings";
import { PlayerCard, type CardPlayer, type MenuItem } from "../PlayerCard/PlayerCard";

export type PitchPlayer = CardPlayer & LineupPlayer;

export interface CardExtras {
  onClick?: () => void;
  menu?: MenuItem[];
  ring?: string;
  badge?: ReactNode;
  ghost?: boolean;
  dimmed?: boolean;
  selected?: boolean;
}

/**
 * Pitch image behind any content (the Builder puts its slots in here). The frame keeps the image
 * aspect ratio as a minimum height and spreads the rows over it: GK by the goal at the top, FWD
 * towards the bottom box. Taller content stretches the image instead of cropping it. Width is
 * capped so GK and FWD rows fit on one laptop screen.
 */
export const PitchFrame = forwardRef<HTMLDivElement, { children: ReactNode; label: string; className?: string }>(
  function PitchFrame({ children, label, className = "" }, ref) {
    return (
      <section ref={ref} aria-label={label} className={`pitch relative mx-auto flex w-full max-w-[680px] flex-col overflow-hidden px-[3%] pb-[4%] pt-[5%] ${className}`}>
        <div className="relative flex flex-1 flex-col justify-around gap-2">{children}</div>
      </section>
    );
  },
);

export function PitchRow({ label, children, testId }: { label: string; children: ReactNode; testId?: string }) {
  return (
    <ul aria-label={label} data-testid={testId} className="flex items-start justify-center gap-1.5 sm:gap-2">
      {children}
    </ul>
  );
}

export const CARD_WIDTH = "w-[19%] max-w-[96px] min-w-[54px]";

/**
 * A squad on the pitch: XI rows built from the formation, bench strip below with bench order
 * numbers. Cards deal on GK -> FWD; when the squad changes, unchanged players stay still and only
 * incoming / outgoing ones move (keys are player ids).
 */
export const Pitch = forwardRef<
  HTMLDivElement,
  {
    players: PitchPlayer[];
    mode?: "expected" | "actual";
    label?: string;
    extras?: (p: PitchPlayer) => CardExtras;
    layoutPrefix?: string;
    footer?: ReactNode;
  }
>(function Pitch({ players, mode = "expected", label = "Squad", extras, layoutPrefix = "pitch", footer }, ref) {
  const reduced = useReducedMotion();
  const l = lineup(players);
  const order = dealOrder(l);
  const card = (p: PitchPlayer) => {
    const x = extras?.(p) ?? {};
    return (
      <motion.li
        key={p.id}
        layoutId={`${layoutPrefix}-${p.id}`}
        layout="position"
        custom={order.get(p.id) ?? 0}
        variants={dealVariants}
        initial={reduced ? false : "hidden"}
        animate="shown"
        exit={reduced ? undefined : "exit"}
        className={CARD_WIDTH}
      >
        <PlayerCard player={p} mode={mode} {...x} />
      </motion.li>
    );
  };
  return (
    <LayoutGroup id={layoutPrefix}>
      <div ref={ref} className="mx-auto flex w-full max-w-[680px] flex-col gap-2">
        <PitchFrame label={`${label}: ${l.formation}`}>
          <span className="sr-only">Formation {l.formation}</span>
          {l.rows.map((row) => (
            <PitchRow key={row.pos} label={POS_LABEL[row.pos]} testId={`row-${row.pos}`}>
              <AnimatePresence mode="popLayout" initial={!reduced}>
                {row.players.map(card)}
              </AnimatePresence>
            </PitchRow>
          ))}
        </PitchFrame>
        {l.bench.length > 0 && (
          <div className="rounded-xl border border-line bg-raised px-2 py-2">
            <p className="label mb-1 px-1">Bench</p>
            <ol aria-label="Bench" data-testid="bench" className="flex items-start justify-center gap-1.5 sm:gap-2">
              <AnimatePresence mode="popLayout" initial={!reduced}>
                {l.bench.map((p, k) => (
                  <motion.li
                    key={p.id}
                    layoutId={`${layoutPrefix}-${p.id}`}
                    layout="position"
                    custom={order.get(p.id) ?? 0}
                    variants={dealVariants}
                    initial={reduced ? false : "hidden"}
                    animate="shown"
                    exit={reduced ? undefined : "exit"}
                    className={`${CARD_WIDTH} flex flex-col items-center gap-1`}
                  >
                    <span className="num text-xs font-bold text-muted" data-testid="bench-order">
                      {p.pos === "GK" ? "GK" : (p.bench_order ?? k + 1)}
                    </span>
                    <PlayerCard player={p} mode={mode} {...(extras?.(p) ?? {})} />
                  </motion.li>
                ))}
              </AnimatePresence>
            </ol>
          </div>
        )}
        {footer}
      </div>
    </LayoutGroup>
  );
});
