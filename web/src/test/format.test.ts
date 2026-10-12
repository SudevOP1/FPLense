import { describe, expect, it } from "vitest";
import { countdownParts, deadlineText, money, MINUS, points, ratingTier, relative, signed, tone, urgency } from "@/lib/format";

describe("format", () => {
  it("rating bands: 90+ elite down to under 60 poor", () => {
    expect([99, 90, 89, 80, 79, 70, 69, 60, 59, 50].map(ratingTier)).toEqual([
      "elite",
      "elite",
      "great",
      "great",
      "good",
      "good",
      "fair",
      "fair",
      "poor",
      "poor",
    ]);
  });
  it("prices are £x.xm from integer tenths", () => {
    expect(money(55)).toBe("£5.5m");
    expect(money(1000)).toBe("£100.0m");
    expect(money(0)).toBe("£0.0m");
    expect(money(-5)).toBe(`${MINUS}£0.5m`);
    expect(money(null)).toBe("–");
  });

  it("expected points 1 decimal, actual integers", () => {
    expect(points(5.241)).toBe("5.2");
    expect(points(12, "actual")).toBe("12");
    expect(points(-1, "actual")).toBe(`${MINUS}1`);
    expect(points(undefined)).toBe("–");
  });

  it("deltas always carry their sign: +2.4, −4", () => {
    expect(signed(2.44)).toBe("+2.4");
    expect(signed(-4, 0)).toBe(`${MINUS}4`);
    expect(signed(-4, 0)).toBe("−4");
    expect(signed(0)).toBe("0.0");
    expect(signed(-0.04)).toBe("0.0");
    expect(tone(2.4)).toBe("good");
    expect(tone(-4)).toBe("bad");
    expect(tone(0.01)).toBe("neutral");
  });

  it("local deadline text with a relative hint", () => {
    const now = Date.parse("2026-10-08T10:00:00Z");
    expect(deadlineText("2026-10-10T10:00:00Z", now, "UTC")).toBe("Sat 10:00 · in 2 days");
    expect(deadlineText("2026-10-10T10:00:00Z", now, "Asia/Kolkata")).toBe("Sat 15:30 · in 2 days");
    expect(relative("2026-10-08T15:00:00Z", now)).toBe("in 5 hours");
    expect(relative("2026-10-08T10:35:00Z", now)).toBe("in 35 minutes");
    expect(relative("2026-10-08T07:00:00Z", now)).toBe("3 hours ago");
    expect(relative("2026-10-09T10:00:00Z", now)).toBe("tomorrow");
  });

  it("deadline urgency: amber < 24 h, red < 1 h", () => {
    expect(urgency(2 * 86_400_000)).toBe("calm");
    expect(urgency(23 * 3_600_000)).toBe("amber");
    expect(urgency(59 * 60_000)).toBe("red");
    expect(urgency(0)).toBe("passed");
    expect(countdownParts(90_061_000)).toEqual({ d: 1, h: 1, m: 1, s: 1 });
  });
});
