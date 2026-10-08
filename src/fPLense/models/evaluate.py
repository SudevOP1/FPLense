"""Forecast metrics (PLAN.md §8 P3): MAE, RMSE, gain vs B0 with a gameweek block-bootstrap CI,
per-GW Spearman, top-k precision, calibration deciles, breakdown by position, plus the plots.

Predictions are made per fixture and scored per **player-gameweek** (the sum over a player's
fixtures in that GW), the unit the resume claim and the optimizer use.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from fPLense import config

GW_KEYS = ["season", "gw"]


def pred_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("pred_")]


def to_player_gw(preds: pd.DataFrame) -> pd.DataFrame:
    """Sum targets and predictions over each player's fixtures in a gameweek (DGW -> 2 rows)."""
    cols = pred_columns(preds)
    agg = {"y": "sum", "position": "first", "regular": "first", "fixture": "count"}
    agg.update({c: "sum" for c in cols})
    out = preds.groupby([*GW_KEYS, "element"], as_index=False, sort=True).agg(agg)
    return out.rename(columns={"fixture": "n_fixtures"})


def mae(y, pred) -> float:
    return float(np.mean(np.abs(np.asarray(y, float) - np.asarray(pred, float))))


def rmse(y, pred) -> float:
    return float(np.sqrt(np.mean((np.asarray(y, float) - np.asarray(pred, float)) ** 2)))


def gain_pct(base_mae: float, model_mae: float) -> float:
    """MAE improvement of the model over the baseline, in percent (positive = better)."""
    return 100.0 * (base_mae - model_mae) / base_mae


def bootstrap_gain_ci(
    df: pd.DataFrame,
    model_col: str,
    base_col: str = "pred_b0",
    n_reps: int = config.BOOTSTRAP_REPS,
    seed: int = config.RANDOM_STATE,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """(point, lo, hi) MAE gain %, resampling whole gameweeks with replacement.

    Gameweeks are the blocks because errors within a GW share fixtures, weather and rotation.
    """
    y = df["y"].to_numpy(float)
    g = df.groupby(GW_KEYS, sort=True).ngroup().to_numpy()
    n_gw = g.max() + 1
    err_m = np.bincount(g, np.abs(y - df[model_col].to_numpy(float)), minlength=n_gw)
    err_b = np.bincount(g, np.abs(y - df[base_col].to_numpy(float)), minlength=n_gw)
    point = 100.0 * (1.0 - err_m.sum() / err_b.sum())
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_gw, size=(n_reps, n_gw))
    reps = 100.0 * (1.0 - err_m[idx].sum(axis=1) / err_b[idx].sum(axis=1))
    lo, hi = np.quantile(reps, [alpha / 2, 1 - alpha / 2])
    return float(point), float(lo), float(hi)


def top_k_precision(y, pred, k: int = config.TOP_K) -> float:
    """Share of the predicted top-k whose actual score reaches the actual k-th best score.

    Ties at the k-th actual score all count as "top k" (FPL scores tie a lot).
    """
    y = np.asarray(y, float)
    pred = np.asarray(pred, float)
    k = min(k, len(y))
    if k == 0:
        return float("nan")
    picked = np.argsort(-pred, kind="stable")[:k]
    threshold = np.sort(y)[::-1][k - 1]
    return float(np.mean(y[picked] >= threshold))


def per_gw(df: pd.DataFrame, col: str, k: int = config.TOP_K) -> pd.DataFrame:
    """One row per gameweek: n, MAE, Spearman, top-k precision for one prediction column."""
    rows = []
    for (season, gw), grp in df.groupby(GW_KEYS, sort=True):
        y, p = grp["y"].to_numpy(float), grp[col].to_numpy(float)
        rho = spearmanr(y, p).statistic if np.ptp(y) > 0 and np.ptp(p) > 0 else np.nan
        rows.append(
            {
                "season": season,
                "gw": gw,
                "n": len(grp),
                "mae": mae(y, p),
                "spearman": float(rho),
                f"top{k}": top_k_precision(y, p, k),
            }
        )
    return pd.DataFrame(rows)


def calibration(df: pd.DataFrame, col: str, n_bins: int = 10) -> pd.DataFrame:
    """Prediction deciles vs mean actual points."""
    bins = pd.qcut(df[col].rank(method="first"), n_bins, labels=False)
    return (
        df.assign(decile=bins + 1)
        .groupby("decile")
        .agg(n=("y", "size"), mean_pred=(col, "mean"), mean_actual=("y", "mean"))
        .reset_index()
    )


def model_metrics(df: pd.DataFrame, col: str, base_col: str = "pred_b0") -> dict:
    gw = per_gw(df, col)
    out = {
        "n": len(df),
        "mae": mae(df["y"], df[col]),
        "rmse": rmse(df["y"], df[col]),
        "spearman_per_gw": float(gw["spearman"].mean()),
        f"top{config.TOP_K}_precision_per_gw": float(gw[f"top{config.TOP_K}"].mean()),
    }
    if col != base_col:
        point, lo, hi = bootstrap_gain_ci(df, col, base_col)
        out.update({"mae_gain_pct": point, "mae_gain_ci95": [lo, hi]})
    return out


def summarise(player_gw: pd.DataFrame, base_col: str = "pred_b0") -> dict:
    """Metrics per subset (all / regulars), per model, plus regulars by position."""
    cols = pred_columns(player_gw)
    subsets = {"all": player_gw, "regulars": player_gw[player_gw["regular"]]}
    out: dict = {"n_gameweeks": int(player_gw.groupby(GW_KEYS).ngroups)}
    for name, sub in subsets.items():
        out[name] = {c.removeprefix("pred_"): model_metrics(sub, c, base_col) for c in cols}
    regs = subsets["regulars"]
    out["regulars_by_position"] = {
        pos: {
            c.removeprefix("pred_"): {
                "n": len(grp),
                "mae": mae(grp["y"], grp[c]),
                "mae_gain_pct": gain_pct(mae(grp["y"], grp[base_col]), mae(grp["y"], grp[c])),
            }
            for c in cols
        }
        for pos, grp in regs.groupby("position", sort=False)
    }
    return out


# --- tables and plots ----------------------------------------------------------------------

MODEL_LABELS = {
    "b0": "B0 rolling form",
    "ridge": "B1 Ridge",
    "lgbm": "M1 LightGBM (L2)",
    "lgbm_l1": "M2 LightGBM (L1)",
}


def metrics_table(summary: dict) -> pd.DataFrame:
    rows = []
    for subset in ("regulars", "all"):
        for model, m in summary[subset].items():
            ci = m.get("mae_gain_ci95")
            rows.append(
                {
                    "subset": subset,
                    "model": MODEL_LABELS.get(model, model),
                    "n": m["n"],
                    "MAE": round(m["mae"], 3),
                    "RMSE": round(m["rmse"], 3),
                    "MAE gain vs B0": "-"
                    if ci is None
                    else f"{m['mae_gain_pct']:+.1f}% [{ci[0]:+.1f}, {ci[1]:+.1f}]",
                    "Spearman/GW": round(m["spearman_per_gw"], 3),
                    f"Top-{config.TOP_K} prec./GW": round(
                        m[f"top{config.TOP_K}_precision_per_gw"], 3
                    ),
                }
            )
    return pd.DataFrame(rows)


def plot_metrics_table(table: pd.DataFrame, out_path: Path, title: str) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cells = table.map(lambda v: f"{v:.3f}" if isinstance(v, float) else str(v))
    fig, ax = plt.subplots(figsize=(13, 0.32 * len(table) + 0.8))
    ax.axis("off")
    tbl = ax.table(cellText=cells.values, colLabels=table.columns, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.auto_set_column_width(list(range(len(table.columns))))
    tbl.scale(1, 1.4)
    for (r, _), cell in tbl.get_celld().items():
        if r == 0:
            cell.set_facecolor("#e6e6e6")
            cell.set_text_props(weight="bold")
    ax.set_title(title, fontsize=11, pad=10)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_mae_by_gw(player_gw: pd.DataFrame, out_path: Path, title: str) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    regs = player_gw[player_gw["regular"]]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for col in pred_columns(regs):
        name = col.removeprefix("pred_")
        gw = per_gw(regs, col)
        ax.plot(gw["gw"], gw["mae"], marker="o", ms=3, lw=1.5, label=MODEL_LABELS.get(name, name))
    ax.set_xlabel("Gameweek")
    ax.set_ylabel("MAE (points per player-GW)")
    ax.set_title(title)
    ax.grid(alpha=0.3)
    ax.legend()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path
