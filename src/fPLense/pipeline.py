"""FPLense command-line pipeline.

    python -m fPLense.pipeline --refresh-history          # download vaastav history -> Parquet lake
    python -m fPLense.pipeline --refresh-history --force  # re-download every raw file
    python -m fPLense.pipeline --refresh-odds             # football-data.co.uk odds -> lake
    python -m fPLense.pipeline --refresh-elo              # Kaggle ClubElo snapshots -> lake
    python -m fPLense.pipeline --build                    # DuckDB views + calibration plot
    python -m fPLense.pipeline --evaluate                 # walk-forward + holdout + ablation
    python -m fPLense.pipeline --evaluate --step 2 --no-ablation   # quicker check
    python -m fPLense.pipeline --train                    # final LightGBM -> data/published/
    python -m fPLense.pipeline --explain                  # SHAP plots -> docs/img/
    python -m fPLense.pipeline --backtest                 # optimizer backtest 2025-26 GW5-38
    python -m fPLense.pipeline --refresh --predict --horizon 5          # live path (gated)
    python -m fPLense.pipeline --refresh --predict --horizon 5 --force  # run regardless
    python -m fPLense.pipeline --history                  # season archive, actuals, hindsight
    python -m fPLense.pipeline --ratings                  # card ratings -> published/ratings.json

The live path (--refresh / --predict) exits early with code 0 unless the next FPL deadline is
less than 48 h away and predictions for that gameweek don't exist yet; --force overrides.
"""

from __future__ import annotations

import argparse
import logging

from fPLense import config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fPLense.pipeline", description="FPLense pipeline")
    parser.add_argument(
        "--refresh-history",
        action="store_true",
        help="download the 10 historical seasons (vaastav) and write data/lake/player_match/",
    )
    parser.add_argument(
        "--refresh-odds",
        action="store_true",
        help="download football-data.co.uk E0.csv per season and write data/lake/odds/",
    )
    parser.add_argument(
        "--refresh-elo",
        action="store_true",
        help="download Kaggle EloRatings.csv -> data/lake/elo/ (token: see PLAN.md 0.2)",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="create data/fplense.duckdb from db/sql/*.sql and save the odds calibration plot",
    )
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="walk-forward 2025-26 + 2024-25 holdout + ablation -> data/published/metrics.json",
    )
    parser.add_argument(
        "--step", type=int, default=1, help="walk-forward: score every Nth gameweek (default 1)"
    )
    parser.add_argument(
        "--ablation-step", type=int, default=2, help="ablation walk-forward step (default 2)"
    )
    parser.add_argument("--no-ablation", action="store_true", help="skip the ablation runs")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="evaluate: delete saved fold checkpoints in data/eval/folds/ first",
    )
    parser.add_argument(
        "--train",
        action="store_true",
        help="fit the final LightGBM on all seasons -> data/published/model.txt",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="SHAP beeswarm, dependence plots and waterfalls for model.txt -> docs/img/",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="optimizer backtest on the saved walk-forward predictions -> published/backtest.json",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="live: FPL API + current-season odds -> data/lake/live/ (gated, see --force)",
    )
    parser.add_argument(
        "--predict",
        action="store_true",
        help="live: next-N-GW predictions, SHAP and squad -> data/published/ (gated)",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="archive every finished GW (backfill as-of where needed), actuals, hindsight-best "
        "squads and the season summary -> data/published/history/",
    )
    parser.add_argument(
        "--force-history",
        action="store_true",
        help="--history: rebuild existing backfilled GWs too (live archives are never replaced)",
    )
    parser.add_argument(
        "--ratings",
        action="store_true",
        help="FPLense card ratings for the latest predictions -> data/published/ratings.json",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=config.HORIZON,
        help=f"gameweeks predicted / looked ahead by the optimizer (default {config.HORIZON})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download files that exist; live path: ignore the deadline gate",
    )
    parser.add_argument(
        "--seasons", nargs="*", metavar="YYYY-YY", help=f"subset of {config.SEASONS}"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.seasons:
        unknown = sorted(set(args.seasons) - set(config.SEASONS))
        if unknown:
            parser.error(f"unknown seasons: {unknown}")

    actions = (args.refresh_history, args.refresh_odds, args.refresh_elo, args.build)
    live = args.refresh or args.predict
    others = args.evaluate or args.train or args.explain or args.backtest
    others = others or args.history or args.ratings
    if not (any(actions) or others or live):
        parser.print_help()
        return 0

    if args.refresh_history:
        from fPLense.etl.load_history import refresh_history

        _print_counts("player_match rows", refresh_history(args.seasons, force=args.force))

    if args.refresh_odds:
        from fPLense.etl.load_odds import refresh_odds

        _print_counts("odds matches", refresh_odds(args.seasons, force=args.force))

    if args.refresh_elo:
        from fPLense.etl.load_elo import KaggleTokenError, refresh_elo

        try:
            print(f"elo snapshot rows: {refresh_elo(force=args.force):,}")
        except KaggleTokenError as exc:
            print(f"error: {exc}")
            return 1

    if args.build:
        build_feature_store()

    if args.evaluate or args.train or args.explain:
        from fPLense.models.train import load_features

        df = load_features()
        print(f"feature rows: {len(df):,} ({df['regular'].sum():,} regulars)")
        if args.evaluate:
            evaluate_models(
                df,
                step=args.step,
                ablation_step=None if args.no_ablation else args.ablation_step,
                fresh=args.fresh,
            )
        if args.train:
            from fPLense.models.train import train_final

            model = train_final(df)
            print(
                f"model: {model.booster_.num_trees()} trees "
                f"(early-stopping best iteration {model.early_stopping_best_iteration_}) "
                f"-> {config.MODEL_PATH}"
            )
        if args.explain:
            explain_model(df)

    if args.backtest:
        run_backtest(args.horizon)

    code = run_live(args) if live else 0

    if args.history:
        code = run_history(args.force_history) or code
    if args.ratings:
        code = run_ratings() or code
    return code


def run_history(force: bool) -> int:
    from fPLense.models.history import BackfillRefusedError
    from fPLense.models.history import run_history as history

    try:
        rep = history(force=force)
    except (BackfillRefusedError, FileNotFoundError) as exc:
        print(f"error: {exc}")
        return 1
    print(
        f"history: archived GWs {rep['archived']} (new live {rep['live_archived']}, "
        f"backfilled {rep['backfilled']}), hindsight squads written for {rep['hindsight']}"
    )
    for r in rep["summary"]:
        cap = f"{r['capture_ratio']:.2f}" if r["capture_ratio"] is not None else "n/a"
        print(
            f"  GW{r['gw']:>2} [{r['source']:>8}]: model pick {r['model_actual']:>3} "
            f"(expected {r['model_expected']:.1f}), hindsight-best {r['hindsight_points']:>3}, "
            f"average {r['average_entry_score']}, highest {r['highest_score']}, capture {cap}"
        )
    print(f"-> {config.HISTORY_DIR} (runtime {rep['runtime_s']}s)")
    return 0


def run_ratings() -> int:
    import json

    import pandas as pd

    from fPLense.etl.ratings import publish_ratings

    if not config.LATEST_PATH.exists():
        print("error: no published predictions yet; run --predict first")
        return 1
    latest = json.loads(config.LATEST_PATH.read_text(encoding="utf-8"))
    table = pd.read_parquet(config.PUBLISHED_DIR / latest["files"]["predictions"])
    doc = publish_ratings(table, latest["gw"])
    r = pd.Series([v["rating"] for v in doc["players"].values()])
    print(
        f"ratings: {len(r)} players, source {doc['source']} (EA FC not used), "
        f"median {r.median():.0f}, range {r.min()}-{r.max()} -> {config.RATINGS_PATH}"
    )
    return 0


def run_live(args) -> int:
    """The live path: gate on the next deadline, then refresh and/or predict."""
    import json

    import pandas as pd

    from fPLense.etl import fetch_api, net
    from fPLense.models.predict import should_refresh

    if not 1 <= args.horizon <= config.PREDICT_HORIZON_MAX:
        print(f"error: --horizon must be 1..{config.PREDICT_HORIZON_MAX}")
        return 2
    session = net.make_session()
    cached = config.API_CACHE_DIR / "bootstrap-static.json"
    if args.refresh:
        bootstrap = fetch_api.fetch_bootstrap(session)
    elif cached.exists():
        bootstrap = json.loads(cached.read_text(encoding="utf-8"))
    else:
        print("error: no live data yet; run with --refresh first")
        return 1
    nxt = fetch_api.next_event(fetch_api.parse_events(bootstrap))
    gw, deadline = nxt if nxt else (None, None)
    published = gw is not None and config.predictions_path(gw).exists()
    due, reason = should_refresh(deadline, pd.Timestamp.now(tz="UTC"), published, args.force)
    print(f"next gameweek: {gw} (deadline {deadline}); {'running' if due else 'skip'}: {reason}")
    if not due:
        return 0

    if args.refresh:
        from fPLense.etl.load_odds import build_odds_lake, download_odds, fetch_upcoming_odds

        meta = fetch_api.refresh_live(session=session, bootstrap=bootstrap)
        print(
            f"live lake: {meta['history_rows']:,} rows through GW{meta['last_finished_gw']} "
            f"({meta['players_fetched']} players fetched, {meta['zero_minute_players']} "
            f"with 0 minutes) -> {config.LIVE_DIR}"
        )
        download_odds([config.CURRENT_SEASON])
        n = build_odds_lake([config.CURRENT_SEASON])[config.CURRENT_SEASON]
        upcoming = fetch_upcoming_odds(session)
        upcoming.to_parquet(config.LIVE_UPCOMING_ODDS_PATH, index=False)
        print(f"odds: {n} played matches, {len(upcoming)} upcoming (fixtures.csv E0)")

    if args.predict:
        from fPLense.models.predict import run_predict

        out = run_predict(horizon=args.horizon)
        latest, squad = out["latest"], out["squad"]
        print(
            f"predictions GW{latest['gws'][0]}-{latest['gws'][-1]} for {latest['players']} "
            f"players ({latest['feature_rows']:,} fixture rows); "
            f"odds sources {latest['odds_sources']}"
        )
        names = {p["element"]: p["name"] for p in squad["players"]}
        print(
            f"squad: cost £{squad['cost'] / 10:.1f}m, expected {squad['expected_points']:.1f} pts, "
            f"captain {names[squad['captain']]}, vice {names[squad['vice']]}"
        )
        top = out["table"].nlargest(10, "P_h")[["web_name", "club_short", "pos", "p1", "P_h"]]
        print(top.round(2).to_string(index=False))
        print(f"-> {config.PUBLISHED_DIR / latest['files']['predictions']}")
    return 0


def explain_model(df) -> None:
    from fPLense.models.explain import run_shap, save_summary

    summary = run_shap(df)
    path = save_summary(summary)
    print(f"SHAP on {summary['sample_rows']:,} rows of {summary['sample_season']}")
    print("mean |SHAP| (points per fixture), top 10:")
    for f, v in list(summary["mean_abs_shap"].items())[:10]:
        print(f"  {f:>24}: {v:.3f}")
    for key, w in summary["waterfalls"].items():
        print(
            f"waterfall {key}: {w['name']} {w['season']} GW{w['gw']} "
            f"pred {w['prediction']:.2f} (actual {w['actual']:.0f})"
        )
    print(f"plots -> {config.DOCS_IMG_DIR}; summary -> {path}")


def run_backtest(horizon: int) -> None:
    from fPLense.optimize import backtest

    result = backtest.run_backtest(horizon=horizon)
    path = backtest.save(result)
    img = backtest.plot_cumulative(result.per_gw, config.DOCS_IMG_DIR / "backtest_cumulative.png")
    result.per_gw.to_parquet(config.EVAL_DIR / "backtest_per_gw.parquet", index=False)
    s = result.summary
    print(f"backtest {s['season']} GW{s['gws'][0]}-{s['gws'][-1]}, horizon {s['horizon']}:")
    for k, label in s["strategies"].items():
        print(f"  {label:>30}: {s['total_points'][k]:>5} pts, {s['transfers_made'][k]} transfers")
    if "a_minus_b" in s:
        lo, hi = s["a_minus_b_ci95"]
        print(
            f"  A - B: {s['a_minus_b']:+d} pts [95% CI {lo:+.0f}, {hi:+.0f}], "
            f"A ahead in {s['a_beats_b_gws']}/{len(s['gws'])} GWs"
        )
    if "a_minus_c" in s:
        lo, hi = s["a_minus_c_ci95"]
        print(f"  A - C: {s['a_minus_c']:+d} pts [95% CI {lo:+.0f}, {hi:+.0f}]")
    print(f"-> {path}, {img} (runtime {s['runtime_s']}s)")


def evaluate_models(df, step: int, ablation_step: int | None, fresh: bool = False) -> None:
    from fPLense.models.evaluate import metrics_table
    from fPLense.models.walk_forward import run_evaluation

    metrics = run_evaluation(df, step=step, ablation_step=ablation_step, fresh=fresh)
    for view in ("walk_forward", "holdout"):
        print(f"\n{view}:")
        print(metrics_table(metrics[view]).to_string(index=False))
    if "ablation" in metrics:
        print("\nablation (regulars, LightGBM L2):")
        for name, m in metrics["ablation"].items():
            if isinstance(m, dict) and "regulars_mae" in m:
                lo, hi = m["regulars_mae_gain_ci95"]
                print(
                    f"  {name:>20}: MAE {m['regulars_mae']:.3f} "
                    f"({m['regulars_mae_gain_pct']:+.1f}% [{lo:+.1f}, {hi:+.1f}])"
                )
    print(f"\nmetrics ->{config.METRICS_PATH} (runtime {metrics['runtime_s']}s)")


def _print_counts(label: str, counts: dict[str, int]) -> None:
    print(label)
    for season, n in counts.items():
        print(f"  {season}: {n:>7,}")
    print(f"  total:   {sum(counts.values()):>7,}")


def build_feature_store() -> None:
    from fPLense.db.build import build, summary
    from fPLense.etl.odds_features import calibration_table, plot_calibration

    con = build()
    for key, value in summary(con).items():
        print(f"{key:>28}: {value:>9,}")
    seasons = ", ".join(f"'{s}'" for s in config.SEASONS)
    cs = con.sql(
        f"""
        select mo.p_clean_sheet, (tm.goals_against = 0) as clean_sheet
        from v_match_odds mo
        join v_team_match tm using (season, fixture, team_id)
        where mo.season in ({seasons}) and mo.p_clean_sheet is not null
        """
    ).df()
    table = calibration_table(cs["p_clean_sheet"], cs["clean_sheet"])
    out = plot_calibration(
        table,
        config.DOCS_IMG_DIR / "odds_cs_calibration.png",
        title=f"Implied vs actual clean sheets, {config.SEASONS[0]} to {config.SEASONS[-1]}",
    )
    print(
        f"clean sheets: implied mean {cs.p_clean_sheet.mean():.3f}, "
        f"actual rate {cs.clean_sheet.mean():.3f} (n={len(cs):,}) -> {out}"
    )
    print(table.round(3).to_string(index=False))
    con.close()


if __name__ == "__main__":
    raise SystemExit(main())
