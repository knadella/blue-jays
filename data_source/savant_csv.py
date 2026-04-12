"""Incremental Statcast data fetch from Baseball Savant CSV API."""

from __future__ import annotations

import io
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from config import TEAM_ABBREVS
from data_source.statcast_weekly import STATCAST_LOCAL_DIR, try_load_statcast_local

logger = logging.getLogger(__name__)

SAVANT_CSV_URL = "https://baseballsavant.mlb.com/statcast_search/csv"

# Savant uses slightly different abbreviations than our config
_SAVANT_ABBREV_MAP: dict[str, str] = {
    "CHW": "CWS",
    "ARI": "AZ",
    "OAK": "ATH",
}


def _savant_abbrev(abbrev: str) -> str:
    return _SAVANT_ABBREV_MAP.get(abbrev, abbrev)


def _fetch_savant_csv(
    abbrev: str,
    start_date: str,
    end_date: str,
    season: int,
    *,
    timeout: int = 120,
) -> pd.DataFrame | None:
    """Fetch pitch-level Statcast data from Baseball Savant CSV endpoint.

    Returns a DataFrame or None if no data / error.
    """
    import requests

    sav = _savant_abbrev(abbrev)
    params = {
        "all": "true",
        "type": "detail",
        "hfTeam": f"{sav}|",
        "game_date_gt": start_date,
        "game_date_lt": end_date,
        "hfSea": f"{season}|",
        "sortBy": "game_date",
        "sortOrder": "asc",
        "csv": "true",
    }

    logger.info("Fetching Savant CSV for %s: %s → %s", abbrev, start_date, end_date)
    try:
        resp = requests.get(SAVANT_CSV_URL, params=params, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Savant CSV fetch failed for %s: %s", abbrev, e)
        return None

    text = resp.text.strip()
    if not text or text.startswith("<!") or len(text) < 100:
        logger.info("No data returned for %s (%s → %s)", abbrev, start_date, end_date)
        return None

    try:
        df = pd.read_csv(io.StringIO(text), low_memory=False)
    except Exception as e:
        logger.warning("Failed to parse Savant CSV for %s: %s", abbrev, e)
        return None

    if len(df) == 0:
        return None

    # Ensure game_date is datetime
    if "game_date" in df.columns:
        df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")

    logger.info("Fetched %d rows for %s", len(df), abbrev)
    return df


def fetch_incremental(
    abbrev: str,
    season: int,
    *,
    local_dir: Path | None = None,
) -> int:
    """Fetch new Statcast data for a team since the last load.

    Returns the number of new rows added.
    """
    local_dir = local_dir or STATCAST_LOCAL_DIR
    local_dir.mkdir(parents=True, exist_ok=True)
    path = local_dir / f"{season}_{abbrev}.parquet"

    existing = try_load_statcast_local(abbrev, season)

    if existing is not None and len(existing) > 0:
        gd = pd.to_datetime(existing["game_date"], errors="coerce")
        max_date = gd.max()
        if pd.isna(max_date):
            start = f"{season}-03-20"
        else:
            start = (max_date + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        start = f"{season}-03-20"
        existing = None

    end = date.today().strftime("%Y-%m-%d")
    if start >= end:
        logger.info("No new dates for %s (last: %s)", abbrev, start)
        return 0

    new_df = _fetch_savant_csv(abbrev, start, end, season)
    if new_df is None or len(new_df) == 0:
        return 0

    if existing is not None and len(existing) > 0:
        combined = pd.concat([existing, new_df], ignore_index=True)
        # Deduplicate by unique pitch identifier
        dedup_cols = ["game_pk", "at_bat_number", "pitch_number"]
        if all(c in combined.columns for c in dedup_cols):
            combined = combined.drop_duplicates(subset=dedup_cols, keep="last")
    else:
        combined = new_df

    combined.to_parquet(path, index=False)
    new_count = len(combined) - (len(existing) if existing is not None else 0)
    logger.info("Wrote %s: %d total rows (+%d new)", path.name, len(combined), new_count)
    return max(new_count, 0)


def fetch_all_teams_incremental(
    season: int,
    *,
    delay_seconds: float = 5.0,
    local_dir: Path | None = None,
) -> dict[str, Any]:
    """Fetch incremental Statcast data for all MLB teams.

    Returns a summary dict with counts.
    """
    results: dict[str, int] = {}
    total_new = 0
    errors: list[str] = []

    abbrevs = sorted(set(TEAM_ABBREVS.values()))
    for i, abbrev in enumerate(abbrevs):
        try:
            new_rows = fetch_incremental(abbrev, season, local_dir=local_dir)
            results[abbrev] = new_rows
            total_new += new_rows
        except Exception as e:
            logger.exception("Error fetching %s: %s", abbrev, e)
            errors.append(f"{abbrev}: {e}")
            results[abbrev] = -1

        # Rate limit: don't hammer Savant
        if i < len(abbrevs) - 1 and delay_seconds > 0:
            time.sleep(delay_seconds)

    return {
        "teams_processed": len(abbrevs),
        "teams_with_new_data": sum(1 for v in results.values() if v > 0),
        "total_new_rows": total_new,
        "errors": errors,
        "details": results,
    }
