import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

/** Preload the two Latin web fonts (the rest of the subsets load on demand). */
function preloadFonts(): Plugin {
  return {
    name: "fplense-preload-fonts",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(_html, ctx) {
        const files = Object.keys(ctx.bundle ?? {}).filter((f) => /(inter|space-grotesk)-latin-wght-normal-.*\.woff2$/.test(f));
        return files.map((f) => ({
          tag: "link",
          attrs: { rel: "preload", href: `/${f}`, as: "font", type: "font/woff2", crossorigin: "" },
          injectTo: "head" as const,
        }));
      },
    },
  };
}

export default defineConfig({
  plugins: [react(), preloadFonts()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: { port: 5173 },
  build: {
    target: "es2022",
    rollupOptions: {
      output: {
        // vendor chunks so the main chunk stays small and caches well between deploys
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          query: ["@tanstack/react-query"],
          motion: ["framer-motion"],
          charts: ["recharts"],
          dnd: ["@dnd-kit/core", "@dnd-kit/sortable", "@dnd-kit/utilities"],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/polyfills.ts", "./src/test/setup.ts"],
    css: false,
    testTimeout: 15000,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
