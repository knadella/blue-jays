#!/usr/bin/env python3
"""Download Statcast pitch-level data to local Parquet files (offline use for the weekly SPA).

Writes ``data/statcast_local/{season}_{TEAM}.parquet``. The API loads these before hitting Savant.

Examples::

    python scripts/download_statcast_extracts.py --seasons 2025 --abbrev TOR
    python scripts/download_statcast_extracts.py --seasons 2024 2025 2026 --all-teams
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import TEAM_ABBREVS  # noqa: E402

from data_source.statcast_weekly import (  # noqa: E402
    STATCAST_LOCAL_DIR,
    download_team_season_statcast,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    p = argparse.ArgumentParser(description="Download Statcast extracts to data/statcast_local/")
    p.add_argument("--seasons", nargs="+", type=int, required=True, help="Season years, e.g. 2025 2026")
    p.add_argument(
        "--abbrev",
        action="append",
        default=[],
        help="Savant team code (repeat for multiple), e.g. TOR NYY",
    )
    p.add_argument(
        "--all-teams",
        action="store_true",
        help=f"All {len(TEAM_ABBREVS)} clubs (uses TEAM_ABBREVS from config)",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip if the Parquet file already exists and is non-empty",
    )
    args = p.parse_args()

    if args.all_teams:
        abbrevs = sorted(set(TEAM_ABBREVS.values()))
    elif args.abbrev:
        abbrevs = sorted({a.strip().upper() for a in args.abbrev})
    else:
        logger.error("Pass --abbrev TOR (repeatable) or --all-teams")
        return 2

    STATCAST_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[tuple[int, str, str]] = []

    for season in args.seasons:
        for abbrev in abbrevs:
            out = STATCAST_LOCAL_DIR / f"{season}_{abbrev}.parquet"
            if args.skip_existing and out.is_file() and out.stat().st_size > 0:
                logger.info("skip existing %s", out.name)
                continue
            try:
                df = download_team_season_statcast(abbrev, season)
            except Exception as exc:
                logger.error("%s %s: %s", season, abbrev, exc)
                failures.append((season, abbrev, str(exc)))
                continue
            if df is None or len(df) == 0:
                logger.warning("%s %s: no rows; not writing %s", season, abbrev, out.name)
                failures.append((season, abbrev, "no rows"))
                continue
            df.to_parquet(out, index=False)
            logger.info("wrote %s (%d rows)", out, len(df))

    if failures:
        logger.error("%d job(s) failed or empty", len(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
