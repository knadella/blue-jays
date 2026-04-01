"""Pydantic schemas exposed by the FastAPI backend."""

from __future__ import annotations

from typing import Optional

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
    actual_wins: int = 0
    actual_losses: int = 0
    actual_division_place: int = 1
    streak: str = ""
    run_differential: int = 0
    schedule_strength_played: Optional[float] = None
    schedule_strength_remaining: Optional[float] = None
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


class DivisionStanding(BaseModel):
    team: str
    projected_wins: int


class DashboardResponse(BaseModel):
    season: int
    favorite_team: str
    team_simulation: TeamSimulationView
    team_ratings: TeamRatings
    remaining_schedule: list[ScheduleGame] = Field(default_factory=list)
    division_standings: dict[str, list[DivisionStanding]] = Field(default_factory=dict)
    meta: DashboardMeta


# ---------------------------------------------------------------------------
# Evaluation schemas
# ---------------------------------------------------------------------------


class EvaluationMetrics(BaseModel):
    log_loss: float
    brier_score: float
    accuracy: float
    runs_mae: float
    runs_mae_home: float
    runs_mae_away: float
    home_win_rate: float


class BaselineMetrics(BaseModel):
    constant_accuracy: float
    constant_brier: float
    constant_log_loss: float


class CalibrationBin(BaseModel):
    bin_start: float
    bin_end: float
    predicted_mean: float
    observed_frequency: float
    count: int


class GamePrediction(BaseModel):
    game_date: str
    home_team: str
    away_team: str
    predicted_home_win_prob: float
    actual_home_win: int
    predicted_home_runs: float
    predicted_away_runs: float
    actual_home_runs: int
    actual_away_runs: int


class MCMCDiagnostics(BaseModel):
    rhat_max: float
    ess_bulk_min: float
    ess_tail_min: float
    divergences: int
    warnings: list[str] = Field(default_factory=list)


class EvaluationResponse(BaseModel):
    season: int
    n_games: int
    model_source: str
    metrics: EvaluationMetrics
    baselines: BaselineMetrics
    mcmc_diagnostics: Optional[MCMCDiagnostics] = None
    calibration: list[CalibrationBin] = Field(default_factory=list)
    biggest_surprises: list[GamePrediction] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Admin / refresh schemas
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Walk-forward evaluation schemas
# ---------------------------------------------------------------------------


class WalkForwardWindow(BaseModel):
    window_start: str
    window_end: str
    train_games: int
    test_games: int
    log_loss: float
    brier_score: float
    accuracy: float


class WalkForwardResponse(BaseModel):
    season: int
    evaluation_type: str
    step_days: int
    n_windows: int
    n_games_scored: int
    metrics: EvaluationMetrics
    baselines: BaselineMetrics
    calibration: list[CalibrationBin] = Field(default_factory=list)
    windows: list[WalkForwardWindow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Admin / refresh schemas
# ---------------------------------------------------------------------------


class RefreshResponse(BaseModel):
    status: str
    season: int
    games_completed: int
    timestamp: str


class RefitResponse(BaseModel):
    status: str
    season: int
    games_fitted: int
    model_source: str
    diagnostics: Optional[dict] = None
    timestamp: str
