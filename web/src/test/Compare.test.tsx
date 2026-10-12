import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { calls, fixtures } from "./handlers";
import { renderRoute } from "./render";

const compareCalls = () => calls.filter((c) => c.path === "/api/compare").map((c) => c.body as { slots: { kind: string; gw: number | null; value: unknown }[] });

describe("Compare", () => {
  it("shows 2 slots by default (model pick vs hindsight best, last finished GW)", async () => {
    renderRoute("/compare");
    expect(await screen.findByRole("region", { name: "Team A: Model pick GW2" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Team B: Hindsight best GW2" })).toBeInTheDocument();
    expect(compareCalls().at(-1)!.slots.map((s) => [s.kind, s.gw])).toEqual([
      ["model_pick", 2],
      ["hindsight", 2],
    ]);
  });

  it("takes a 3rd slot and refuses a 4th", async () => {
    const { user } = renderRoute("/compare?a=model_pick.2&b=hindsight.2");
    await screen.findByRole("region", { name: "Team B: Hindsight best GW2" });
    await user.click(screen.getByRole("button", { name: "Add a team" }));
    expect(await screen.findByRole("region", { name: "Team C: Pasted team" })).toBeInTheDocument();
    expect(compareCalls().at(-1)!.slots).toHaveLength(3);
    const add = screen.getByRole("button", { name: "Add a team" });
    expect(add).toBeDisabled();
    expect(screen.queryByRole("button", { name: /\+ Add team/ })).toBeNull();
    expect(compareCalls().every((b) => b.slots.length <= 3)).toBe(true);
  });

  it("each slot has its own GW picker", async () => {
    const { user } = renderRoute("/compare?a=model_pick.2&b=hindsight.2");
    await screen.findByRole("region", { name: "Team A: Model pick GW2" });
    await user.selectOptions(screen.getByLabelText("Gameweek for team A"), "1");
    await waitFor(() => expect(compareCalls().at(-1)!.slots[0]).toMatchObject({ kind: "model_pick", gw: 1 }));
    expect(compareCalls().at(-1)!.slots[1]).toMatchObject({ kind: "hindsight", gw: 2 });
    expect(screen.getByLabelText("Gameweek for team B")).toHaveValue("2");
  });

  it("pasting an invalid code shows the error", async () => {
    const { user } = renderRoute("/compare?a=model_pick.2&b=hindsight.2");
    await screen.findByRole("region", { name: "Team A: Model pick GW2" });
    await user.selectOptions(screen.getByLabelText("Source for team B"), "code");
    const field = await screen.findByLabelText("Team code for B");
    const bad = fixtures.decodeOut.code.slice(0, -1) + (fixtures.decodeOut.code.endsWith("0") ? "1" : "0");
    await user.type(field, bad);
    await user.click(screen.getByRole("button", { name: "Use" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This code looks like a typo");
  });

  it("highlights players shared between teams", async () => {
    renderRoute("/compare?a=model_pick.2&b=hindsight.2");
    const a = await screen.findByRole("region", { name: "Team A: Model pick GW2" });
    const sharedId = fixtures.compare.shared[0].id;
    const card = a.querySelector(`[data-player="${sharedId}"]`)!;
    expect(card.className).toContain("ring-accent");
    const notShared = fixtures.compare.slots[0].squad.players.find((p) => !fixtures.compare.shared.some((s) => s.id === p.id))!;
    expect(a.querySelector(`[data-player="${notShared.id}"]`)!.className).not.toContain("ring-accent");
    expect(within(a).getAllByText("DIFF").length).toBe(fixtures.compare.slots[0].differentials.length);
  });
});
