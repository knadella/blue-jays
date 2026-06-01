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
    DEFAULT_TEAM_ABBREV,
    GITHUB_PAGES_CORS_ORIGIN_REGEX,
    SELECTABLE_TEAMS,
    TEAM_ABBREVS,
    resolve_team,
)

from .schemas import PlayersResponse, RefreshResponse, StandingsResponse, TodayResponse
from .services.game_story import build_today_payload
from .services.standings import build_standings_payload
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


@app.on_event("startup")
def _prewarm_players_on_startup() -> None:
    """Warm the season-players payload for every selectable team in the
    background, so the first real request is served from the persisted cache.

    Runs in a daemon thread (non-blocking startup) and is skipped when
    ``SKIP_DASHBOARD_WARMUP`` is set — handy for fast local dev restarts.
    """
    import os
    import threading

    if os.getenv("SKIP_DASHBOARD_WARMUP", "").strip().lower() in ("1", "true", "yes", "on"):
        return

    def _warm() -> None:
        for abbrev in SELECTABLE_TEAMS:
            try:
                _, _, team_id = resolve_team(abbrev)
                serve_players_payload(DEFAULT_SEASON, team_id=team_id, abbrev=abbrev)
                logger.info("prewarmed players for %s %s", abbrev, DEFAULT_SEASON)
            except Exception:  # noqa: BLE001
                logger.warning("startup prewarm failed for %s", abbrev, exc_info=True)

    threading.Thread(target=_warm, name="players-prewarm", daemon=True).start()


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


@app.get("/api/teams")
def teams() -> dict:
    """Teams offered in the picker, in display order."""
    out = []
    for ab in SELECTABLE_TEAMS:
        abbrev, name, _ = resolve_team(ab)
        out.append({"abbrev": abbrev, "name": name})
    return {"teams": out, "default": DEFAULT_TEAM_ABBREV}


@app.get("/api/today", response_model=TodayResponse)
def today(team: str = Query(DEFAULT_TEAM_ABBREV)) -> TodayResponse:
    """Post-game story for the most recent completed game for *team*."""
    _, name, team_id = resolve_team(team)
    payload = build_today_payload(team_id=team_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"No recent Final game found for {name}")
    return payload


@app.get("/api/players")
def players(
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
    team: str = Query(DEFAULT_TEAM_ABBREV),
):
    """Season-long net WPA contribution per player for *team*.

    Served from the persisted payload on disk when its games-included fingerprint
    matches the current schedule; otherwise rebuilt and re-persisted.
    """
    from fastapi.responses import Response

    abbrev, _, team_id = resolve_team(team)
    return Response(
        content=serve_players_payload(season, team_id=team_id, abbrev=abbrev),
        media_type="application/json",
    )


@app.get("/api/standings", response_model=StandingsResponse)
def standings(
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
    team: str = Query(DEFAULT_TEAM_ABBREV),
) -> StandingsResponse:
    """Division standings, recent momentum, and record by opponent quality for *team*."""
    _, name, _ = resolve_team(team)
    return build_standings_payload(season, favorite=name)


@app.get("/api/weekly-actuals")
def weekly_actuals(
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
    team: str = Query(DEFAULT_TEAM_ABBREV),
):
    """Pitch-level Statcast splits by ISO week (offense + run prevention) for *team*."""
    from fastapi.responses import Response

    from .services.weekly_cache import WEEKLY_CACHE_DIR

    abbrev, name, _ = resolve_team(team)
    cache_path = WEEKLY_CACHE_DIR / f"{season}_{abbrev}.json"
    if cache_path.exists():
        return Response(
            content=cache_path.read_bytes(),
            media_type="application/json",
        )

    return build_weekly_actuals_payload(season=season, team=name)


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
