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
  actual_points: WinPoint[];
  simulation_density: SimulationDensityCell[];
  projected_final_wins: number;
  projected_division_place: number;
  playoff_probability: number;
}

export interface DashboardResponse {
  season: number;
  favorite_team: string;
  team_simulation: TeamSimulationView;
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

export async function fetchDashboard(team: string, season = 2026): Promise<DashboardResponse> {
  const params = new URLSearchParams({ team, season: String(season) });
  const response = await fetch(`http://localhost:8000/api/dashboard?${params.toString()}`);
  if (!response.ok) {
    throw new Error("Failed to fetch dashboard data.");
  }
  return response.json();
}
