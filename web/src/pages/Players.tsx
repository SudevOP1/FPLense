import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { usePlayers } from "@/api/hooks";
import type { Player } from "@/api/types";
import { PlayerPhoto } from "@/components/PlayerCard/PlayerPhoto";
import { FdrChip } from "@/components/PlayerDrawer/PlayerDrawer";
import { GLOSSARY, InfoTip } from "@/components/ui/Bits";
import { ErrorState, PageHeader, Skeleton } from "@/components/ui/States";
import { money, pct, points, POSITIONS, type Pos } from "@/lib/format";
import { usePlayerDrawer } from "@/lib/playerDrawer";
import { useTitle } from "@/lib/useTitle";

type Col = "name" | "rating" | "price" | "pos" | "club" | "availability" | "p" | "P_h";
const PAGE = 60;

const VALUE: Record<Col, (p: Player) => number | string> = {
  name: (p) => p.web_name.toLowerCase(),
  rating: (p) => p.rating,
  price: (p) => p.price,
  pos: (p) => POSITIONS.indexOf(p.pos as Pos),
  club: (p) => p.club_short,
  availability: (p) => p.availability,
  p: (p) => p.p,
  P_h: (p) => p.P_h,
};

export default function Players() {
  useTitle("Players");
  const players = usePlayers();
  const drawer = usePlayerDrawer();
  const [params, setParams] = useSearchParams();
  const sort = (params.get("sort") as Col) || "P_h";
  const dir = params.get("dir") === "asc" ? 1 : -1;
  const pos = (params.get("pos") as Pos | null) ?? null;
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(PAGE);
  const gws = players.data?.gws ?? [];

  const rows = useMemo(() => {
    const n = q.trim().toLowerCase();
    const list = (players.data?.players ?? []).filter((p) => (!pos || p.pos === pos) && (!n || `${p.name} ${p.club}`.toLowerCase().includes(n)));
    return list.sort((a, b) => {
      const va = VALUE[sort](a);
      const vb = VALUE[sort](b);
      return (va < vb ? -1 : va > vb ? 1 : 0) * dir;
    });
  }, [players.data, q, pos, sort, dir]);

  const setSort = (c: Col) => {
    const next = new URLSearchParams(params);
    next.set("sort", c);
    next.set("dir", sort === c && dir === -1 ? "asc" : "desc");
    setParams(next, { replace: true });
  };
  const header = (c: Col, label: string, extra?: React.ReactNode) => (
    <th scope="col" aria-sort={sort === c ? (dir === 1 ? "ascending" : "descending") : "none"} className="whitespace-nowrap px-2 py-2 text-left">
      <button type="button" onClick={() => setSort(c)} className="inline-flex min-h-[36px] items-center gap-1 font-semibold text-muted hover:text-ink">
        {label}
        <span aria-hidden>{sort === c ? (dir === 1 ? "▲" : "▼") : ""}</span>
      </button>
      {extra}
    </th>
  );

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Players" sub="Every player's expected points over the next gameweeks. Tap a row for the details and the model's reasoning." />
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="label">Search</span>
          <input type="search" className="field w-56" placeholder="Name or club…" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <div role="group" aria-label="Filter by position" className="flex flex-wrap gap-1">
          {[null, ...POSITIONS].map((p) => (
            <button
              key={p ?? "all"}
              type="button"
              aria-pressed={pos === p}
              onClick={() => {
                const next = new URLSearchParams(params);
                if (p) next.set("pos", p);
                else next.delete("pos");
                setParams(next, { replace: true });
              }}
              className={`chip min-h-[36px] ${pos === p ? "border-navy bg-navy text-surface" : "border-line text-muted"}`}
            >
              {p ?? "All"}
            </button>
          ))}
        </div>
      </div>
      {players.isPending && <Skeleton className="h-[600px]" />}
      {players.isError && <ErrorState error={players.error} onRetry={() => players.refetch()} />}
      {players.data && (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <caption className="sr-only">Players sorted by {sort}</caption>
            <thead className="border-b border-line">
              <tr>
                {header("name", "Player")}
                {header("rating", "Rating")}
                {header("price", "Price")}
                {header("pos", "Pos")}
                {header("club", "Club")}
                {header("availability", "Avail.")}
                <th scope="col" className="px-2 py-2 text-left font-semibold text-muted">
                  Next 5 (FDR)
                </th>
                {gws.map((g) => (
                  <th key={g} scope="col" className="num px-2 py-2 text-right font-semibold text-muted">
                    GW{g}
                  </th>
                ))}
                {header("P_h", "P_h", <InfoTip text={GLOSSARY.P_h} label="About P_h" />)}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, shown).map((p) => (
                <tr key={p.id} className="border-b border-line/60 hover:bg-line/30">
                  <td className="px-2 py-1.5">
                    <button type="button" className="flex items-center gap-2 text-left" onClick={() => drawer.open(p.id)}>
                      <PlayerPhoto src={p.photo_url} name={p.name} className="w-7 shrink-0 rounded-sm" />
                      <span className="max-w-[10rem] truncate font-semibold" title={p.name}>
                        {p.web_name}
                      </span>
                    </button>
                  </td>
                  <td className="num px-2">{p.rating}</td>
                  <td className="num px-2">{money(p.price)}</td>
                  <td className="px-2">{p.pos}</td>
                  <td className="px-2">{p.club_short}</td>
                  <td className={`num px-2 ${p.availability < 1 ? "text-warn" : ""}`} title={p.news || undefined}>
                    {pct(p.availability)}
                  </td>
                  <td className="px-2">
                    <span className="flex gap-1">
                      {p.fixtures.slice(0, 5).map((f) => (
                        <span key={`${f.gw}-${f.kickoff}`} className="flex flex-col items-center text-[10px] leading-tight text-muted">
                          {f.opponent}
                          {f.home ? "" : "(a)"}
                          <FdrChip fdr={f.fdr} />
                        </span>
                      ))}
                    </span>
                  </td>
                  {gws.map((g) => (
                    <td key={g} className="num px-2 text-right">
                      {points(p.expected.find((e) => e.gw === g)?.points ?? 0)}
                    </td>
                  ))}
                  <td className="num px-2 text-right font-bold">{points(p.P_h)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > shown && (
            <button type="button" className="btn-ghost m-2" onClick={() => setShown((n) => n + PAGE)}>
              Show more ({rows.length - shown} left)
            </button>
          )}
          {rows.length === 0 && <p className="p-4 text-sm text-muted">No players match.</p>}
        </div>
      )}
    </div>
  );
}
