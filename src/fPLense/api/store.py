"""Read-only access to ``data/published/`` for the API.

Every file is loaded on first use and cached with its modification time; when a refresh commits
new files (and the host redeploys or the files change in place) the next request reloads them.
Nothing here runs the ETL, DuckDB or the model (PLAN.md §5 runtime rule).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from fPLense import config
from fPLense.etl.ratings import RATING_SOURCE, fplense_rating, photo_url

HISTORY = config.HISTORY_DIR.name


class NotPublishedError(LookupError):
    """The published folder has no predictions yet (the pipeline hasn't run)."""


class Store:
    def __init__(self, root: Path | str = config.PUBLISHED_DIR):
        self.root = Path(root)
        self._cache: dict[tuple[Path, str], tuple[int, Any]] = {}
        self._lock = threading.Lock()

    # --- generic cached loading ---------------------------------------------------------------

    def _load(self, path: Path, loader: Callable[[Path], Any], tag: str = "") -> Any:
        try:
            mtime = path.stat().st_mtime_ns
        except FileNotFoundError:
            return None
        key = (path, tag)
        hit = self._cache.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        value = loader(path)
        with self._lock:
            self._cache[key] = (mtime, value)
        return value

    def json(self, rel: str) -> Any:
        return self._load(self.root / rel, lambda p: json.loads(p.read_text(encoding="utf-8")))

    def parquet(self, rel: str) -> pd.DataFrame | None:
        return self._load(self.root / rel, pd.read_parquet)

    # --- published files ----------------------------------------------------------------------

    def latest(self) -> dict:
        doc = self.json(config.LATEST_PATH.name)
        if not doc:
            raise NotPublishedError("no published predictions yet (run the pipeline's --predict)")
        return doc

    def predictions(self) -> pd.DataFrame:
        """The newest predictions with card rating and photo URL, indexed by player id."""
        latest = self.latest()
        rel = latest["files"]["predictions"]
        return self._load(self.root / rel, self._decorate, tag=f"decorated:{self._ratings_mtime()}")

    def _ratings_mtime(self) -> int:
        p = self.root / config.RATINGS_PATH.name
        return p.stat().st_mtime_ns if p.exists() else 0

    def _decorate(self, path: Path) -> pd.DataFrame:
        df = pd.read_parquet(path)
        ratings = self.json(config.RATINGS_PATH.name)
        if ratings:
            r = {int(k): v["rating"] for k, v in ratings["players"].items()}
            df["rating"] = df["element"].map(r)
            missing = df["rating"].isna()
            if missing.any():
                df.loc[missing, "rating"] = fplense_rating(df)[missing]
            df["rating_source"] = ratings.get("source", RATING_SOURCE)
        else:
            df["rating"] = fplense_rating(df)
            df["rating_source"] = RATING_SOURCE
        df["rating"] = df["rating"].astype("int64")
        df["photo_url"] = [photo_url(c) for c in df["code"]]
        return df.set_index("element", drop=False)

    def shap(self) -> pd.DataFrame | None:
        df = self.parquet(self.latest()["files"]["shap"])
        return None if df is None else df.set_index("element", drop=False)

    def squad_next(self) -> dict | None:
        return self.json(self.latest()["files"]["squad"])

    def metrics(self) -> dict | None:
        return self.json(config.METRICS_PATH.name)

    def mae_by_gw(self) -> dict | None:
        return self.json(config.MAE_BY_GW_PATH.name)

    def shap_importance(self) -> dict | None:
        return self.json(config.SHAP_IMPORTANCE_PATH.name)

    def backtest(self) -> dict | None:
        return self.json(config.BACKTEST_PATH.name)

    def fixtures(self) -> list[dict]:
        doc = self.json(config.FIXTURES_PUBLISHED_PATH.name)
        return doc["fixtures"] if doc else []

    def actuals(self) -> pd.DataFrame | None:
        return self.parquet(config.ACTUALS_PATH.name)

    def season(self) -> dict | None:
        return self.json(f"{HISTORY}/season.json")

    def summary(self) -> dict | None:
        return self.json(f"{HISTORY}/summary.json")

    # --- the per-GW archive -------------------------------------------------------------------

    def archived_gws(self) -> list[int]:
        root = self.root / HISTORY
        if not root.exists():
            return []
        return sorted(
            int(d.name[2:])
            for d in root.iterdir()
            if d.is_dir() and d.name.startswith("gw") and (d / "predictions.parquet").exists()
        )

    def archive(self, gw: int) -> dict | None:
        d = f"{HISTORY}/gw{int(gw):02d}"
        preds = self.parquet(f"{d}/predictions.parquet")
        if preds is None:
            return None
        return {
            "predictions": preds.set_index("element", drop=False),
            "squad": self.json(f"{d}/squad_pred.json"),
            "meta": self.json(f"{d}/meta.json") or {},
            "hindsight": self.json(f"{d}/squad_hindsight.json"),
        }

    def finished_gws(self) -> list[int]:
        season = self.season()
        if not season:
            return []
        return [e["gw"] for e in season["events"] if e["finished"]]

    def generated_at(self) -> str | None:
        try:
            return self.latest().get("generated_at")
        except NotPublishedError:
            return None
