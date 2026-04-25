"""Pre-compute and disk-cache WeeklyActualsResponse for instant API serving (Blue Jays only)."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from config import TEAM_ABBREVS

from ..schemas import WeeklyActualsResponse
from .weekly_actuals import FAVORITE_TEAM, build_weekly_actuals_payload

logger = logging.getLogger(__name__)

WEEKLY_CACHE_DIR = Path(os.getenv("WEEKLY_CACHE_DIR", ".cache/weekly_cache"))


def _cache_path(season: int, abbrev: str) -> Path:
    return WEEKLY_CACHE_DIR / f"{season}_{abbrev}.json"


def read_weekly_cache(season: int, abbrev: str) -> WeeklyActualsResponse | None:
    """Read a pre-computed WeeklyActualsResponse from disk cache."""
    path = _cache_path(season, abbrev)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return WeeklyActualsResponse(**data)
    except Exception as e:
        logger.warning("Failed to read weekly cache %s: %s", path, e)
        return None


def warm_weekly_cache(season: int) -> dict[str, Any]:
    """Pre-compute and cache the Blue Jays' WeeklyActualsResponse."""
    abbrev = TEAM_ABBREVS[FAVORITE_TEAM]
    t0 = time.monotonic()
    try:
        payload = build_weekly_actuals_payload(season=season, skip_cache=True)
        WEEKLY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_path(season, abbrev)
        path.write_text(payload.model_dump_json())
        elapsed = round(time.monotonic() - t0, 1)
        logger.info("Cached %s (%s): %d weeks, %.1fs", FAVORITE_TEAM, abbrev, len(payload.weeks), elapsed)
        return {
            "team": FAVORITE_TEAM,
            "abbrev": abbrev,
            "weeks": len(payload.weeks),
            "elapsed_s": elapsed,
            "status": "ok",
        }
    except Exception as e:
        elapsed = round(time.monotonic() - t0, 1)
        logger.exception("Failed to cache %s: %s", FAVORITE_TEAM, e)
        return {"team": FAVORITE_TEAM, "status": "error", "error": str(e), "elapsed_s": elapsed}
