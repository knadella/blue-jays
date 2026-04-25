import { useEffect, useState } from "react";

import { fetchWeeklyActuals, type WeeklyActualsResponse } from "./api";
import { OffenseSavantBars } from "./components/OffenseSavantBars";
import { PitchingSavantBars } from "./components/PitchingSavantBars";
import { getTeamAbbrev } from "./teamMetadata";
import { useScrollChoreo } from "./useScrollChoreo";

const TEAM = "Toronto Blue Jays";
const DEFAULT_SEASON = Number(import.meta.env.VITE_MLB_SEASON) || 2026;

export default function App() {
  const [season] = useState(DEFAULT_SEASON);
  const [payload, setPayload] = useState<WeeklyActualsResponse | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [slowHint, setSlowHint] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  useScrollChoreo();

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    setLoading(true);
    const t0 = Date.now();
    const tick = window.setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    const hint = window.setTimeout(() => setSlowHint(true), 12000);

    fetchWeeklyActuals(season, controller.signal)
      .then((data) => {
        setPayload(data);
        setError(null);
      })
      .catch((err: Error) => {
        if (err.name === "AbortError") {
          return;
        }
        setError(err.message || String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
        window.clearInterval(tick);
        window.clearTimeout(hint);
        setSlowHint(false);
      });

    return () => controller.abort();
  }, [season]);

  return (
    <div className="app-root">
      <header className="hero hero--compact">
        <div className="hero-inner">
          <div className="masthead">
            <div className="masthead-brand">
              <div className="hero-mark" aria-hidden="true">
                <span className="hero-diamond" />
              </div>
              <div className="eyebrow-row eyebrow-row--season">
                <span className="eyebrow">Toronto Blue Jays · Statcast · {season}</span>
              </div>
              <h1>
                <span className="headline-line">What actually</span>
                <span className="headline-line accent">happened this week.</span>
              </h1>
              <p className="hero-tagline fan-voice">
                Plate discipline, contact quality, and pitch-type results — offense when this club is in the box,
                run prevention when it is on the mound and in the field. No projections, just pitch-level progression.
              </p>
            </div>
          </div>
        </div>
        <div className="hero-sunset" aria-hidden="true" />
      </header>

      <div className="app-shell">
        {loading && (
          <div className="section-card loading-card scroll-choreo scroll-choreo--card" data-scroll-choreo>
            <p className="loading-primary">
              Loading Statcast week buckets for {getTeamAbbrev(TEAM)} ({season})…{" "}
              <span className="loading-elapsed" aria-live="polite">
                ({elapsed}s)
              </span>
            </p>
            {slowHint && (
              <p className="loading-hint">
                The local API reads Parquet from <code>data/statcast_local/</code> when present (fast). Without that
                file for this club and year, it may download Statcast from Savant on first load (often several minutes).
                Keep <code>uvicorn</code> on <code>127.0.0.1:8000</code> and, in dev, leave <code>VITE_API_URL</code>{" "}
                unset so Vite proxies <code>/api</code>.
              </p>
            )}
          </div>
        )}

        {error && (
          <div className="section-card error-card scroll-choreo scroll-choreo--card" data-scroll-choreo>
            {error}
          </div>
        )}

        {payload && !loading && (
          <>
            <div className="hero-row scroll-choreo scroll-choreo--dash" data-scroll-choreo>
              <div className="kpi-column">
                <div className="kpi-tile scroll-choreo scroll-choreo--kpi" data-scroll-choreo>
                  <span className="kpi-value">
                    {payload.wins}–{payload.losses}
                  </span>
                  <span className="kpi-label">Record</span>
                </div>
                <div className="kpi-tile scroll-choreo scroll-choreo--kpi" data-scroll-choreo>
                  <span className="kpi-value">{payload.streak || "—"}</span>
                  <span className="kpi-label">Streak</span>
                </div>
                <div className="kpi-tile scroll-choreo scroll-choreo--kpi" data-scroll-choreo>
                  <span className="kpi-value">{payload.run_differential > 0 ? `+${payload.run_differential}` : payload.run_differential}</span>
                  <span className="kpi-label">Run diff</span>
                </div>
              </div>
              <section className="section-card chart-card hero-chart scroll-choreo scroll-choreo--card" data-scroll-choreo>
                <div className="section-header section-header--rich">
                  <div className="section-header__copy">
                    <h2>Offense by month</h2>
                  </div>
                  {payload.runs_per_game > 0 && (
                    <span className="section-header__stat">
                      <span className="section-header__stat-val">{payload.runs_per_game.toFixed(1)} R/G</span>
                    </span>
                  )}
                </div>
                {payload.weeks.length === 0 && (
                  <div className="empty-weeks-actions">
                    <p className="empty-weeks-copy">
                      No Statcast data yet for {season}. The season may not have started, or extracts haven't been downloaded.
                    </p>
                  </div>
                )}
                <OffenseSavantBars
                  weeks={payload.weeks}
                  teamLabel={payload.team}
                  leagueShape={[]}
                  leagueTeams={0}
                  chaseZoneGrid={payload.chase_zone_grid}
                  whiffZoneGrid={payload.whiff_zone_grid}
                  barrelGrid={payload.barrel_grid}
                  sprayGrid={payload.spray_grid}
                />
              </section>
            </div>

            <div className="section-stride scroll-choreo scroll-choreo--stride" data-scroll-choreo aria-hidden="true">
              <div className="section-stride__content">
                <span className="section-stride__label">Run prevention</span>
                <span className="section-stride__line" />
              </div>
            </div>

            <section className="section-card chart-card scroll-choreo scroll-choreo--card" data-scroll-choreo>
              <div className="section-header section-header--rich">
                <div className="section-header__copy">
                  <h2>Pitching &amp; defense</h2>
                </div>
                {payload.runs_allowed_per_game > 0 && (
                  <span className="section-header__stat">
                    <span className="section-header__stat-val">{payload.runs_allowed_per_game.toFixed(1)} RA/G</span>
                  </span>
                )}
              </div>
              <PitchingSavantBars
                weeks={payload.weeks}
                teamLabel={payload.team}
                leagueShape={[]}
                leagueTeams={0}
                chaseZoneGrid={payload.pitching_chase_zone_grid}
                whiffZoneGrid={payload.pitching_whiff_zone_grid}
                barrelGrid={payload.pitching_barrel_grid}
                sprayGrid={payload.pitching_spray_grid}
              />
            </section>

          </>
        )}

        <footer className="site-footer">
          <p className="site-footer__line fan-voice">
            Built for readers who want the shape of a season in swings, chases, and barrels — not a playoff odds bar.
          </p>
          <p className="site-footer__sig">Statcast and Sunday doubleheaders.</p>
        </footer>
      </div>
    </div>
  );
}
