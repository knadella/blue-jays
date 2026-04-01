import { useEffect, useRef, useState } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import { CumulativeWinsChart } from "./components/CumulativeWinsChart";
import { ScheduleHeatmap } from "./components/ScheduleHeatmap";
import { TeamRatingCharts } from "./components/TeamRatingCharts";
import { getTeamAbbrev } from "./teamMetadata";

function ordinal(value: number) {
  const mod100 = value % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${value}th`;
  switch (value % 10) {
    case 1: return `${value}st`;
    case 2: return `${value}nd`;
    case 3: return `${value}rd`;
    default: return `${value}th`;
  }
}

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
  const [slowLoadHint, setSlowLoadHint] = useState(false);
  const [loadSeconds, setLoadSeconds] = useState(0);
  const dashboardCacheRef = useRef(new Map<string, DashboardResponse>());
  const prefetchInFlightRef = useRef(new Set<string>());

  const divisionKey = `${league} ${division}`;
  const standings = dashboard?.division_standings?.[divisionKey];
  const divisionTeams = standings?.length
    ? standings.map((s) => s.team)
    : DIVISION_TEAMS[divisionKey] ?? [];
  const displayedTeam = dashboard?.favorite_team ?? team;

  const getFirstPlaceTeam = (divKey: string): string => {
    const fallback = DIVISION_TEAMS[divKey]?.[0] ?? "";
    if (dashboard?.division_standings?.[divKey]?.length) {
      return dashboard.division_standings[divKey][0].team;
    }
    return fallback;
  };

  const handleLeagueChange = (next: string) => {
    setLeague(next);
    const firstDiv = LEAGUE_DIVISIONS[next][0];
    setDivision(firstDiv);
    setTeam(getFirstPlaceTeam(`${next} ${firstDiv}`));
  };

  const handleDivisionChange = (next: string) => {
    setDivision(next);
    setTeam(getFirstPlaceTeam(`${league} ${next}`));
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
        const msg = err.message || String(err);
        const networkHint =
          msg === "Failed to fetch" || msg === "Load failed" || msg.includes("NetworkError")
            ? " (check API URL and CORS: Fly secret CORS_ORIGINS must include https://<user>.github.io — host only, no /repo path)"
            : "";
        setError(`${msg}${networkHint}`);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [team]);

  useEffect(() => {
    if (!loading) {
      setSlowLoadHint(false);
      setLoadSeconds(0);
      return;
    }
    const start = Date.now();
    setLoadSeconds(0);
    const tick = window.setInterval(() => {
      setLoadSeconds(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    const hintId = window.setTimeout(() => setSlowLoadHint(true), 8000);
    return () => {
      window.clearInterval(tick);
      window.clearTimeout(hintId);
      setSlowLoadHint(false);
    };
  }, [loading]);

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
        <div className="section-card loading-card">
          <p className="loading-primary">
            {dashboard ? `Updating ${team} dashboard...` : "Loading dashboard data..."}{" "}
            <span className="loading-elapsed" aria-live="polite">
              ({loadSeconds}s)
            </span>
          </p>
          {slowLoadHint && (
            <p className="loading-hint">
              The first request to the API can take several minutes while the model fits on the
              server (this is normal on a new deploy or empty cache). Later loads are fast once a
              snapshot exists. If this never finishes, confirm the GitHub Actions build used the
              correct <code>VITE_API_URL</code> and that Fly <code>CORS_ORIGINS</code> includes{" "}
              <code>https://YOURUSERNAME.github.io</code> (host only).
            </p>
          )}
        </div>
      )}
      {error && <div className="section-card error-card">{error}</div>}

      {dashboard && (
        <>
          <div className="hero-row">
            <div className="kpi-column">
              <div className="kpi-tile">
                <span className="kpi-value">
                  {dashboard.team_simulation.actual_wins}–{dashboard.team_simulation.actual_losses}
                </span>
                <span className="kpi-label">Record</span>
              </div>
              <div className="kpi-tile">
                <span className="kpi-value">
                  {ordinal(dashboard.team_simulation.actual_division_place)}
                </span>
                <span className="kpi-label">{dashboard.team_simulation.division}</span>
              </div>
              <div className="kpi-tile">
                <span className="kpi-value">{dashboard.team_simulation.streak || "-"}</span>
                <span className="kpi-label">Streak</span>
              </div>
              <div className="kpi-tile">
                <span className="kpi-value">
                  {dashboard.team_simulation.run_differential > 0 ? "+" : ""}
                  {dashboard.team_simulation.run_differential}
                </span>
                <span className="kpi-label">Run Diff</span>
              </div>
            </div>

            <section className="section-card chart-card hero-chart">
              <div className="section-header">
                <h2>Win Projections</h2>
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
          </div>

          <section className="section-card chart-card ratings-section">
            <div className="section-header">
              <h2>Team Ratings</h2>
              <span>Monthly projections (team vs league); YTD actuals as horizontal lines</span>
            </div>
            <TeamRatingCharts
              monthly={dashboard.monthly_run_rates}
              team={displayedTeam}
              teamVsActual={dashboard.team_rating_vs_actual}
              leagueActualScored={dashboard.league_runs_scored_per_game_actual}
              leagueActualAllowed={dashboard.league_runs_allowed_per_game_actual}
            />
          </section>

          <section className="section-card chart-card ratings-section">
            <div className="section-header">
              <h2>Strength of Schedule</h2>
            </div>
            <ScheduleHeatmap
              schedule={dashboard.remaining_schedule}
              team={displayedTeam}
              season={dashboard.season}
              scheduleStrengthPlayed={dashboard.team_simulation.schedule_strength_played}
              scheduleStrengthRemaining={dashboard.team_simulation.schedule_strength_remaining}
            />
          </section>
        </>
      )}
    </div>
  );
}
