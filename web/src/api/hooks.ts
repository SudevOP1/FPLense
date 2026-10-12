// TanStack Query hooks, one per endpoint. Solver calls (optimize, evaluate, compare, transfers)
// are queries keyed on their inputs: a request still in flight is cancelled when the inputs
// change (the AbortSignal is passed to fetch), and the previous result stays on screen meanwhile.

import { keepPreviousData, QueryClient, useMutation, useQuery } from "@tanstack/react-query";
import { ApiError, request } from "./client";
import type {
  CompareIn,
  CompareOut,
  DecodeOut,
  EncodeIn,
  EncodeOut,
  Entry,
  EntryGwOut,
  EvaluateIn,
  EvaluateOut,
  Health,
  HistoryGw,
  HistorySummary,
  Meta,
  ModelCard,
  OptimizeIn,
  PlayerDetail,
  PlayersOut,
  Squad,
  TransferIn,
  TransferOut,
} from "./types";

export const STALE_MS = 5 * 60_000;

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: STALE_MS,
        refetchOnWindowFocus: false,
        retry: (count, err) => {
          const status = err instanceof ApiError ? err.status : 0;
          if (status >= 400 && status < 500) return false;
          return count < 2;
        },
      },
    },
  });
}

export const keys = {
  health: ["health"] as const,
  meta: ["meta"] as const,
  model: ["model"] as const,
  players: (gw?: number) => ["players", gw ?? "next"] as const,
  player: (id: number) => ["player", id] as const,
  best: (gw?: number) => ["best", gw ?? "next"] as const,
  summary: ["history", "summary"] as const,
  historyGw: (gw: number) => ["history", gw] as const,
  entry: (id: number) => ["entry", id] as const,
  entryGw: (id: number, gw: number, predictGw?: number) => ["entry", id, gw, predictGw ?? null] as const,
};

export function useHealth(options: { refetchInterval?: number | false } = {}) {
  return useQuery({
    queryKey: keys.health,
    queryFn: ({ signal }) => request<Health>("/api/health", { signal }),
    staleTime: 30_000,
    retry: 8,
    retryDelay: (n) => Math.min(1000 * 2 ** n, 8000),
    ...options,
  });
}

export function useMeta() {
  return useQuery({ queryKey: keys.meta, queryFn: ({ signal }) => request<Meta>("/api/meta", { signal }) });
}

export function useModel() {
  return useQuery({ queryKey: keys.model, queryFn: ({ signal }) => request<ModelCard>("/api/model", { signal }) });
}

export function usePlayers(gw?: number) {
  return useQuery({
    queryKey: keys.players(gw),
    queryFn: ({ signal }) => request<PlayersOut>("/api/players", { signal, query: { gw } }),
    placeholderData: keepPreviousData,
  });
}

export function usePlayer(id: number | null) {
  return useQuery({
    queryKey: keys.player(id ?? 0),
    queryFn: ({ signal }) => request<PlayerDetail>(`/api/players/${id}`, { signal }),
    enabled: id != null,
  });
}

export function useBestSquad(gw?: number, enabled = true) {
  return useQuery({
    queryKey: keys.best(gw),
    queryFn: ({ signal }) => request<Squad>("/api/squads/best", { signal, query: { gw } }),
    enabled,
  });
}

export function useOptimize(body: OptimizeIn | null) {
  return useQuery({
    queryKey: ["optimize", body],
    queryFn: ({ signal }) => request<Squad>("/api/squads/optimize", { signal, body }),
    enabled: body != null,
    placeholderData: keepPreviousData,
  });
}

export function useEvaluate(body: EvaluateIn | null) {
  return useQuery({
    queryKey: ["evaluate", body],
    queryFn: ({ signal }) => request<EvaluateOut>("/api/squads/evaluate", { signal, body }),
    enabled: body != null && body.players.length > 0,
    placeholderData: keepPreviousData,
  });
}

export function useHistorySummary() {
  return useQuery({
    queryKey: keys.summary,
    queryFn: ({ signal }) => request<HistorySummary>("/api/history/summary", { signal }),
  });
}

export function useHistoryGw(gw: number | null) {
  return useQuery({
    queryKey: keys.historyGw(gw ?? 0),
    queryFn: ({ signal }) => request<HistoryGw>(`/api/history/${gw}`, { signal }),
    enabled: gw != null,
    placeholderData: keepPreviousData,
  });
}

export function useEntry(teamId: number | null) {
  return useQuery({
    queryKey: keys.entry(teamId ?? 0),
    queryFn: ({ signal }) => request<Entry>(`/api/entry/${teamId}`, { signal }),
    enabled: teamId != null,
    staleTime: 10 * 60_000,
  });
}

export function useEntryGw(teamId: number | null, gw: number | null, predictGw?: number) {
  return useQuery({
    queryKey: keys.entryGw(teamId ?? 0, gw ?? 0, predictGw),
    queryFn: ({ signal }) =>
      request<EntryGwOut>(`/api/entry/${teamId}/gw/${gw}`, { signal, query: { predict_gw: predictGw } }),
    enabled: teamId != null && gw != null,
    placeholderData: keepPreviousData,
  });
}

export function useTransferPlan(body: TransferIn | null) {
  return useQuery({
    queryKey: ["transfers", body],
    queryFn: ({ signal }) => request<TransferOut>("/api/transfers/plan", { signal, body }),
    enabled: body != null,
    placeholderData: keepPreviousData,
    staleTime: STALE_MS,
  });
}

export function useCompare(body: CompareIn | null) {
  return useQuery({
    queryKey: ["compare", body],
    queryFn: ({ signal }) => request<CompareOut>("/api/compare", { signal, body }),
    enabled: body != null && body.slots.length >= 2,
    placeholderData: keepPreviousData,
  });
}

export function useDecode() {
  return useMutation({
    mutationFn: (code: string) => request<DecodeOut>("/api/codes/decode", { body: { code } }),
  });
}

export function useEncode() {
  return useMutation({
    mutationFn: (body: EncodeIn) => request<EncodeOut>("/api/codes/encode", { body }),
  });
}

export function asApiError(err: unknown): ApiError | null {
  return err instanceof ApiError ? err : null;
}
