import type { Config } from "tailwindcss";

// Colours, radii, shadows and motion come from CSS variables in src/theme.css (light + dark);
// Tailwind only maps utility names onto those tokens.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        surface: token("surface"),
        raised: token("raised"),
        line: token("line"),
        ink: token("ink"),
        muted: token("muted"),
        navy: token("navy"),
        coral: token("coral"),
        accent: token("accent"),
        "on-accent": token("on-accent"),
        good: token("good"),
        bad: token("bad"),
        warn: token("warn"),
        slotA: token("slot-a"),
        slotB: token("slot-b"),
        slotC: token("slot-c"),
        "on-slot": token("on-slot"),
      },
      fontFamily: {
        sans: ['"Inter Variable"', "Inter-fallback", "system-ui", "sans-serif"],
        display: ['"Space Grotesk Variable"', "SpaceGrotesk-fallback", "system-ui", "sans-serif"],
      },
      borderRadius: { sm: "var(--radius-sm)", DEFAULT: "var(--radius)", lg: "var(--radius-lg)", xl: "var(--radius-xl)" },
      boxShadow: { sm: "var(--shadow-sm)", DEFAULT: "var(--shadow)", lg: "var(--shadow-lg)" },
      transitionDuration: { fast: "120ms", base: "200ms", slow: "320ms" },
      transitionTimingFunction: { out: "cubic-bezier(0.22, 1, 0.36, 1)" },
    },
  },
  plugins: [],
} satisfies Config;
