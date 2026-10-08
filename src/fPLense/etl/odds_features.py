"""Turn pre-match bookmaker odds into implied goals and clean-sheet probabilities (PLAN.md §3e).

1. De-vig: ``p_i = (1/o_i) / sum_j (1/o_j)`` for home/draw/away and for over/under 2.5.
2. Implied total goals ``mu``: solve ``1 - e^-mu (1 + mu + mu^2/2) = p_over2.5`` (Poisson).
3. Split ``mu`` into ``lam_home = s*mu`` and ``lam_away = (1-s)*mu`` so that
   ``P(Skellam(lam_home, lam_away) > 0) = p_home`` (independent Poisson goals).
4. Per team: own lambda = implied xG, ``p_clean_sheet = exp(-opponent lambda)``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import poisson, skellam

MU_BOUNDS = (0.2, 6.0)
SHARE_BOUNDS = (0.05, 0.95)


def devig(*odds: float) -> tuple[float, ...]:
    """Remove the bookmaker margin: normalised inverse odds. NaN if any price is missing/invalid."""
    inv = np.array([1.0 / o if o and o > 1.0 else np.nan for o in odds], dtype=float)
    if np.isnan(inv).any():
        return tuple(np.nan for _ in odds)
    return tuple(inv / inv.sum())


def p_over_25(mu: float) -> float:
    """P(total goals >= 3) for Poisson(mu)."""
    return float(poisson.sf(2, mu))


def implied_mu(p_over: float) -> float:
    """Total-goals mean whose Poisson P(over 2.5) equals ``p_over`` (clipped to MU_BOUNDS)."""
    if not np.isfinite(p_over):
        return np.nan
    lo, hi = MU_BOUNDS
    if p_over <= p_over_25(lo):
        return lo
    if p_over >= p_over_25(hi):
        return hi
    return float(brentq(lambda mu: p_over_25(mu) - p_over, lo, hi))


def p_home_win(share: float, mu: float) -> float:
    """P(home goals > away goals) with home ~ Poisson(share*mu), away ~ Poisson((1-share)*mu)."""
    return float(skellam.sf(0, share * mu, (1 - share) * mu))


def split_mu(mu: float, p_home: float) -> tuple[float, float]:
    """``(lam_home, lam_away)`` summing to ``mu`` that reproduce ``p_home`` (share clipped)."""
    if not (np.isfinite(mu) and np.isfinite(p_home)):
        return np.nan, np.nan
    lo, hi = SHARE_BOUNDS
    if p_home <= p_home_win(lo, mu):
        s = lo
    elif p_home >= p_home_win(hi, mu):
        s = hi
    else:
        s = brentq(lambda share: p_home_win(share, mu) - p_home, lo, hi)
    return float(s * mu), float((1 - s) * mu)


def add_implied(df: pd.DataFrame) -> pd.DataFrame:
    """Add de-vigged probabilities and implied goals to a frame of chosen pre-match odds.

    Expects ``odds_h, odds_d, odds_a, odds_over, odds_under``; adds ``p_home, p_draw, p_away,
    p_over, mu, lam_home, lam_away, p_cs_home, p_cs_away``.
    """
    out = df.copy()
    hda = [devig(h, d, a) for h, d, a in zip(out.odds_h, out.odds_d, out.odds_a, strict=True)]
    out[["p_home", "p_draw", "p_away"]] = pd.DataFrame(hda, index=out.index, dtype=float)
    ou = [devig(o, u)[0] for o, u in zip(out.odds_over, out.odds_under, strict=True)]
    out["p_over"] = np.array(ou, dtype=float)
    out["mu"] = out["p_over"].map(implied_mu)
    lams = [split_mu(m, p) for m, p in zip(out.mu, out.p_home, strict=True)]
    out[["lam_home", "lam_away"]] = pd.DataFrame(lams, index=out.index, dtype=float)
    out["p_cs_home"] = np.exp(-out["lam_away"])
    out["p_cs_away"] = np.exp(-out["lam_home"])
    return out


def calibration_table(p_clean_sheet: pd.Series, clean_sheet: pd.Series, bins: int = 10):
    """Deciles of implied clean-sheet probability vs the actual clean-sheet rate."""
    d = pd.DataFrame({"p": p_clean_sheet, "cs": clean_sheet.astype(float)}).dropna()
    d["decile"] = pd.qcut(d["p"], bins, labels=False, duplicates="drop")
    return (
        d.groupby("decile")
        .agg(p_mean=("p", "mean"), cs_rate=("cs", "mean"), n=("cs", "size"))
        .reset_index()
    )


def plot_calibration(table: pd.DataFrame, path: Path, title: str = "") -> Path:
    """Save the predicted-vs-actual clean-sheet calibration plot."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(5.5, 5))
    lim = max(table.p_mean.max(), table.cs_rate.max()) * 1.08
    ax.plot([0, lim], [0, lim], ls="--", color="grey", lw=1, label="perfect calibration")
    ax.plot(table.p_mean, table.cs_rate, marker="o", color="#2a6fdb", label="decile")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("implied clean-sheet probability (decile mean)")
    ax.set_ylabel("actual clean-sheet rate")
    ax.set_title(title or "Bookmaker-implied clean-sheet calibration")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
