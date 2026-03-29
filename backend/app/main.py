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
)
from .services.dashboard import build_dashboard_payload, warm_dashboard_cache
from .services.evaluation import build_evaluation, build_walk_forward_evaluation
from .services.refresh import refit_model, refresh_actuals

logger = logging.getLogger(__name__)

app = FastAPI(title="MLB Forecast API", version="2.0.0")
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


@app.get("/api/teams")
def teams() -> list[str]:
    return ALL_TEAMS


@app.get("/api/dashboard", response_model=DashboardResponse)
def dashboard(
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
    team: str = Query("Toronto Blue Jays"),
    force_refit: bool = Query(False),
) -> DashboardResponse:
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
    result = refresh_actuals(season)
    return RefreshResponse(**result)


@app.post("/api/admin/refit-model", response_model=RefitResponse)
async def admin_refit_model(
    _auth: Annotated[None, Depends(verify_admin_key)],
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
) -> RefitResponse:
    """Fetch fresh data, run a full MCMC refit, and update caches.

    Intended to be called weekly.  Slow (minutes) -- runs the MCMC fit
    in a worker thread so the event loop stays responsive.
    """
    result = await asyncio.to_thread(refit_model, season)
    return RefitResponse(**result)
