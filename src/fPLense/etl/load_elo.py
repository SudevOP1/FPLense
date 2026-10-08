"""Download ClubElo ratings (Kaggle ``adamgbor/club-football-match-data-2000-2025``) to the lake.

``EloRatings.csv`` holds dated ClubElo snapshots (1st and 15th of each month). Kept: English
clubs from 2016-07-01 → ``data/lake/elo/part.parquet`` (``date, club, elo``). The feature views
take each team's latest snapshot dated strictly before its gameweek starts (DuckDB ``ASOF JOIN``).

Needs a Kaggle API token (PLAN.md §0.2): ``KAGGLE_USERNAME``/``KAGGLE_KEY`` or ``KAGGLE_API_TOKEN``
environment variables, ``~/.kaggle/kaggle.json`` or ``~/.kaggle/access_token``.

Licence: MIT (credit the dataset; ratings originate from clubelo.com).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from fPLense import config
from fPLense.etl.load_history import _load_manifest, _save_manifest, sha256

log = logging.getLogger(__name__)

TOKEN_HELP = "Kaggle token not found: see PLAN.md §0.2"

# ClubElo renamed Nottingham Forest in Jan 2025; the old name keeps a frozen copy afterwards.
# Rows are renamed to the canonical name and, where both exist on a date, the row that already
# used the canonical name wins.
CLUB_ALIASES = {"Nottm Forest": "Nott'm Forest"}


class KaggleTokenError(RuntimeError):
    """No usable Kaggle credentials."""


def kaggle_dir() -> Path:
    return Path(os.environ.get("KAGGLE_CONFIG_DIR", Path.home() / ".kaggle"))


def read_token_file(path: Path) -> str:
    """Read ``access_token``, tolerating UTF-16 (what PowerShell's ``>`` redirect writes)."""
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        text = data.decode("utf-8-sig")
    return text.strip()


def kaggle_env(environ: dict[str, str] | None = None, config_dir: Path | None = None) -> dict:
    """Environment for the ``kaggle`` CLI, or :class:`KaggleTokenError` if no token exists."""
    env = dict(os.environ if environ is None else environ)
    if env.get("KAGGLE_API_TOKEN") or (env.get("KAGGLE_USERNAME") and env.get("KAGGLE_KEY")):
        return env
    config_dir = config_dir or kaggle_dir()
    token = config_dir / "access_token"
    if token.exists():
        # passed explicitly so a UTF-16 file still works (the CLI itself would crash on it)
        env["KAGGLE_API_TOKEN"] = read_token_file(token)
        if env["KAGGLE_API_TOKEN"]:
            return env
    if (config_dir / "kaggle.json").exists():
        return env
    raise KaggleTokenError(TOKEN_HELP)


def raw_path() -> Path:
    return config.RAW_DIR / "kaggle" / config.ELO_KAGGLE_FILE


def download_elo(*, force: bool = False) -> Path:
    dest = raw_path()
    if dest.exists() and not force:
        log.info("skip (exists) %s", dest)
        return dest
    env = kaggle_env()
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "kaggle",
        "datasets",
        "download",
        "-d",
        config.ELO_KAGGLE_DATASET,
        "-f",
        config.ELO_KAGGLE_FILE,
        "-p",
        str(dest.parent),
        "--force",
    ]
    log.info("kaggle download %s/%s", config.ELO_KAGGLE_DATASET, config.ELO_KAGGLE_FILE)
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-1:]
        raise RuntimeError(f"kaggle download failed: {' '.join(tail)} ({TOKEN_HELP} if auth)")
    zipped = dest.with_name(dest.name + ".zip")
    if zipped.exists():  # older CLI versions zip single-file downloads
        with zipfile.ZipFile(zipped) as zf:
            zf.extract(config.ELO_KAGGLE_FILE, dest.parent)
        zipped.unlink()
    manifest = _load_manifest()
    manifest[dest.relative_to(config.RAW_DIR).as_posix()] = {
        "url": f"kaggle://{config.ELO_KAGGLE_DATASET}/{config.ELO_KAGGLE_FILE}",
        "sha256": sha256(dest),
        "bytes": dest.stat().st_size,
        "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _save_manifest(manifest)
    return dest


def clean_elo(raw: pd.DataFrame) -> pd.DataFrame:
    """English clubs from ``ELO_START_DATE``: ``date`` (date), ``club``, ``elo``; aliases merged."""
    df = raw.rename(columns=str.lower)
    df = df[(df["country"] == config.ELO_COUNTRY)].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[df["date"] >= pd.Timestamp(config.ELO_START_DATE).date()]
    df["canonical"] = ~df["club"].isin(CLUB_ALIASES)
    df["club"] = df["club"].replace(CLUB_ALIASES)
    df = df.sort_values(["date", "club", "canonical"]).drop_duplicates(
        ["date", "club"], keep="last"
    )
    df["elo"] = pd.to_numeric(df["elo"]).astype("float64")
    return df[["date", "club", "elo"]].reset_index(drop=True)


def build_elo_lake() -> int:
    df = clean_elo(pd.read_csv(raw_path()))
    out = config.ELO_DIR / "part.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    log.info("elo: %d snapshots rows (%s .. %s) -> %s", len(df), df.date.min(), df.date.max(), out)
    return len(df)


def refresh_elo(*, force: bool = False) -> int:
    download_elo(force=force)
    return build_elo_lake()
