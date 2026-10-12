import { motion } from "framer-motion";
import { useId } from "react";
import { SPRING } from "@/lib/motion";

/** Tabs with a sliding underline indicator (shared layout animation). */
export function Tabs<T extends string>({
  label,
  tabs,
  value,
  onChange,
}: {
  label: string;
  tabs: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  const id = useId();
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 border-b border-line">
      {tabs.map((t) => {
        const active = t.value === value;
        return (
          <button
            key={t.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.value)}
            className={`relative min-h-[44px] px-3 text-sm font-semibold transition-colors duration-fast ${
              active ? "text-ink" : "text-muted hover:text-ink"
            }`}
          >
            {t.label}
            {active && (
              <motion.span
                layoutId={`tab-underline-${id}`}
                transition={SPRING}
                className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent"
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
