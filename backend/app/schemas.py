"""Pydantic schemas exposed by the FastAPI backend."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WinPoint(BaseModel):
    date: str
    wins: int


class SimulationDensityCell(BaseModel):
    date: str
    wins: int
    probability: float


class TeamSimulationView(BaseModel):
    team: str
    division: str
    actual_points: list[WinPoint] = Field(default_factory=list)
    simulation_density: list[SimulationDensityCell] = Field(default_factory=list)
    projected_final_wins: int
    projected_division_place: int
    playoff_probability: float


class DashboardMeta(BaseModel):
    generated_at: str
    games_completed: int
    games_remaining: int
    model_source: str
    simulation_count: int


class TeamRating(BaseModel):
    team: str
    value: float


class TeamRatings(BaseModel):
    offense: list[TeamRating] = Field(default_factory=list)
    defense: list[TeamRating] = Field(default_factory=list)


class ScheduleGame(BaseModel):
    date: str
    opponent: str
    is_home: bool
    opponent_strength: float


class DashboardResponse(BaseModel):
    season: int
    favorite_team: str
    team_simulation: TeamSimulationView
    team_ratings: TeamRatings
    remaining_schedule: list[ScheduleGame] = Field(default_factory=list)
    meta: DashboardMeta
