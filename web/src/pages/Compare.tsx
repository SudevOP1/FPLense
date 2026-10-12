import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { arrayMove, horizontalListSortingStrategy, SortableContext, sortableKeyboardCoordinates, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useId, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { asApiError, useCompare, useMeta } from "@/api/hooks";
import type { CompareOut, Meta, SlotOut } from "@/api/types";
import { Dumbbell, GroupedBars, HBars, HorizonLines } from "@/components/charts/Charts";
import { PasteCodeField } from "@/components/CodeBox/CodeBox";
import { GwSelect } from "@/components/GwPicker/GwPicker";
import { Pitch } from "@/components/Pitch/Pitch";
import { Badge, SlotBadge } from "@/components/ui/Bits";
import { Sheet } from "@/components/ui/Sheet";
import { EmptyState, ErrorState, PageHeader, Skeleton, Spinner } from "@/components/ui/States";
import { KIND_LABEL, LETTERS, MAX_SLOTS, searchFromSlots, slotLabel, slotsFromSearch, toApiSlot, type CompareKind, type CompareSlot, type Letter } from "@/lib/compareSlots";
import { money, points, POSITIONS } from "@/lib/format";
import { toPitchPlayers } from "@/lib/pitch";
import { usePlayerDrawer } from "@/lib/playerDrawer";
import { slotBorder, slotRing } from "@/lib/slotStyles";
import { load } from "@/lib/storage";
import { decode, TeamCodeError } from "@/lib/teamCode";
import { useToast } from "@/lib/toast";
import { usePasteCode } from "@/lib/usePasteCode";
import { useTitle } from "@/lib/useTitle";

type SourceKind = CompareKind | "builder";

function gwOptions(kind: CompareKind, meta: Meta | undefined): number[] {
  if (!meta) return [];
  if (kind === "hindsight" || kind === "entry") return meta.finished_gws;
  return [...new Set([...meta.archived_gws, meta.next_gw])].sort((a, b) => a - b);
}

function defaultGw(kind: CompareKind, meta: Meta | undefined): number | null {
  if (!meta) return null;
  if (kind === "code") return null;
  if (kind === "model_pick") return meta.current_gw ?? meta.next_gw;
  return meta.current_gw ?? null;
}

/** Source picker + GW picker for one slot. */
function SlotEditor({
  letter,
  slot,
  meta,
  onChange,
  onRemove,
  canRemove,
  onMove,
  index,
  count,
}: {
  letter: Letter;
  slot: CompareSlot;
  meta: Meta | undefined;
  onChange: (s: CompareSlot) => void;
  onRemove: () => void;
  canRemove: boolean;
  onMove: (dir: -1 | 1) => void;
  index: number;
  count: number;
}) {
  const sortable = useSortable({ id: letter });
  const sourceId = useId();
  const teamInput = useId();
  const [teamText, setTeamText] = useState(slot.kind === "entry" ? String(slot.value ?? "") : String(load<number | null>("teamId", null) ?? ""));
  const [codeError, setCodeError] = useState<string | null>(null);
  const style = { transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition };

  const setKind = (k: SourceKind) => {
    setCodeError(null);
    if (k === "builder") {
      const code = load<string | null>("builderCode", null);
      if (!code) {
        setCodeError("The Builder has no complete team yet: finish a 15-player squad there first.");
        return;
      }
      onChange({ kind: "code", gw: null, value: code, label: "Builder draft" });
      return;
    }
    if (k === "entry") {
      const id = Number(teamText);
      onChange({ kind: "entry", gw: defaultGw("entry", meta), value: Number.isInteger(id) && id > 0 ? id : null });
      return;
    }
    onChange({ kind: k, gw: defaultGw(k, meta), value: k === "code" ? slot.value : null });
  };
  const gws = gwOptions(slot.kind, meta);

  return (
    <div ref={sortable.setNodeRef} style={style} className={`card flex flex-col gap-3 border-t-4 p-3 ${slotBorder(letter)}`}>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="flex h-9 w-9 cursor-grab items-center justify-center rounded text-muted hover:bg-line/40"
          aria-label={`Reorder team ${letter} (drag, or use arrow keys)`}
          {...sortable.attributes}
          {...sortable.listeners}
        >
          ⠿
        </button>
        <SlotBadge letter={letter} />
        <span className="min-w-0 flex-1 truncate font-semibold">{slotLabel(slot)}</span>
        <button type="button" className="btn-ghost h-9 min-h-0 w-9 px-0" aria-label={`Move team ${letter} left`} disabled={index === 0} onClick={() => onMove(-1)}>
          ‹
        </button>
        <button type="button" className="btn-ghost h-9 min-h-0 w-9 px-0" aria-label={`Move team ${letter} right`} disabled={index === count - 1} onClick={() => onMove(1)}>
          ›
        </button>
        <button type="button" className="btn-ghost h-9 min-h-0 w-9 px-0" aria-label={`Remove team ${letter}`} disabled={!canRemove} onClick={onRemove}>
          ×
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={sourceId} className="sr-only">
          Source for team {letter}
        </label>
        <select
          id={sourceId}
          value={slot.label === "Builder draft" ? "builder" : slot.kind}
          onChange={(e) => setKind(e.target.value as SourceKind)}
          className="field min-h-[40px] w-auto py-1 text-sm"
        >
          {(["entry", "model_pick", "hindsight", "code"] as CompareKind[]).map((k) => (
            <option key={k} value={k}>
              {KIND_LABEL[k]}
            </option>
          ))}
          <option value="builder">From Builder</option>
        </select>
        {gws.length > 0 && (
          <GwSelect
            gws={gws}
            value={slot.gw}
            onChange={(gw) => onChange({ ...slot, gw })}
            label={`Gameweek for team ${letter}`}
            format={(g) => (meta && g === meta.next_gw ? `GW${g} (next)` : `GW${g}`)}
          />
        )}
      </div>
      {slot.kind === "entry" && (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const id = Number(teamText);
            if (Number.isInteger(id) && id > 0) onChange({ ...slot, value: id });
          }}
        >
          <label htmlFor={teamInput} className="sr-only">
            FPL team ID for team {letter}
          </label>
          <input id={teamInput} inputMode="numeric" placeholder="FPL team ID" value={teamText} onChange={(e) => setTeamText(e.target.value)} className="field num" />
          <button type="submit" className="btn-secondary">
            Load
          </button>
        </form>
      )}
      {slot.kind === "code" && slot.label !== "Builder draft" && (
        <PasteCodeField label={`Team code for ${letter}`} onLoad={(code) => onChange({ ...slot, value: code })} button="Use" />
      )}
      {codeError && (
        <p role="alert" className="text-sm text-bad">
          {codeError}
        </p>
      )}
    </div>
  );
}

function SlotSummary({ s }: { s: SlotOut }) {
  const finished = s.squad.actual_points != null;
  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
      <dt className="text-muted">Expected</dt>
      <dd className="num text-right font-semibold">{points(s.squad.expected_points)}</dd>
      <dt className="text-muted">Actual</dt>
      <dd className="num text-right font-semibold">{finished ? points(s.squad.actual_points, "actual") : "–"}</dd>
      <dt className="text-muted">Cost</dt>
      <dd className="num text-right font-semibold">{money(s.squad.cost)}</dd>
      <dt className="text-muted">Captain</dt>
      <dd className="num text-right font-semibold">
        {finished ? points(s.captain_actual, "actual") : points(s.captain_expected)}
      </dd>
      <dt className="text-muted">Bench</dt>
      <dd className="num text-right font-semibold">{finished ? points(s.bench_actual, "actual") : points(s.bench_expected)}</dd>
    </dl>
  );
}

function Results({ data }: { data: CompareOut }) {
  const drawer = usePlayerDrawer();
  const sharedBy = new Map(data.shared.map((s) => [s.id, s.slots]));
  const allFinished = data.slots.every((s) => s.squad.actual_points != null);
  return (
    <div className="flex flex-col gap-5">
      <div className="-mx-4 flex snap-x snap-mandatory gap-4 overflow-x-auto px-4 pb-2 lg:mx-0 lg:grid lg:snap-none lg:overflow-visible lg:px-0" style={{ gridTemplateColumns: `repeat(${data.slots.length}, minmax(0, 1fr))` }}>
        {data.slots.map((s) => {
          const diffs = new Set(s.differentials);
          return (
            <section
              key={s.letter}
              aria-label={`Team ${s.letter}: ${s.squad.label}`}
              className="flex w-[88vw] max-w-[440px] shrink-0 snap-center flex-col gap-3 lg:w-auto lg:max-w-none"
            >
              <div className="flex items-center gap-2">
                <SlotBadge letter={s.letter} />
                <h2 className="truncate font-semibold">{s.squad.label}</h2>
                {s.squad.source === "backfill" && <Badge tone="warn">Backfilled</Badge>}
              </div>
              <div className="card p-3">
                <SlotSummary s={s} />
              </div>
              <Pitch
                players={toPitchPlayers(s.squad)}
                mode={s.squad.actual_points != null ? "actual" : "expected"}
                label={`Team ${s.letter}`}
                layoutPrefix={`cmp-${s.letter}`}
                extras={(p) => {
                  const shared = sharedBy.get(p.id);
                  return {
                    onClick: () => drawer.open(p.id),
                    ring: shared ? "ring-accent" : undefined,
                    badge: diffs.has(p.id) ? <Badge tone="neutral">DIFF</Badge> : undefined,
                  };
                }}
              />
            </section>
          );
        })}
      </div>
      <p className="text-sm text-muted">
        <span className="mr-1 inline-block h-3 w-3 rounded-sm ring-2 ring-accent" aria-hidden /> Coral ring: player in more than one team (
        {data.shared.length} shared). DIFF: only in that team.
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        <GroupedBars
          title={`${allFinished ? "Actual" : "Expected"} points by position (starting XI)`}
          categories={[...POSITIONS]}
          slots={data.slots.map((s) => ({
            letter: s.letter,
            values: POSITIONS.map((pos) => {
              const row = s.by_position.find((b) => b.pos === pos);
              return row ? (allFinished ? row.actual : row.expected) : null;
            }),
          }))}
        />
        <Dumbbell rows={data.slots.map((s) => ({ letter: s.letter, expected: s.squad.expected_points, actual: s.squad.actual_points }))} />
        {data.horizon.length > 1 && (
          <HorizonLines gws={data.horizon.map((h) => h.gw)} slots={data.slots.map((s, k) => ({ letter: s.letter, values: data.horizon.map((h) => h.points[k] ?? null) }))} />
        )}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {data.slots.map((s) => {
          const xi = s.squad.players.filter((p) => p.starter);
          const value = (p: (typeof xi)[number]) => ((allFinished ? p.actual : p.expected) ?? 0) * (p.captain ? 2 : 1);
          return (
            <HBars
              key={s.letter}
              title={`Team ${s.letter}: points per player`}
              summary={`Team ${s.letter} ${allFinished ? "actual" : "expected"} points per starter, captain doubled.`}
              rows={[...xi].sort((a, b) => value(b) - value(a)).map((p) => ({ label: `${p.web_name}${p.captain ? " (C)" : ""}`, value: value(p) }))}
              valueLabel="Points"
            />
          );
        })}
      </div>
    </div>
  );
}

export default function Compare() {
  useTitle("Compare");
  const meta = useMeta();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [pasted, setPasted] = useState<string | null>(null);
  const fromUrl = slotsFromSearch(params);
  const slots: CompareSlot[] = useMemo(() => {
    if (fromUrl.length >= 1) return fromUrl;
    const done = meta.data?.current_gw;
    if (!meta.data || !done) return [];
    return [
      { kind: "model_pick", gw: done, value: null },
      { kind: "hindsight", gw: done, value: null },
    ];
    // the URL string is the real dependency
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.toString(), meta.data]);

  const write = (next: CompareSlot[]) => setParams(searchFromSlots(next), { replace: true });
  const ready = slots.filter((s) => (s.kind === "entry" || s.kind === "code" ? s.value != null : true));
  const body = useMemo(
    () => (slots.length >= 2 && ready.length === slots.length ? { slots: slots.map(toApiSlot) } : null),
    [slots, ready.length],
  );
  const q = useCompare(body);
  const err = asApiError(q.error);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));

  const add = (slot?: CompareSlot) => {
    if (slots.length >= MAX_SLOTS) {
      toast.show(`You can compare up to ${MAX_SLOTS} teams.`, { tone: "bad" });
      return;
    }
    write([...slots, slot ?? { kind: "model_pick", gw: meta.data?.next_gw ?? null, value: null }]);
  };

  usePasteCode((code) => setPasted(code));
  const loadPasted = (index: number) => {
    if (!pasted) return;
    try {
      decode(pasted);
    } catch (e) {
      toast.show(e instanceof TeamCodeError ? e.message : "That code couldn't be read.", { tone: "bad" });
      setPasted(null);
      return;
    }
    const slot: CompareSlot = { kind: "code", gw: null, value: pasted };
    if (index >= slots.length) add(slot);
    else write(slots.map((s, k) => (k === index ? slot : s)));
    setPasted(null);
  };

  const copyAll = async () => {
    const codes = (q.data?.slots ?? []).map((s) => `${s.letter}: ${s.squad.code ?? "(no code)"}`).join("\n");
    try {
      await navigator.clipboard.writeText(codes);
      toast.show("All team codes copied", { tone: "good" });
    } catch {
      toast.show("Couldn't reach the clipboard.", { tone: "bad" });
    }
  };

  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const from = LETTERS.indexOf(e.active.id as Letter);
    const to = LETTERS.indexOf(e.over.id as Letter);
    write(arrayMove(slots, from, to));
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Compare"
        sub="Two or three teams side by side, each from its own source and gameweek. Paste a team code anywhere on this page to load it."
        actions={
          <>
            <button type="button" className="btn-secondary" onClick={() => add()} disabled={slots.length >= MAX_SLOTS} aria-disabled={slots.length >= MAX_SLOTS}>
              Add a team
            </button>
            <button type="button" className="btn-secondary" onClick={copyAll} disabled={!q.data}>
              Copy all codes
            </button>
          </>
        }
      />

      {meta.isPending && <Skeleton className="h-28" />}
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={slots.map((_, k) => LETTERS[k])} strategy={horizontalListSortingStrategy}>
          <div className="grid gap-3 md:grid-cols-3" aria-label="Teams to compare">
            {slots.map((s, k) => (
              <SlotEditor
                key={LETTERS[k]}
                letter={LETTERS[k]}
                index={k}
                count={slots.length}
                slot={s}
                meta={meta.data}
                canRemove={slots.length > 1}
                onChange={(next) => write(slots.map((x, j) => (j === k ? next : x)))}
                onRemove={() => write(slots.filter((_, j) => j !== k))}
                onMove={(d) => write(arrayMove(slots, k, k + d))}
              />
            ))}
            {slots.length < MAX_SLOTS && (
              <button type="button" onClick={() => add()} className="card flex min-h-[120px] items-center justify-center border-dashed text-sm font-semibold text-muted hover:text-ink">
                + Add team {LETTERS[slots.length]}
              </button>
            )}
          </div>
        </SortableContext>
      </DndContext>

      {slots.length < 2 && meta.data && <EmptyState title="Add one more team" body="Compare needs at least two teams. Pick a source for the next slot." />}
      {slots.length >= 2 && ready.length < slots.length && (
        <p className="text-sm text-muted">
          {slots.length - ready.length} of {slots.length} teams still need a team ID or code; the others will show once every slot is filled.
        </p>
      )}
      {q.isFetching && (
        <p className="flex items-center gap-2 text-sm text-muted" aria-live="polite">
          <Spinner label="Comparing" /> Comparing…
        </p>
      )}
      {q.isError && (
        <ErrorState title={err?.status === 422 ? "One of these teams can't be loaded" : "Compare didn't load"} error={q.error} onRetry={() => q.refetch()} />
      )}
      {q.isPending && body && <Skeleton className="h-[520px] rounded-xl" />}
      {q.data && <Results data={q.data} />}

      <Sheet open={pasted != null} onClose={() => setPasted(null)} title="Load the pasted team?" side="center">
        <div className="flex flex-col gap-3">
          <p className="num break-all text-xs text-muted">{pasted}</p>
          <div className="flex flex-wrap gap-2">
            {slots.map((_, k) => (
              <button key={k} type="button" className={`btn-secondary ring-2 ${slotRing(LETTERS[k])}`} onClick={() => loadPasted(k)}>
                Load into slot {LETTERS[k]}
              </button>
            ))}
            {slots.length < MAX_SLOTS && (
              <button type="button" className="btn-primary" onClick={() => loadPasted(slots.length)}>
                Load this team into slot {LETTERS[slots.length]}?
              </button>
            )}
          </div>
        </div>
      </Sheet>
    </div>
  );
}
