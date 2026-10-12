import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ENTRY_ID, fixtures } from "./handlers";
import { renderRoute } from "./render";

describe("My Team", () => {
  it("submit a team ID: header, pitch, lineup helper and season chart render", async () => {
    const { user, router } = renderRoute("/me");
    await user.type(await screen.findByLabelText("Your FPL team ID"), String(ENTRY_ID));
    await user.click(screen.getByRole("button", { name: "Load team" }));
    expect(router.state.location.pathname).toBe(`/me/${ENTRY_ID}`);
    expect(await screen.findByRole("heading", { name: fixtures.entry.team_name, level: 1 })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: /^Your lineup: \d-\d-\d$/ })).toBeInTheDocument();
    expect(screen.getByText("Lineup helper:")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Suggested XI" })).toBeInTheDocument();
    expect(screen.getByText("Your season")).toBeInTheDocument();
    expect(localStorage.getItem("fplense:teamId")).toBe(String(ENTRY_ID));
  });

  it("the suggested XI highlights the helper's changes", async () => {
    const { user } = renderRoute(`/me/${ENTRY_ID}`);
    await user.click(await screen.findByRole("radio", { name: "Suggested XI" }));
    const pitch = await screen.findByRole("region", { name: /^Suggested lineup/ });
    for (const id of fixtures.entryGw2.lineup_changes) {
      expect(pitch.querySelector(`[data-player="${id}"]`)!.className).toContain("ring-accent");
    }
  });

  it("an unknown team ID gets a friendly 404 message", async () => {
    renderRoute("/me/999");
    expect(await screen.findByText("Couldn't load that team")).toBeInTheDocument();
    expect(screen.getByText("No FPL team with ID 999.")).toBeInTheDocument();
    expect(screen.getByLabelText("Your FPL team ID")).toBeInTheDocument();
  });

  it("a 429 shows a retry hint", async () => {
    renderRoute("/me/429");
    expect(await screen.findByText("Too many requests: try again in 12 seconds.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("explains where to find the team ID", async () => {
    const { user } = renderRoute("/me");
    await user.click(await screen.findByRole("button", { name: "Where do I find my ID?" }));
    expect(screen.getByText(/fantasy\.premierleague\.com\/entry\//)).toBeInTheDocument();
  });
});
