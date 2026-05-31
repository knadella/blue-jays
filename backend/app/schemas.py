"""Pydantic schemas exposed by the FastAPI backend."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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
    wins: int
    losses: int
    runs_per_game: float = 0.0
    runs_allowed_per_game: float = 0.0
    run_differential: int = 0
    streak: str = ""
    weeks: list[WeeklyBucket] = Field(default_factory=list)
    statcast_rows: int = 0
    data_through: Optional[str] = None
    generated_at: str
    note: Optional[str] = None
    chase_zone_grid: Optional[ChaseZoneGrid] = None
    whiff_zone_grid: Optional[WhiffZoneGrid] = None
    barrel_grid: Optional[BarrelGrid] = None
    spray_grid: Optional[SprayGrid] = None
    pitching_chase_zone_grid: Optional[ChaseZoneGrid] = None
    pitching_whiff_zone_grid: Optional[WhiffZoneGrid] = None
    pitching_barrel_grid: Optional[BarrelGrid] = None
    pitching_spray_grid: Optional[SprayGrid] = None


# ---------------------------------------------------------------------------
# Admin / refresh schemas
# ---------------------------------------------------------------------------


class RefreshResponse(BaseModel):
    status: str
    season: int
    games_completed: int
    timestamp: str


# ---------------------------------------------------------------------------
# Today (post-game story)
# ---------------------------------------------------------------------------


class GameHeader(BaseModel):
    game_pk: int
    game_date: str
    venue: str
    home_team: str
    home_abbr: str
    away_team: str
    away_abbr: str
    home_score: int
    away_score: int
    jays_won: bool
    jays_score: int
    opp_score: int


class WEPoint(BaseModel):
    play_index: int
    inning: int
    half: str  # "T" or "B"
    we_jays: float


class LeveragePlay(BaseModel):
    play_index: int
    inning: int
    half: str
    score_before: str
    description: str
    wpa_jays: float
    we_before_jays: float
    we_after_jays: float
    # State going INTO the play, used to explain why the WPA was big or small.
    outs_before: int = 0
    bases_before: str = "000"  # 3-char mask, "1" = runner present
    jays_diff_before: int = 0  # Jays score minus opponent score, going in
    why: str = ""  # one-line plain-English explanation of the WPA magnitude


class Contributor(BaseModel):
    player_id: int
    name: str
    wpa: float
    pa: int
    rbi: int = 0
    best_play: Optional[str] = None
    worst_play: Optional[str] = None


class PitcherLine(BaseModel):
    player_id: int
    name: str
    role: str  # "starter" | "relief"
    ip: str
    h: int
    r: int
    er: int
    k: int
    bb: int
    pitches: int
    note: str = ""


class TodayResponse(BaseModel):
    header: GameHeader
    we_trajectory: list[WEPoint]
    leverage_plays: list[LeveragePlay]
    top_contributors: list[Contributor]
    negative_contributors: list[Contributor]
    starter: Optional[PitcherLine] = None
    relievers: list[PitcherLine] = Field(default_factory=list)
    bullpen_pitches: int = 0
    opp_starter: Optional[PitcherLine] = None
    we_table_meta: dict
    generated_at: str


# ---------------------------------------------------------------------------
# Players (season-long net contribution)
# ---------------------------------------------------------------------------


class BatterWindow(BaseModel):
    wpa: float
    games: int
    pa: int
    rbi: int = 0
    # Production line (helps decode the WPA number)
    ab: int = 0
    h: int = 0
    hr: int = 0
    so: int = 0
    bb: int = 0
    avg: Optional[float] = None
    obp: Optional[float] = None
    slg: Optional[float] = None


class PitcherWindow(BaseModel):
    wpa: float
    games: int
    starts: int = 0
    bf: int = 0
    pitches: int = 0
    # Production line
    ip: str = "0.0"
    er: int = 0
    so: int = 0
    bb: int = 0
    era: Optional[float] = None


class BatterCard(BaseModel):
    player_id: int
    name: str
    wpa: float
    games: int
    pa: int
    rbi: int = 0
    ab: int = 0
    h: int = 0
    hr: int = 0
    so: int = 0
    bb: int = 0
    avg: Optional[float] = None
    obp: Optional[float] = None
    slg: Optional[float] = None
    recent30: Optional[BatterWindow] = None
    spark_30: list[float] = Field(default_factory=list)


class PitcherCard(BaseModel):
    player_id: int
    name: str
    wpa: float
    games: int
    starts: int = 0
    bf: int = 0
    pitches: int = 0
    ip: str = "0.0"
    er: int = 0
    so: int = 0
    bb: int = 0
    era: Optional[float] = None
    recent30: Optional[PitcherWindow] = None
    spark_30: list[float] = Field(default_factory=list)


class PlayersResponse(BaseModel):
    season: int
    games_included: int
    last_game_date: Optional[str] = None
    batters: list[BatterCard] = Field(default_factory=list)
    pitchers: list[PitcherCard] = Field(default_factory=list)
    generated_at: str


# ---------------------------------------------------------------------------
# Standings (division table + momentum + quality of competition)
# ---------------------------------------------------------------------------


class TeamStanding(BaseModel):
    team: str
    abbrev: str
    w: int
    l: int
    pct: float
    gb: float  # games back of the division leader (0.0 for the leader)
    streak: str  # e.g. "W3", "L1", or "—"
    last10: str  # e.g. "7-3"
    last10_results: list[str] = Field(default_factory=list)  # oldest→newest
    run_diff: int
    is_favorite: bool = False


class QualityRecord(BaseModel):
    label: str
    w: int
    l: int
    pct: float


class StandingsResponse(BaseModel):
    season: int
    division: str
    last_game_date: Optional[str] = None
    teams: list[TeamStanding] = Field(default_factory=list)
    # Favorite-team momentum
    favorite_streak: str = "—"
    favorite_last10: str = "0-0"
    favorite_run_diff: int = 0
    favorite_results: list[str] = Field(default_factory=list)  # last ~20, oldest→newest
    # Quality of competition
    vs_winning: QualityRecord
    vs_losing: QualityRecord
    generated_at: str
