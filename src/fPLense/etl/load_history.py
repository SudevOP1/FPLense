"""Download the vaastav/Fantasy-Premier-League history, normalise it and write the Parquet lake.

Raw files land in ``data/raw/vaastav/<season>/`` with SHA-256 hashes in ``data/raw/manifest.json``.
Files already downloaded are skipped unless ``force=True``.

Source: https://github.com/vaastav/Fantasy-Premier-League (cite as its README asks).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from fPLense import config
from fPLense.etl import net
from fPLense.etl.normalize import normalize_season

log = logging.getLogger(__name__)

# 2016-17..2018-19 files are latin-1, 2019-20+ are UTF-8 (reading those as latin-1 garbles
# accented names, e.g. "é"), so try UTF-8 first.
ENCODINGS = ("utf-8", "latin-1")


def season_files(season: str) -> list[str]:
    """Relative paths (under ``data/<season>/`` in the repo) to download for one season."""
    files = ["gws/merged_gw.csv", "players_raw.csv"]
    if season >= config.FIRST_SEASON_WITH_FIXTURES:
        files.append("fixtures.csv")
    if season >= config.FIRST_SEASON_WITH_TEAMS:
        files.append("teams.csv")  # master_team_list.csv stops at 2023-24
    return files


def raw_path(season: str | None, rel: str) -> Path:
    base = config.RAW_DIR / "vaastav"
    return base / rel if season is None else base / season / rel


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest() -> dict:
    if config.MANIFEST_PATH.exists():
        return json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


def _save_manifest(manifest: dict) -> None:
    config.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), "utf-8")


def download(url: str, dest: Path, manifest: dict, *, force: bool = False, session=None) -> Path:
    key = dest.relative_to(config.RAW_DIR).as_posix()
    if dest.exists() and not force:
        log.info("skip (exists) %s", key)
        manifest.setdefault(key, {"url": url, "sha256": sha256(dest)})
        return dest
    log.info("download %s", url)
    resp = net.get(url, session)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    manifest[key] = {
        "url": url,
        "sha256": sha256(dest),
        "bytes": dest.stat().st_size,
        "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    return dest


def download_history(seasons: list[str] | None = None, *, force: bool = False) -> None:
    seasons = seasons or config.SEASONS
    manifest = _load_manifest()
    session = net.make_session()
    try:
        download(
            f"{config.VAASTAV_BASE_URL}/master_team_list.csv",
            raw_path(None, "master_team_list.csv"),
            manifest,
            force=force,
            session=session,
        )
        for season in seasons:
            for rel in season_files(season):
                download(
                    f"{config.VAASTAV_BASE_URL}/{season}/{rel}",
                    raw_path(season, rel),
                    manifest,
                    force=force,
                    session=session,
                )
    finally:
        _save_manifest(manifest)


def read_csv(path: Path) -> pd.DataFrame:
    for encoding in ENCODINGS[:-1]:
        try:
            return pd.read_csv(path, encoding=encoding, low_memory=False)
        except UnicodeDecodeError:
            log.debug("%s is not %s, retrying", path.name, encoding)
    return pd.read_csv(path, encoding=ENCODINGS[-1], low_memory=False)


def build_lake(seasons: list[str] | None = None) -> dict[str, int]:
    """Normalise each downloaded season and write ``player_match/season=…/part.parquet``.

    Returns ``{season: rows written}``.
    """
    seasons = seasons or config.SEASONS
    teams = read_csv(raw_path(None, "master_team_list.csv"))
    counts: dict[str, int] = {}
    for season in seasons:
        fixtures_path = raw_path(season, "fixtures.csv")
        teams_path = raw_path(season, "teams.csv")
        df = normalize_season(
            read_csv(raw_path(season, "gws/merged_gw.csv")),
            season=season,
            players_raw=read_csv(raw_path(season, "players_raw.csv")),
            master_team_list=teams,
            fixtures=read_csv(fixtures_path) if fixtures_path.exists() else None,
            teams=read_csv(teams_path) if teams_path.exists() else None,
        )
        out = config.PLAYER_MATCH_DIR / f"season={season}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        # hive layout: ``season`` lives in the directory name, not inside the file
        df.drop(columns="season").to_parquet(out, index=False)
        counts[season] = len(df)
        log.info("%s: %d rows -> %s", season, len(df), out)
    return counts


def read_player_match(seasons: list[str] | None = None) -> pd.DataFrame:
    """Read the player_match lake back into one frame, with ``season`` as a plain string."""
    filters = [("season", "in", seasons)] if seasons else None
    df = pd.read_parquet(config.PLAYER_MATCH_DIR, partitioning="hive", filters=filters)
    df["season"] = df["season"].astype(str)
    return df[["season", *[c for c in df.columns if c != "season"]]]


def refresh_history(seasons: list[str] | None = None, *, force: bool = False) -> dict[str, int]:
    download_history(seasons, force=force)
    return build_lake(seasons)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    parser.add_argument("--seasons", nargs="*", help="subset of seasons, e.g. 2024-25 2025-26")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    counts = refresh_history(args.seasons, force=args.force)
    print(f"total rows: {sum(counts.values()):,}")


if __name__ == "__main__":
    main()
