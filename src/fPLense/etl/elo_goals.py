"""Elo-only goal estimate for fixtures without bookmaker odds (PLAN.md §8 P5).

football-data's ``fixtures.csv`` only lists the next round, and nothing during international
breaks, so most horizon fixtures have no odds. For those, a Poisson regression fitted on the 10
historical seasons gives each side's expected goals from Elo alone::

    log(lambda_team) = b0 + b1 * elo_diff / 100 + b2 * is_home

The two lambdas then go through the same independent-Poisson maths as the odds path (Skellam for
win/draw/loss, ``exp(-lambda_opp)`` for a clean sheet), and the rows are labelled
``source_1x2 = source_ou = "elo"`` so ``odds_source`` records which estimate a fixture used.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.stats import poisson, skellam

from fPLense.etl.load_odds import LAKE_COLUMNS

ELO_SOURCE = "elo"


@dataclass(frozen=True)
class EloGoalModel:
    intercept: float
    coef_elo_100: float  # per 100 Elo points of difference
    coef_home: float
    n: int = 0

    def lam(self, elo_diff, is_home) -> np.ndarray:
        x = np.asarray(elo_diff, float) / 100.0
        h = np.asarray(is_home, float)
        return np.exp(self.intercept + self.coef_elo_100 * x + self.coef_home * h)

    def to_dict(self) -> dict:
        return asdict(self)


def fit(goals, elo_diff, is_home) -> EloGoalModel:
    """Poisson GLM (log link, no penalty) of a team's goals on Elo difference and home."""
    from sklearn.linear_model import PoissonRegressor

    d = pd.DataFrame(
        {"g": np.asarray(goals, float), "e": np.asarray(elo_diff, float) / 100.0}
    ).assign(h=np.asarray(is_home, float))
    d = d.dropna()
    reg = PoissonRegressor(alpha=0.0, max_iter=1000).fit(d[["e", "h"]], d["g"])
    return EloGoalModel(
        intercept=float(reg.intercept_),
        coef_elo_100=float(reg.coef_[0]),
        coef_home=float(reg.coef_[1]),
        n=len(d),
    )


def fit_from_views(con, seasons: list[str]) -> EloGoalModel:
    """Fit on every historical team-match: goals for vs pre-match Elo difference and venue."""
    s = ", ".join(f"'{x}'" for x in seasons)
    d = con.sql(
        f"""
        select tm.goals_for, mo.elo_diff, mo.is_home::int as is_home
        from v_match_odds mo
        join v_team_match tm using (season, fixture, team_id)
        where mo.season in ({s}) and mo.elo_diff is not null and tm.goals_for is not null
        """
    ).df()
    return fit(d["goals_for"], d["elo_diff"], d["is_home"])


def implied(lam_home, lam_away) -> pd.DataFrame:
    """Win/draw/loss, over 2.5 and clean-sheet probabilities from two Poisson means."""
    lh = np.asarray(lam_home, float)
    la = np.asarray(lam_away, float)
    mu = lh + la
    return pd.DataFrame(
        {
            "p_home": skellam.sf(0, lh, la),
            "p_draw": skellam.pmf(0, lh, la),
            "p_away": skellam.cdf(-1, lh, la),
            "p_over": poisson.sf(2, mu),
            "mu": mu,
            "lam_home": lh,
            "lam_away": la,
            "p_cs_home": np.exp(-la),
            "p_cs_away": np.exp(-lh),
        }
    )


def latest_elo(elo: pd.DataFrame, club: str, before) -> float:
    """Club's latest Elo snapshot dated strictly before ``before`` (NaN if none)."""
    d = elo[(elo["club"] == club) & (pd.to_datetime(elo["date"]) < pd.Timestamp(before))]
    return float(d.sort_values("date")["elo"].iloc[-1]) if len(d) else np.nan


def estimate_rows(
    fixtures: pd.DataFrame, model: EloGoalModel, elo: pd.DataFrame, names: pd.DataFrame
) -> pd.DataFrame:
    """Odds-lake rows (``LAKE_COLUMNS``) for ``fixtures`` from Elo alone.

    ``fixtures`` needs ``home, away`` (FPL names), ``date`` (the gameweek's first kick-off
    date: Elo is taken strictly before it, as in ``v_match_odds``). ``names`` is the team-name map.
    """
    nm = names.set_index("fpl_name")
    rows = []
    for f in fixtures.itertuples(index=False):
        eh = latest_elo(elo, nm.at[f.home, "clubelo_name"], f.date)
        ea = latest_elo(elo, nm.at[f.away, "clubelo_name"], f.date)
        diff = eh - ea
        ts = pd.Timestamp(f.date)
        rows.append(
            {
                "date": (ts.tz_convert(None) if ts.tzinfo else ts).normalize(),
                "home_team": nm.at[f.home, "fd_name"],
                "away_team": nm.at[f.away, "fd_name"],
                "lam_home_": float(model.lam(diff, 1)),
                "lam_away_": float(model.lam(-diff, 0)),
            }
        )
    if not rows:
        return pd.DataFrame(columns=LAKE_COLUMNS)
    df = pd.DataFrame(rows)
    out = pd.concat(
        [df[["date", "home_team", "away_team"]], implied(df["lam_home_"], df["lam_away_"])],
        axis=1,
    )
    out["source_1x2"] = ELO_SOURCE
    out["source_ou"] = ELO_SOURCE
    for c in LAKE_COLUMNS:
        if c not in out:
            out[c] = np.nan
    out["time"] = out["time"].astype("string")
    for c in ("home_team", "away_team", "source_1x2", "source_ou"):
        out[c] = out[c].astype("string")
    return out[LAKE_COLUMNS]
