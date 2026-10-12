import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { calls } from "./handlers";
import { renderRoute } from "./render";

async function openBuilder() {
  const r = renderRoute("/builder");
  const list = await screen.findByRole("list", { name: "Player list" });
  await waitFor(() => expect(within(list).getAllByRole("button").length).toBeGreaterThan(5));
  // only Club A's six players (1 GK, 2 DEF, 2 MID, 1 FWD) in the list
  await r.user.selectOptions(screen.getByLabelText("Club"), "Club A");
  return { ...r, list };
}

const row = (list: HTMLElement, name: string) => within(list).getByText(name, { selector: "span" }).closest("button")!;
const onPitch = (id: number) => document.querySelector(`[data-slot] [data-player="${id}"]`);

describe("Builder", () => {
  it("tap a slot, then a player: the player is placed in that slot", async () => {
    const { user, list } = await openBuilder();
    const gkSlots = screen.getAllByRole("button", { name: /Empty GK slot/ });
    await user.click(gkSlots[0]);
    expect(screen.getByRole("button", { name: /Empty GK slot \(selected/ })).toBeInTheDocument();
    await user.click(row(list, "P1"));
    await waitFor(() => expect(onPitch(1)).not.toBeNull());
    expect(screen.getAllByRole("button", { name: /Empty GK slot/ })).toHaveLength(1);
    expect(row(list, "P1")).toBeDisabled();
  });

  it("a 4th player from one club shows the club message", async () => {
    const { user, list } = await openBuilder();
    for (const name of ["P1", "P2", "P3"]) await user.click(row(list, name));
    await waitFor(() => expect(onPitch(3)).not.toBeNull());
    await user.click(row(list, "P4"));
    expect(await screen.findByText("You already have 3 Club A players (max 3 per club).")).toBeInTheDocument();
    expect(onPitch(4)).toBeNull();
  });

  it("undo and redo", async () => {
    const { user, list } = await openBuilder();
    await user.click(row(list, "P2"));
    await waitFor(() => expect(onPitch(2)).not.toBeNull());
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(onPitch(2)).toBeNull());
    await user.click(screen.getByRole("button", { name: "Redo" }));
    await waitFor(() => expect(onPitch(2)).not.toBeNull());
    await user.keyboard("{Control>}z{/Control}");
    await waitFor(() => expect(onPitch(2)).toBeNull());
    await user.keyboard("{Control>}{Shift>}z{/Shift}{/Control}");
    await waitFor(() => expect(onPitch(2)).not.toBeNull());
  });

  it("auto-complete calls the optimizer with the current picks locked", async () => {
    const { user, list } = await openBuilder();
    await user.click(row(list, "P1"));
    await user.click(row(list, "P6"));
    await waitFor(() => expect(onPitch(6)).not.toBeNull());
    await user.click(screen.getByRole("button", { name: /Auto-complete/ }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/squads/optimize")).toBe(true));
    const call = calls.find((c) => c.path === "/api/squads/optimize")!;
    expect((call.body as { locked: number[] }).locked.sort()).toEqual([1, 6]);
    // the optimizer's squad fills all 15 slots
    await waitFor(() => expect(screen.queryAllByRole("button", { name: /Empty .* slot/ })).toHaveLength(0));
  });

  it("swaps a starter with a bench player by tapping both", async () => {
    const { user } = await openBuilder();
    await user.click(screen.getByRole("button", { name: /Auto-complete/ }));
    await waitFor(() => expect(screen.queryAllByRole("button", { name: /Empty .* slot/ })).toHaveLength(0));
    const bench = screen.getByRole("list", { name: "Bench" });
    const benchCard = within(bench).getAllByRole("listitem")[1].querySelector("[data-player]")!;
    const benchId = Number(benchCard.getAttribute("data-player"));
    const xiDef = within(screen.getByRole("list", { name: "Defenders" })).getAllByRole("listitem")[0].querySelector("[data-player]")!;
    const xiId = Number(xiDef.getAttribute("data-player"));
    await user.click(within(xiDef as HTMLElement).getAllByRole("button")[0]);
    await user.click(within(benchCard as HTMLElement).getAllByRole("button")[0]);
    await waitFor(() => expect(bench.querySelector(`[data-player="${xiId}"]`)).not.toBeNull());
    expect(document.querySelector(`[data-slot^="xi"] [data-player="${benchId}"]`)).not.toBeNull();
  });
});
