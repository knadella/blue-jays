"""FastAPI entrypoint for MLB Forecast V2."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from config import ALL_TEAMS, DEFAULT_SEASON

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
)
from .services.dashboard import build_dashboard_payload
from .services.evaluation import build_evaluation
from .services.refresh import refit_model, refresh_actuals

app = FastAPI(title="MLB Forecast API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# ---------------------------------------------------------------------------
# Admin endpoints (triggered by external cron / scheduler)
# ---------------------------------------------------------------------------


@app.post("/api/admin/refresh-actuals", response_model=RefreshResponse)
def admin_refresh_actuals(
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
) -> RefreshResponse:
    """Clear caches and re-fetch game scores from the MLB API.

    Intended to be called daily.  Fast (~30 s) -- no model refit.
    """
    result = refresh_actuals(season)
    return RefreshResponse(**result)


@app.post("/api/admin/refit-model", response_model=RefitResponse)
async def admin_refit_model(
    season: int = Query(DEFAULT_SEASON, ge=2000, le=2100),
) -> RefitResponse:
    """Fetch fresh data, run a full MCMC refit, and update caches.

    Intended to be called weekly.  Slow (minutes) -- runs the MCMC fit
    in a worker thread so the event loop stays responsive.
    """
    result = await asyncio.to_thread(refit_model, season)
    return RefitResponse(**result)
