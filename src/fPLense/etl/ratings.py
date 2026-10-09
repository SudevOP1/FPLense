"""Player-card ratings and photo URLs (PLAN.md §8 P6).

**FPLense rating only.** The EA SPORTS FC ratings were dropped on 2026-10-09 (developer's choice;
PLAN.md's cut list allows it), so every card shows our own rating, always labelled as ours:

    rating = round(50 + 49 x percentile of P_h within position), among available players

Available = status not ``u`` and availability > 0. An unavailable player is placed on the same
scale against the available players of his position, so a long-term injury reads low instead of
vanishing. Range 50..99.

Photos are **hotlinked** from the Premier League CDN by ``code`` (stable across seasons); the
backend only builds the URL and never downloads, stores or re-hosts an image (PLAN.md §0.3).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from fPLense import config

RATING_SOURCE = "fplense"


def photo_url(code) -> str | None:
    """CDN URL of a player's photo (``code`` = bootstrap ``elements[].code``, not ``id``)."""
    if code is None or (isinstance(code, float) and np.isnan(code)):
        return None
    return config.PHOTO_URL_TEMPLATE.format(code=int(code))


def is_available(df: pd.DataFrame) -> pd.Series:
    keep = pd.Series(True, index=df.index)
    if "status" in df:
        keep &= df["status"].astype(str) != "u"
    if "availability" in df:
        keep &= pd.to_numeric(df["availability"], errors="coerce").fillna(1.0) > 0
    return keep


def fplense_rating(df: pd.DataFrame, value: str = "P_h") -> pd.Series:
    """50 + 49 x percentile of ``value`` within position among available players (int 50..99).

    Percentile = share of available same-position players with a lower value, plus half the
    ties, scaled so the best is 1.0 (the worst available player gets 50, the best 99).
    """
    avail = is_available(df)
    v = pd.to_numeric(df[value], errors="coerce").fillna(0.0)
    out = pd.Series(50, index=df.index, dtype="int64")
    for _pos, idx in df.groupby("pos").groups.items():
        ref = np.sort(v[idx][avail[idx]].to_numpy())
        if len(ref) == 0:
            continue
        x = v[idx].to_numpy()
        below = np.searchsorted(ref, x, side="left")
        ties = np.searchsorted(ref, x, side="right") - below
        pct = (below + 0.5 * np.maximum(ties - 1, 0)) / max(len(ref) - 1, 1)
        out[idx] = np.rint(50 + 49 * np.clip(pct, 0.0, 1.0)).astype("int64")
    return out


def ratings_table(predictions: pd.DataFrame) -> pd.DataFrame:
    """``element, code, rating, rating_source, photo_url`` for every player."""
    return pd.DataFrame(
        {
            "element": predictions["element"].astype("int64").to_numpy(),
            "code": predictions["code"].astype("int64").to_numpy(),
            "rating": fplense_rating(predictions).to_numpy(),
            "rating_source": RATING_SOURCE,
            "photo_url": [photo_url(c) for c in predictions["code"]],
        }
    )


def publish_ratings(
    predictions: pd.DataFrame, gw: int, out_dir: Path = config.PUBLISHED_DIR
) -> dict:
    """Write ``ratings.json`` (``element -> {code, rating, source}``) next to the predictions."""
    t = ratings_table(predictions)
    doc = {
        "season": config.CURRENT_SEASON,
        "gw": int(gw),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": RATING_SOURCE,
        "formula": "round(50 + 49 x percentile of P_h within position, available players)",
        "ea_fc": "not used: EA SPORTS FC ratings were dropped on 2026-10-09 (DECISIONS.md P6)",
        "players": {
            str(r.element): {"code": int(r.code), "rating": int(r.rating)}
            for r in t.itertuples(index=False)
        },
    }
    path = Path(out_dir) / config.RATINGS_PATH.name
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return doc
