"""Optimizer backtest over a past season (PLAN.md §8 P4).

Strategies, all starting with £100m at ``BACKTEST_START_GW`` and making at most one free transfer
per GW (no hits, no chips):

- **A** ``lgbm``: squad ILP + transfer planner on the walk-forward LightGBM predictions.
- **B** ``b0``: the same optimizer on the rolling-form baseline (B0) predictions.
- **C** ``greedy``: points-per-£ heuristic squad and greedy single swaps, on LightGBM predictions.

Every prediction for GW k comes from the walk-forward fold trained only on data before GW k, so the
backtest uses no future information. The horizon value ``P_h`` for GW k+j (j >= 1) is the player's
latest per-fixture prediction x his club's number of fixtures in GW k+j (the published schedule),
discounted by 0.9 per GW. Prices are the real per-GW ``value``; players are sold at the current
price (the half-of-the-rise selling rule is ignored for every strategy alike).

Scoring uses the actual points of the chosen XI with simplified auto-subs (bench order, formation
kept legal) and the captain's points doubled (the vice's if the captain didn't play).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from fPLense import config
from fPLense.optimize.squad_ilp import (
    SquadResult,
    best_xi,
    check_squad,
    greedy_squad,
    pick_squad,
    result_from_selection,
    validate_pool,
)
from fPLense.optimize.transfers import plan_transfers, recommended

log = logging.getLogger(__name__)

STRATEGIES: dict[str, dict[str, str]] = {
    "lgbm": {"pred": "pred_lgbm", "method": "ilp", "label": "A: ILP + LightGBM"},
    "b0": {"pred": "pred_b0", "method": "ilp", "label": "B: ILP + rolling form (B0)"},
    "greedy": {"pred": "pred_lgbm", "method": "greedy", "label": "C: greedy pts/£ + LightGBM"},
}


# --- inputs -----------------------------------------------------------------------------------


def load_inputs(
    season: str = config.BACKTEST_SEASON, eval_dir: Path = config.EVAL_DIR
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(walk-forward predictions per fixture, actual player-fixture rows) for ``season``."""
    from fPLense.db.build import build

    path = eval_dir / f"walk_forward_{season.replace('-', '_')}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `python -m fPLense.pipeline --evaluate`")
    preds = pd.read_parquet(path)
    con = build(":memory:")
    actual = con.sql(
        f"""
        select season, gw, element, name, position, team, fixture, minutes,
               total_points, value
        from v_player_match where season = '{season}'
        """
    ).df()
    con.close()
    return preds, actual


def player_gw_table(preds: pd.DataFrame, actual: pd.DataFrame) -> pd.DataFrame:
    """One row per (gw, element): price, club, minutes, points, fixtures and summed predictions."""
    pred_cols = [c for c in preds.columns if c.startswith("pred_")]
    act = (
        actual.sort_values(["gw", "element", "fixture"])
        .groupby(["gw", "element"], as_index=False)
        .agg(
            name=("name", "first"),
            pos=("position", "first"),
            club=("team", "first"),
            price=("value", "first"),
            minutes=("minutes", "sum"),
            points=("total_points", "sum"),
            n_fix=("fixture", "nunique"),
        )
    )
    pr = preds.groupby(["gw", "element"], as_index=False)[pred_cols].sum()
    out = act.merge(pr, on=["gw", "element"], how="left")
    return out.sort_values(["gw", "element"]).reset_index(drop=True)


def team_fixture_counts(actual: pd.DataFrame) -> pd.DataFrame:
    """Fixtures per (club, gw) from the season's schedule; 0 for blank gameweeks."""
    counts = actual.groupby(["team", "gw"])["fixture"].nunique().unstack(fill_value=0)
    all_gws = range(1, int(actual["gw"].max()) + 1)
    return counts.reindex(columns=all_gws, fill_value=0)


def gw_pool(
    pg: pd.DataFrame,
    team_fix: pd.DataFrame,
    gw: int,
    pred_col: str,
    horizon: int = config.HORIZON,
    discount: float = config.HORIZON_DISCOUNT,
) -> pd.DataFrame:
    """The optimizer pool at the GW ``gw`` deadline, indexed by element.

    Every player seen so far this season, with his latest price/club. A player missing from GW
    ``gw`` although his club plays has left the game: ``status = "u"``, no predicted points.
    """
    seen = pg[pg["gw"] <= gw].sort_values("gw")
    last = seen.groupby("element").tail(1).set_index("element")
    now = pg[pg["gw"] == gw].set_index("element")

    pool = last[["name", "pos", "club", "price"]].copy()
    pool["last_gw"] = last["gw"].astype(int)
    # fixtures the club played after the player's last row (GW gw included): > 0 means he left
    club_after = []
    for c, lg in zip(pool["club"], pool["last_gw"], strict=True):
        cols = [g for g in range(lg + 1, gw + 1) if g in team_fix.columns]
        club_after.append(int(team_fix.loc[c, cols].sum()) if c in team_fix.index else 0)
    listed = pool.index.isin(now.index)
    departed = ~listed & (np.asarray(club_after) > 0)
    pool["status"] = np.where(departed, "u", "a")

    # rate = latest per-fixture prediction (from the latest GW the player had a fixture)
    with_fix = seen[seen["n_fix"] > 0].groupby("element").tail(1).set_index("element")
    rate = (with_fix[pred_col] / with_fix["n_fix"]).reindex(pool.index).fillna(0.0)
    p1 = now[pred_col].reindex(pool.index).fillna(0.0)
    fut = np.zeros(len(pool))
    for j in range(1, horizon):
        g = gw + j
        if g in team_fix.columns:
            n = team_fix[g].reindex(pool["club"]).fillna(0).to_numpy()
            fut += discount**j * rate.to_numpy() * n
    pool["p1"] = np.where(departed, 0.0, p1)
    pool["P_h"] = np.where(departed, 0.0, p1.to_numpy() + fut)
    pool["minutes"] = now["minutes"].reindex(pool.index).fillna(0).astype(int)
    pool["points"] = now["points"].reindex(pool.index).fillna(0).astype(int)
    pool["price"] = pool["price"].astype(int)
    return pool


# --- scoring ----------------------------------------------------------------------------------


def _formation_ok(pos: pd.Series, xi: list) -> bool:
    counts = pos.loc[xi].value_counts()
    return counts.get("GK", 0) == 1 and all(
        counts.get(p, 0) >= config.XI_MIN[p] for p in ("DEF", "MID", "FWD")
    )


def score_gw(pool: pd.DataFrame, res: SquadResult) -> tuple[int, dict]:
    """Actual points of the XI after simplified auto-subs, captain doubled (vice as fallback)."""
    played = pool["minutes"] > 0
    xi = list(res.starters)
    bench = list(res.bench)
    subs = []
    for s in list(xi):
        if played.get(s, False):
            continue
        for b in bench:
            if not played.get(b, False):
                continue
            if (pool.at[s, "pos"] == "GK") != (pool.at[b, "pos"] == "GK"):
                continue
            trial = [b if p == s else p for p in xi]
            if _formation_ok(pool["pos"], trial):
                xi = trial
                bench.remove(b)
                subs.append((s, b))
                break
    pts = int(pool.loc[xi, "points"].sum())
    if played.get(res.captain, False):
        armband = res.captain
    elif played.get(res.vice, False) and res.vice in xi:
        armband = res.vice
    else:
        armband = None
    if armband is not None:
        pts += int(pool.at[armband, "points"])
    return pts, {"subs": subs, "armband": armband}


# --- strategies -------------------------------------------------------------------------------


def greedy_transfer(pool: pd.DataFrame, squad: list, bank: int) -> tuple[list, list, list, int]:
    """Best single like-for-like swap by ``P_h`` gain that stays legal (or none)."""
    pool = validate_pool(pool)
    in_squad = pool.index.isin(squad)
    clubs = pool.loc[squad, "club"].astype(str).value_counts()
    best = (0.0, None, None)
    candidates = pool[~in_squad]
    if "status" in candidates:
        candidates = candidates[candidates["status"] != "u"]
    for out in squad:
        o = pool.loc[out]
        cand = candidates[
            (candidates["pos"] == o["pos"]) & (candidates["price"] <= o["price"] + bank)
        ]
        club_n = cand["club"].astype(str).map(clubs).fillna(0)
        club_n = club_n - (cand["club"].astype(str) == str(o["club"])).astype(int)
        cand = cand[club_n < config.MAX_PER_CLUB]
        if cand.empty:
            continue
        i = cand["P_h"].idxmax()
        gain = cand.at[i, "P_h"] - o["P_h"]
        if gain > best[0] + 1e-9:
            best = (gain, out, i)
    if best[1] is None:
        return list(squad), [], [], bank
    _, out, inn = best
    new = [inn if p == out else p for p in squad]
    return new, [inn], [out], bank + int(pool.at[out, "price"] - pool.at[inn, "price"])


@dataclass
class BacktestResult:
    per_gw: pd.DataFrame
    summary: dict


def simulate(
    pg: pd.DataFrame,
    team_fix: pd.DataFrame,
    strategy: str,
    gws: list[int],
    horizon: int = config.HORIZON,
    budget: int = config.BUDGET,
) -> pd.DataFrame:
    spec = STRATEGIES[strategy]
    squad: list | None = None
    bank = budget
    rows = []
    for gw in gws:
        pool = gw_pool(pg, team_fix, gw, spec["pred"], horizon)
        ins: list = []
        outs: list = []
        if squad is None:
            pick = pick_squad if spec["method"] == "ilp" else greedy_squad
            res = pick(pool, budget)
            bank = budget - res.cost
        elif spec["method"] == "ilp":
            opt = recommended(plan_transfers(pool, squad, bank, free_transfers=1, max_transfers=1))
            res, bank, ins, outs = opt.result, opt.bank_after, opt.ins, opt.outs
        else:
            new, ins, outs, bank = greedy_transfer(pool, squad, bank)
            vp = validate_pool(pool)
            starters, captain = best_xi(vp, new)
            res = result_from_selection(vp, new, starters, captain, status="Heuristic")
        problems = check_squad(validate_pool(pool), res, budget=res.cost + bank)
        if problems or bank < 0:
            raise AssertionError(f"{strategy} GW{gw}: illegal squad {problems}, bank {bank}")
        squad = res.squad
        pts, info = score_gw(pool, res)
        rows.append(
            {
                "strategy": strategy,
                "gw": gw,
                "points": pts,
                "expected": round(res.expected_points, 3),
                "transfers": len(ins),
                "in": ", ".join(pool.loc[ins, "name"]),
                "out": ", ".join(pool.loc[outs, "name"]),
                "captain": pool.at[res.captain, "name"],
                "armband_played": info["armband"] is not None,
                "auto_subs": len(info["subs"]),
                "squad_value": res.cost,
                "bank": bank,
            }
        )
        log.info("%s GW%d: %d pts (in %s)", strategy, gw, pts, rows[-1]["in"] or "-")
    out = pd.DataFrame(rows)
    out["cum_points"] = out["points"].cumsum()
    return out


def run_backtest(
    season: str = config.BACKTEST_SEASON,
    start_gw: int = config.BACKTEST_START_GW,
    horizon: int = config.HORIZON,
    strategies: list[str] | None = None,
    inputs: tuple[pd.DataFrame, pd.DataFrame] | None = None,
) -> BacktestResult:
    t0 = time.time()
    preds, actual = inputs if inputs is not None else load_inputs(season)
    pg = player_gw_table(preds, actual)
    team_fix = team_fixture_counts(actual)
    gws = sorted(g for g in pg["gw"].unique() if g >= start_gw)
    per_gw = pd.concat(
        [simulate(pg, team_fix, s, gws, horizon) for s in (strategies or list(STRATEGIES))],
        ignore_index=True,
    )
    totals = per_gw.groupby("strategy")["points"].sum()
    wide = per_gw.pivot(index="gw", columns="strategy", values="points")
    summary = {
        "season": season,
        "gws": [int(g) for g in gws],
        "horizon": horizon,
        "discount": config.HORIZON_DISCOUNT,
        "rules": "£100m start, <=1 free transfer per GW, no hits, no chips, simplified auto-subs",
        "strategies": {s: STRATEGIES[s]["label"] for s in totals.index},
        "total_points": {s: int(v) for s, v in totals.items()},
        "per_gw_points": {s: [int(v) for v in wide[s]] for s in wide.columns},
        "transfers_made": {
            s: int(v) for s, v in per_gw.groupby("strategy")["transfers"].sum().items()
        },
        "runtime_s": round(time.time() - t0, 1),
    }
    if {"lgbm", "b0"} <= set(wide.columns):
        diff = wide["lgbm"] - wide["b0"]
        summary["a_minus_b"] = int(diff.sum())
        summary["a_minus_b_ci95"] = _bootstrap_sum_ci(diff.to_numpy())
        summary["a_beats_b_gws"] = int((diff > 0).sum())
    if {"lgbm", "greedy"} <= set(wide.columns):
        diff = wide["lgbm"] - wide["greedy"]
        summary["a_minus_c"] = int(diff.sum())
        summary["a_minus_c_ci95"] = _bootstrap_sum_ci(diff.to_numpy())
    return BacktestResult(per_gw=per_gw, summary=summary)


def _bootstrap_sum_ci(
    diff: np.ndarray, n_reps: int = config.BOOTSTRAP_REPS, seed: int = config.RANDOM_STATE
) -> list[float]:
    """95% CI for a season total difference, resampling gameweeks with replacement."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diff), size=(n_reps, len(diff)))
    lo, hi = np.quantile(diff[idx].sum(axis=1), [0.025, 0.975])
    return [float(lo), float(hi)]


def plot_cumulative(per_gw: pd.DataFrame, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    for s, g in per_gw.groupby("strategy", sort=False):
        ax.plot(g["gw"], g["cum_points"], label=f"{STRATEGIES[s]['label']} ({g['points'].sum()})")
    ax.set_xlabel("gameweek")
    ax.set_ylabel("cumulative points")
    season = config.BACKTEST_SEASON
    ax.set_title(
        f"Optimizer backtest, {season} GW{int(per_gw['gw'].min())}-{int(per_gw['gw'].max())}"
    )
    ax.legend()
    ax.grid(alpha=0.3)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def save(result: BacktestResult, path: Path = config.BACKTEST_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.summary, indent=2), encoding="utf-8")
    return path
