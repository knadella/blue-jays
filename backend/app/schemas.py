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


class TeamRatingVsActual(BaseModel):
    """Season-to-date actual run rates vs model projection for the dashboard team."""

    runs_scored_per_game_projected: float
    runs_scored_per_game_actual: Optional[float] = None
    runs_allowed_per_game_projected: float
    runs_allowed_per_game_actual: Optional[float] = None


class MonthlyRunRatePoint(BaseModel):
    """Per month: team + league projections and actuals for that calendar month."""

    month: int
    label: str
    runs_scored_projected: float
    runs_allowed_projected: float
    league_runs_scored_projected: float
    league_runs_allowed_projected: float
    runs_scored_actual: Optional[float] = None
    runs_allowed_actual: Optional[float] = None
    league_runs_scored_actual: Optional[float] = None
    league_runs_allowed_actual: Optional[float] = None


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
    team_rating_vs_actual: TeamRatingVsActual
    monthly_run_rates: list[MonthlyRunRatePoint] = Field(default_factory=list)
    remaining_schedule: list[ScheduleGame] = Field(default_factory=list)
    division_standings: dict[str, list[DivisionStanding]] = Field(default_factory=dict)
    meta: DashboardMeta


# ---------------------------------------------------------------------------
# Weekly Statcast actuals (pitch-level progression)
# ---------------------------------------------------------------------------


class PitchTypeRow(BaseModel):
    pitch_type: str
    pitch_label: str
    pitches: int
    swing_rate: float
    whiff_rate: Optional[float] = None
    chase_rate: Optional[float] = None
    xwoba_on_contact: Optional[float] = None


class WeekSideMetrics(BaseModel):
    """Plate-discipline and contact summary for one split (offense or run prevention)."""

    pitches: int
    plate_appearances: int = 0
    swing_rate: Optional[float] = None
    whiff_rate: Optional[float] = None
    zone_swing_rate: Optional[float] = None
    chase_rate: Optional[float] = None
    contact_rate: Optional[float] = None
    called_strike_rate: Optional[float] = None
    xwoba_on_contact: Optional[float] = None
    xwoba: Optional[float] = None
    avg_exit_velo_bip: Optional[float] = None
    hard_hit_rate: Optional[float] = None
    barrel_rate: Optional[float] = None
    avg_launch_angle_bip: Optional[float] = None
    groundball_rate: Optional[float] = None
    flyball_rate: Optional[float] = None
    popup_rate: Optional[float] = None
    avg_iso_value_bip: Optional[float] = None
    if_standard_pct: Optional[float] = None
    if_strategic_pct: Optional[float] = None
    of_strategic_pct: Optional[float] = None


class WeeklyBucket(BaseModel):
    week_key: str
    week_start: str
    week_end: str
    offense: WeekSideMetrics
    run_prevention: WeekSideMetrics
    hitting_vs_pitch_types: list[PitchTypeRow] = Field(default_factory=list)
    pitching_pitch_types: list[PitchTypeRow] = Field(default_factory=list)


class OffenseMonthLeagueShape(BaseModel):
    """Apr–Sep calendar month: offense metric ranks vs other clubs that month (1 = best)."""

    month: int = Field(..., ge=4, le=9)
    xwoba_pct: Optional[int] = None
    chase_pct: Optional[int] = None
    whiff_pct: Optional[int] = None
    hard_hit_pct: Optional[int] = None
    xwoba_rank: Optional[int] = None
    barrel_rank: Optional[int] = None
    chase_rank: Optional[int] = None
    whiff_rank: Optional[int] = None
    # Pitching/defense ranks (1 = best, i.e. lowest xwOBA allowed, lowest barrel allowed, highest chase generated, highest whiff generated)
    p_xwoba_rank: Optional[int] = None
    p_barrel_rank: Optional[int] = None
    p_chase_rank: Optional[int] = None
    p_whiff_rank: Optional[int] = None


class ChaseZoneCell(BaseModel):
    x: int
    y: int
    n: int
    sw: int
    iz: int


class ChaseZoneMonth(BaseModel):
    month: int
    cells: list[ChaseZoneCell]


class ChaseZoneGrid(BaseModel):
    sz_top: float
    sz_bot: float
    zone_width: float
    nx: int
    ny: int
    x_range: list[float]
    y_range: list[float]
    months: list[ChaseZoneMonth]


class WhiffZoneCell(BaseModel):
    x: int
    y: int
    n: int
    wh: int


class WhiffZoneMonth(BaseModel):
    month: int
    cells: list[WhiffZoneCell]


class WhiffZoneGrid(BaseModel):
    sz_top: float
    sz_bot: float
    zone_width: float
    nx: int
    ny: int
    x_range: list[float]
    y_range: list[float]
    months: list[WhiffZoneMonth]


class BarrelCell(BaseModel):
    x: int
    y: int
    n: int
    brl: int


class BarrelMonth(BaseModel):
    month: int
    cells: list[BarrelCell]


class BarrelGrid(BaseModel):
    nx: int
    ny: int
    ev_range: list[float]
    la_range: list[float]
    months: list[BarrelMonth]


class SprayCell(BaseModel):
    x: int
    y: int
    n: int
    xw: float


class SprayMonth(BaseModel):
    month: int
    cells: list[SprayCell]


class SprayGrid(BaseModel):
    nx: int
    ny: int
    x_range: list[float]
    y_range: list[float]
    months: list[SprayMonth]


class WeeklyActualsResponse(BaseModel):
    season: int
    team: str
    team_abbrev: str
    division: str
    wins: int
    losses: int
    runs_per_game: float = 0.0
    runs_allowed_per_game: float = 0.0
    runs_per_game_rank: int = 0
    runs_allowed_per_game_rank: int = 0
    run_differential: int = 0
    division_place: int = 0
    streak: str = ""
    weeks: list[WeeklyBucket] = Field(default_factory=list)
    statcast_rows: int = 0
    data_through: Optional[str] = None
    generated_at: str
    note: Optional[str] = None
    offense_monthly_league_shape: list[OffenseMonthLeagueShape] = Field(default_factory=list)
    league_offense_months_teams: int = 0
    chase_zone_grid: Optional[ChaseZoneGrid] = None
    whiff_zone_grid: Optional[WhiffZoneGrid] = None
    barrel_grid: Optional[BarrelGrid] = None
    spray_grid: Optional[SprayGrid] = None
    pitching_chase_zone_grid: Optional[ChaseZoneGrid] = None
    pitching_whiff_zone_grid: Optional[WhiffZoneGrid] = None
    pitching_barrel_grid: Optional[BarrelGrid] = None
    pitching_spray_grid: Optional[SprayGrid] = None


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
