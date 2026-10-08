"""Next-N-gameweek expected points for every player (PLAN.md §8 P5).

Feature rows for upcoming fixtures are built by the **same DuckDB views** as the training data:
each upcoming fixture is appended to the current season's lake as a row with every outcome
blanked (exactly what the P2 leakage test proves is safe), and ``v_features`` is read back for
that gameweek. One view build per horizon gameweek, each over *history + that GW's fixtures*, so
every horizon GW sees the form as it stands today (a later GW never averages over blank rows).
``days_rest`` for GW 2+ of the horizon comes from the fixture schedule instead (the view would
count from the player's last played match).

Per player: per-fixture predictions → summed per GW (double GW = 2 fixtures, blank GW = 0) →
multiplied by availability (``chance_of_playing_next_round / 100``, NaN = 100%, status ``u`` = 0)
→ ``P_h`` = discounted sum over the horizon. The next GW's SHAP values (summed over its fixtures)
are published with the predictions; the squad ILP runs with default settings.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from fPLense import config
from fPLense.etl.fetch_api import _finish_rows
from fPLense.etl.normalize import COLUMNS, SCHEMA

log = logging.getLogger(__name__)

# Everything a row only learns after the deadline (same list as tests/test_no_leakage.py).
OUTCOME_COLUMNS = [
    "minutes",
    "total_points",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "own_goals",
    "penalties_saved",
    "penalties_missed",
    "yellow_cards",
    "red_cards",
    "saves",
    "bonus",
    "bps",
    "influence",
    "creativity",
    "threat",
    "ict_index",
    "starts",
    "expected_goals",
    "expected_assists",
    "expected_goal_involvements",
    "expected_goals_conceded",
    "defensive_contribution",
    "clearances_blocks_interceptions",
    "recoveries",
    "tackles",
    "team_h_score",
    "team_a_score",
    "team_score",
    "opp_score",
    "selected",
    "transfers_in",
    "transfers_out",
    "transfers_balance",
]


# --- small pure pieces (unit-tested) ----------------------------------------------------------


def availability(players: pd.DataFrame) -> pd.Series:
    """Chance of playing as a 0..1 multiplier: NaN = 100%, status ``u`` (left/unavailable) = 0."""
    chance = pd.to_numeric(players["chance_of_playing_next_round"], errors="coerce")
    avail = (chance.fillna(100.0) / 100.0).clip(0.0, 1.0)
    if "status" in players:
        avail = avail.where(players["status"].astype(str) != "u", 0.0)
    return avail.astype(float)


def gw_points(per_fixture: pd.DataFrame, elements, gws: list[int]) -> pd.DataFrame:
    """Sum per-fixture predictions per (player, GW): rows = ``elements``, columns = ``gws``.

    A double GW adds its two fixtures; a blank GW (no fixture) is 0.
    """
    if len(per_fixture):
        wide = per_fixture.pivot_table(
            index="element", columns="gw", values="pred", aggfunc="sum", fill_value=0.0
        )
    else:
        wide = pd.DataFrame()
    return wide.reindex(index=list(elements), columns=list(gws), fill_value=0.0).fillna(0.0)


def should_refresh(
    deadline: pd.Timestamp | None,
    now: pd.Timestamp,
    already_published: bool,
    force: bool = False,
    window_hours: float = config.REFRESH_WINDOW_HOURS,
) -> tuple[bool, str]:
    """Run only when the next deadline is < ``window_hours`` away and it isn't published yet."""
    if force:
        return True, "forced"
    if deadline is None:
        return False, "season over: no next gameweek"
    left = (pd.Timestamp(deadline) - pd.Timestamp(now)).total_seconds() / 3600
    if left < 0:
        return False, "next deadline already passed"
    if left > window_hours:
        return False, f"next deadline is {left:.0f}h away (> {window_hours:.0f}h)"
    if already_published:
        return False, "predictions for the next gameweek already exist"
    return True, f"next deadline in {left:.0f}h"


def schedule_rest(fixtures: pd.DataFrame) -> pd.DataFrame:
    """``(fixture, team_id, days_rest)`` from the schedule: days since the club's previous fixture
    (calendar days in UTC, like ``date_diff('day', ...)`` in ``v_player_form``)."""
    sides = pd.concat(
        [
            fixtures[["fixture", "kickoff_time", "team_h"]].rename(columns={"team_h": "team_id"}),
            fixtures[["fixture", "kickoff_time", "team_a"]].rename(columns={"team_a": "team_id"}),
        ]
    ).sort_values(["team_id", "kickoff_time", "fixture"])
    day = sides["kickoff_time"].dt.tz_convert("UTC").dt.normalize()
    sides["days_rest"] = (day - day.groupby(sides["team_id"]).shift()).dt.days
    return sides[["fixture", "team_id", "days_rest"]]


def future_rows(
    players: pd.DataFrame,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    season: str = config.CURRENT_SEASON,
) -> pd.DataFrame:
    """One lake-format row per (player, upcoming fixture of his club), every outcome blanked.

    Known before the deadline and kept: identity, fixture, kick-off, venue, FDR, price.
    """
    parts = []
    for side, home in (("team_h", True), ("team_a", False)):
        f = fixtures[["fixture", "gw", "kickoff_time", side]].rename(columns={side: "team_id"})
        p = players[["element", "name", "position", "team_id", "now_cost"]].merge(f, on="team_id")
        p["was_home"] = home
        parts.append(p)
    df = pd.concat(parts, ignore_index=True).drop(columns="team_id")
    df = df.rename(columns={"now_cost": "value"})
    for c in OUTCOME_COLUMNS:
        df[c] = np.nan
    df = _finish_rows(df, season, fixtures, teams)
    df[OUTCOME_COLUMNS] = np.nan  # derive_scores filled team/opp score from the blank inputs
    return _lake_types(df)


def _lake_types(df: pd.DataFrame) -> pd.DataFrame:
    """Lake column order/types, but outcomes as float64 so they can be NULL."""
    for col, kind in SCHEMA:
        if col in OUTCOME_COLUMNS:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        elif kind == "int":
            df[col] = pd.to_numeric(df[col]).astype("int64")
        elif kind == "float":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        elif kind == "str":
            df[col] = df[col].astype("string")
        elif kind == "ts":
            df[col] = pd.to_datetime(df[col], utc=True)
        elif kind == "bool":
            df[col] = df[col].astype(bool)
    return df[COLUMNS]


# --- odds for upcoming fixtures ---------------------------------------------------------------


def fixture_names(fixtures: pd.DataFrame) -> pd.DataFrame:
    """``fixture, gw, home, away, date``; ``date`` = the GW's first kick-off (Elo cut-off)."""
    gw_start = fixtures.groupby("gw")["kickoff_time"].transform("min")
    return pd.DataFrame(
        {
            "fixture": fixtures["fixture"].to_numpy(),
            "gw": fixtures["gw"].to_numpy(),
            "home": fixtures["team_h_name"].to_numpy(),
            "away": fixtures["team_a_name"].to_numpy(),
            "date": gw_start.dt.tz_convert("UTC").dt.normalize().dt.tz_localize(None).to_numpy(),
        }
    )


def upcoming_odds(
    upcoming: pd.DataFrame,
    fd_rows: pd.DataFrame,
    elo_model,
    elo: pd.DataFrame,
    names: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Odds-lake rows for upcoming fixtures: bookmaker odds where ``fixtures.csv`` lists the match,
    else the Elo-only estimate. Returns ``(rows, sources)``; ``sources`` = fixture → source."""
    from fPLense.etl.elo_goals import estimate_rows

    fx = fixture_names(upcoming)
    nm = names.set_index("fpl_name")["fd_name"]
    fx["home_fd"] = fx["home"].map(nm)
    fx["away_fd"] = fx["away"].map(nm)
    if fx[["home_fd", "away_fd"]].isna().any().any():
        bad = sorted(
            set(fx.loc[fx["home_fd"].isna(), "home"]) | set(fx.loc[fx["away_fd"].isna(), "away"])
        )
        raise ValueError(f"clubs missing from team_names.csv: {bad}")
    keys = set(zip(fd_rows.get("home_team", []), fd_rows.get("away_team", []), strict=True))
    has_odds = [(h, a) in keys for h, a in zip(fx["home_fd"], fx["away_fd"], strict=True)]
    fx["has_odds"] = has_odds
    from_fd = pd.DataFrame()
    if fx["has_odds"].any():
        from_fd = fd_rows.merge(
            fx.loc[fx["has_odds"], ["home_fd", "away_fd"]],
            left_on=["home_team", "away_team"],
            right_on=["home_fd", "away_fd"],
        ).drop(columns=["home_fd", "away_fd"])
    from_elo = estimate_rows(fx.loc[~fx["has_odds"]], elo_model, elo, names)
    rows = pd.concat([r for r in (from_fd, from_elo) if len(r)], ignore_index=True)
    src_fd = fd_rows.set_index(["home_team", "away_team"])["source_1x2"] if len(fd_rows) else None
    sources = []
    for f in fx.itertuples(index=False):
        sources.append(src_fd.loc[(f.home_fd, f.away_fd)] if f.has_odds else "elo")
    return rows, pd.DataFrame({"fixture": fx["fixture"], "odds_source": sources})


# --- feature build ----------------------------------------------------------------------------


def write_temp_lake(
    root: Path, history: pd.DataFrame, future: pd.DataFrame, odds: pd.DataFrame, elo: pd.DataFrame
) -> Path:
    season = config.CURRENT_SEASON
    pm = pd.concat([_lake_types(history.copy()), future], ignore_index=True)
    out = root / "player_match" / f"season={season}" / "part.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pm.drop(columns="season").to_parquet(out, index=False)
    o = root / "odds" / f"season={season}" / "part.parquet"
    o.parent.mkdir(parents=True, exist_ok=True)
    odds.to_parquet(o, index=False)
    (root / "elo").mkdir(parents=True, exist_ok=True)
    elo.to_parquet(root / "elo" / "part.parquet", index=False)
    return root


def gw_features(
    history: pd.DataFrame,
    future: pd.DataFrame,
    odds: pd.DataFrame,
    elo: pd.DataFrame,
    gw: int,
    workdir: Path,
) -> pd.DataFrame:
    """``v_features`` rows of the current season's GW ``gw`` (history + that GW's fixtures)."""
    from fPLense.db.build import build, features

    root = write_temp_lake(workdir / f"gw{gw:02d}", history, future[future["gw"] == gw], odds, elo)
    con = build(":memory:", lake_dir=root)
    try:
        return features(con, f"season = '{config.CURRENT_SEASON}' and gw = {int(gw)}")
    finally:
        con.close()


def horizon_features(
    history: pd.DataFrame,
    players: pd.DataFrame,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    gws: list[int],
    odds: pd.DataFrame,
    elo: pd.DataFrame,
) -> pd.DataFrame:
    """Feature rows for every upcoming fixture in ``gws`` (one view build per GW)."""
    upcoming = fixtures[fixtures["gw"].isin(gws)]
    future = future_rows(players, upcoming, teams)
    rest = schedule_rest(fixtures)
    out = []
    with tempfile.TemporaryDirectory(prefix="fplense_predict_") as tmp:
        for j, gw in enumerate(gws):
            rows = gw_features(history, future, odds, elo, gw, Path(tmp))
            if j > 0 and len(rows):  # the view counts rest from the last *played* match
                rows = rows.drop(columns="days_rest").merge(
                    rest, on=["fixture", "team_id"], how="left"
                )
            out.append(rows)
    df = pd.concat([r for r in out if len(r)], ignore_index=True)
    from fPLense.models.train import add_regular_flag

    return add_regular_flag(df)


# --- main -------------------------------------------------------------------------------------


def _fixture_labels(fixtures: pd.DataFrame, teams: pd.DataFrame, sources: pd.DataFrame):
    """Per (team_id, gw): ``"CHE (H), ars (A)"`` and the odds source(s)."""
    short = teams.set_index("team_id")["team_short"]
    src = sources.set_index("fixture")["odds_source"]
    rows = []
    for f in fixtures.itertuples(index=False):
        s = src.get(f.fixture, "")
        rows.append((f.team_h, f.gw, f.kickoff_time, f"{short[f.team_a]} (H)", s))
        rows.append((f.team_a, f.gw, f.kickoff_time, f"{short[f.team_h]} (A)", s))
    d = pd.DataFrame(rows, columns=["team_id", "gw", "ko", "label", "src"]).sort_values("ko")
    return d.groupby(["team_id", "gw"]).agg(
        label=("label", ", ".join), src=("src", lambda s: "/".join(s))
    )


def assemble(
    players: pd.DataFrame,
    preds: pd.DataFrame,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    sources: pd.DataFrame,
    gws: list[int],
    discount: float = config.HORIZON_DISCOUNT,
) -> pd.DataFrame:
    """One row per player: identity, price (tenths), availability, p per GW, p1, P_h, fixtures."""
    from fPLense.optimize.squad_ilp import discounted_sum

    raw = gw_points(preds, players["element"], gws)
    avail = availability(players).to_numpy()
    out = players[
        [
            "element",
            "web_name",
            "name",
            "code",
            "team",
            "team_short",
            "position",
            "now_cost",
            "status",
            "chance_of_playing_next_round",
            "news",
            "selected_by_percent",
            "season_minutes",
            "season_points",
        ]
    ].reset_index(drop=True)
    out = out.rename(columns={"team": "club", "team_short": "club_short", "position": "pos"})
    out["price"] = out["now_cost"].astype(int)  # integer tenths for the ILP
    out["availability"] = avail
    per_gw = raw.to_numpy() * avail[:, None]
    labels = _fixture_labels(fixtures[fixtures["gw"].isin(gws)], teams, sources)
    for k, gw in enumerate(gws):
        out[f"p_gw{gw:02d}"] = per_gw[:, k]
        lab = labels.reindex(pd.MultiIndex.from_arrays([players["team_id"], [gw] * len(players)]))
        out[f"fx_gw{gw:02d}"] = lab["label"].fillna("blank").to_numpy()
        out[f"src_gw{gw:02d}"] = lab["src"].fillna("").to_numpy()
    out["p1"] = per_gw[:, 0]
    out["P_h"] = discounted_sum(per_gw, discount)
    nxt = preds[preds["gw"] == gws[0]].groupby("element")
    out["minutes_r3"] = out["element"].map(nxt["minutes_r3"].first())
    out["regular"] = out["element"].map(nxt["regular"].first()).fillna(False).astype(bool)
    out["odds_source"] = out[f"src_gw{gws[0]:02d}"]
    return out


def shap_next_gw(model, rows: pd.DataFrame) -> pd.DataFrame:
    """Next-GW SHAP per player (summed over a DGW's fixtures) + first fixture's feature values."""
    from fPLense.models.explain import shap_frame

    sv = shap_frame(model, rows)
    sv["element"] = rows["element"].to_numpy()
    summed = sv.groupby("element").sum()
    vals = rows.groupby("element")[config.FEATURES].first()
    vals = vals.rename(columns={f: f"val_{f}" for f in config.FEATURES})
    vals["val_position"] = vals["val_position"].astype(str)
    summed.columns = [c if c == "base_value" else f"shap_{c}" for c in summed.columns]
    summed = summed.astype("float32")  # published every GW: float32 halves the file
    summed["n_fixtures"] = rows.groupby("element").size()
    num = vals.columns.drop("val_position")
    vals[num] = vals[num].astype("float32")
    return summed.join(vals).reset_index()


def load_live(live_dir: Path = config.LIVE_DIR) -> dict[str, Any]:
    hist = live_dir / "player_match" / f"season={config.CURRENT_SEASON}" / "part.parquet"
    if not hist.exists():
        raise FileNotFoundError(f"{hist} not found; run `python -m fPLense.pipeline --refresh`")
    history = pd.read_parquet(hist)
    history.insert(0, "season", config.CURRENT_SEASON)
    players = pd.read_parquet(live_dir / config.LIVE_PLAYERS_PATH.name)
    fixtures = pd.read_parquet(live_dir / config.LIVE_FIXTURES_PATH.name)
    teams_from_players = (
        players[["team_id", "team", "team_short"]].drop_duplicates("team_id").reset_index(drop=True)
    )
    meta = json.loads((live_dir / config.LIVE_META_PATH.name).read_text(encoding="utf-8"))
    fd_path = live_dir / config.LIVE_UPCOMING_ODDS_PATH.name
    past_path = live_dir / config.LIVE_HISTORY_PAST_PATH.name
    return {
        "history": history,
        "players": players,
        "fixtures": fixtures,
        "teams": teams_from_players,
        "meta": meta,
        "fd_rows": pd.read_parquet(fd_path) if fd_path.exists() else pd.DataFrame(),
        "history_past": pd.read_parquet(past_path) if past_path.exists() else None,
    }


def horizon_gws(fixtures: pd.DataFrame, next_gw: int, horizon: int) -> list[int]:
    last = int(fixtures["gw"].max())
    return [g for g in range(next_gw, next_gw + horizon) if g <= last]


def run_predict(
    horizon: int = config.HORIZON,
    model=None,
    live_dir: Path = config.LIVE_DIR,
    out_dir: Path = config.PUBLISHED_DIR,
) -> dict[str, Any]:
    """Predict the next ``horizon`` GWs and write predictions / SHAP / squad / latest.json."""
    from fPLense.db.build import build
    from fPLense.etl import elo_goals
    from fPLense.models.explain import load_model, top_contributions
    from fPLense.models.train import lgbm_frame
    from fPLense.optimize.squad_ilp import pick_squad

    t0 = datetime.now(UTC)
    live = load_live(live_dir)
    meta, fixtures, players, teams = live["meta"], live["fixtures"], live["players"], live["teams"]
    if meta.get("next_gw") is None:
        raise RuntimeError("season over: no next gameweek to predict")
    next_gw = int(meta["next_gw"])
    gws = horizon_gws(fixtures, next_gw, horizon)
    model = load_model() if model is None else model

    # Elo-only goal model, fitted on the 10 historical seasons
    con = build(":memory:")
    try:
        elo_model = elo_goals.fit_from_views(con, config.SEASONS)
    finally:
        con.close()
    elo = pd.read_parquet(config.ELO_DIR / "part.parquet")
    names = pd.read_csv(config.TEAM_NAMES_PATH)

    upcoming = fixtures[fixtures["gw"].isin(gws)]
    new_odds, sources = upcoming_odds(upcoming, live["fd_rows"], elo_model, elo, names)
    played_odds_path = config.ODDS_DIR / f"season={config.CURRENT_SEASON}" / "part.parquet"
    played = pd.read_parquet(played_odds_path) if played_odds_path.exists() else None
    odds = pd.concat([d for d in (played, new_odds) if d is not None and len(d)], ignore_index=True)
    odds = odds.drop_duplicates(["home_team", "away_team"], keep="first")

    rows = horizon_features(live["history"], players, fixtures, teams, gws, odds, elo)
    rows["pred"] = model.predict(lgbm_frame(rows))
    table = assemble(players, rows, fixtures, teams, sources, gws)

    sv = shap_next_gw(model, rows[rows["gw"] == next_gw].reset_index(drop=True))
    tops = top_contributions(
        sv.set_index("element").filter(like="shap_").rename(columns=lambda c: c[5:])
    )
    table["top_shap"] = (
        table["element"]
        .map(tops.map(lambda t: "; ".join(f"{f} {v:+.2f}" for f, v in t)))
        .fillna("")
    )
    if live["history_past"] is not None:
        table = table.merge(live["history_past"], on="element", how="left")
    else:
        table["prev_season_pts_per90"] = np.nan

    pool = table.set_index("element")
    squad = pick_squad(pool)

    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / config.predictions_path(next_gw).name
    shap_path = out_dir / config.shap_path(next_gw).name
    squad_path = out_dir / config.squad_path(next_gw).name
    table.to_parquet(pred_path, index=False)
    sv.to_parquet(shap_path, index=False)
    squad_doc = squad_json(squad, pool, next_gw, gws)
    squad_path.write_text(json.dumps(squad_doc, indent=2), encoding="utf-8")

    src_counts = sources.merge(upcoming[["fixture", "gw"]], on="fixture")
    latest = {
        "season": config.CURRENT_SEASON,
        "gw": next_gw,
        "gws": gws,
        "deadline": meta.get("next_deadline"),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "data_fetched_at": meta.get("fetched_at"),
        "data_through_gw": meta.get("last_finished_gw"),
        "horizon": len(gws),
        "discount": config.HORIZON_DISCOUNT,
        "bench_weight": config.BENCH_WEIGHT,
        "files": {
            "predictions": pred_path.name,
            "shap": shap_path.name,
            "squad": squad_path.name,
        },
        "players": len(table),
        "feature_rows": len(rows),
        "odds_sources": {
            str(gw): g["odds_source"].value_counts().to_dict() for gw, g in src_counts.groupby("gw")
        },
        "elo_goal_model": elo_model.to_dict(),
        "model_trees": int(model.num_trees()) if hasattr(model, "num_trees") else None,
        "runtime_s": round((datetime.now(UTC) - t0).total_seconds(), 1),
    }
    (out_dir / config.LATEST_PATH.name).write_text(json.dumps(latest, indent=2), encoding="utf-8")
    publish_assets(out_dir)
    return {"latest": latest, "squad": squad_doc, "table": table}


def squad_json(res, pool: pd.DataFrame, gw: int, gws: list[int]) -> dict[str, Any]:
    starters = set(res.starters)
    bench_order = {p: k + 1 for k, p in enumerate(res.bench)}
    players = []
    for i in res.squad:
        r = pool.loc[i]
        players.append(
            {
                "element": int(i),
                "name": str(r["web_name"]),
                "club": str(r["club"]),
                "club_short": str(r["club_short"]),
                "pos": str(r["pos"]),
                "price": int(r["price"]),
                "p1": round(float(r["p1"]), 3),
                "P_h": round(float(r["P_h"]), 3),
                "starter": i in starters,
                "bench_order": bench_order.get(i),
                "captain": i == res.captain,
                "vice": i == res.vice,
            }
        )
    return {
        "gw": gw,
        "gws": gws,
        "budget": config.BUDGET,
        "cost": res.cost,
        "bank": config.BUDGET - res.cost,
        "expected_points": round(res.expected_points, 3),
        "objective": round(res.objective, 3),
        "captain": int(res.captain),
        "vice": int(res.vice),
        "players": players,
    }


def publish_assets(out_dir: Path = config.PUBLISHED_DIR) -> list[str]:
    """Copy the model-card images into ``published/img`` and write ``mae_by_gw.json`` (the app
    reads only ``data/published/``)."""
    img = out_dir / config.PUBLISHED_IMG_DIR.name
    img.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in config.PUBLISHED_IMAGES:
        src = config.DOCS_IMG_DIR / name
        if src.exists():
            shutil.copy2(src, img / name)
            copied.append(name)
    wf = config.EVAL_DIR / "walk_forward_2025_26.parquet"
    if wf.exists():
        from fPLense.models.evaluate import per_gw, to_player_gw

        pgw = to_player_gw(pd.read_parquet(wf))
        regs = pgw[pgw["regular"]]
        doc = {"season": config.TARGET_SEASON, "subset": "regulars", "models": {}}
        for col in ("pred_b0", "pred_ridge", "pred_lgbm"):
            g = per_gw(regs, col)
            doc["models"][col.removeprefix("pred_")] = {
                "gw": [int(x) for x in g["gw"]],
                "mae": [round(float(x), 4) for x in g["mae"]],
            }
        (out_dir / config.MAE_BY_GW_PATH.name).write_text(json.dumps(doc, indent=2), "utf-8")
    return copied
