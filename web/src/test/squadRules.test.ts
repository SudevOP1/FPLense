import { describe, expect, it } from "vitest";
import { emptyDraft, firstEmpty, ordered, place, swap, type Draft } from "@/lib/builder";
import type { Pos } from "@/lib/format";
import { formation, placeProblem, ruleChips, ruleProblems, xiShapeProblem, type RulePlayer } from "@/lib/squadRules";

// 2 GK, 5 DEF, 5 MID, 3 FWD from 15 different clubs, £100.0m in total
function squad(): RulePlayer[] {
  const layout: [Pos, number][] = [
    ["GK", 45], ["GK", 40],
    ["DEF", 60], ["DEF", 55], ["DEF", 50], ["DEF", 45], ["DEF", 40],
    ["MID", 120], ["MID", 90], ["MID", 75], ["MID", 60], ["MID", 50],
    ["FWD", 140], ["FWD", 80], ["FWD", 50],
  ];
  return layout.map(([pos, price], k) => ({ id: k + 1, pos, price, club: `Club ${k}`, web_name: `P${k + 1}` }));
}

describe("ruleProblems (mirrors the Python rule_problems)", () => {
  it("a legal squad has no problems", () => {
    const s = squad();
    expect(s.reduce((a, p) => a + p.price, 0)).toBe(1000);
    expect(ruleProblems(s)).toEqual([]);
  });

  it("budget: reports how far over", () => {
    const s = squad();
    s[0].price += 5;
    expect(ruleProblems(s)).toEqual([{ rule: "budget", message: "costs £100.5m: £0.5m over the £100.0m budget" }]);
    expect(ruleProblems(s, { enforceBudget: false })).toEqual([]);
  });

  it("quotas: too many of a position, and a full squad missing one", () => {
    const s = squad();
    s[2] = { ...s[2], pos: "MID" };
    const msgs = ruleProblems(s).map((p) => p.message);
    expect(msgs).toContain("6 MID: a squad holds exactly 5");
    expect(msgs).toContain("4 DEF: a squad needs exactly 5");
  });

  it("3 per club", () => {
    const s = squad().map((p, k) => (k < 4 ? { ...p, club: "Arsenal" } : p));
    expect(ruleProblems(s)).toContainEqual({ rule: "club", message: "4 players from Arsenal: max 3 per club" });
  });

  it("partial squads report the size only", () => {
    expect(ruleProblems(squad().slice(0, 5))).toEqual([{ rule: "size", message: "5 of 15 players picked" }]);
  });

  it("XI shape and armbands", () => {
    const s = squad();
    const xi = [1, 3, 4, 8, 9, 10, 11, 12, 13, 14, 15]; // 1 GK, 2 DEF: illegal
    const msgs = ruleProblems(s, { starters: xi, captain: 2, vice: 2 }).map((p) => p.message);
    expect(msgs).toContain("the XI needs at least 3 DEF");
    expect(msgs).toContain("the captain must be in the XI");
    expect(msgs).toContain("the vice-captain must be another starter");
  });
});

describe("placeProblem / chips", () => {
  it("a 4th player from one club gets the club message", () => {
    const s = squad().slice(0, 3).map((p) => ({ ...p, club: "Arsenal" }));
    const extra: RulePlayer = { id: 99, pos: "MID", club: "Arsenal", price: 50, web_name: "Saka" };
    expect(placeProblem(s, extra, "MID")).toBe("You already have 3 Arsenal players (max 3 per club).");
    // replacing one of the three is fine
    expect(placeProblem(s, { ...extra, pos: "DEF" }, "DEF", s[2].id)).toBeNull();
  });

  it("position mismatch and duplicates", () => {
    const s = squad();
    expect(placeProblem(s, s[0], "GK")).toBe("P1 is already in your squad.");
    expect(placeProblem([], { id: 50, pos: "FWD", club: "X", price: 50, web_name: "Kane" }, "DEF")).toBe("Kane is a FWD; this is a DEF slot.");
  });

  it("chips: money left, 2-5-5-3 and clubs", () => {
    const s = squad();
    const [budget, quota, club] = ruleChips(s);
    expect(budget).toMatchObject({ ok: true, label: "£0.0m left" });
    expect(quota).toMatchObject({ ok: true, label: "2-5-5-3" });
    expect(club).toMatchObject({ ok: true, label: "Max 3 per club" });
    const over = ruleChips(s.map((p) => ({ ...p, price: p.price + 1, club: "Spurs" })));
    expect(over[0]).toMatchObject({ ok: false, label: "£1.5m over" });
    expect(over[2]).toMatchObject({ ok: false, label: "15 from Spurs" });
  });

  it("XI shape and formation", () => {
    expect(xiShapeProblem(["GK", "DEF", "DEF", "MID", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD"])).toBe("The XI needs at least 3 DEF.");
    expect(xiShapeProblem(["GK", "GK", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD"])).toBe("The XI needs exactly 1 goalkeeper.");
    expect(formation(["GK", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "MID", "FWD", "FWD"])).toBe("3-5-2");
  });
});

describe("builder draft", () => {
  const all = new Map(squad().map((p) => [p.id, p]));
  function full(): Draft {
    let d = emptyDraft();
    for (const p of squad()) {
      const r = place(d, firstEmpty(d, p.pos)!, p, all);
      if (r.draft === null) throw new Error(r.error);
      d = r.draft;
    }
    return d;
  }

  it("fills 2-5-5-3 and orders the XI GK -> FWD", () => {
    const d = full();
    const o = ordered(d);
    expect(o.starters).toHaveLength(11);
    expect(o.bench).toHaveLength(4);
    expect(o.starters.map((i) => all.get(i)!.pos)).toEqual(["GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD"]);
  });

  it("swaps XI and bench only when the XI stays legal", () => {
    const d = full();
    // bench FWD in for an XI MID: 4-3-3 is legal
    const ok = swap(d, { zone: "xi", index: 5 }, { zone: "bench", index: 3 });
    expect(ok.error).toBeNull();
    // bench GK for an outfield starter: refused
    expect(swap(d, { zone: "xi", index: 1 }, { zone: "bench", index: 0 }).error).toBe("Goalkeepers can only swap with goalkeepers.");
    // 2 DEF would be illegal: move the bench DEF? first make 3 DEF by swapping out two DEF for MID/FWD
    const a = swap(d, { zone: "xi", index: 1 }, { zone: "bench", index: 2 }).draft!; // DEF out, MID in -> 3 DEF
    const b = swap(a, { zone: "xi", index: 2 }, { zone: "bench", index: 3 }); // DEF out, FWD in -> 2 DEF
    expect(b.error).toBe("The XI needs at least 3 DEF.");
  });
});
