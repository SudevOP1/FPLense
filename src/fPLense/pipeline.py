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

Later phases add --refresh, --predict.
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
        "--horizon",
        type=int,
        default=config.HORIZON,
        help=f"gameweeks the optimizer looks ahead (default {config.HORIZON})",
    )
    parser.add_argument("--force", action="store_true", help="re-download files that exist")
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
    if not (any(actions) or args.evaluate or args.train or args.explain or args.backtest):
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
