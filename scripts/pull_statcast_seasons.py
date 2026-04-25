#!/usr/bin/env python3
"""Pull full-season Statcast pitch-level data for WE-table construction.

Caches each season as ``.cache/statcast_seasons/<year>.parquet``. Skips seasons
already cached and non-empty. Pulls in roughly month-sized chunks via
``pybaseball.statcast`` so a transient failure only re-downloads a slice.

Usage:
    .venv/bin/python scripts/pull_statcast_seasons.py 2019 2021 2022 2023 2024
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import pybaseball

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache" / "statcast_seasons"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(asctime)s %(message)s")
log = logging.getLogger("pull_statcast_seasons")

# Regular-season approximate windows. We over-cover; pybaseball only returns
# what's there. (Statcast spans regular season + playoffs; we'll filter to
# game_type == 'R' downstream.)
SEASON_WINDOWS = {
    2019: ("2019-03-20", "2019-09-30"),
    2020: ("2020-07-23", "2020-09-27"),
    2021: ("2021-04-01", "2021-10-03"),
    2022: ("2022-04-07", "2022-10-05"),
    2023: ("2023-03-30", "2023-10-01"),
    2024: ("2024-03-28", "2024-09-30"),
    2025: ("2025-03-27", "2025-09-28"),
}


def _month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        # advance ~30d
        nxt = cur.replace(day=1)
        # next month boundary
        if nxt.month == 12:
            nxt = nxt.replace(year=nxt.year + 1, month=1)
        else:
            nxt = nxt.replace(month=nxt.month + 1)
        chunk_end = min(end, nxt - pd.Timedelta(days=1).to_pytimedelta() if hasattr(pd.Timedelta(days=1), "to_pytimedelta") else end)
        # simpler: use pandas
        from datetime import timedelta
        chunk_end = min(end, nxt - timedelta(days=1))
        chunks.append((cur, chunk_end))
        cur = nxt
    return chunks


def pull_season(year: int) -> Path | None:
    if year not in SEASON_WINDOWS:
        log.error("no window for season %d", year)
        return None
    out = CACHE_DIR / f"{year}.parquet"
    if out.is_file() and out.stat().st_size > 0:
        log.info("skip cached %s", out.name)
        return out

    start_s, end_s = SEASON_WINDOWS[year]
    start = date.fromisoformat(start_s)
    end = date.fromisoformat(end_s)

    frames: list[pd.DataFrame] = []
    for c_start, c_end in _month_chunks(start, end):
        log.info("pulling %s -> %s ...", c_start, c_end)
        t0 = time.time()
        df = None
        for attempt in (1, 2):
            try:
                df = pybaseball.statcast(
                    start_dt=c_start.isoformat(),
                    end_dt=c_end.isoformat(),
                    verbose=False,
                )
                break
            except Exception as exc:  # noqa: BLE001
                log.error("chunk %s..%s attempt %d failed: %s", c_start, c_end, attempt, exc)
                time.sleep(2)
        dt_s = time.time() - t0
        if df is None or len(df) == 0:
            log.warning("empty/failed chunk %s..%s (%.1fs)", c_start, c_end, dt_s)
            continue
        log.info("  got %d rows in %.1fs", len(df), dt_s)
        frames.append(df)

    if not frames:
        log.error("no data for %d", year)
        return None

    full = pd.concat(frames, ignore_index=True)
    # drop dup pitches if windows overlap
    if {"game_pk", "at_bat_number", "pitch_number"}.issubset(full.columns):
        before = len(full)
        full = full.drop_duplicates(subset=["game_pk", "at_bat_number", "pitch_number"])
        log.info("deduped %d -> %d", before, len(full))

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    full.to_parquet(out, index=False)
    log.info("wrote %s (%d rows, %.1f MB)", out, len(full), out.stat().st_size / 1e6)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("years", nargs="+", type=int)
    args = p.parse_args()

    pybaseball.cache.enable()
    for y in args.years:
        try:
            pull_season(y)
        except Exception as exc:  # noqa: BLE001
            log.error("season %d failed: %s", y, exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
