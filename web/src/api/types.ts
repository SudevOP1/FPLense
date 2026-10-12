// Types generated from web/openapi.json (npm run gen:types -> schema.d.ts), plus the Model Card
// payload, which /api/model returns as free-form JSON.

import type { components } from "./schema";

type S = components["schemas"];

export type Health = S["Health"];
export type Meta = S["Meta"];
export type Headline = S["Headline"];
export type Player = S["Player"];
export type PlayersOut = S["PlayersOut"];
export type PlayerDetail = S["PlayerDetail"];
export type ShapItem = S["ShapItem"];
export type FixtureTick = S["FixtureTick"];
export type GwPoints = S["GwPoints"];
export type SquadPlayer = S["SquadPlayer"];
export type Squad = S["Squad"];
export type Problem = S["Problem"];
export type OptimizeIn = S["OptimizeIn"];
export type EvaluateIn = S["EvaluateIn"];
export type EvaluateOut = S["EvaluateOut"];
export type SummaryRow = S["SummaryRow"];
export type HistorySummary = S["HistorySummary"];
export type HistoryGw = S["HistoryGw"];
export type Entry = S["Entry"];
export type EntryGw = S["EntryGw"];
export type EntryGwOut = S["EntryGwOut"];
export type TransferIn = S["TransferIn"];
export type TransferOut = S["TransferOut"];
export type TransferOption = S["TransferOptionOut"];
export type PathStep = S["PathStepOut"];
export type Move = S["Move"];
export type Slot = S["Slot"];
export type SlotKind = Slot["kind"];
export type CompareIn = S["CompareIn"];
export type CompareOut = S["CompareOut"];
export type SlotOut = S["SlotOut"];
export type DecodeOut = S["DecodeOut"];
export type EncodeIn = S["EncodeIn"];
export type EncodeOut = S["EncodeOut"];

export interface ModelStats {
  n: number;
  mae: number;
  rmse?: number;
  spearman_per_gw?: number;
  top20_precision_per_gw?: number;
  mae_gain_pct?: number;
  mae_gain_ci95?: [number, number];
}

export interface ModelCard {
  headline: Headline | null;
  metrics: {
    generated_at?: string;
    regulars_definition?: string;
    bootstrap?: string;
    features?: number;
    walk_forward?: {
      target_season: string;
      gws: number[];
      n_gameweeks: number;
      all: Record<string, ModelStats>;
      regulars: Record<string, ModelStats>;
    };
    holdout?: { test: string; regulars?: Record<string, ModelStats> };
    ablation?: Record<string, unknown>;
  } | null;
  mae_by_gw: {
    season: string;
    subset: string;
    models: Record<string, { gw: number[]; mae: number[] }>;
  } | null;
  shap_importance: {
    base_value: number;
    mean_abs_shap: Record<string, number>;
    sample_rows?: number;
  } | null;
  backtest: {
    season: string;
    gws: number[];
    rules: string;
    strategies: Record<string, string>;
    total_points: Record<string, number>;
    per_gw_points: Record<string, number[]>;
    a_minus_b?: number;
    a_minus_b_ci95?: [number, number];
    a_beats_b_gws?: number;
  } | null;
}
