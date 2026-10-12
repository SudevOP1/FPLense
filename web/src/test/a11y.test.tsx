// No axe violations on any page, in light and dark themes. (jsdom has no layout, so axe can't
// measure colour contrast here; that's checked by hand on the kitchen-sink route.)
import { screen, waitFor } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { ENTRY_ID } from "./handlers";
import { renderRoute } from "./render";
import { media } from "./setup";

const PAGES: [string, string, () => Promise<unknown>][] = [
  ["Home", "/", () => screen.findByRole("heading", { name: /Best XI for GW/ })],
  ["Best Team", "/best", () => screen.findByRole("region", { name: /^Model pick GW3: \d-\d-\d$/ })],
  ["Season Replay", "/season", () => screen.findByRole("heading", { name: /Model pick · GW2/ })],
  ["My Team (form)", "/me", () => screen.findByLabelText("Your FPL team ID")],
  ["My Team", `/me/${ENTRY_ID}`, () => screen.findByText("Lineup helper:")],
  ["Transfers", `/me/${ENTRY_ID}/transfers`, () => screen.findByRole("button", { name: "Plan transfers" })],
  ["Compare", "/compare", () => screen.findByRole("region", { name: "Team B: Hindsight best GW2" })],
  ["Builder", "/builder", () => screen.findByRole("list", { name: "Player list" })],
  ["Players", "/players", () => screen.findByRole("table")],
  ["Model Card", "/model", () => screen.findByRole("heading", { name: "Walk-forward results (regulars)" })],
  ["Not found", "/nope", () => screen.findByRole("heading", { name: "Offside!" })],
];


describe.each(["light", "dark"] as const)("accessibility (%s theme)", (theme) => {
  it.each(PAGES)("%s has no axe violations", async (_name, path, ready) => {
    media.dark = theme === "dark";
    const { container } = renderRoute(path);
    await ready();
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe(theme));
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
