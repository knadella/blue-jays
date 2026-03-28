"""Orchestration for daily actuals refresh and weekly model refit."""

from __future__ import annotations

from datetime import datetime, timezone

from config import ALL_TEAMS, DEFAULT_SEASON
from data_source.mlb_api import (
    clear_schedule_cache,
    completed_game_rows,
    fetch_schedule,
    split_schedule,
)

from .dashboard import clear_dashboard_cache
from .modeling import fit_or_load_snapshot


def refresh_actuals(season: int = DEFAULT_SEASON) -> dict:
    """Clear caches so the next request picks up fresh game scores.

    This is the *daily* path -- fast, no MCMC fit.  It invalidates the
    schedule LRU (so the MLB API is re-queried) and the dashboard LRU
    (so payloads are rebuilt with the existing posterior + fresh scores).
    """
    clear_schedule_cache()
    clear_dashboard_cache()

    schedule = fetch_schedule(season)
    completed, _ = split_schedule(schedule)

    return {
        "status": "ok",
        "season": season,
        "games_completed": len(completed),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def refit_model(season: int = DEFAULT_SEASON) -> dict:
    """Fetch fresh data, run a full MCMC refit, and refresh caches.

    This is the *weekly* path -- slow (minutes), produces a new posterior
    snapshot on disk, then clears the dashboard cache so subsequent
    requests use the updated model.
    """
    clear_schedule_cache()

    schedule = fetch_schedule(season)
    completed, _ = split_schedule(schedule)
    games = completed_game_rows(completed)

    snapshot = fit_or_load_snapshot(
        season=season,
        completed_games=games,
        teams=ALL_TEAMS,
        force_refit=True,
    )

    clear_dashboard_cache()

    return {
        "status": "ok",
        "season": season,
        "games_fitted": len(games),
        "model_source": snapshot.source,
        "diagnostics": snapshot.diagnostics,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
