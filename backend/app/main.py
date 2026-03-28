"""FastAPI entrypoint for MLB Forecast V2."""

from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from config import ALL_TEAMS, DEFAULT_SEASON

from .schemas import DashboardResponse
from .services.dashboard import build_dashboard_payload

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
