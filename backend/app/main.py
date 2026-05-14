"""FastAPI entrypoint — Blue-Jays-only Statcast weekly progression."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from config import (
    ADMIN_API_KEY,
    CORS_ORIGINS,
    DEFAULT_SEASON,
    GITHUB_PAGES_CORS_ORIGIN_REGEX,
    TEAM_ABBREVS,
)

from .schemas import PlayersResponse, RefreshResponse, TodayResponse
from .services.game_story import build_today_payload
from .services.player_season import (
    invalidate_players_payload,
    serve_players_payload,
)
from .services.weekly_actuals import build_weekly_actuals_payload

logger = logging.getLogger(__name__)

FAVORITE_TEAM = "Toronto Blue Jays"

app = FastAPI(title="Toronto Blue Jays Statcast Weekly", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=GITHUB_PAGES_CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_admin_key(
    x_admin_key: Annotated[Optional[str], Header(alias="X-Admin-Key")] = None,
) -> None:
    if not ADMIN_API_KEY:
        return
    if not x_admin_key or x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Key")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "team": FAVORITE_TEAM, "health": "/api/health"}


@app.get("/api/team")
def team() -> dict[str, str]:
    return {"team": FAVORITE_TEAM}


@app.get("/api/today", response_model=TodayResponse)
def today() -> TodayResponse:
    """Post-game story for the most recent completed Blue Jays game."""
    payload = build_today_payload()
    if payload is None:
        raise HTTPException(status_code=404, detail="No recent Final Blue Jays game found")
    return payload


@app.get("/api/players")
def players(season: int = Query(DEFAULT_SEASON, ge=2000, le=2100)):
    """Season-long net WPA contribution per Blue Jays player.

    Served from the persisted payload on disk when its games-included fingerprint
    matches the current schedule; otherwise rebuilt and re-persisted.
    """
    from fastapi.responses import Response

    return Response(content=serve_players_payload(season), media_type="application/json")


@app.get("/api/weekly-actuals")
def weekly_actuals(
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
):
    """Pitch-level Statcast splits by ISO week (offense + run prevention) for the Blue Jays."""
    from fastapi.responses import Response

    from .services.weekly_cache import WEEKLY_CACHE_DIR

    abbrev = TEAM_ABBREVS[FAVORITE_TEAM]
    cache_path = WEEKLY_CACHE_DIR / f"{season}_{abbrev}.json"
    if cache_path.exists():
        return Response(
            content=cache_path.read_bytes(),
            media_type="application/json",
        )

    return build_weekly_actuals_payload(season=season)


# ---------------------------------------------------------------------------
# Admin endpoints (triggered by external cron / scheduler)
# ---------------------------------------------------------------------------


@app.post("/api/admin/refresh-actuals", response_model=RefreshResponse)
def admin_refresh_actuals(
    _auth: Annotated[None, Depends(verify_admin_key)],
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
) -> RefreshResponse:
    """Clear caches and re-fetch game scores from the MLB API for the Blue Jays."""
    from datetime import datetime, timezone

    from data_source.mlb_api import (
        clear_schedule_cache,
        fetch_schedule,
        split_schedule,
    )

    clear_schedule_cache()
    schedule = fetch_schedule(season)
    completed, _ = split_schedule(schedule)
    completed_for_team = [
        g for g in completed
        if g.get("home_name") == FAVORITE_TEAM or g.get("away_name") == FAVORITE_TEAM
    ]

    return RefreshResponse(
        status="ok",
        season=season,
        games_completed=len(completed_for_team),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/api/admin/refresh-players")
def admin_refresh_players(
    _auth: Annotated[None, Depends(verify_admin_key)],
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
) -> RefreshResponse:
    """Invalidate the persisted players payload and rebuild it from per-game cache."""
    import json
    from datetime import datetime, timezone

    invalidate_players_payload(season)
    raw = serve_players_payload(season)
    games_completed = int(json.loads(raw).get("games_included", 0))
    return RefreshResponse(
        status="ok",
        season=season,
        games_completed=games_completed,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/api/admin/refresh-statcast")
async def admin_refresh_statcast(
    _auth: Annotated[None, Depends(verify_admin_key)],
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
) -> dict:
    """Fetch incremental Blue Jays Statcast data from Savant, then pre-compute the weekly cache."""
    import time

    from data_source.savant_csv import fetch_incremental

    from .services.weekly_cache import warm_weekly_cache

    abbrev = TEAM_ABBREVS[FAVORITE_TEAM]
    t0 = time.monotonic()
    new_rows = await asyncio.to_thread(fetch_incremental, abbrev, season)
    cache_result = await asyncio.to_thread(warm_weekly_cache, season)
    elapsed = round(time.monotonic() - t0, 1)
    return {
        "status": "ok",
        "elapsed_s": elapsed,
        "team": FAVORITE_TEAM,
        "abbrev": abbrev,
        "new_rows": new_rows,
        "cache": cache_result,
    }
