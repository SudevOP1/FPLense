import { DndContext, DragOverlay, MouseSensor, TouchSensor, useDraggable, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from "@dnd-kit/core";
import { LayoutGroup } from "framer-motion";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { request } from "@/api/client";
import { useDecode, useEvaluate, useMeta, usePlayers } from "@/api/hooks";
import type { Entry, EntryGwOut, EvaluateIn, Player, Squad } from "@/api/types";
import { CodeBox, PasteCodeField } from "@/components/CodeBox/CodeBox";
import { CARD_WIDTH, PitchFrame, PitchRow } from "@/components/Pitch/Pitch";
import { PlayerPhoto } from "@/components/PlayerCard/PlayerPhoto";
import { TeamSlot } from "@/components/TeamSlot/TeamSlot";
import { AnimatedNumber } from "@/components/ui/Motion";
import { RuleChips } from "@/components/ui/RuleChips";
import { Sheet } from "@/components/ui/Sheet";
import { ErrorState, PageHeader, Skeleton, Spinner } from "@/components/ui/States";
import {
  commit,
  emptyDraft,
  firstEmpty,
  fromSquad,
  getSlot,
  isComplete,
  ordered,
  parseSlotKey,
  pickedIds,
  place,
  redo,
  removeAt,
  setArmband,
  slotKey,
  swap,
  undo,
  type Draft,
  type History,
  type Result,
  type SlotRef,
} from "@/lib/builder";
import { useCompareTray } from "@/lib/compareTray";
import { errorMessage } from "@/lib/errors";
import { money, points, POS_LABEL, POSITIONS, type Pos } from "@/lib/format";
import { usePlayerDrawer } from "@/lib/playerDrawer";
import { ruleChips, type RulePlayer } from "@/lib/squadRules";
import { load, remove, save } from "@/lib/storage";
import { encode } from "@/lib/teamCode";
import { useToast } from "@/lib/toast";
import { usePasteCode } from "@/lib/usePasteCode";
import { useTitle } from "@/lib/useTitle";

type SortKey = "p" | "value" | "rating" | "price";
const PAGE = 40;

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

function ListRow({ p, picked, onPick, disabledReason }: { p: Player; picked: boolean; onPick: () => void; disabledReason: string | null }) {
  const drag = useDraggable({ id: `player:${p.id}`, disabled: picked });
  return (
    <li ref={drag.setNodeRef} {...drag.listeners} className={drag.isDragging ? "opacity-40" : ""}>
      <button
        type="button"
        onClick={onPick}
        disabled={picked}
        title={picked ? `${p.web_name} is already in your squad` : (disabledReason ?? `Add ${p.name}`)}
        className="flex min-h-[52px] w-full items-center gap-2 rounded px-2 text-left text-sm hover:bg-line/40 disabled:opacity-40"
      >
        <PlayerPhoto src={p.photo_url} name={p.name} className="w-7 shrink-0 rounded-sm" />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold">{p.web_name}</span>
          <span className="text-xs text-muted">
            {p.pos} · {p.club_short}
            {p.status !== "a" && <span className="text-warn"> · {p.news || "flagged"}</span>}
          </span>
        </span>
        <span className="num w-12 text-right text-muted">{money(p.price)}</span>
        <span className="num w-10 text-right font-semibold">{points(p.p)}</span>
      </button>
    </li>
  );
}

export default function Builder() {
  useTitle("Builder");
  const [params, setParams] = useSearchParams();
  const meta = useMeta();
  const players = usePlayers();
  const decodeCode = useDecode();
  const toast = useToast();
  const tray = useCompareTray();
  const drawer = usePlayerDrawer();
  const [hist, setHist] = useState<History>(() => ({ past: [], present: load<Draft | null>("builderDraft", null) ?? emptyDraft(), future: [] }));
  const draft = hist.present;
  const [selected, setSelected] = useState<SlotRef | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [teamText, setTeamText] = useState(String(load<number | null>("teamId", null) ?? ""));
  const [filters, setFilters] = useState<{ q: string; pos: Pos | "ALL"; club: string; max: number; sort: SortKey }>({ q: "", pos: "ALL", club: "", max: 150, sort: "p" });
  const [shown, setShown] = useState(PAGE);
  const ids = { q: useId(), pos: useId(), club: useId(), max: useId(), sort: useId(), team: useId() };

  const all = useMemo(() => new Map((players.data?.players ?? []).map((p) => [p.id, p])), [players.data]);
  const rulePlayers = useMemo(() => new Map<number, RulePlayer>([...all].map(([id, p]) => [id, { id, pos: p.pos, club: p.club, price: p.price, web_name: p.web_name }])), [all]);
  const squad = pickedIds(draft).map((id) => rulePlayers.get(id)).filter((p): p is RulePlayer => !!p);
  const chips = ruleChips(squad);

  const apply = useCallback((r: Result, ok?: string) => {
    if (r.error != null) {
      setMessage(r.error);
      return false;
    }
    setMessage(ok ?? null);
    setHist((h) => commit(h, r.draft));
    return true;
  }, []);

  // persist the draft, and its code once complete (Compare's "From Builder")
  useEffect(() => {
    save("builderDraft", draft);
    if (isComplete(draft)) {
      const o = ordered(draft);
      try {
        save("builderCode", encode(o.starters, o.bench, draft.captain!, draft.vice!));
      } catch {
        remove("builderCode");
      }
    } else remove("builderCode");
  }, [draft]);

  const code = useMemo(() => {
    if (!isComplete(draft)) return null;
    const o = ordered(draft);
    try {
      return encode(o.starters, o.bench, draft.captain!, draft.vice!);
    } catch {
      return null;
    }
  }, [draft]);

  const loadSquad = useCallback(
    (s: Pick<Squad, "players" | "starters" | "bench" | "captain" | "vice">, label: string) => {
      setHist((h) => commit(h, fromSquad(s)));
      setSelected(null);
      setMessage(null);
      toast.show(`${label} loaded`, { tone: "good" });
    },
    [toast],
  );

  const loadCode = useCallback(
    (text: string) => {
      decodeCode.mutate(text, {
        onSuccess: (out) => loadSquad(out.squad, "Team code"),
        onError: (e) => setMessage(errorMessage(e)),
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [loadSquad],
  );

  // ?t=<code> loads a shared team; ?add=<id> drops a player into the first matching slot
  const handled = useRef<string | null>(null);
  useEffect(() => {
    const t = params.get("t");
    const add = Number(params.get("add"));
    const key = params.toString();
    if (handled.current === key) return;
    if (t) {
      handled.current = key;
      loadCode(t);
    } else if (add && rulePlayers.has(add)) {
      handled.current = key;
      const p = rulePlayers.get(add)!;
      const slot = firstEmpty(hist.present, p.pos);
      if (slot) apply(place(hist.present, slot, p, rulePlayers), `${p.web_name} added.`);
      else setMessage(`No empty ${p.pos} slot: remove someone first.`);
      setParams({}, { replace: true });
    }
  }, [params, rulePlayers, loadCode, apply, hist.present, setParams]);

  const [pasted, setPasted] = useState<string | null>(null);
  usePasteCode(setPasted);

  // undo / redo shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z") return;
      if ((e.target as HTMLElement | null)?.closest("input, textarea")) return;
      e.preventDefault();
      setHist((h) => (e.shiftKey ? redo(h) : undo(h)));
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const tapSlot = (r: SlotRef) => {
    if (selected && (selected.zone !== r.zone || selected.index !== r.index)) {
      const a = getSlot(draft, selected);
      const b = getSlot(draft, r);
      if (a.id != null || b.id != null) {
        apply(swap(draft, selected, r), "Swapped.");
        setSelected(null);
        return;
      }
    }
    setSelected(selected && selected.zone === r.zone && selected.index === r.index ? null : r);
    if (!getSlot(draft, r).id) setFilters((f) => ({ ...f, pos: getSlot(draft, r).pos }));
  };

  const pickPlayer = (p: Player) => {
    const rp = rulePlayers.get(p.id)!;
    const target = selected && getSlot(draft, selected).pos === p.pos ? selected : firstEmpty(draft, p.pos);
    if (!target) {
      setMessage(selected ? `${p.web_name} is a ${p.pos}; the selected slot is a ${getSlot(draft, selected).pos} slot.` : `No empty ${p.pos} slot: tap a ${p.pos} to replace them.`);
      return;
    }
    if (apply(place(draft, target, rp, rulePlayers), `${p.web_name} added.`)) setSelected(null);
  };

  const evalBody = useDebounced<EvaluateIn | null>(
    useMemo(() => {
      const picked = pickedIds(draft);
      if (!picked.length) return null;
      const o = ordered(draft);
      return {
        players: picked,
        starters: picked.length === 15 ? o.starters : null,
        captain: picked.length === 15 ? draft.captain : null,
        vice: picked.length === 15 ? draft.vice : null,
      };
    }, [draft]),
    400,
  );
  const evaluated = useEvaluate(evalBody);
  const localExpected = draft.xi.reduce((a, s) => a + (s.id != null ? (all.get(s.id)?.p ?? 0) : 0), 0) + (draft.captain != null ? (all.get(draft.captain)?.p ?? 0) : 0);

  const autoComplete = async () => {
    const locked = pickedIds(draft);
    setBusy("auto");
    try {
      const out = await request<Squad>("/api/squads/optimize", { body: { locked } });
      loadSquad(out, "Auto-complete");
    } catch (e) {
      setMessage(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const importTeam = async () => {
    const id = Number(teamText);
    if (!Number.isInteger(id) || id <= 0) {
      setMessage("A team ID is a whole number, like 1234567.");
      return;
    }
    setBusy("import");
    try {
      const entry = await request<Entry>(`/api/entry/${id}`);
      if (!entry.current_event) throw new Error("That team hasn't played a gameweek yet.");
      const gw = await request<EntryGwOut>(`/api/entry/${id}/gw/${entry.current_event}`);
      loadSquad(gw.squad, entry.team_name);
      save("teamId", id);
      setImportOpen(false);
    } catch (e) {
      setMessage(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const sensors = useSensors(useSensor(MouseSensor, { activationConstraint: { distance: 6 } }), useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 6 } }));
  const onDragStart = (e: DragStartEvent) => setDragging(String(e.active.id));
  const onDragEnd = (e: DragEndEvent) => {
    setDragging(null);
    const over = e.over ? parseSlotKey(String(e.over.id)) : null;
    if (!over) return;
    const id = String(e.active.id);
    if (id.startsWith("player:")) {
      const p = rulePlayers.get(Number(id.slice(7)));
      if (p) apply(place(draft, over, p, rulePlayers), `${p.web_name} added.`);
    } else if (id.startsWith("slot:")) {
      const from = parseSlotKey(id.slice(5));
      if (from) apply(swap(draft, from, over), "Swapped.");
    }
  };

  const clubs = useMemo(() => [...new Set((players.data?.players ?? []).map((p) => p.club))].sort(), [players.data]);
  const list = useMemo(() => {
    const q = filters.q.trim().toLowerCase();
    const rows = (players.data?.players ?? []).filter(
      (p) =>
        (filters.pos === "ALL" || p.pos === filters.pos) &&
        (!filters.club || p.club === filters.club) &&
        p.price <= filters.max * 1 &&
        (!q || `${p.name} ${p.web_name}`.toLowerCase().includes(q)),
    );
    const key: Record<SortKey, (p: Player) => number> = { p: (p) => p.p, value: (p) => p.P_h / p.price, rating: (p) => p.rating, price: (p) => p.price };
    return rows.sort((a, b) => key[filters.sort](b) - key[filters.sort](a));
  }, [players.data, filters]);
  const pickedSet = new Set(pickedIds(draft));

  const cardFor = (id: number | null) => {
    if (id == null) return null;
    const p = all.get(id);
    if (!p) return null;
    return { ...p, expected: p.p, captain: draft.captain === id, vice: draft.vice === id };
  };
  const menuFor = (r: SlotRef, id: number) => {
    const inXi = r.zone === "xi";
    return [
      { label: "Make captain", onSelect: () => apply(setArmband(draft, id, "captain")), disabled: !inXi },
      { label: "Make vice-captain", onSelect: () => apply(setArmband(draft, id, "vice")), disabled: !inXi },
      { label: "Player details", onSelect: () => drawer.open(id) },
      { label: "Remove", onSelect: () => apply({ draft: removeAt(draft, r), error: null }) },
    ];
  };
  const isSel = (r: SlotRef) => selected?.zone === r.zone && selected.index === r.index;
  const rows = POSITIONS.map((pos) => ({
    pos,
    slots: draft.xi.map((s, index) => ({ s, ref: { zone: "xi" as const, index } })).filter(({ s }) => s.pos === pos),
  }));

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Builder"
        sub="Drag a player onto a slot, or tap a slot and then a player. Tap two slots to swap. Ctrl+Z undoes."
        actions={
          <>
            <button type="button" className="btn-secondary" onClick={() => setHist((h) => undo(h))} disabled={!hist.past.length} title="Undo (Ctrl+Z)">
              Undo
            </button>
            <button type="button" className="btn-secondary" onClick={() => setHist((h) => redo(h))} disabled={!hist.future.length} title="Redo (Ctrl+Shift+Z)">
              Redo
            </button>
            <button type="button" className="btn-primary" onClick={autoComplete} disabled={busy != null || pickedIds(draft).length === 15}>
              {busy === "auto" && <Spinner label="Auto-completing" />} Auto-complete
            </button>
          </>
        }
      />

      {/* sticky summary on phones: the rules and points stay visible while scrolling the list */}
      <div className="sticky top-14 z-20 -mx-4 flex flex-wrap items-start justify-between gap-3 border-b border-line bg-bg/95 px-4 py-2 backdrop-blur md:static md:mx-0 md:border-0 md:bg-transparent md:p-0 md:backdrop-blur-none">
        <RuleChips chips={chips} message={message} />
        <div className="card flex items-center gap-4 px-4 py-2">
          <span className="text-sm text-muted">Expected GW{meta.data?.next_gw ?? ""}</span>
          <AnimatedNumber value={evaluated.data && !evaluated.isPlaceholderData ? (evaluated.data.expected_points ?? localExpected) : localExpected} className="text-2xl font-bold" />
          {evaluated.isFetching && <Spinner label="Checking with the server" />}
        </div>
      </div>
      {evaluated.data && evaluated.data.problems.length > 0 && pickedIds(draft).length === 15 && (
        <ul className="text-sm text-bad" aria-label="Server rule check">
          {evaluated.data.problems.map((p) => (
            <li key={p.message}>• {p.message}</li>
          ))}
        </ul>
      )}

      <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => setDragging(null)}>
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <div className="mx-auto flex w-full max-w-[680px] flex-col gap-2">
            <LayoutGroup id="builder">
              <PitchFrame label="Your draft">
                {rows.map((row) => (
                  <PitchRow key={row.pos} label={POS_LABEL[row.pos]} testId={`row-${row.pos}`}>
                    {row.slots.map(({ s, ref }) => (
                      <li key={slotKey(ref)} className={CARD_WIDTH}>
                        <TeamSlot slotKey={slotKey(ref)} pos={s.pos} player={cardFor(s.id)} selected={isSel(ref)} onTap={() => tapSlot(ref)} menu={s.id != null ? menuFor(ref, s.id) : undefined} />
                      </li>
                    ))}
                  </PitchRow>
                ))}
              </PitchFrame>
              <div className="rounded-xl border border-line bg-raised px-2 py-2">
                <p className="label mb-1 px-1">Bench (in order)</p>
                <ol aria-label="Bench" className="flex items-start justify-center gap-1.5 sm:gap-2">
                  {draft.bench.map((s, index) => {
                    const ref = { zone: "bench" as const, index };
                    return (
                      <li key={slotKey(ref)} className={CARD_WIDTH}>
                        <TeamSlot
                          slotKey={slotKey(ref)}
                          pos={s.pos}
                          player={cardFor(s.id)}
                          selected={isSel(ref)}
                          onTap={() => tapSlot(ref)}
                          menu={s.id != null ? menuFor(ref, s.id) : undefined}
                          benchLabel={s.pos === "GK" ? "GK" : String(index + (draft.bench[0].pos === "GK" ? 0 : 1))}
                        />
                      </li>
                    );
                  })}
                </ol>
              </div>
            </LayoutGroup>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn-secondary" onClick={() => setImportOpen(true)}>
                Import My Team
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => {
                  setHist((h) => commit(h, emptyDraft()));
                  setSelected(null);
                  setMessage("Draft cleared. Undo brings it back.");
                }}
              >
                Reset
              </button>
              {code && (
                <button type="button" className="btn-secondary" onClick={() => tray.add({ kind: "code", gw: null, value: code, label: "Builder draft" })}>
                  Add to compare
                </button>
              )}
            </div>
            {code ? (
              <CodeBox code={code} route="/builder" />
            ) : (
              <p className="text-sm text-muted">
                {pickedIds(draft).length < 15 ? "Fill all 15 slots" : "Pick a captain and vice-captain (⋯ menu on a starter)"} to get a shareable team code.
              </p>
            )}
            <div className="card p-3">
              <PasteCodeField onLoad={loadCode} busy={decodeCode.isPending} serverError={decodeCode.isError ? errorMessage(decodeCode.error) : null} />
            </div>
          </div>

          <section aria-labelledby="pl" className="card flex min-h-0 flex-col gap-3 p-3">
            <h2 id="pl" className="font-semibold">
              Players {selected && <span className="text-sm font-normal text-muted">· picking for the {getSlot(draft, selected).pos} slot</span>}
            </h2>
            <div className="grid grid-cols-2 gap-2">
              <div className="col-span-2 flex flex-col gap-1">
                <label htmlFor={ids.q} className="label">
                  Search
                </label>
                <input id={ids.q} type="search" className="field" placeholder="Name…" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor={ids.pos} className="label">
                  Position
                </label>
                <select id={ids.pos} className="field" value={filters.pos} onChange={(e) => setFilters({ ...filters, pos: e.target.value as Pos | "ALL" })}>
                  <option value="ALL">All</option>
                  {POSITIONS.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor={ids.club} className="label">
                  Club
                </label>
                <select id={ids.club} className="field" value={filters.club} onChange={(e) => setFilters({ ...filters, club: e.target.value })}>
                  <option value="">All clubs</option>
                  {clubs.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor={ids.max} className="label">
                  Max price {money(filters.max)}
                </label>
                <input id={ids.max} type="range" min={40} max={150} step={5} value={filters.max} onChange={(e) => setFilters({ ...filters, max: Number(e.target.value) })} className="accent-[rgb(var(--accent))]" />
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor={ids.sort} className="label">
                  Sort by
                </label>
                <select id={ids.sort} className="field" value={filters.sort} onChange={(e) => setFilters({ ...filters, sort: e.target.value as SortKey })}>
                  <option value="p">Expected points</option>
                  <option value="value">Value (P_h per £)</option>
                  <option value="rating">Rating</option>
                  <option value="price">Price</option>
                </select>
              </div>
            </div>
            {players.isPending && <Skeleton className="h-80" />}
            {players.isError && <ErrorState error={players.error} onRetry={() => players.refetch()} />}
            <ul aria-label="Player list" className="max-h-[640px] overflow-y-auto">
              {list.slice(0, shown).map((p) => (
                <ListRow key={p.id} p={p} picked={pickedSet.has(p.id)} onPick={() => pickPlayer(p)} disabledReason={null} />
              ))}
            </ul>
            {list.length > shown && (
              <button type="button" className="btn-ghost" onClick={() => setShown((n) => n + PAGE)}>
                Show more ({list.length - shown} left)
              </button>
            )}
            {players.data && list.length === 0 && <p className="text-sm text-muted">No players match these filters.</p>}
          </section>
        </div>
        <DragOverlay>
          {dragging?.startsWith("player:") && all.get(Number(dragging.slice(7))) ? (
            <div className="card px-3 py-2 text-sm font-semibold shadow-lg">{all.get(Number(dragging.slice(7)))!.web_name}</div>
          ) : null}
        </DragOverlay>
      </DndContext>

      <Sheet open={pasted != null} onClose={() => setPasted(null)} title="Load the pasted team?" side="center">
        <div className="flex flex-col gap-3">
          <p className="num break-all text-xs text-muted">{pasted}</p>
          <p className="text-sm">It replaces your draft; Undo brings the draft back.</p>
          <button
            type="button"
            className="btn-primary"
            onClick={() => {
              if (pasted) loadCode(pasted);
              setPasted(null);
            }}
          >
            Load into the Builder
          </button>
        </div>
      </Sheet>

      <Sheet open={importOpen} onClose={() => setImportOpen(false)} title="Import My Team" side="center">
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            void importTeam();
          }}
        >
          <label htmlFor={ids.team} className="label">
            FPL team ID
          </label>
          <input id={ids.team} inputMode="numeric" className="field num" value={teamText} onChange={(e) => setTeamText(e.target.value)} />
          <button type="submit" className="btn-primary" disabled={busy === "import"}>
            {busy === "import" && <Spinner label="Importing" />} Import
          </button>
          {message && <p className="text-sm text-bad">{message}</p>}
        </form>
      </Sheet>
    </div>
  );
}
