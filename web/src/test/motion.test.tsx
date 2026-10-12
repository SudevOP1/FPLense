import { act, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import type { Squad } from "@/api/types";
import { Pitch } from "@/components/Pitch/Pitch";
import { AnimatedNumber, Confetti } from "@/components/ui/Motion";
import { fixtures } from "./handlers";
import { renderRoute, renderWithProviders } from "./render";
import { media } from "./setup";

const squad = fixtures.squadBest as unknown as Squad;

describe("reduced motion", () => {
  it("count-ups jump straight to the final value", () => {
    media.reducedMotion = true;
    const { container } = renderWithProviders(<Counter />);
    expect(container.querySelector(".num")!.textContent).toBe("0.0");
    act(() => screen.getByRole("button", { name: "bump" }).click());
    expect(container.querySelector(".num")!.textContent).toBe("100.0");
  });

  it("numbers count when motion is allowed (the value isn't final on the same frame)", async () => {
    media.reducedMotion = false;
    const { container } = renderWithProviders(<Counter />);
    const btn = screen.getByRole("button", { name: "bump" });
    act(() => btn.click());
    expect(container.querySelector(".num")!.textContent).not.toBe("100.0");
    await screen.findByText("100.0", undefined, { timeout: 2000 });
  });

  it("no confetti with reduced motion, a single burst without", () => {
    media.reducedMotion = true;
    renderWithProviders(<Confetti event="test" fire />);
    expect(screen.queryByTestId("confetti")).toBeNull();
    media.reducedMotion = false;
    sessionStorage.clear();
    renderWithProviders(<Confetti event="test2" fire />);
    expect(screen.getByTestId("confetti")).toBeInTheDocument();
  });

  it("confetti fires at most once per session per event", () => {
    renderWithProviders(<Confetti event="once" fire />);
    expect(screen.getAllByTestId("confetti")).toHaveLength(1);
    renderWithProviders(<Confetti event="once" fire />);
    expect(screen.getAllByTestId("confetti")).toHaveLength(1);
  });

  it("pitch cards render in their final state immediately", () => {
    media.reducedMotion = true;
    const { container } = renderWithProviders(<Pitch players={squad.players} />);
    const items = container.querySelectorAll("li");
    expect(items.length).toBeGreaterThanOrEqual(15);
    for (const li of items) {
      const style = (li as HTMLElement).style;
      expect(style.opacity === "" || style.opacity === "1").toBe(true);
      expect(style.transform === "" || style.transform === "none").toBe(true);
    }
  });

  it("the in-app toggle turns motion off too", async () => {
    const { user } = renderRoute("/model");
    await user.click(await screen.findByRole("button", { name: "Settings" }));
    await user.click(screen.getByRole("checkbox", { name: /Reduce motion/ }));
    expect(document.documentElement.classList.contains("reduce-motion")).toBe(true);
    expect(localStorage.getItem("fplense:reduceMotion")).toBe("true");
  });
});

function Counter() {
  const [v, setV] = useState(0);
  return (
    <>
      <AnimatedNumber value={v} />
      <button type="button" onClick={() => setV(100)}>
        bump
      </button>
    </>
  );
}
