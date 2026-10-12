import { motion, useAnimationControls } from "framer-motion";
import { useEffect, useRef } from "react";
import { shake } from "@/lib/motion";
import { useReducedMotion } from "@/lib/settings";
import type { Chip } from "@/lib/squadRules";

function RuleChip({ chip }: { chip: Chip }) {
  const controls = useAnimationControls();
  const reduced = useReducedMotion();
  const wasOk = useRef(chip.ok);
  useEffect(() => {
    // one 2-px shake when a chip turns red; never repeats while it stays red
    if (wasOk.current && !chip.ok && !reduced) void controls.start(shake);
    wasOk.current = chip.ok;
  }, [chip.ok, controls, reduced]);
  return (
    <motion.li
      animate={controls}
      title={chip.message}
      data-rule={chip.id}
      data-ok={chip.ok}
      className={`chip transition-colors duration-base ${
        chip.ok ? "border-good/40 bg-good/10 text-good" : "border-bad/50 bg-bad/10 text-bad"
      }`}
    >
      <span aria-hidden>{chip.ok ? "✓" : "!"}</span>
      <span className="num">{chip.label}</span>
      <span className="sr-only">: {chip.message}</span>
    </motion.li>
  );
}

/** Live rule chips; changes are announced to screen readers. */
export function RuleChips({ chips, message }: { chips: Chip[]; message?: string | null }) {
  return (
    <div>
      <ul className="flex flex-wrap gap-2" aria-label="Squad rules">
        {chips.map((c) => (
          <RuleChip key={c.id} chip={c} />
        ))}
      </ul>
      <p aria-live="polite" className={`mt-2 min-h-[1.25rem] text-sm ${message ? "text-bad" : "text-muted"}`}>
        {message ?? chips.find((c) => !c.ok)?.message ?? ""}
      </p>
    </div>
  );
}
