import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { calls, ENTRY_ID, fixtures } from "./handlers";
import { renderRoute } from "./render";

async function openPlan() {
  const r = renderRoute(`/me/${ENTRY_ID}/transfers`);
  await r.user.click(await screen.findByRole("button", { name: "Plan transfers" }));
  await screen.findByRole("heading", { name: /Options for GW/ });
  return r;
}

describe("Transfers", () => {
  it("sends the team, bank (prefilled) and free transfers", async () => {
    await openPlan();
    const body = calls.find((c) => c.path === "/api/transfers/plan")!.body as Record<string, unknown>;
    expect(body).toMatchObject({ team_id: ENTRY_ID, bank: fixtures.entry.bank, free_transfers: 1 });
  });

  it("highlights the recommended option", async () => {
    await openPlan();
    const rec = fixtures.transfers.options.find((o) => o.recommended)!;
    const item = screen.getByRole("listitem", { name: `${rec.n_transfers} transfer${rec.n_transfers === 1 ? "" : "s"} (recommended)` });
    expect(item).toHaveAttribute("data-recommended", "true");
    expect(item.className).toContain("ring-accent");
    expect(within(item).getByText("Recommended")).toBeInTheDocument();
    expect(document.querySelectorAll('[data-recommended="true"]')).toHaveLength(1);
  });

  it("shows the hit cost with its sign", async () => {
    await openPlan();
    const two = screen.getByRole("listitem", { name: /^2 transfers/ });
    const hits = fixtures.transfers.options.find((o) => o.n_transfers === 2)!.hits;
    expect(hits).toBe(4);
    expect(within(two).getByText("−4")).toBeInTheDocument();
    expect(screen.getByText(/Selling prices:/)).toBeInTheDocument();
  });

  it("lists the path to the best team in order", async () => {
    const { user } = await openPlan();
    const steps = within(screen.getByRole("list", { name: "Path steps" })).getAllByTestId("path-step");
    const path = fixtures.transfers.path!;
    expect(steps).toHaveLength(path.steps.length);
    steps.forEach((li, k) => {
      const step = path.steps[k];
      expect(within(li).getByText(String(step.n_moves))).toBeInTheDocument();
      expect(li).toHaveTextContent(step.new_moves[0].out.web_name);
      expect(li).toHaveTextContent(step.new_moves[0].into.web_name);
      expect(li).toHaveTextContent(k < path.make_now ? "Make now" : "Later, with free transfers");
    });
    expect(screen.getByText(path.advice)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Preview the target squad" }));
    expect(await screen.findByRole("region", { name: /^Squad after the plan/ })).toBeInTheDocument();
  });
});
