const API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "http://localhost:8000";

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
