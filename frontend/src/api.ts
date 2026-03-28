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
  const response = await fetch("http://localhost:8000/api/teams");
  if (!response.ok) {
    throw new Error("Failed to fetch teams.");
  }
  return response.json();
}

export async function fetchDashboard(
  team: string,
  season = 2026,
  signal?: AbortSignal,
): Promise<DashboardResponse> {
  const params = new URLSearchParams({ team, season: String(season) });
  const response = await fetch(`http://localhost:8000/api/dashboard?${params.toString()}`, { signal });
  if (!response.ok) {
    throw new Error("Failed to fetch dashboard data.");
  }
  return response.json();
}
