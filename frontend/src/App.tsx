import { useEffect, useState } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import { CumulativeWinsChart } from "./components/CumulativeWinsChart";

const LEAGUE_DIVISIONS: Record<string, string[]> = {
  AL: ["East", "Central", "West"],
  NL: ["East", "Central", "West"],
};

const DIVISION_TEAMS: Record<string, string[]> = {
  "AL East": ["New York Yankees", "Baltimore Orioles", "Boston Red Sox", "Tampa Bay Rays", "Toronto Blue Jays"],
  "AL Central": ["Cleveland Guardians", "Kansas City Royals", "Detroit Tigers", "Minnesota Twins", "Chicago White Sox"],
  "AL West": ["Houston Astros", "Seattle Mariners", "Texas Rangers", "Oakland Athletics", "Los Angeles Angels"],
  "NL East": ["Philadelphia Phillies", "Atlanta Braves", "New York Mets", "Washington Nationals", "Miami Marlins"],
  "NL Central": ["Milwaukee Brewers", "Chicago Cubs", "St. Louis Cardinals", "Cincinnati Reds", "Pittsburgh Pirates"],
  "NL West": ["Los Angeles Dodgers", "San Diego Padres", "Arizona Diamondbacks", "San Francisco Giants", "Colorado Rockies"],
};

const TEAM_ABBREV: Record<string, string> = {
  "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
  "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS",
  "Chicago Cubs": "CHC", "Chicago White Sox": "CHW",
  "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
  "Colorado Rockies": "COL", "Detroit Tigers": "DET",
  "Houston Astros": "HOU", "Kansas City Royals": "KC",
  "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
  "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL",
  "Minnesota Twins": "MIN", "New York Mets": "NYM",
  "New York Yankees": "NYY", "Oakland Athletics": "OAK",
  "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT",
  "San Diego Padres": "SD", "San Francisco Giants": "SF",
  "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
  "Tampa Bay Rays": "TB", "Texas Rangers": "TEX",
  "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
};

export default function App() {
  const [league, setLeague] = useState("AL");
  const [division, setDivision] = useState("East");
  const [team, setTeam] = useState("Toronto Blue Jays");
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const divisionKey = `${league} ${division}`;
  const divisionTeams = DIVISION_TEAMS[divisionKey] ?? [];

  const handleLeagueChange = (next: string) => {
    setLeague(next);
    const firstDiv = LEAGUE_DIVISIONS[next][0];
    setDivision(firstDiv);
    setTeam(DIVISION_TEAMS[`${next} ${firstDiv}`][0]);
  };

  const handleDivisionChange = (next: string) => {
    setDivision(next);
    setTeam(DIVISION_TEAMS[`${league} ${next}`][0]);
  };

  useEffect(() => {
    setLoading(true);
    fetchDashboard(team)
      .then((payload) => {
        setDashboard(payload);
        setError(null);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [team]);

  return (
    <div className="app-shell">
      <header className="masthead">
        <div>
          <div className="eyebrow">MLB Forecast</div>
          <h1>Team Season Projections</h1>
        </div>
      </header>

      <nav className="team-picker" aria-label="Team selector">
        <div className="pill-group">
          <span className="pill-label">League</span>
          {["AL", "NL"].map((l) => (
            <button
              key={l}
              className={`pill ${league === l ? "active" : ""}`}
              onClick={() => handleLeagueChange(l)}
            >
              {l}
            </button>
          ))}
        </div>

        <div className="pill-separator" />

        <div className="pill-group">
          <span className="pill-label">Division</span>
          {LEAGUE_DIVISIONS[league].map((d) => (
            <button
              key={d}
              className={`pill ${division === d ? "active" : ""}`}
              onClick={() => handleDivisionChange(d)}
            >
              {d}
            </button>
          ))}
        </div>

        <div className="pill-separator" />

        <div className="pill-group">
          <span className="pill-label">Team</span>
          {divisionTeams.map((t) => (
            <button
              key={t}
              className={`pill pill-team ${team === t ? "active" : ""}`}
              onClick={() => setTeam(t)}
              title={t}
            >
              {TEAM_ABBREV[t] ?? t}
            </button>
          ))}
        </div>
      </nav>

      {loading && <div className="section-card">Loading dashboard data...</div>}
      {error && <div className="section-card error-card">{error}</div>}

      {dashboard && !loading && (
        <section className="section-card chart-card">
          <div className="section-header">
            <h2>Win Projections</h2>
            <span>
              {dashboard.meta.games_completed} completed, {dashboard.meta.games_remaining} remaining
            </span>
          </div>
          <CumulativeWinsChart
            actualPoints={dashboard.team_simulation.actual_points}
            simulationDensity={dashboard.team_simulation.simulation_density}
            team={dashboard.team_simulation.team}
            season={dashboard.season}
            projectedFinalWins={dashboard.team_simulation.projected_final_wins}
            projectedDivisionPlace={dashboard.team_simulation.projected_division_place}
            playoffProbability={dashboard.team_simulation.playoff_probability}
          />
        </section>
      )}
    </div>
  );
}
