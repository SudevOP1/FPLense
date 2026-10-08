"""Download football-data.co.uk Premier League CSVs and write pre-match odds to the lake.

``data/raw/football_data/<code>/E0.csv`` (code ``1617`` = 2016-17) → ``data/lake/odds/season=…/``.

- **Closing odds are dropped at load** (any column whose bookmaker prefix is followed by ``C``,
  e.g. ``B365CH``, ``PSCA``, ``AvgC>2.5``, ``B365CAHH``, ``AHCh``). They are taken at kick-off,
  after the FPL deadline, so using them would be leakage.
- Fallback per match (PLAN.md §3e): market average (``Avg*``, or Betbrain ``BbAv*`` before
  2019-20), then Bet365 (``B365*``). Pinnacle is not used (missing for much of 2025-26).
- Implied goals / clean-sheet probability are added by :mod:`fPLense.etl.odds_features`.

Source: https://www.football-data.co.uk (free; attribute the site).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from fPLense import config
from fPLense.etl import net
from fPLense.etl.load_history import _load_manifest, _save_manifest, download
from fPLense.etl.odds_features import add_implied

log = logging.getLogger(__name__)

# <bookmaker or Max/Avg/Bb prefix> + "C" + <market suffix>, plus the closing Asian-handicap line
CLOSING_RE = re.compile(r"^[A-Za-z0-9]+C(H|D|A|>2\.5|<2\.5|AHH|AHA)$|^AHCh$")
ENCODINGS = ("utf-8-sig", "latin-1")  # newer files start with a UTF-8 BOM

# (output column, candidate source columns in priority order)
PRICE_COLUMNS: list[tuple[str, tuple[str, ...]]] = [
    ("avg_h", ("AvgH", "BbAvH")),
    ("avg_d", ("AvgD", "BbAvD")),
    ("avg_a", ("AvgA", "BbAvA")),
    ("avg_over", ("Avg>2.5", "BbAv>2.5")),
    ("avg_under", ("Avg<2.5", "BbAv<2.5")),
    ("b365_h", ("B365H",)),
    ("b365_d", ("B365D",)),
    ("b365_a", ("B365A",)),
    ("b365_over", ("B365>2.5",)),
    ("b365_under", ("B365<2.5",)),
]

LAKE_COLUMNS = [
    "date",
    "time",
    "home_team",
    "away_team",
    "fthg",
    "ftag",
    *[c for c, _ in PRICE_COLUMNS],
    "odds_h",
    "odds_d",
    "odds_a",
    "odds_over",
    "odds_under",
    "source_1x2",
    "source_ou",
    "p_home",
    "p_draw",
    "p_away",
    "p_over",
    "mu",
    "lam_home",
    "lam_away",
    "p_cs_home",
    "p_cs_away",
]


def drop_closing(df: pd.DataFrame) -> pd.DataFrame:
    closing = [c for c in df.columns if CLOSING_RE.match(str(c))]
    return df.drop(columns=closing)


def parse_dates(s: pd.Series) -> pd.Series:
    """``dd/mm/yy`` (2016-17) or ``dd/mm/yyyy`` (later), day first."""
    s = s.astype(str).str.strip()
    short = s.str.len() == 8
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    out[short] = pd.to_datetime(s[short], format="%d/%m/%y")
    out[~short] = pd.to_datetime(s[~short], format="%d/%m/%Y")
    return out


def _choose(df: pd.DataFrame, first: list[str], second: list[str], names: list[str]):
    """Per row, take the ``first`` price set if complete, else ``second``; return source label."""
    a = df[first].to_numpy(dtype=float)
    b = df[second].to_numpy(dtype=float)
    use_a = ~np.isnan(a).any(axis=1)
    use_b = ~use_a & ~np.isnan(b).any(axis=1)
    chosen = np.where(use_a[:, None], a, np.where(use_b[:, None], b, np.nan))
    for i, name in enumerate(names):
        df[name] = chosen[:, i]
    return np.where(use_a, "avg", np.where(use_b, "b365", None))


def clean_odds(raw: pd.DataFrame) -> pd.DataFrame:
    """One football-data CSV (any season) → lake columns, closing odds removed first."""
    df = drop_closing(raw)
    if "Div" in df.columns:
        df = df[df["Div"] == "E0"]
    df = df.dropna(subset=["HomeTeam", "AwayTeam"]).copy()
    out = pd.DataFrame(index=df.index)
    out["date"] = parse_dates(df["Date"])
    out["time"] = df["Time"] if "Time" in df.columns else pd.NA
    out["time"] = out["time"].astype("string")  # no Time column before 2019-20
    out["home_team"] = df["HomeTeam"].astype(str).str.strip()
    out["away_team"] = df["AwayTeam"].astype(str).str.strip()
    for col in ("FTHG", "FTAG"):
        out[col.lower()] = pd.to_numeric(df[col], errors="coerce") if col in df else np.nan
    for name, candidates in PRICE_COLUMNS:
        src = next((c for c in candidates if c in df.columns), None)
        out[name] = pd.to_numeric(df[src], errors="coerce") if src else np.nan
    out["source_1x2"] = _choose(
        out,
        ["avg_h", "avg_d", "avg_a"],
        ["b365_h", "b365_d", "b365_a"],
        ["odds_h", "odds_d", "odds_a"],
    )
    out["source_ou"] = _choose(
        out, ["avg_over", "avg_under"], ["b365_over", "b365_under"], ["odds_over", "odds_under"]
    )
    out = add_implied(out)
    out["source_1x2"] = out["source_1x2"].astype("string")
    out["source_ou"] = out["source_ou"].astype("string")
    return out[LAKE_COLUMNS].reset_index(drop=True)


def raw_path(season: str) -> Path:
    return config.RAW_DIR / "football_data" / config.fd_season_code(season) / "E0.csv"


def read_csv(path: Path) -> pd.DataFrame:
    for encoding in ENCODINGS[:-1]:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            log.debug("%s is not %s, retrying", path, encoding)
    return pd.read_csv(path, encoding=ENCODINGS[-1])


def download_odds(seasons: list[str], *, force: bool = False) -> None:
    manifest = _load_manifest()
    session = net.make_session()
    try:
        for season in seasons:
            url = f"{config.FOOTBALL_DATA_BASE_URL}/{config.fd_season_code(season)}/E0.csv"
            # the in-progress season's file grows every week: always re-fetch it
            again = force or season == config.CURRENT_SEASON
            download(url, raw_path(season), manifest, force=again, session=session)
    finally:
        _save_manifest(manifest)


def build_odds_lake(seasons: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for season in seasons:
        df = clean_odds(read_csv(raw_path(season)))
        if season in config.SEASONS and len(df) != config.MATCHES_PER_SEASON:
            raise ValueError(
                f"{season}: expected {config.MATCHES_PER_SEASON} matches, got {len(df)}"
            )
        out = config.ODDS_DIR / f"season={season}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out, index=False)
        counts[season] = len(df)
        missing = int(df["lam_home"].isna().sum())
        log.info("%s: %d matches (%d without implied goals) -> %s", season, len(df), missing, out)
    return counts


def fetch_upcoming_odds(session=None) -> pd.DataFrame:
    """Next-round Premier League odds from ``fixtures.csv`` (``Div == "E0"``), closing columns
    dropped, implied goals added. Empty (with lake columns) when the file has no E0 rows, e.g.
    during an international break."""
    import io

    resp = net.get(config.FOOTBALL_DATA_FIXTURES_URL, session)
    raw = None
    for encoding in ENCODINGS:
        try:
            raw = pd.read_csv(io.BytesIO(resp.content), encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    return upcoming_from_frame(raw)


def upcoming_from_frame(raw: pd.DataFrame | None) -> pd.DataFrame:
    if raw is None or "Div" not in raw or not (raw["Div"] == "E0").any():
        return pd.DataFrame(columns=LAKE_COLUMNS)
    return clean_odds(raw[raw["Div"] == "E0"])


def read_odds(seasons: list[str] | None = None) -> pd.DataFrame:
    filters = [("season", "in", seasons)] if seasons else None
    df = pd.read_parquet(config.ODDS_DIR, partitioning="hive", filters=filters)
    df["season"] = df["season"].astype(str)
    return df


def refresh_odds(
    seasons: list[str] | None = None, *, force: bool = False, current: bool = True
) -> dict[str, int]:
    """Download and build the odds lake for the 10 seasons (plus the current one if ``current``)."""
    seasons = list(seasons or config.SEASONS)
    if current and config.CURRENT_SEASON not in seasons:
        seasons.append(config.CURRENT_SEASON)
    download_odds(seasons, force=force)
    return build_odds_lake(seasons)
