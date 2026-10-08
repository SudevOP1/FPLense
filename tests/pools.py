"""Synthetic player pools shared by the optimizer tests (no data needed)."""

from __future__ import annotations

import numpy as np
import pandas as pd

PRICE_RANGE = {"GK": (40, 60), "DEF": (40, 70), "MID": (45, 130), "FWD": (45, 150)}


def random_pool(n: int = 200, seed: int = 0, n_clubs: int = 20) -> pd.DataFrame:
    """Synthetic pool: integer prices in tenths, points loosely rising with price."""
    rng = np.random.default_rng(seed)
    pos = rng.choice(["GK", "DEF", "MID", "FWD"], size=n, p=[0.12, 0.33, 0.37, 0.18])
    lo = np.array([PRICE_RANGE[p][0] for p in pos])
    hi = np.array([PRICE_RANGE[p][1] for p in pos])
    price = rng.integers(lo, hi + 1)
    p1 = np.clip(price / 25 + rng.normal(0, 1.2, n), 0, None)
    return pd.DataFrame(
        {
            "pos": pos,
            "club": rng.choice([f"C{k:02d}" for k in range(n_clubs)], size=n),
            "price": price,
            "p1": p1,
            "P_h": p1 * 2.4 + rng.normal(0, 0.8, n).clip(-1, 1),
        },
        index=pd.RangeIndex(1000, 1000 + n, name="element"),
    )
