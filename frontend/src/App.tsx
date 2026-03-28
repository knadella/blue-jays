import { useEffect, useState } from "react";

import { fetchDashboard, fetchTeams, type DashboardResponse } from "./api";
import { CumulativeWinsChart } from "./components/CumulativeWinsChart";

export default function App() {
  const [teams, setTeams] = useState<string[]>([]);
  const [team, setTeam] = useState("Toronto Blue Jays");
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchTeams()
      .then(setTeams)
      .catch((err: Error) => setError(err.message));
  }, []);

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
          <h1>Cumulative wins tracker</h1>
          <p className="lede">
            Actual cumulative wins to date with projected cumulative wins through the rest of the season.
          </p>
        </div>
        <div className="controls">
          <label htmlFor="team-picker">Highlight team</label>
          <select
            id="team-picker"
            value={team}
            onChange={(event) => setTeam(event.target.value)}
          >
            {(teams.length > 0 ? teams : [team]).map((entry) => (
              <option key={entry} value={entry}>
                {entry}
              </option>
            ))}
          </select>
        </div>
      </header>

      {loading && <div className="section-card">Loading dashboard data...</div>}
      {error && <div className="section-card error-card">{error}</div>}

      {dashboard && !loading && (
        <section className="section-card chart-card">
          <div className="section-header">
            <div>
              <h2>Cumulative wins by team</h2>
              <span>
                {dashboard.meta.games_completed} completed games, {dashboard.meta.games_remaining} remaining, {dashboard.meta.simulation_count.toLocaleString()} simulations, model {dashboard.meta.model_source}
              </span>
            </div>
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
