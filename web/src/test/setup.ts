import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, expect, vi } from "vitest";
import * as axeMatchers from "vitest-axe/matchers";
import { calls } from "./handlers";
import { server } from "./server";

expect.extend(axeMatchers);
// pages are lazy chunks: the first findBy* in a file also waits for Vite to transform the page
configure({ asyncUtilTimeout: 8000 });

/** Tests flip this to mock `prefers-reduced-motion: reduce`. */
export const media = { reducedMotion: false, dark: false };

function installBrowserMocks() {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches:
      (query.includes("prefers-reduced-motion: reduce") && media.reducedMotion) ||
      (query.includes("prefers-color-scheme: dark") && media.dark),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
  class RO {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  window.ResizeObserver = RO as unknown as typeof ResizeObserver;
  window.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  } as unknown as typeof IntersectionObserver;
  // jsdom has no canvas; axe probes it for colour checks
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext;
  window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;
  Element.prototype.scrollIntoView = vi.fn();
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined), readText: vi.fn() },
  });
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  media.reducedMotion = false;
  media.dark = false;
  installBrowserMocks();
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem("fplense:tourDone", "true"); // the first-visit tour has its own test
  calls.length = 0;
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
  document.documentElement.removeAttribute("data-theme");
});
afterAll(() => server.close());
