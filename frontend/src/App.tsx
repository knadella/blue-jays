import { useEffect, useRef, useState } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import { CumulativeWinsChart } from "./components/CumulativeWinsChart";
import { ScheduleHeatmap } from "./components/ScheduleHeatmap";
import { TeamRatingCharts } from "./components/TeamRatingCharts";
import { getTeamAbbrev } from "./teamMetadata";

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

export default function App() {
  const [league, setLeague] = useState("AL");
  const [division, setDivision] = useState("East");
  const [team, setTeam] = useState("Toronto Blue Jays");
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const dashboardCacheRef = useRef(new Map<string, DashboardResponse>());
  const prefetchInFlightRef = useRef(new Set<string>());

  const divisionKey = `${league} ${division}`;
  const divisionTeams = DIVISION_TEAMS[divisionKey] ?? [];
  const displayedTeam = dashboard?.favorite_team ?? team;

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
    const controller = new AbortController();
    const cacheKey = `2026:${team}`;
    const cachedDashboard = dashboardCacheRef.current.get(cacheKey);

    setError(null);
    if (cachedDashboard) {
      setDashboard(cachedDashboard);
      setLoading(false);
      return () => controller.abort();
    }

    setLoading(true);
    fetchDashboard(team, 2026, controller.signal)
      .then((payload) => {
        dashboardCacheRef.current.set(cacheKey, payload);
        setDashboard(payload);
        setError(null);
      })
      .catch((err: Error) => {
        if (err.name === "AbortError") {
          return;
        }
        setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [team]);

  useEffect(() => {
    if (loading || !dashboard || dashboard.favorite_team !== team) {
      return;
    }

    for (const nextTeam of divisionTeams) {
      if (nextTeam === team) {
        continue;
      }

      const cacheKey = `2026:${nextTeam}`;
      if (
        dashboardCacheRef.current.has(cacheKey) ||
        prefetchInFlightRef.current.has(cacheKey)
      ) {
        continue;
      }

      prefetchInFlightRef.current.add(cacheKey);
      fetchDashboard(nextTeam)
        .then((payload) => {
          dashboardCacheRef.current.set(cacheKey, payload);
        })
        .catch(() => {
          // Ignore prefetch failures; the interactive request will retry.
        })
        .finally(() => {
          prefetchInFlightRef.current.delete(cacheKey);
        });
    }
  }, [dashboard, divisionTeams, loading, team]);

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
              {getTeamAbbrev(t)}
            </button>
          ))}
        </div>
      </nav>

      {loading && (
        <div className="section-card">
          {dashboard ? `Updating ${team} dashboard...` : "Loading dashboard data..."}
        </div>
      )}
      {error && <div className="section-card error-card">{error}</div>}

      {dashboard && (
        <>
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
              team={displayedTeam}
              season={dashboard.season}
              projectedFinalWins={dashboard.team_simulation.projected_final_wins}
              projectedDivisionPlace={dashboard.team_simulation.projected_division_place}
              playoffProbability={dashboard.team_simulation.playoff_probability}
            />
          </section>

          <section className="section-card chart-card ratings-section">
            <div className="section-header">
              <h2>Team Ratings</h2>
              <span>Posterior model estimates, runs per game</span>
            </div>
            <TeamRatingCharts
              offense={dashboard.team_ratings.offense}
              defense={dashboard.team_ratings.defense}
              team={displayedTeam}
            />
          </section>

          <section className="section-card chart-card ratings-section">
            <div className="section-header">
              <h2>Strength of Schedule</h2>
              <span>Remaining opponents by difficulty</span>
            </div>
            <ScheduleHeatmap
              schedule={dashboard.remaining_schedule}
              team={displayedTeam}
              season={dashboard.season}
            />
          </section>
        </>
      )}
    </div>
  );
}
