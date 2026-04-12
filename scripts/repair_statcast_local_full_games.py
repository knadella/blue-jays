#!/usr/bin/env python3
"""Expand local Statcast Parquet files from pitcher-only Savant pulls to full-game pitch logs.

Savant ``team=`` searches return pitches thrown by that club's staff only, which omits their batting
half-innings. The weekly SPA then shows empty offense trends. This script re-fetches each
``game_pk`` via ``statcast_single_game`` and rewrites the Parquet.

Requires network. Examples::

    python scripts/repair_statcast_local_full_games.py --season 2025 --abbrev TOR
    python scripts/repair_statcast_local_full_games.py --season 2025 --all-in-dir
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from data_source.statcast_weekly import (  # noqa: E402
    STATCAST_LOCAL_DIR,
    expand_statcast_team_frame_to_full_games,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_FNAME = re.compile(r"^(\d{4})_([A-Z]{2,3})\.parquet$", re.I)


def main() -> int:
    p = argparse.ArgumentParser(description="Repair local Statcast Parquet extracts (full games).")
    p.add_argument("--season", type=int, required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--abbrev", type=str, help="Team code, e.g. TOR")
    g.add_argument("--all-in-dir", action="store_true", help=f"Every {{season}}_*.parquet under {STATCAST_LOCAL_DIR}")
    args = p.parse_args()

    paths: list[tuple[Path, str]] = []
    if args.abbrev:
        abb = args.abbrev.strip().upper()
        fp = STATCAST_LOCAL_DIR / f"{args.season}_{abb}.parquet"
        if not fp.is_file():
            logger.error("Missing %s", fp)
            return 2
        paths.append((fp, abb))
    else:
        for fp in sorted(STATCAST_LOCAL_DIR.glob(f"{args.season}_*.parquet")):
            m = _FNAME.match(fp.name)
            if not m:
                continue
            paths.append((fp, m.group(2).upper()))

    if not paths:
        logger.error("No Parquet files matched.")
        return 2

    failures: list[str] = []
    for fp, abbrev in paths:
        try:
            df = pd.read_parquet(fp)
            before = len(df)
            out = expand_statcast_team_frame_to_full_games(df, abbrev)
            after = len(out)
            out.to_parquet(fp, index=False)
            logger.info("%s: %d -> %d rows (wrote)", fp.name, before, after)
        except Exception as exc:
            logger.exception("%s: %s", fp.name, exc)
            failures.append(f"{fp.name}: {exc}")

    if failures:
        for f in failures:
            logger.error("%s", f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
