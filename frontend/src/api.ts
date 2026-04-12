/** In dev, default to same-origin so Vite can proxy `/api` → FastAPI (no CORS, no prod URL). */
const API_BASE =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ??
  (import.meta.env.DEV ? "" : "http://localhost:8000");

const _viteApiUrl = (import.meta.env.VITE_API_URL as string | undefined)?.trim();
if (import.meta.env.DEV && _viteApiUrl) {
  const u = _viteApiUrl.replace(/\/$/, "");
  const local =
    u.startsWith("http://127.0.0.1:") ||
    u.startsWith("http://localhost:") ||
    u === "http://127.0.0.1" ||
    u === "http://localhost";
  if (!local) {
    console.warn(
      "[mlb] VITE_API_URL is set to a non-loopback URL in dev. The browser will skip the Vite /api proxy (hangs, CORS, or wrong data). Remove VITE_API_URL from repo-root .env / .env.local for local work.",
      u,
    );
  }
}

export interface WinPoint {
  date: string;
  wins: number;
}

export interface SimulationDensityCell {
  date: string;
  wins: number;
  probability: number;
}

export interface TeamSimulationView {
  team: string;
  division: string;
  actual_wins: number;
  actual_losses: number;
  actual_division_place: number;
  streak: string;
  run_differential: number;
  /** 0–10 mean opponent quality on games already played (higher = harder). */
  schedule_strength_played: number | null;
  /** 0–10 mean opponent quality on games left (higher = harder). */
  schedule_strength_remaining: number | null;
  actual_points: WinPoint[];
  simulation_density: SimulationDensityCell[];
  projected_final_wins: number;
  projected_division_place: number;
  playoff_probability: number;
}

export interface TeamRating {
  team: string;
  value: number;
}

export interface TeamRatings {
  offense: TeamRating[];
  defense: TeamRating[];
}

export interface TeamRatingVsActual {
  runs_scored_per_game_projected: number;
  runs_scored_per_game_actual: number | null;
  runs_allowed_per_game_projected: number;
  runs_allowed_per_game_actual: number | null;
}

export interface MonthlyRunRatePoint {
  month: number;
  label: string;
  runs_scored_projected: number;
  runs_allowed_projected: number;
  league_runs_scored_projected: number;
  league_runs_allowed_projected: number;
  runs_scored_actual: number | null;
  runs_allowed_actual: number | null;
  league_runs_scored_actual: number | null;
  league_runs_allowed_actual: number | null;
}

export interface ScheduleGame {
  date: string;
  opponent: string;
  is_home: boolean;
  opponent_strength: number;
}

export interface DivisionStanding {
  team: string;
  projected_wins: number;
}

export interface DashboardResponse {
  season: number;
  favorite_team: string;
  team_simulation: TeamSimulationView;
  team_ratings: TeamRatings;
  team_rating_vs_actual: TeamRatingVsActual;
  monthly_run_rates: MonthlyRunRatePoint[];
  remaining_schedule: ScheduleGame[];
  division_standings: Record<string, DivisionStanding[]>;
  meta: {
    generated_at: string;
    games_completed: number;
    games_remaining: number;
    model_source: string;
    simulation_count: number;
  };
}

export async function fetchTeams(): Promise<string[]> {
  const response = await fetch(`${API_BASE}/api/teams`);
  if (!response.ok) {
    throw new Error("Failed to fetch teams.");
  }
  return response.json();
}

async function fetchSampleDashboard(): Promise<DashboardResponse> {
  const base = import.meta.env.BASE_URL;
  const response = await fetch(`${base}sample-dashboard.json`);
  if (!response.ok) {
    throw new Error("Sample data not found.");
  }
  return response.json();
}

export interface PitchTypeRow {
  pitch_type: string;
  pitch_label: string;
  pitches: number;
  swing_rate: number;
  whiff_rate: number | null;
  chase_rate: number | null;
  xwoba_on_contact: number | null;
}

export interface WeekSideMetrics {
  pitches: number;
  plate_appearances: number;
  swing_rate: number | null;
  whiff_rate: number | null;
  zone_swing_rate: number | null;
  chase_rate: number | null;
  contact_rate: number | null;
  called_strike_rate: number | null;
  xwoba_on_contact: number | null;
  xwoba: number | null;
  avg_exit_velo_bip: number | null;
  hard_hit_rate: number | null;
  barrel_rate: number | null;
  avg_launch_angle_bip: number | null;
  groundball_rate: number | null;
  flyball_rate: number | null;
  popup_rate: number | null;
  avg_iso_value_bip: number | null;
  if_standard_pct: number | null;
  if_strategic_pct: number | null;
  of_strategic_pct: number | null;
}

export interface WeeklyBucket {
  week_key: string;
  week_start: string;
  week_end: string;
  offense: WeekSideMetrics;
  run_prevention: WeekSideMetrics;
  hitting_vs_pitch_types: PitchTypeRow[];
  pitching_pitch_types: PitchTypeRow[];
}

/** Apr–Sep: 1–99 offense ranks vs other clubs that calendar month (when API has enough extracts). */
export interface OffenseMonthLeagueShape {
  month: number;
  xwoba_pct: number | null;
  chase_pct: number | null;
  whiff_pct: number | null;
  hard_hit_pct: number | null;
  xwoba_rank: number | null;
  barrel_rank: number | null;
  chase_rank: number | null;
  whiff_rank: number | null;
  p_xwoba_rank: number | null;
  p_barrel_rank: number | null;
  p_chase_rank: number | null;
  p_whiff_rank: number | null;
}

export interface ChaseZoneCell {
  x: number;
  y: number;
  n: number;
  sw: number;
  iz: number;
}

export interface ChaseZoneMonth {
  month: number;
  cells: ChaseZoneCell[];
}

export interface ChaseZoneGrid {
  sz_top: number;
  sz_bot: number;
  zone_width: number;
  nx: number;
  ny: number;
  x_range: [number, number];
  y_range: [number, number];
  months: ChaseZoneMonth[];
}

export interface WhiffZoneCell {
  x: number; y: number; n: number; wh: number;
}
export interface WhiffZoneMonth {
  month: number; cells: WhiffZoneCell[];
}
export interface WhiffZoneGrid {
  sz_top: number; sz_bot: number; zone_width: number;
  nx: number; ny: number;
  x_range: [number, number]; y_range: [number, number];
  months: WhiffZoneMonth[];
}

export interface BarrelCell {
  x: number; y: number; n: number; brl: number;
}
export interface BarrelMonth {
  month: number; cells: BarrelCell[];
}
export interface BarrelGrid {
  nx: number; ny: number;
  ev_range: [number, number]; la_range: [number, number];
  months: BarrelMonth[];
}

export interface SprayCell {
  x: number; y: number; n: number; xw: number;
}
export interface SprayMonth {
  month: number; cells: SprayCell[];
}
export interface SprayGrid {
  nx: number; ny: number;
  x_range: [number, number]; y_range: [number, number];
  months: SprayMonth[];
}

export interface WeeklyActualsResponse {
  season: number;
  team: string;
  team_abbrev: string;
  division: string;
  wins: number;
  losses: number;
  runs_per_game: number;
  runs_allowed_per_game: number;
  runs_per_game_rank: number;
  runs_allowed_per_game_rank: number;
  run_differential: number;
  division_place: number;
  streak: string;
  weeks: WeeklyBucket[];
  statcast_rows: number;
  data_through: string | null;
  generated_at: string;
  note: string | null;
  offense_monthly_league_shape: OffenseMonthLeagueShape[];
  league_offense_months_teams: number;
  chase_zone_grid?: ChaseZoneGrid;
  whiff_zone_grid?: WhiffZoneGrid;
  barrel_grid?: BarrelGrid;
  spray_grid?: SprayGrid;
  pitching_chase_zone_grid?: ChaseZoneGrid;
  pitching_whiff_zone_grid?: WhiffZoneGrid;
  pitching_barrel_grid?: BarrelGrid;
  pitching_spray_grid?: SprayGrid;
}

async function fetchSampleWeeklyActuals(): Promise<WeeklyActualsResponse> {
  const base = import.meta.env.BASE_URL;
  const response = await fetch(`${base}sample-weekly-actuals.json`);
  if (!response.ok) {
    throw new Error("Sample weekly data not found.");
  }
  return response.json();
}

export async function fetchWeeklyActuals(
  team: string,
  season: number,
  signal?: AbortSignal,
): Promise<WeeklyActualsResponse> {
  const params = new URLSearchParams({ team, season: String(season) });
  const url = `${API_BASE}/api/weekly-actuals?${params.toString()}`;
  try {
    const response = await fetch(url, { signal });
    if (!response.ok) {
      throw new Error(`Weekly data HTTP ${response.status}. Is the API running on 127.0.0.1:8000?`);
    }
    return response.json();
  } catch (e: unknown) {
    const name = e && typeof e === "object" && "name" in e ? String((e as { name: string }).name) : "";
    if (name === "AbortError") {
      throw e;
    }
    // Fall back to bundled sample data if the API is unreachable or returns an error
    console.warn("API unavailable, using sample weekly-actuals data.");
    return fetchSampleWeeklyActuals();
  }
}

export async function fetchDashboard(
  team: string,
  season = 2026,
  signal?: AbortSignal,
): Promise<DashboardResponse> {
  const params = new URLSearchParams({ team, season: String(season) });
  try {
    const response = await fetch(`${API_BASE}/api/dashboard?${params.toString()}`, { signal });
    if (!response.ok) {
      throw new Error("Failed to fetch dashboard data.");
    }
    return response.json();
  } catch (err) {
    // In local dev, fall back to sample data if the backend is unreachable
    if (import.meta.env.DEV) {
      console.warn("Backend unreachable, using sample dashboard data for preview.");
      return fetchSampleDashboard();
    }
    throw err;
  }
}
