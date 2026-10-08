"""FPLense command-line pipeline.

    python -m fPLense.pipeline --refresh-history          # download vaastav history -> Parquet lake
    python -m fPLense.pipeline --refresh-history --force  # re-download every raw file
    python -m fPLense.pipeline --refresh-odds             # football-data.co.uk odds -> lake
    python -m fPLense.pipeline --refresh-elo              # Kaggle ClubElo snapshots -> lake
    python -m fPLense.pipeline --build                    # DuckDB views + calibration plot

Later phases add --train, --refresh, --predict and --horizon.
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

    if not (args.refresh_history or args.refresh_odds or args.refresh_elo or args.build):
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
    return 0


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
