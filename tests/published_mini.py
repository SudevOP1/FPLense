"""A tiny synthetic ``data/published/`` folder for the API tests (PLAN.md §8 P6).

Built at test time with the same writer functions the pipeline uses (``predict.squad_json``,
``history.write_archive``, ``history.hindsight_squad``, ``ratings.publish_ratings``...), so the
API is tested against files of the real shape without committing binary fixtures.

Season state: GW1 (backfilled) and GW2 (live) are finished and archived; GW3 is next, with
predictions for GW3-4. 10 clubs x (1 GK, 2 DEF, 2 MID, 1 FWD) = 60 players, ids 1-60.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from fPLense import config
from fPLense.etl.ratings import publish_ratings
from fPLense.models import history
from fPLense.models.predict import squad_json
from fPLense.optimize.squad_ilp import pick_squad

CLUBS = [f"Club {c}" for c in "ABCDEFGHIJ"]
SHORT = [f"C{c}A" for c in "ABCDEFGHIJ"]
LAYOUT = ["GK", "DEF", "DEF", "MID", "MID", "FWD"]
PRICE = {"GK": (40, 55), "DEF": (40, 65), "MID": (50, 120), "FWD": (55, 130)}
NEXT_GW = 3
GWS = [3, 4]
FINISHED = [1, 2]
SHAP_FEATURES = ["minutes_r3", "pts_last1", "price", "position"]


def players(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for c, (club, short) in enumerate(zip(CLUBS, SHORT, strict=True)):
        for k, pos in enumerate(LAYOUT):
            pid = c * len(LAYOUT) + k + 1
            lo, hi = PRICE[pos]
            price = int(rng.integers(lo, hi + 1))
            rows.append(
                {
                    "element": pid,
                    "web_name": f"P{pid}",
                    "name": f"Player {pid}",
                    "code": 100_000 + pid,
                    "club": club,
                    "club_short": short,
                    "team_id": c + 1,
                    "pos": pos,
                    "now_cost": price,
                    "price": price,
                    "status": "a",
                    "chance_of_playing_next_round": np.nan,
                    "news": "",
                    "selected_by_percent": float(rng.uniform(0, 40)),
                    "season_minutes": int(rng.integers(0, 180)),
                    "season_points": int(rng.integers(0, 20)),
                }
            )
    df = pd.DataFrame(rows)
    base = df["price"] / 20 + rng.normal(0, 0.8, len(df))
    df.loc[df.index[-1], ["status", "chance_of_playing_next_round", "news"]] = ["i", 0.0, "Knee"]
    for gw in GWS:
        df[f"p_gw{gw:02d}"] = np.clip(base + rng.normal(0, 0.3, len(df)), 0, None)
        df[f"fx_gw{gw:02d}"] = "CXA (H)"
        df[f"src_gw{gw:02d}"] = "elo"
    df["availability"] = np.where(df["status"] == "i", 0.0, 1.0)
    for gw in GWS:
        df[f"p_gw{gw:02d}"] *= df["availability"]
    df["p1"] = df[f"p_gw{GWS[0]:02d}"]
    df["P_h"] = df[f"p_gw{GWS[0]:02d}"] + 0.9 * df[f"p_gw{GWS[1]:02d}"]
    df["minutes_r3"] = 90.0
    df["regular"] = True
    df["odds_source"] = "elo"
    df["top_shap"] = "minutes_r3 +1.00"
    df["prev_season_pts_per90"] = np.nan
    return df


def build(root: Path) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(11)
    table = players()
    pool = table.set_index("element")

    # --- the live predictions for GW3-4 -----------------------------------------------------
    table.drop(columns="team_id").to_parquet(root / config.predictions_path(NEXT_GW).name)
    squad = squad_json(pick_squad(pool), pool, NEXT_GW, GWS)
    (root / config.squad_path(NEXT_GW).name).write_text(json.dumps(squad), encoding="utf-8")
    shap = pd.DataFrame({"element": table["element"], "base_value": np.float32(1.2)})
    for f in SHAP_FEATURES:
        shap[f"shap_{f}"] = rng.normal(0, 0.5, len(table)).astype("float32")
        shap[f"val_{f}"] = "MID" if f == "position" else rng.uniform(0, 90, len(table))
    shap["n_fixtures"] = 1
    shap.to_parquet(root / config.shap_path(NEXT_GW).name)
    latest = {
        "season": config.CURRENT_SEASON,
        "gw": NEXT_GW,
        "gws": GWS,
        "deadline": "2026-09-05T10:00:00+00:00",
        "generated_at": "2026-09-03T05:00:00+00:00",
        "data_through_gw": 2,
        "horizon": len(GWS),
        "discount": 0.9,
        "bench_weight": 0.1,
        "files": {
            "predictions": config.predictions_path(NEXT_GW).name,
            "shap": config.shap_path(NEXT_GW).name,
            "squad": config.squad_path(NEXT_GW).name,
        },
    }
    (root / config.LATEST_PATH.name).write_text(json.dumps(latest), encoding="utf-8")
    metrics = {
        "walk_forward": {
            "target_season": "2025-26",
            "regulars": {
                "b0": {
                    "mae": 2.535,
                    "rmse": 3.3,
                    "n": 7365,
                    "spearman_per_gw": 0.17,
                    "top20_precision_per_gw": 0.16,
                    "mae_gain_pct": 0.0,
                    "mae_gain_ci95": None,
                },
                "lgbm": {
                    "mae": 2.246,
                    "rmse": 3.0,
                    "n": 7365,
                    "spearman_per_gw": 0.32,
                    "top20_precision_per_gw": 0.22,
                    "mae_gain_pct": 11.4,
                    "mae_gain_ci95": [10.2, 12.6],
                },
            },
        }
    }
    (root / config.METRICS_PATH.name).write_text(json.dumps(metrics), encoding="utf-8")
    publish_ratings(table, NEXT_GW, root)

    # --- the season so far: fixtures, actuals, archives, hindsight, summary -----------------
    fixtures = []
    for gw in range(1, 5):
        order = rng.permutation(10)
        for k in range(5):
            h, a = int(order[2 * k]) + 1, int(order[2 * k + 1]) + 1
            done = gw in FINISHED
            fixtures.append(
                {
                    "fixture": 100 * gw + k,
                    "gw": gw,
                    "kickoff_time": f"2026-08-{14 + 7 * gw:02d}T14:00:00+00:00",
                    "team_h": h,
                    "team_a": a,
                    "team_h_name": CLUBS[h - 1],
                    "team_a_name": CLUBS[a - 1],
                    "team_h_short": SHORT[h - 1],
                    "team_a_short": SHORT[a - 1],
                    "team_h_difficulty": 3.0,
                    "team_a_difficulty": 2.0,
                    "team_h_score": 1.0 if done else None,
                    "team_a_score": 0.0 if done else None,
                    "finished": done,
                }
            )
    (root / config.FIXTURES_PUBLISHED_PATH.name).write_text(
        json.dumps({"season": config.CURRENT_SEASON, "fixtures": fixtures}), encoding="utf-8"
    )
    act_rows = []
    for gw in FINISHED:
        minutes = rng.choice([0, 90], size=len(table), p=[0.25, 0.75])
        pts = np.where(minutes > 0, rng.poisson(3, len(table)), 0)
        for r, m, p in zip(table.itertuples(), minutes, pts, strict=True):
            act_rows.append(
                {
                    "element": r.element,
                    "gw": gw,
                    "total_points": int(p),
                    "minutes": int(m),
                    "price": int(r.price),
                    "fixtures": 1,
                    "fixtures_played": int(m > 0),
                    "pos": r.pos,
                    "team_id": r.team_id,
                    "team": r.club,
                }
            )
    act = pd.DataFrame(act_rows)
    act.to_parquet(root / config.ACTUALS_PATH.name, index=False)

    hist = root / config.HISTORY_DIR.name
    events = []
    for gw in range(1, 5):
        events.append(
            {
                "id": gw,
                "deadline_time": f"2026-08-{13 + 7 * gw:02d}T10:00:00Z",
                "finished": gw in FINISHED,
                "data_checked": gw in FINISHED,
                "average_entry_score": 50 + gw if gw in FINISHED else 0,
                "highest_score": 120 + gw if gw in FINISHED else None,
                "is_current": gw == 2,
                "is_next": gw == NEXT_GW,
            }
        )
    season = history.season_doc({"events": events})
    hist.mkdir(parents=True, exist_ok=True)
    (hist / "season.json").write_text(json.dumps(season), encoding="utf-8")
    meta_model = {"model_sha256": "0" * 64, "train_max_season": "2025-26"}
    rows = []
    for gw, source in zip(FINISHED, ("backfill", "live"), strict=True):
        t = table.assign(**{f"p_gw{gw:02d}": table["p1"] * (0.8 + 0.1 * gw)})
        p = t.set_index("element").assign(p1=t[f"p_gw{gw:02d}"].to_numpy())
        sq = squad_json(pick_squad(p), p, gw, [gw, gw + 1])
        meta = {
            "made_at": f"2026-08-{12 + 7 * gw:02d}T05:00:00+00:00",
            "model_sha256": meta_model["model_sha256"],
            "model_train_max_season": meta_model["train_max_season"],
            "source": source,
        }
        if source == "backfill":
            meta["caveat"] = "rebuilt after the fact; availability unknown (100%)"
        history.write_archive(gw, history.archive_frame(t, gw), sq, meta, hist)
        hind = {"gw": gw, **history.hindsight_squad(history.actual_pool(act, gw))}
        d = config.history_gw_dir(gw, hist)
        (d / "squad_hindsight.json").write_text(json.dumps(hind), encoding="utf-8")
        rows.append(
            history.summary_row(
                gw,
                history.read_archive(gw, hist),
                hind,
                act,
                {e["gw"]: e for e in season["events"]}[gw],
            )
        )
    summary = {
        "season": config.CURRENT_SEASON,
        "generated_at": "2026-09-03T05:00:00+00:00",
        "note": "capture_ratio is a product stat",
        "gws": rows,
    }
    (hist / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return root


def picks_json(ids: list[int], gw: int, bank: int = 15, value: int = 985) -> dict:
    """An FPL ``entry/{id}/event/{gw}/picks/`` response for a squad of mini-pool ids (shape copied
    from ``tests/fixtures/picks_sample.json``)."""
    sample = json.loads((config.TESTS_FIXTURES_DIR / "picks_sample.json").read_text("utf-8"))
    picks = []
    for k, i in enumerate(ids):
        picks.append(
            {
                "element": int(i),
                "position": k + 1,
                "multiplier": 2 if k == 0 else (1 if k < 11 else 0),
                "is_captain": k == 0,
                "is_vice_captain": k == 1,
                "element_type": 1,
            }
        )
    eh = {**sample["entry_history"], "event": gw, "bank": bank, "value": value}
    return {"active_chip": None, "automatic_subs": [], "entry_history": eh, "picks": picks}
