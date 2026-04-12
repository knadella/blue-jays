"""Pre-compute and disk-cache WeeklyActualsResponse for instant API serving."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from config import TEAM_ABBREVS

from ..schemas import WeeklyActualsResponse
from .weekly_actuals import build_weekly_actuals_payload

logger = logging.getLogger(__name__)

WEEKLY_CACHE_DIR = Path(os.getenv("WEEKLY_CACHE_DIR", ".cache/weekly_cache"))


def _cache_path(season: int, abbrev: str) -> Path:
    return WEEKLY_CACHE_DIR / f"{season}_{abbrev}.json"


def read_weekly_cache(season: int, abbrev: str) -> WeeklyActualsResponse | None:
    """Read a pre-computed WeeklyActualsResponse from disk cache.

    Returns None if cache file doesn't exist or is corrupt.
    """
    path = _cache_path(season, abbrev)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return WeeklyActualsResponse(**data)
    except Exception as e:
        logger.warning("Failed to read weekly cache %s: %s", path, e)
        return None


def warm_weekly_cache_for_team(
    season: int,
    team: str,
) -> dict[str, Any]:
    """Pre-compute and cache WeeklyActualsResponse for one team."""
    abbrev = TEAM_ABBREVS.get(team, "")
    if not abbrev:
        return {"team": team, "status": "unknown_team"}

    t0 = time.monotonic()
    try:
        payload = build_weekly_actuals_payload(season=season, team=team)
        WEEKLY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_path(season, abbrev)
        path.write_text(payload.model_dump_json())
        elapsed = round(time.monotonic() - t0, 1)
        logger.info("Cached %s (%s): %d weeks, %.1fs", team, abbrev, len(payload.weeks), elapsed)
        return {"team": team, "abbrev": abbrev, "weeks": len(payload.weeks), "elapsed_s": elapsed, "status": "ok"}
    except Exception as e:
        elapsed = round(time.monotonic() - t0, 1)
        logger.exception("Failed to cache %s: %s", team, e)
        return {"team": team, "status": "error", "error": str(e), "elapsed_s": elapsed}


def warm_weekly_cache(season: int) -> dict[str, Any]:
    """Pre-compute and cache WeeklyActualsResponse for ALL teams.

    This is the main function called by the admin endpoint after Statcast refresh.
    """
    t0 = time.monotonic()
    results: list[dict[str, Any]] = []

    for team in sorted(TEAM_ABBREVS.keys()):
        result = warm_weekly_cache_for_team(season, team)
        results.append(result)

    elapsed = round(time.monotonic() - t0, 1)
    ok_count = sum(1 for r in results if r["status"] == "ok")
    logger.info("Weekly cache warm complete: %d/%d teams in %.1fs", ok_count, len(results), elapsed)

    return {
        "teams_cached": ok_count,
        "teams_total": len(results),
        "elapsed_s": elapsed,
        "details": results,
    }
