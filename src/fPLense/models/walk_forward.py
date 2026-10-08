"""Expanding-window walk-forward validation by gameweek (PLAN.md §8 P3).

For target season 2025-26 and k = 5 … 38: train on every earlier season plus 2025-26 GWs < k,
predict GW k. Every model (B0, Ridge, LightGBM L2 / L1) sees exactly the same folds. A second view
fits once on seasons before 2024-25 and scores all of 2024-25 GW5+.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from fPLense import config
from fPLense.models import baselines, evaluate, train

log = logging.getLogger(__name__)

MODELS = ("b0", "ridge", "lgbm", "lgbm_l1")
KEEP = ["season", "gw", "element", "fixture", "name", "team", "position", "regular", "y"]


def folds(
    df: pd.DataFrame,
    target_season: str = config.TARGET_SEASON,
    gws: list[int] = config.EVAL_GWS,
    step: int = 1,
    train_from: str | None = None,
) -> Iterator[tuple[int, np.ndarray, np.ndarray]]:
    """Yield ``(k, train_mask, test_mask)``: train = strictly before (target_season, k)."""
    season, gw = df["season"].to_numpy(), df["gw"].to_numpy()
    earlier = season < target_season
    if train_from is not None:
        earlier &= season >= train_from
    in_target = season == target_season
    for k in gws[::step]:
        test = in_target & (gw == k)
        if not test.any():
            continue
        yield k, earlier | (in_target & (gw < k)), test


def predict_fold(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    models: tuple[str, ...] = MODELS,
    features: list[str] = config.FEATURES,
) -> dict[str, np.ndarray]:
    preds: dict[str, np.ndarray] = {}
    for name in models:
        if name == "b0":
            preds[name] = baselines.rolling_baseline(test_df)
        elif name == "ridge":
            preds[name] = baselines.predict_ridge(
                baselines.fit_ridge(train_df, features), test_df, features
            )
        elif name in ("lgbm", "lgbm_l1"):
            objective = "regression" if name == "lgbm" else "l1"
            model = train.fit_lgbm(train_df, features, objective=objective)
            preds[name] = train.predict_lgbm(model, test_df, features)
        else:
            raise ValueError(f"unknown model {name!r}")
    return preds


def _frame(test_df: pd.DataFrame, preds: dict[str, np.ndarray], **extra) -> pd.DataFrame:
    out = test_df[KEEP].copy()
    for name, p in preds.items():
        out[f"pred_{name}"] = p
    for key, value in extra.items():
        out[key] = value
    return out


def run_walk_forward(
    df: pd.DataFrame,
    models: tuple[str, ...] = MODELS,
    features: list[str] = config.FEATURES,
    step: int = 1,
    train_from: str | None = None,
    target_season: str = config.TARGET_SEASON,
    gws: list[int] = config.EVAL_GWS,
    checkpoint_dir: Path | None = None,
) -> pd.DataFrame:
    """Per-fixture predictions for every test GW, with the fold's training cutoff recorded.

    With ``checkpoint_dir``, each fold is saved as ``gwKK.parquet`` and reused if it already
    exists, so an interrupted run resumes where it stopped (``pipeline --evaluate --fresh``
    clears the checkpoints).
    """
    out = []
    for k, train_mask, test_mask in folds(df, target_season, gws, step, train_from):
        ckpt = checkpoint_dir / f"gw{k:02d}.parquet" if checkpoint_dir else None
        if ckpt is not None and ckpt.exists():
            out.append(pd.read_parquet(ckpt))
            log.info("%s GW%d: reused %s", target_season, k, ckpt)
            continue
        t0 = time.perf_counter()
        train_df, test_df = df[train_mask], df[test_mask]
        preds = predict_fold(train_df, test_df, models, features)
        last = train_df.loc[train.gw_order(train_df).idxmax(), ["season", "gw"]]
        fold = _frame(
            test_df, preds, train_rows=len(train_df), train_last=f"{last.season} GW{int(last.gw)}"
        )
        if ckpt is not None:
            ckpt.parent.mkdir(parents=True, exist_ok=True)
            fold.to_parquet(ckpt, index=False)
        out.append(fold)
        log.info(
            "%s GW%d: train %d rows (to %s GW%d), test %d rows, %.1fs",
            target_season,
            k,
            len(train_df),
            last.season,
            int(last.gw),
            len(test_df),
            time.perf_counter() - t0,
        )
    return pd.concat(out, ignore_index=True)


def run_holdout(
    df: pd.DataFrame,
    models: tuple[str, ...] = MODELS,
    features: list[str] = config.FEATURES,
    holdout_season: str = config.HOLDOUT_SEASON,
    min_gw: int = config.EVAL_GWS[0],
) -> pd.DataFrame:
    """One fit on seasons before ``holdout_season``; score its GW ``min_gw``+."""
    train_df = df[df["season"] < holdout_season]
    test_df = df[(df["season"] == holdout_season) & (df["gw"] >= min_gw)]
    return _frame(test_df, predict_fold(train_df, test_df, models, features))


def run_ablation(
    df: pd.DataFrame, step: int = 2, checkpoint_dir: Path | None = None
) -> dict[str, pd.DataFrame]:
    """LightGBM (L2) per feature ladder step, plus the full set trained on 2022-23+ only."""
    configs: dict[str, tuple[list[str], str | None]] = {
        name: (feats, None) for name, feats in config.ABLATION_SETS.items()
    }
    configs["iv_odds_elo_2022on"] = (config.FEATURES, config.XG_FIRST_SEASON)
    out = {}
    for name, (feats, train_from) in configs.items():
        log.info("ablation %s: %d features, train from %s", name, len(feats), train_from or "all")
        out[name] = run_walk_forward(
            df,
            models=("b0", "lgbm"),
            features=feats,
            step=step,
            train_from=train_from,
            checkpoint_dir=checkpoint_dir / f"ablation_{name}" if checkpoint_dir else None,
        )
    return out


def ablation_summary(results: dict[str, pd.DataFrame]) -> dict:
    out = {}
    for name, preds in results.items():
        s = evaluate.summarise(evaluate.to_player_gw(preds))
        reg = s["regulars"]["lgbm"]
        out[name] = {
            "regulars_mae": reg["mae"],
            "regulars_b0_mae": s["regulars"]["b0"]["mae"],
            "regulars_mae_gain_pct": reg["mae_gain_pct"],
            "regulars_mae_gain_ci95": reg["mae_gain_ci95"],
            "regulars_spearman_per_gw": reg["spearman_per_gw"],
            "all_mae": s["all"]["lgbm"]["mae"],
            "regulars_mae_by_position": {
                pos: m["lgbm"]["mae"] for pos, m in s["regulars_by_position"].items()
            },
        }
    return out


def run_evaluation(
    df: pd.DataFrame | None = None,
    step: int = 1,
    ablation_step: int | None = 2,
    eval_dir: Path = config.EVAL_DIR,
    metrics_path: Path = config.METRICS_PATH,
    img_dir: Path = config.DOCS_IMG_DIR,
    fresh: bool = False,
) -> dict:
    """Run walk-forward + holdout (+ ablation), save predictions, metrics.json and plots.

    Folds are checkpointed under ``eval_dir/folds/``; ``fresh=True`` deletes them first (do this
    after any change to features or models, or old folds would be reused).
    """
    if df is None:
        df = train.load_features()
    ckpt = eval_dir / "folds"
    if fresh and ckpt.exists():
        shutil.rmtree(ckpt)
    eval_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    wf = run_walk_forward(df, step=step, checkpoint_dir=ckpt / f"walk_forward_step{step}")
    wf.to_parquet(eval_dir / "walk_forward_2025_26.parquet", index=False)
    wf_gw = evaluate.to_player_gw(wf)
    holdout_path = eval_dir / "holdout_2024_25.parquet"
    if holdout_path.exists() and not fresh:
        holdout = pd.read_parquet(holdout_path)
        log.info("holdout: reused %s", holdout_path)
    else:
        holdout = run_holdout(df)
        holdout.to_parquet(holdout_path, index=False)

    metrics: dict = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "unit": "player-gameweek (sum of per-fixture predictions)",
        "regulars_definition": f"lagged minutes_r3 >= {config.REGULAR_MIN_MINUTES_R3}",
        "bootstrap": f"{config.BOOTSTRAP_REPS} resamples of gameweeks (block bootstrap)",
        "features": len(config.FEATURES),
        "lgbm_params": config.LGBM_PARAMS,
        "walk_forward": {
            "target_season": config.TARGET_SEASON,
            "gws": [int(g) for g in sorted(wf["gw"].unique())],
            "step": step,
            **evaluate.summarise(wf_gw),
        },
        "holdout": {
            "train": f"{config.SEASONS[0]} to the season before {config.HOLDOUT_SEASON}",
            "test": f"{config.HOLDOUT_SEASON} GW{config.EVAL_GWS[0]}+",
            **evaluate.summarise(evaluate.to_player_gw(holdout)),
        },
    }
    if ablation_step:
        abl = run_ablation(df, step=ablation_step, checkpoint_dir=ckpt / f"step{ablation_step}")
        for name, preds in abl.items():
            preds.to_parquet(eval_dir / f"ablation_{name}.parquet", index=False)
        metrics["ablation"] = {
            "step": ablation_step,
            "feature_counts": {k: len(v) for k, v in config.ABLATION_SETS.items()},
            **ablation_summary(abl),
        }
    metrics["runtime_s"] = round(time.perf_counter() - t0, 1)

    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    title = f"Walk-forward {config.TARGET_SEASON} GW{config.EVAL_GWS[0]}-{config.EVAL_GWS[-1]}"
    evaluate.plot_metrics_table(
        evaluate.metrics_table(metrics["walk_forward"]),
        img_dir / "metrics_table.png",
        title=f"{title} (per player-GW; gain vs B0 with 95% block-bootstrap CI)",
    )
    evaluate.plot_mae_by_gw(wf_gw, img_dir / "mae_by_gw.png", title=f"{title}: MAE on regulars")
    return metrics
