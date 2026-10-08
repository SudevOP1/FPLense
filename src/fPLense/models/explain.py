"""SHAP explanations for the LightGBM points model (PLAN.md §8 P4).

``shap.TreeExplainer`` computes exact TreeSHAP values: per row, ``base_value + sum(shap) =
prediction`` (points per fixture). Global view: a beeswarm over a 5K-row sample of the target
season plus dependence plots; local view: waterfalls for single player-fixtures. ``shap_frame``
and ``top_contributions`` are what P5 writes next to the published predictions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import lightgbm as lgb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap

from fPLense import config
from fPLense.models.train import lgbm_frame

log = logging.getLogger(__name__)


def load_model(path: Path = config.MODEL_PATH) -> lgb.Booster:
    if not Path(path).exists():
        raise FileNotFoundError(f"{path} not found; run `python -m fPLense.pipeline --train`")
    return lgb.Booster(model_file=str(path))


def _booster(model) -> lgb.Booster:
    return model.booster_ if hasattr(model, "booster_") else model


def explain(model, df: pd.DataFrame, features: list[str] = config.FEATURES) -> shap.Explanation:
    """SHAP values for ``df`` rows (the model's own feature order)."""
    booster = _booster(model)
    X = lgbm_frame(df, features)
    expl = shap.TreeExplainer(booster)(X)
    # numeric data for colouring (position -> its category code), readable values for waterfalls
    numeric = X.apply(lambda s: s.cat.codes.astype(float) if s.dtype == "category" else s)
    expl.data = numeric.to_numpy(float)
    expl.display_data = X.astype(object).to_numpy()
    return expl


def shap_frame(model, df: pd.DataFrame, features: list[str] = config.FEATURES) -> pd.DataFrame:
    """Per-row SHAP values as a DataFrame (one column per feature) plus ``base_value``.

    Uses LightGBM's built-in TreeSHAP (``pred_contrib``), identical to ``shap.TreeExplainer``
    for this model and cheaper for the few thousand rows P5 publishes each week.
    """
    booster = _booster(model)
    contrib = booster.predict(lgbm_frame(df, features), pred_contrib=True)
    out = pd.DataFrame(contrib[:, :-1], columns=features, index=df.index)
    out["base_value"] = contrib[:, -1]
    return out


def top_contributions(sv: pd.DataFrame, k: int = config.SHAP_TOP_K) -> pd.Series:
    """For each row, the ``k`` features with the largest |SHAP|, as ``[(feature, value), ...]``."""
    vals = sv.drop(columns="base_value", errors="ignore")
    arr = vals.to_numpy(float)
    order = np.argsort(-np.abs(arr), axis=1)[:, :k]
    cols = np.asarray(vals.columns)
    return pd.Series(
        [
            [(str(cols[j]), round(float(arr[r, j]), 3)) for j in order[r]]
            for r in range(arr.shape[0])
        ],
        index=sv.index,
    )


def importance(expl: shap.Explanation) -> pd.Series:
    """Mean |SHAP| per feature, largest first (points per fixture)."""
    vals = np.abs(np.asarray(expl.values)).mean(axis=0)
    return pd.Series(vals, index=expl.feature_names).sort_values(ascending=False)


def sample_rows(
    df: pd.DataFrame,
    n: int = config.SHAP_SAMPLE_ROWS,
    season: str | None = config.SHAP_SAMPLE_SEASON,
    seed: int = config.RANDOM_STATE,
) -> pd.DataFrame:
    sub = df[df["season"] == season] if season else df
    return sub.sample(min(n, len(sub)), random_state=seed)


def pick_examples(
    df: pd.DataFrame, model, season: str = config.SHAP_SAMPLE_SEASON, gw: int | None = None
) -> dict[str, pd.Series]:
    """One premium forward (the priciest regular FWD) and one budget defender (the regular DEF
    priced <= £4.5m with the highest prediction) in one gameweek (default: the season's last)."""
    sub = df[(df["season"] == season) & df["regular"]]
    gw = int(sub["gw"].max()) if gw is None else gw
    sub = sub[sub["gw"] == gw].copy()
    sub["pred"] = _booster(model).predict(lgbm_frame(sub))
    fwd = sub[sub["position"] == "FWD"].sort_values(["price", "pred"], ascending=False)
    defs = sub[(sub["position"] == "DEF") & (sub["price"] <= 4.5)].sort_values(
        "pred", ascending=False
    )
    if fwd.empty or defs.empty:
        raise ValueError(f"no premium FWD / budget DEF among regulars in {season} GW{gw}")
    return {"premium_fwd": fwd.iloc[0], "budget_def": defs.iloc[0]}


# --- plots ------------------------------------------------------------------------------------


def _save(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close("all")
    return path


def plot_beeswarm(expl: shap.Explanation, path: Path, max_display: int = 20) -> Path:
    shap.plots.beeswarm(expl, max_display=max_display, show=False)
    plt.title("SHAP: impact on predicted points per fixture")
    return _save(path)


def plot_dependence(expl: shap.Explanation, feature: str, path: Path) -> Path:
    shap.plots.scatter(expl[:, feature], color=expl, show=False)
    plt.title(f"SHAP dependence: {feature}")
    return _save(path)


def plot_waterfall(expl_row: shap.Explanation, path: Path, title: str) -> Path:
    shap.plots.waterfall(expl_row, max_display=12, show=False)
    plt.title(title)
    return _save(path)


def run_shap(
    df: pd.DataFrame, model=None, out_dir: Path = config.DOCS_IMG_DIR
) -> dict[str, object]:
    """Beeswarm, dependence plots and two waterfalls -> ``out_dir``; returns a summary dict."""
    model = load_model() if model is None else model
    sample = sample_rows(df)
    expl = explain(model, sample)
    imp = importance(expl)
    paths = {"beeswarm": plot_beeswarm(expl, out_dir / "shap_beeswarm.png")}
    for f in config.SHAP_DEPENDENCE_FEATURES:
        paths[f"dependence_{f}"] = plot_dependence(expl, f, out_dir / f"shap_dependence_{f}.png")

    examples = pick_examples(df, model)
    ex_df = pd.DataFrame(examples).T
    ex_expl = explain(model, ex_df)
    waterfalls = {}
    for k, (key, row) in enumerate(examples.items()):
        title = (
            f"{row['name']} ({row['position']}, £{float(row['price']):.1f}m), "
            f"{row['season']} GW{int(row['gw'])} vs {row.get('opponent_team_name', '?')}"
        )
        paths[f"waterfall_{key}"] = plot_waterfall(
            ex_expl[k], out_dir / f"shap_waterfall_{key}.png", title
        )
        waterfalls[key] = {
            "name": str(row["name"]),
            "position": str(row["position"]),
            "price": float(row["price"]),
            "season": str(row["season"]),
            "gw": int(row["gw"]),
            "prediction": float(ex_expl[k].base_values + ex_expl[k].values.sum()),
            "actual": float(row[config.TARGET]),
            "base_value": float(ex_expl[k].base_values),
        }
    summary = {
        "sample_rows": len(sample),
        "sample_season": config.SHAP_SAMPLE_SEASON,
        "base_value": float(np.mean(expl.base_values)),
        "mean_abs_shap": {f: round(float(v), 4) for f, v in imp.items()},
        "waterfalls": waterfalls,
        "plots": {k: Path(p).name for k, p in paths.items()},
    }
    return summary


def save_summary(summary: dict, path: Path = config.SHAP_IMPORTANCE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path
