"""Data access and pure helpers for the Streamlit app (``app/``).

The app reads only ``data/published/`` (plus a picks fetch when the user submits a team ID on the
Transfer Planner). Everything here is plain pandas so it can be unit-tested without Streamlit;
the pages add ``st.cache_data`` around the loaders.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from fPLense import config

POSITIONS = ["GK", "DEF", "MID", "FWD"]


# --- loaders ----------------------------------------------------------------------------------


def read_json(name: str, published: Path = config.PUBLISHED_DIR) -> dict | None:
    path = Path(published) / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_latest(published: Path = config.PUBLISHED_DIR) -> dict | None:
    """``latest.json`` (pointer to the newest predictions), or ``None`` before the first run."""
    return read_json(config.LATEST_PATH.name, published)


def load_predictions(latest: dict, published: Path = config.PUBLISHED_DIR) -> pd.DataFrame:
    return pd.read_parquet(Path(published) / latest["files"]["predictions"])


def load_shap(latest: dict, published: Path = config.PUBLISHED_DIR) -> pd.DataFrame:
    return pd.read_parquet(Path(published) / latest["files"]["shap"])


def load_squad(latest: dict, published: Path = config.PUBLISHED_DIR) -> dict:
    return read_json(latest["files"]["squad"], published)


def image_path(name: str, published: Path = config.PUBLISHED_DIR) -> Path | None:
    path = Path(published) / config.PUBLISHED_IMG_DIR.name / name
    return path if path.exists() else None


# --- time -------------------------------------------------------------------------------------


def time_until(deadline: str | None, now: pd.Timestamp | None = None) -> str:
    """``"1d 17h"`` until the deadline, ``"passed"`` after it, ``"n/a"`` without one."""
    if not deadline:
        return "n/a"
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    secs = (pd.Timestamp(deadline) - now).total_seconds()
    if secs <= 0:
        return "passed"
    days, rem = divmod(int(secs), 86_400)
    hours, rem = divmod(rem, 3_600)
    return f"{days}d {hours}h" if days else f"{hours}h {rem // 60}m"


def age(ts: str | None, now: pd.Timestamp | None = None) -> str:
    """How long ago ``ts`` was: ``"3h ago"``, ``"2d ago"``."""
    if not ts:
        return "n/a"
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    hours = (now - pd.Timestamp(ts)).total_seconds() / 3600
    if hours < 1:
        return f"{max(int(hours * 60), 0)}m ago"
    return f"{hours:.0f}h ago" if hours < 48 else f"{hours / 24:.0f}d ago"


# --- projections ------------------------------------------------------------------------------


def gw_columns(latest: dict, prefix: str = "p") -> list[str]:
    return [f"{prefix}_gw{gw:02d}" for gw in latest["gws"]]


def with_horizon(
    df: pd.DataFrame, latest: dict, horizon: int, discount: float = config.HORIZON_DISCOUNT
) -> pd.DataFrame:
    """Recompute ``P_h`` over the first ``horizon`` predicted GWs (``p1`` = first GW)."""
    from fPLense.optimize.squad_ilp import discounted_sum

    cols = gw_columns(latest)[: max(1, int(horizon))]
    out = df.copy()
    out["P_h"] = discounted_sum(out[cols].to_numpy(float), discount)
    out["p1"] = out[cols[0]].astype(float)
    return out


def filter_projections(
    df: pd.DataFrame,
    positions: list[str] | None = None,
    clubs: list[str] | None = None,
    price_range: tuple[float, float] | None = None,
    min_minutes_r3: float = 0.0,
    search: str = "",
) -> pd.DataFrame:
    """Filter the projections table. ``price_range`` in £m; ``min_minutes_r3`` uses the lagged
    average minutes over the player's last 3 fixtures (NaN counts as 0)."""
    keep = pd.Series(True, index=df.index)
    if positions:
        keep &= df["pos"].isin(positions)
    if clubs:
        keep &= df["club"].isin(clubs)
    if price_range is not None:
        lo, hi = price_range
        keep &= df["price"].between(round(lo * 10), round(hi * 10))
    if min_minutes_r3 > 0:
        keep &= pd.to_numeric(df["minutes_r3"], errors="coerce").fillna(0) >= min_minutes_r3
    if search:
        s = search.strip().lower()
        keep &= df["web_name"].str.lower().str.contains(s, regex=False) | df[
            "name"
        ].str.lower().str.contains(s, regex=False)
    return df[keep]


def waterfall_data(shap_row: pd.Series, k: int = 10) -> pd.DataFrame:
    """Top-``k`` SHAP contributions of one player (+ an "other features" bucket).

    Rows: ``feature, shap, value`` sorted by |shap|; ``base_value + sum(shap)`` = the model's
    next-GW prediction before availability scaling.
    """
    sv = shap_row.filter(like="shap_")
    sv.index = [i.removeprefix("shap_") for i in sv.index]
    sv = sv.astype(float)
    order = sv.abs().sort_values(ascending=False).index
    top = sv[order[:k]]
    rest = float(sv[order[k:]].sum())
    rows = [
        {"feature": f, "shap": float(v), "value": shap_row.get(f"val_{f}", np.nan)}
        for f, v in top.items()
    ]
    if len(order) > k:
        rows.append({"feature": f"{len(order) - k} other features", "shap": rest, "value": None})
    return pd.DataFrame(rows)


# --- optimizer --------------------------------------------------------------------------------


def squad_pool(df: pd.DataFrame) -> pd.DataFrame:
    """Predictions → the ILP pool (indexed by player id; ``price`` in integer tenths)."""
    cols = ["pos", "club", "price", "p1", "P_h", "status", "chance_of_playing_next_round"]
    pool = df.set_index("element")[cols + ["web_name", "club_short"]].copy()
    pool["price"] = pool["price"].astype(int)
    return pool


def squad_table(pool: pd.DataFrame, res) -> pd.DataFrame:
    """One row per squad player with role (starter / bench order), captain and vice flags."""
    bench_order = {p: k + 1 for k, p in enumerate(res.bench)}
    rows = []
    for i in res.squad:
        r = pool.loc[i]
        rows.append(
            {
                "element": i,
                "name": r["web_name"],
                "club": r["club_short"],
                "pos": r["pos"],
                "price": r["price"] / 10,
                "p1": float(r["p1"]),
                "P_h": float(r["P_h"]),
                "starter": i in set(res.starters),
                "bench": bench_order.get(i),
                "captain": i == res.captain,
                "vice": i == res.vice,
            }
        )
    return pd.DataFrame(rows)


def pitch_lines(table: pd.DataFrame) -> dict[str, list[dict]]:
    """Starters grouped by position (pitch rows GK → FWD), plus the ordered bench."""
    starters = table[table["starter"]]
    lines = {pos: starters[starters["pos"] == pos].to_dict("records") for pos in POSITIONS}
    lines["bench"] = table[~table["starter"]].sort_values("bench").to_dict("records")
    return lines


def picks_summary(picks: dict, df: pd.DataFrame) -> pd.DataFrame:
    """The current squad from a picks response, with predictions joined (for display)."""
    p = df.set_index("element")
    rows = []
    for e in picks["squad"]:
        r = p.loc[e] if e in p.index else None
        rows.append(
            {
                "element": e,
                "name": r["web_name"] if r is not None else str(e),
                "club": r["club_short"] if r is not None else "?",
                "pos": r["pos"] if r is not None else "?",
                "price": r["price"] / 10 if r is not None else np.nan,
                "p1": float(r["p1"]) if r is not None else np.nan,
                "P_h": float(r["P_h"]) if r is not None else np.nan,
                "status": r["status"] if r is not None else "?",
            }
        )
    return pd.DataFrame(rows)


def metrics_rows(
    metrics: dict, view: str = "walk_forward", subset: str = "regulars"
) -> pd.DataFrame:
    """Metrics table (MAE, RMSE, gain vs B0 with CI, Spearman, top-20) for the Model Card page."""
    labels = {
        "b0": "B0 rolling form",
        "ridge": "B1 Ridge",
        "lgbm": "M1 LightGBM (L2)",
        "lgbm_l1": "M2 LightGBM (L1)",
    }
    rows = []
    for key, m in metrics[view][subset].items():
        ci = m.get("mae_gain_ci95")
        rows.append(
            {
                "model": labels.get(key, key),
                "n": m.get("n"),
                "MAE": round(m["mae"], 3),
                "RMSE": round(m["rmse"], 3),
                "gain vs B0": (
                    f"{m['mae_gain_pct']:+.1f}% [{ci[0]:.1f}, {ci[1]:.1f}]" if ci else "baseline"
                ),
                "Spearman/GW": round(m["spearman_per_gw"], 3),
                "top-20 prec.": round(m["top20_precision_per_gw"], 3),
            }
        )
    return pd.DataFrame(rows)


def headline(metrics: dict | None) -> dict[str, Any] | None:
    """The resume number: regulars MAE gain of LightGBM vs B0 (walk-forward), with its CI."""
    if not metrics:
        return None
    m = metrics["walk_forward"]["regulars"]
    lgbm, b0 = m["lgbm"], m["b0"]
    return {
        "gain_pct": lgbm["mae_gain_pct"],
        "ci": lgbm["mae_gain_ci95"],
        "mae": lgbm["mae"],
        "b0_mae": b0["mae"],
        "n": lgbm["n"],
        "season": metrics["walk_forward"]["target_season"],
        "spearman": lgbm["spearman_per_gw"],
        "b0_spearman": b0["spearman_per_gw"],
    }
