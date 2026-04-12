"""FastAPI entrypoint for MLB Forecast V2."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from config import (
    ADMIN_API_KEY,
    ALL_TEAMS,
    CORS_ORIGINS,
    DEFAULT_SEASON,
    GITHUB_PAGES_CORS_ORIGIN_REGEX,
    SKIP_DASHBOARD_WARMUP,
    TEAM_ABBREVS,
)

from .schemas import (
    BaselineMetrics,
    CalibrationBin,
    DashboardResponse,
    EvaluationMetrics,
    EvaluationResponse,
    GamePrediction,
    MCMCDiagnostics,
    RefitResponse,
    RefreshResponse,
    WalkForwardResponse,
    WalkForwardWindow,
    WeeklyActualsResponse,
)
from .services.weekly_actuals import build_weekly_actuals_payload

logger = logging.getLogger(__name__)

app = FastAPI(title="MLB Statcast Weekly API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=GITHUB_PAGES_CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _start_dashboard_warmup() -> None:
    """Fit or load the model after boot so the first browser hit is not stuck on MCMC."""

    if SKIP_DASHBOARD_WARMUP:
        return

    def run() -> None:
        try:
            from .services.dashboard import warm_dashboard_cache

            warm_dashboard_cache(DEFAULT_SEASON)
            logger.info("Dashboard cache warmed for season %s", DEFAULT_SEASON)
        except Exception:
            logger.exception(
                "Dashboard warmup failed; first GET /api/dashboard will fit on demand.",
            )

    threading.Thread(target=run, daemon=True, name="dashboard-warmup").start()


def verify_admin_key(
    x_admin_key: Annotated[Optional[str], Header(alias="X-Admin-Key")] = None,
) -> None:
    """Require X-Admin-Key when ADMIN_API_KEY is configured (production)."""
    if not ADMIN_API_KEY:
        return
    if not x_admin_key or x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Key")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    """Cheap check without /api prefix; use IPv4 curl if `localhost` hangs on your OS."""
    return {"status": "ok", "health": "/api/health"}


@app.get("/api/teams")
def teams() -> list[str]:
    return ALL_TEAMS


@app.get("/api/weekly-actuals")
def weekly_actuals(
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
    team: str = Query("Toronto Blue Jays"),
):
    """Pitch-level Statcast splits by ISO week (offense + run prevention)."""
    from fastapi.responses import Response

    from .services.weekly_cache import WEEKLY_CACHE_DIR

    # Fast path: serve cached JSON directly (no Pydantic round-trip)
    favorite = team if team in ALL_TEAMS else "Toronto Blue Jays"
    abbrev = TEAM_ABBREVS.get(favorite, "")
    cache_path = WEEKLY_CACHE_DIR / f"{season}_{abbrev}.json"
    if cache_path.exists():
        return Response(
            content=cache_path.read_bytes(),
            media_type="application/json",
        )

    # Fallback: compute live
    return build_weekly_actuals_payload(season=season, team=team)


@app.get("/api/dashboard", response_model=DashboardResponse)
def dashboard(
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
    team: str = Query("Toronto Blue Jays"),
    force_refit: bool = Query(False),
) -> DashboardResponse:
    from .services.dashboard import build_dashboard_payload

    favorite_team = team if team in ALL_TEAMS else "Toronto Blue Jays"
    return build_dashboard_payload(
        season=season,
        favorite_team=favorite_team,
        force_refit=force_refit,
    )


@app.get("/api/evaluate", response_model=EvaluationResponse)
def evaluate(
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
) -> EvaluationResponse:
    from .services.evaluation import build_evaluation

    raw = build_evaluation(season)
    diag = raw.get("mcmc_diagnostics")
    return EvaluationResponse(
        season=raw["season"],
        n_games=raw["n_games"],
        model_source=raw["model_source"],
        metrics=EvaluationMetrics(**raw["metrics"]),
        baselines=BaselineMetrics(**raw["baselines"]),
        mcmc_diagnostics=MCMCDiagnostics(**diag) if diag else None,
        calibration=[CalibrationBin(**b) for b in raw["calibration"]],
        biggest_surprises=[GamePrediction(**g) for g in raw["biggest_surprises"]],
    )


@app.get("/api/evaluate/walkforward", response_model=WalkForwardResponse)
async def evaluate_walkforward(
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
    step_days: int = Query(7, ge=1, le=30),
) -> WalkForwardResponse:
    """Out-of-sample walk-forward evaluation.

    Fits the model repeatedly on expanding windows and scores predictions
    on unseen future games.  Slow (many MCMC fits) -- runs in a worker thread.
    """
    from .services.evaluation import build_walk_forward_evaluation

    raw = await asyncio.to_thread(build_walk_forward_evaluation, season, step_days)
    return WalkForwardResponse(
        season=raw["season"],
        evaluation_type=raw["evaluation_type"],
        step_days=raw["step_days"],
        n_windows=raw["n_windows"],
        n_games_scored=raw["n_games_scored"],
        metrics=EvaluationMetrics(**raw["metrics"]),
        baselines=BaselineMetrics(**raw["baselines"]),
        calibration=[CalibrationBin(**b) for b in raw["calibration"]],
        windows=[WalkForwardWindow(**w) for w in raw["windows"]],
    )


# ---------------------------------------------------------------------------
# Admin endpoints (triggered by external cron / scheduler)
# ---------------------------------------------------------------------------


@app.post("/api/admin/refresh-actuals", response_model=RefreshResponse)
def admin_refresh_actuals(
    _auth: Annotated[None, Depends(verify_admin_key)],
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
) -> RefreshResponse:
    """Clear caches and re-fetch game scores from the MLB API.

    Intended to be called daily.  Fast (~30 s) -- no model refit.
    """
    from .services.refresh import refresh_actuals

    result = refresh_actuals(season)
    return RefreshResponse(**result)


@app.post("/api/admin/warm-monthly-cache")
async def admin_warm_monthly_cache(
    _auth: Annotated[None, Depends(verify_admin_key)],
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
) -> dict[str, str]:
    """Pre-compute monthly model snapshots to disk so dashboard requests
    never block on MCMC.  Called by the scheduled refresh-actuals action."""
    from .services.dashboard import warm_monthly_projection_cache

    await asyncio.to_thread(warm_monthly_projection_cache, season)
    return {"status": "ok"}


@app.post("/api/admin/refresh-statcast")
async def admin_refresh_statcast(
    _auth: Annotated[None, Depends(verify_admin_key)],
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
) -> dict:
    """Fetch incremental Statcast data from Savant, then pre-compute all weekly caches.

    Intended to be called daily.  Takes ~10-15 minutes for 30 teams.
    """
    import time

    from data_source.savant_csv import fetch_all_teams_incremental

    from .services.weekly_cache import warm_weekly_cache

    t0 = time.monotonic()

    # Step 1: Fetch incremental Statcast data
    fetch_result = await asyncio.to_thread(fetch_all_teams_incremental, season)

    # Step 2: Pre-compute and cache all weekly actuals responses
    cache_result = await asyncio.to_thread(warm_weekly_cache, season)

    elapsed = round(time.monotonic() - t0, 1)
    return {
        "status": "ok",
        "elapsed_s": elapsed,
        "fetch": fetch_result,
        "cache": cache_result,
    }


@app.post("/api/admin/warm-weekly-cache")
async def admin_warm_weekly_cache(
    _auth: Annotated[None, Depends(verify_admin_key)],
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
) -> dict:
    """Pre-compute weekly actuals cache without fetching new data.

    Useful after manually adding parquet files.
    """
    from .services.weekly_cache import warm_weekly_cache

    result = await asyncio.to_thread(warm_weekly_cache, season)
    return {"status": "ok", **result}


@app.post("/api/admin/refit-model", response_model=RefitResponse)
async def admin_refit_model(
    _auth: Annotated[None, Depends(verify_admin_key)],
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
) -> RefitResponse:
    """Fetch fresh data, run a full MCMC refit, and update caches.

    Intended to be called weekly.  Slow (minutes) -- runs the MCMC fit
    in a worker thread so the event loop stays responsive.
    """
    from .services.refresh import refit_model

    result = await asyncio.to_thread(refit_model, season)
    return RefitResponse(**result)
