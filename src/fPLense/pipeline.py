"""FPLense command-line pipeline.

    python -m fPLense.pipeline --refresh-history          # download vaastav history -> Parquet lake
    python -m fPLense.pipeline --refresh-history --force  # re-download every raw file

Later phases add --build, --train, --refresh, --predict and --horizon.
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

    if not args.refresh_history:
        parser.print_help()
        return 0

    from fPLense.etl.load_history import refresh_history

    counts = refresh_history(args.seasons, force=args.force)
    for season, n in counts.items():
        print(f"{season}: {n:>7,}")
    print(f"total:   {sum(counts.values()):>7,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
