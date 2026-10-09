"""Season-history archive (PLAN.md §8 P6): what the model said before each gameweek, what it
would have picked, what actually happened, and the best squad in hindsight.

``data/published/history/gwXX/`` (one folder per gameweek, **write-once**):

- ``predictions.parquet``: per player ``element, code, web_name, pos, club, club_short, price``
  (integer tenths at that GW), ``p`` (expected points for that GW), ``P_h`` (horizon), the
  ``availability`` used.
- ``squad_pred.json``: the model's best squad for the GW (£100m, horizon 5, bench weight 0.1).
- ``meta.json``: ``made_at``, ``model_sha256``, ``model_train_max_season``, ``source`` =
  ``"live"`` (written by ``--predict`` before the deadline) or ``"backfill"`` (rebuilt as-of).
- ``squad_hindsight.json``: the best legal £100m squad on *actual* points (once the GW is over).

A folder that exists is never rewritten (only with ``force``), so a retrain can't change what the
model "said" in the past.

**As-of backfill** for gameweeks that finished before the archive existed: features from the live
lake truncated to fixtures before GW k (the P2 leakage-test mechanism, via the same views as
``predict.py``), prices and clubs from that GW's lake rows, bookmaker odds only for GW k's own
fixtures (pre-closing ``E0.csv`` rows; later horizon GWs use the Elo estimate, like the live path),
Elo snapshots only from before GW k. Availability is unknown for past GWs: backfilled rows use
100% and are labelled ``backfill``. Backfill is refused when the model was trained on the current
season (it would have seen the outcomes).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from fPLense import config

log = logging.getLogger(__name__)

ARCHIVE_COLUMNS = [
    "element",
    "code",
    "web_name",
    "pos",
    "club",
    "club_short",
    "price",
    "p",
    "P_h",
    "availability",
]
PREDICTIONS_FILE = "predictions.parquet"
SQUAD_PRED_FILE = "squad_pred.json"
SQUAD_HINDSIGHT_FILE = "squad_hindsight.json"
META_FILE = "meta.json"
SUMMARY_FILE = "summary.json"
SEASON_FILE = "season.json"


class ArchiveExistsError(FileExistsError):
    """The gameweek is already archived (the archive is write-once; use force to overwrite)."""


class BackfillRefusedError(RuntimeError):
    """The model saw the gameweek's outcomes, so an as-of prediction would be a lie."""


# --- model identity ---------------------------------------------------------------------------


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_model_meta(
    train_max_season: str,
    model_path: Path = config.MODEL_PATH,
    meta_path: Path = config.MODEL_META_PATH,
    trees: int | None = None,
) -> dict:
    """Record which data ``model.txt`` was trained on (read back by every archive write)."""
    doc = {
        "model_sha256": sha256(model_path),
        "train_max_season": train_max_season,
        "trees": trees,
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    Path(meta_path).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def read_model_meta(
    model_path: Path = config.MODEL_PATH, meta_path: Path = config.MODEL_META_PATH
) -> dict:
    """``model_meta.json``, checked against the model file it describes."""
    if not Path(meta_path).exists():
        raise FileNotFoundError(
            f"{meta_path} not found: run `python -m fPLense.pipeline --train` to write it"
        )
    meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    if meta["model_sha256"] != sha256(model_path):
        raise RuntimeError(
            f"{meta_path} describes a different model than {model_path}; rerun --train"
        )
    return meta


def check_backfill_allowed(train_max_season: str, season: str = config.CURRENT_SEASON) -> None:
    if train_max_season >= season:
        raise BackfillRefusedError(
            f"the model was trained on data up to {train_max_season}, so it has seen {season}'s "
            "outcomes; an as-of backfill would leak them"
        )


# --- the write-once archive -------------------------------------------------------------------


def archived_gws(root: Path = config.HISTORY_DIR) -> list[int]:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(
        int(d.name[2:])
        for d in root.iterdir()
        if d.is_dir() and d.name.startswith("gw") and (d / PREDICTIONS_FILE).exists()
    )


def write_archive(
    gw: int,
    predictions: pd.DataFrame,
    squad: dict,
    meta: dict,
    root: Path = config.HISTORY_DIR,
    force: bool = False,
) -> Path:
    """Write ``history/gwXX/`` once. Raises ``ArchiveExistsError`` if it's there (unless forced)."""
    d = config.history_gw_dir(gw, root)
    if (d / PREDICTIONS_FILE).exists() and not force:
        raise ArchiveExistsError(f"{d} is already archived (write-once; use --force-history)")
    missing = [c for c in ARCHIVE_COLUMNS if c not in predictions]
    if missing:
        raise ValueError(f"archive predictions are missing {missing}")
    if meta.get("source") not in {"live", "backfill"}:
        raise ValueError("meta.source must be 'live' or 'backfill'")
    d.mkdir(parents=True, exist_ok=True)
    df = predictions[ARCHIVE_COLUMNS].copy()
    df["price"] = df["price"].astype("int64")
    df.to_parquet(d / PREDICTIONS_FILE, index=False)
    _write_json(d / SQUAD_PRED_FILE, squad)
    _write_json(d / META_FILE, {"gw": int(gw), **meta})
    return d


def archive_frame(table: pd.DataFrame, gw: int) -> pd.DataFrame:
    """A published predictions table -> the archive's columns for GW ``gw``."""
    out = table.copy()
    out["p"] = out[f"p_gw{gw:02d}"].astype(float)
    return out[ARCHIVE_COLUMNS].reset_index(drop=True)


def archive_live(
    table: pd.DataFrame,
    squad: dict,
    gw: int,
    made_at: str,
    model_meta: dict,
    root: Path = config.HISTORY_DIR,
) -> Path | None:
    """Archive a live prediction run for GW ``gw``; a GW already archived is left alone."""
    meta = {
        "made_at": made_at,
        "model_sha256": model_meta["model_sha256"],
        "model_train_max_season": model_meta["train_max_season"],
        "source": "live",
        "horizon_gws": squad.get("gws"),
    }
    try:
        return write_archive(gw, archive_frame(table, gw), squad, meta, root)
    except ArchiveExistsError:
        log.info("GW%d already archived; the archive is write-once", gw)
        return None


def archive_source(gw: int, root: Path = config.HISTORY_DIR) -> str | None:
    meta = _read_json(config.history_gw_dir(gw, root) / META_FILE)
    return meta.get("source") if meta else None


def read_archive(gw: int, root: Path = config.HISTORY_DIR) -> dict[str, Any]:
    d = config.history_gw_dir(gw, root)
    hind = d / SQUAD_HINDSIGHT_FILE
    return {
        "predictions": pd.read_parquet(d / PREDICTIONS_FILE),
        "squad": _read_json(d / SQUAD_PRED_FILE),
        "meta": _read_json(d / META_FILE),
        "hindsight": _read_json(hind) if hind.exists() else None,
    }


# --- as-of backfill ---------------------------------------------------------------------------


def players_at(
    players: pd.DataFrame, history: pd.DataFrame, teams: pd.DataFrame, gw: int
) -> pd.DataFrame:
    """The player list as it stood at GW ``gw``: club and price from that GW's lake rows.

    A player without a GW ``gw`` row (his club blanked) keeps his latest earlier row; players
    whose first row comes after ``gw`` weren't in the game yet and are dropped. Availability is
    unknown for a past GW: status ``a``, chance NaN (= 100%).
    """
    h = history[history["gw"] <= gw].sort_values(["gw", "kickoff_time", "fixture"])
    last = h.groupby("element").tail(1).set_index("element")
    out = players[players["element"].isin(last.index)].copy()
    rows = last.loc[out["element"]]
    names = teams.set_index("team_id")
    out["team_id"] = rows["team_id"].astype("int64").to_numpy()
    out["team"] = out["team_id"].map(names["team"]).to_numpy()
    out["team_short"] = out["team_id"].map(names["team_short"]).to_numpy()
    out["now_cost"] = rows["value"].astype("int64").to_numpy()
    out["price"] = out["now_cost"] / 10
    out["status"] = "a"
    out["chance_of_playing_next_round"] = np.nan
    out["news"] = ""
    return out.reset_index(drop=True)


def gw_start_date(fixtures: pd.DataFrame, gw: int) -> pd.Timestamp:
    """The GW's first kick-off date (UTC, naive): Elo is taken strictly before it."""
    ko = fixtures.loc[fixtures["gw"] == gw, "kickoff_time"].min()
    return ko.tz_convert("UTC").normalize().tz_localize(None)


def backfill_inputs(
    history: pd.DataFrame,
    fixtures: pd.DataFrame,
    played_odds: pd.DataFrame | None,
    elo: pd.DataFrame,
    names: pd.DataFrame,
    elo_model,
    gw: int,
    gws: list[int],
) -> dict[str, Any]:
    """Everything known at GW ``gw``'s deadline: earlier history, odds, Elo."""
    from fPLense.models.predict import fixture_names, upcoming_odds

    hist = history[history["gw"] < gw].copy()
    cutoff = gw_start_date(fixtures, gw)
    elo_k = elo[pd.to_datetime(elo["date"]) < cutoff].copy()
    upcoming = fixtures[fixtures["gw"].isin(gws)]
    played = played_odds if played_odds is not None else pd.DataFrame()
    nm = names.set_index("fpl_name")["fd_name"]
    fx = fixture_names(upcoming)
    keys = set(zip(fx["home"].map(nm), fx["away"].map(nm), strict=True))
    gw_keys = set(
        zip(
            fx.loc[fx["gw"] == gw, "home"].map(nm),
            fx.loc[fx["gw"] == gw, "away"].map(nm),
            strict=True,
        )
    )
    if len(played):
        pair = list(zip(played["home_team"], played["away_team"], strict=True))
        # bookmaker odds are known only for the GW's own round (football-data collects them
        # the Friday before); later horizon GWs use the Elo estimate, as the live path does
        fd_rows = played[[p in gw_keys for p in pair]]
        earlier = played[[p not in keys for p in pair]]
    else:
        fd_rows, earlier = pd.DataFrame(), pd.DataFrame()
    new_odds, sources = upcoming_odds(upcoming, fd_rows, elo_model, elo_k, names)
    odds = pd.concat([d for d in (earlier, new_odds) if len(d)], ignore_index=True)
    return {"history": hist, "odds": odds, "sources": sources, "elo": elo_k}


def backfill_gw(
    gw: int,
    live: dict[str, Any],
    model,
    model_meta: dict,
    elo: pd.DataFrame,
    names: pd.DataFrame,
    elo_model,
    played_odds: pd.DataFrame | None,
    horizon: int = config.HISTORY_HORIZON,
    root: Path = config.HISTORY_DIR,
    force: bool = False,
) -> Path:
    """Rebuild GW ``gw``'s predictions and model pick as of its deadline and archive them."""
    from fPLense.models.predict import assemble, horizon_features, horizon_gws, squad_json
    from fPLense.models.train import lgbm_frame
    from fPLense.optimize.squad_ilp import pick_squad

    check_backfill_allowed(model_meta["train_max_season"])
    fixtures, teams = live["fixtures"], live["teams"]
    gws = horizon_gws(fixtures, gw, horizon)
    inp = backfill_inputs(live["history"], fixtures, played_odds, elo, names, elo_model, gw, gws)
    players = players_at(live["players"], live["history"], teams, gw)
    rows = horizon_features(inp["history"], players, fixtures, teams, gws, inp["odds"], inp["elo"])
    rows["pred"] = model.predict(lgbm_frame(rows))
    table = assemble(players, rows, fixtures, teams, inp["sources"], gws)
    pool = table.set_index("element")
    squad = squad_json(pick_squad(pool), pool, gw, gws)
    meta = {
        "made_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model_sha256": model_meta["model_sha256"],
        "model_train_max_season": model_meta["train_max_season"],
        "source": "backfill",
        "horizon_gws": gws,
        "data_before_gw": gw,
        "odds_sources": inp["sources"]
        .merge(fixtures[["fixture", "gw"]], on="fixture")
        .query("gw == @gw")["odds_source"]
        .value_counts()
        .to_dict(),
        "caveat": "rebuilt after the fact from data before this GW; availability unknown (100%)",
    }
    return write_archive(gw, archive_frame(table, gw), squad, meta, root, force=force)


# --- actuals, hindsight and the season summary ------------------------------------------------


def actuals(history: pd.DataFrame) -> pd.DataFrame:
    """Per (element, gw): ``total_points``, ``minutes``, ``price`` (tenths), ``fixtures``
    (club fixtures in the GW), ``fixtures_played`` (appearances), ``pos``, ``team_id``, ``team``."""
    h = history.sort_values(["gw", "kickoff_time", "fixture"])
    g = h.groupby(["element", "gw"], sort=True)
    out = g.agg(
        total_points=("total_points", "sum"),
        minutes=("minutes", "sum"),
        price=("value", "first"),
        fixtures=("fixture", "size"),
        fixtures_played=("minutes", lambda m: int((m > 0).sum())),
        pos=("position", "first"),
        team_id=("team_id", "first"),
        team=("team", "first"),
    ).reset_index()
    for c in ("total_points", "minutes", "price", "fixtures", "fixtures_played", "team_id"):
        out[c] = out[c].astype("int64")
    return out


def actual_pool(act: pd.DataFrame, gw: int) -> pd.DataFrame:
    """The GW's players as an ILP pool scored on actual points (``p1 = P_h = points``)."""
    a = act[act["gw"] == gw].set_index("element")
    return pd.DataFrame(
        {
            "pos": a["pos"],
            "club": a["team"],
            "price": a["price"].astype("int64"),
            "points": a["total_points"].astype(float),
            "minutes": a["minutes"],
            "p1": a["total_points"].astype(float),
            "P_h": a["total_points"].astype(float),
        }
    )


def hindsight_squad(pool: pd.DataFrame, budget: int = config.BUDGET) -> dict[str, Any]:
    """The best legal squad for one GW on actual points: same ILP and rules (£100m, 2-5-5-3,
    max 3 per club, that GW's prices), bench weight 0; captain = best actual starter.

    Not FPL's Dream Team, which ignores budget and quotas. Score = XI + captain bonus.
    """
    from fPLense.optimize.squad_ilp import pick_squad

    res = pick_squad(pool, budget=budget, bench_w=0.0, filter_unavailable=False)
    xi_points = int(pool.loc[res.starters, "points"].sum())
    captain_points = int(pool.at[res.captain, "points"])
    return {
        "squad": [int(i) for i in res.squad],
        "starters": [int(i) for i in res.starters],
        "bench": [int(i) for i in res.bench],
        "captain": int(res.captain),
        "vice": int(res.vice),
        "cost": int(res.cost),
        "points": xi_points + captain_points,
        "captain_points": captain_points,
    }


def squad_actual(squad: dict, act_gw: pd.DataFrame, pos: pd.Series) -> dict:
    """Actual points of an archived squad: auto-subs from the bench in order, captain doubled
    (vice if the captain didn't play). Players without a row this GW (club blanked) score 0."""
    from fPLense.optimize.squad_ilp import score_actual

    players = squad["players"]
    ids = [p["element"] for p in players]
    starters = [p["element"] for p in players if p["starter"]]
    bench = [p["element"] for p in sorted(players, key=lambda p: p["bench_order"] or 0)]
    bench = [i for i in bench if i not in set(starters)]
    a = act_gw.reindex(ids)
    p = pos.reindex(ids).fillna(pd.Series({q["element"]: q["pos"] for q in players}))
    actual = pd.DataFrame({"points": a["total_points"], "minutes": a["minutes"]}, index=ids)
    return score_actual(p, actual, starters, bench, squad["captain"], squad["vice"])


def expected_gw_points(squad: dict, preds: pd.DataFrame) -> float:
    """The model pick's expected points for its own GW: XI ``p`` + captain ``p`` again."""
    p = preds.set_index("element")["p"]
    xi = [q["element"] for q in squad["players"] if q["starter"]]
    return float(p.reindex(xi).fillna(0).sum() + p.get(squad["captain"], 0.0))


def summary_row(
    gw: int, archive: dict, hindsight: dict, act: pd.DataFrame, event: dict | None
) -> dict:
    act_gw = act[act["gw"] == gw].set_index("element")
    model = squad_actual(archive["squad"], act_gw, act_gw["pos"])
    best = hindsight["points"]
    shared = len(set(hindsight["squad"]) & {q["element"] for q in archive["squad"]["players"]})
    return {
        "gw": gw,
        "source": archive["meta"]["source"],
        "made_at": archive["meta"].get("made_at"),
        "model_expected": round(expected_gw_points(archive["squad"], archive["predictions"]), 2),
        "model_actual": model["points"],
        "model_cost": archive["squad"]["cost"],
        "hindsight_points": best,
        "hindsight_cost": hindsight["cost"],
        "shared_players": shared,
        "average_entry_score": (event or {}).get("average_entry_score"),
        "highest_score": (event or {}).get("highest_score"),
        "capture_ratio": round(model["points"] / best, 4) if best > 0 else None,
    }


def season_doc(bootstrap: dict) -> dict:
    """``history/season.json``: per GW deadline, finished flag, average and highest score."""
    events = []
    for e in sorted(bootstrap["events"], key=lambda e: e["id"]):
        events.append(
            {
                "gw": int(e["id"]),
                "deadline_time": e["deadline_time"],
                "finished": bool(e["finished"]),
                "data_checked": bool(e.get("data_checked", False)),
                "average_entry_score": e.get("average_entry_score"),
                "highest_score": e.get("highest_score"),
                "is_current": bool(e.get("is_current", False)),
                "is_next": bool(e.get("is_next", False)),
            }
        )
    finished = [e["gw"] for e in events if e["finished"]]
    nxt = next((e["gw"] for e in events if e["is_next"]), None)
    return {
        "season": config.CURRENT_SEASON,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "last_finished_gw": max(finished) if finished else 0,
        "next_gw": nxt,
        "events": events,
    }


def fixtures_doc(fixtures: pd.DataFrame, teams: pd.DataFrame) -> dict:
    """``fixtures.json``: the season's schedule, FDR and results (for fixture tickers)."""
    short = teams.set_index("team_id")["team_short"]
    rows = []
    for f in fixtures.sort_values(["kickoff_time", "fixture"]).itertuples(index=False):
        rows.append(
            {
                "fixture": int(f.fixture),
                "gw": int(f.gw),
                "kickoff_time": f.kickoff_time.isoformat(),
                "team_h": int(f.team_h),
                "team_a": int(f.team_a),
                "team_h_name": f.team_h_name,
                "team_a_name": f.team_a_name,
                "team_h_short": short.get(f.team_h),
                "team_a_short": short.get(f.team_a),
                "team_h_difficulty": _num(f.team_h_difficulty),
                "team_a_difficulty": _num(f.team_a_difficulty),
                "team_h_score": _num(f.team_h_score),
                "team_a_score": _num(f.team_a_score),
                "finished": bool(f.finished),
            }
        )
    return {"season": config.CURRENT_SEASON, "fixtures": rows}


# --- the --history run ------------------------------------------------------------------------


def run_history(
    force: bool = False,
    live_dir: Path = config.LIVE_DIR,
    out_dir: Path = config.PUBLISHED_DIR,
    bootstrap_path: Path = config.API_CACHE_DIR / "bootstrap-static.json",
) -> dict[str, Any]:
    """Archive every finished GW (live runs first, backfill for the rest), then actuals,
    hindsight squads, ``season.json``, ``fixtures.json`` and ``summary.json``."""
    from fPLense.models.explain import load_model
    from fPLense.models.predict import load_live

    t0 = datetime.now(UTC)
    root = Path(out_dir) / config.HISTORY_DIR.name
    live = load_live(live_dir)
    bootstrap = json.loads(Path(bootstrap_path).read_text(encoding="utf-8"))
    season = season_doc(bootstrap)
    done = [e["gw"] for e in season["events"] if e["finished"]]
    done = [g for g in done if g <= int(live["meta"].get("last_finished_gw") or 0)]
    model_meta = read_model_meta(
        Path(out_dir) / config.MODEL_PATH.name, Path(out_dir) / config.MODEL_META_PATH.name
    )
    report: dict[str, Any] = {"live_archived": [], "backfilled": [], "hindsight": []}

    # 1) live prediction files published before the archive existed
    latest = _read_json(Path(out_dir) / config.LATEST_PATH.name) or {}
    for path in sorted(Path(out_dir).glob("predictions_gw*.parquet")):
        gw = int(path.stem.removeprefix("predictions_gw"))
        squad_path = Path(out_dir) / config.squad_path(gw).name
        if not squad_path.exists() or gw in archived_gws(root):
            continue  # a live archive is never rewritten, not even with force
        made_at = latest.get("generated_at") if latest.get("gw") == gw else None
        made_at = made_at or datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        table = pd.read_parquet(path)
        squad = _read_json(squad_path)
        meta = {
            "made_at": made_at,
            "model_sha256": model_meta["model_sha256"],
            "model_train_max_season": model_meta["train_max_season"],
            "source": "live",
            "horizon_gws": squad.get("gws"),
        }
        write_archive(gw, archive_frame(table, gw), squad, meta, root)
        report["live_archived"].append(gw)

    # 2) as-of backfill for finished GWs that still have no archive
    # forcing rebuilds backfills only: a live archive is never replaced by a backfill
    have = archived_gws(root)
    todo = [g for g in done if g not in have or (force and archive_source(g, root) == "backfill")]
    if todo:
        from fPLense.db.build import build
        from fPLense.etl import elo_goals

        check_backfill_allowed(model_meta["train_max_season"])
        model = load_model(Path(out_dir) / config.MODEL_PATH.name)
        con = build(":memory:")
        try:
            elo_model = elo_goals.fit_from_views(con, config.SEASONS)
        finally:
            con.close()
        elo = pd.read_parquet(config.ELO_DIR / "part.parquet")
        names = pd.read_csv(config.TEAM_NAMES_PATH)
        odds_path = config.ODDS_DIR / f"season={config.CURRENT_SEASON}" / "part.parquet"
        played = pd.read_parquet(odds_path) if odds_path.exists() else None
        for gw in todo:
            backfill_gw(
                gw, live, model, model_meta, elo, names, elo_model, played, root=root, force=force
            )
            report["backfilled"].append(gw)
            log.info("backfilled GW%d", gw)

    # 3) actuals, hindsight squads, season/fixtures docs, summary
    act = actuals(live["history"])
    act.to_parquet(Path(out_dir) / config.ACTUALS_PATH.name, index=False)
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / SEASON_FILE, season)
    _write_json(
        Path(out_dir) / config.FIXTURES_PUBLISHED_PATH.name,
        fixtures_doc(live["fixtures"], live["teams"]),
    )
    events = {e["gw"]: e for e in season["events"]}
    rows = []
    for gw in done:
        if gw not in archived_gws(root):
            continue
        hind_path = config.history_gw_dir(gw, root) / SQUAD_HINDSIGHT_FILE
        if force or not hind_path.exists():
            _write_json(hind_path, {"gw": gw, **hindsight_squad(actual_pool(act, gw))})
            report["hindsight"].append(gw)
        rows.append(
            summary_row(gw, read_archive(gw, root), _read_json(hind_path), act, events.get(gw))
        )
    summary = {
        "season": config.CURRENT_SEASON,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": (
            "capture_ratio = model pick actual / hindsight-best: a product stat, not a claim; "
            "hindsight-best is the best legal £100m squad on actual points, not FPL's Dream Team"
        ),
        "gws": rows,
    }
    _write_json(root / SUMMARY_FILE, summary)
    report.update(
        summary=rows,
        archived=archived_gws(root),
        runtime_s=round((datetime.now(UTC) - t0).total_seconds(), 1),
    )
    return report


# --- helpers ----------------------------------------------------------------------------------


def _num(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def _write_json(path: Path, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, default=_json_default), encoding="utf-8")


def _read_json(path: Path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _json_default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")
