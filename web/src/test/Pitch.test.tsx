import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Squad } from "@/api/types";
import { Pitch } from "@/components/Pitch/Pitch";
import { formation } from "@/lib/squadRules";
import { fixtures } from "./handlers";
import { renderWithProviders } from "./render";

const squad = fixtures.squadBest as unknown as Squad;

describe("Pitch", () => {
  it("builds XI rows from the formation", () => {
    renderWithProviders(<Pitch players={squad.players} label="Best" />);
    const xi = squad.players.filter((p) => p.starter);
    const shape = formation(xi.map((p) => p.pos));
    expect(screen.getByRole("region", { name: `Best: ${shape}` })).toBeInTheDocument();
    for (const [pos, label] of [
      ["GK", "Goalkeepers"],
      ["DEF", "Defenders"],
      ["MID", "Midfielders"],
      ["FWD", "Forwards"],
    ] as const) {
      const row = screen.getByRole("list", { name: label });
      expect(within(row).getAllByRole("listitem")).toHaveLength(xi.filter((p) => p.pos === pos).length);
    }
  });

  it("shows the bench in bench order with numbers", () => {
    renderWithProviders(<Pitch players={squad.players} />);
    const bench = screen.getByRole("list", { name: "Bench" });
    const expected = squad.players.filter((p) => !p.starter).sort((a, b) => (a.bench_order ?? 0) - (b.bench_order ?? 0));
    const cards = within(bench).getAllByRole("listitem");
    expect(cards).toHaveLength(4);
    cards.forEach((li, k) => {
      expect(li.querySelector("[data-player]")?.getAttribute("data-player")).toBe(String(expected[k].id));
      const order = within(li).getByTestId("bench-order").textContent;
      expect(order).toBe(expected[k].pos === "GK" ? "GK" : String(expected[k].bench_order));
    });
  });

  it("puts the captain and vice armbands on the right players", () => {
    renderWithProviders(<Pitch players={squad.players} />);
    const cap = document.querySelector(`[data-player="${squad.captain}"]`) as HTMLElement;
    const vice = document.querySelector(`[data-player="${squad.vice}"]`) as HTMLElement;
    expect(within(cap).getByLabelText("Captain")).toHaveTextContent("C");
    expect(within(vice).getByLabelText("Vice-captain")).toHaveTextContent("V");
    expect(screen.getAllByLabelText("Captain")).toHaveLength(1);
  });

  it("falls back to a club-tinted silhouette when a photo fails", () => {
    renderWithProviders(<Pitch players={squad.players} />);
    const first = squad.players[0];
    const img = screen.getAllByAltText(`Photo of ${first.web_name}`)[0];
    fireEvent.error(img);
    expect(screen.getByRole("img", { name: `Photo of ${first.web_name} (not available)` })).toBeInTheDocument();
  });
});
