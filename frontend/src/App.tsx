import { useEffect, useMemo, useState } from "react";

import {
  fetchPlayers,
  fetchToday,
  type BatterCard,
  type Contributor,
  type GameRef,
  type LeveragePlay,
  type PitcherCard,
  type PitcherLine,
  type PlayersResponse,
  type TodayResponse,
  type WEPoint,
} from "./api";

const DEFAULT_SEASON = Number(import.meta.env.VITE_MLB_SEASON) || 2026;

type Tab = "today" | "players";

export default function App() {
  const [tab, setTab] = useState<Tab>("today");

  return (
    <div className="today-root">
      <nav className="tab-bar" role="tablist">
        <button
          className={`tab-bar__btn ${tab === "today" ? "tab-bar__btn--active" : ""}`}
          onClick={() => setTab("today")}
          role="tab"
          aria-selected={tab === "today"}
        >
          Today
        </button>
        <button
          className={`tab-bar__btn ${tab === "players" ? "tab-bar__btn--active" : ""}`}
          onClick={() => setTab("players")}
          role="tab"
          aria-selected={tab === "players"}
        >
          Season players
        </button>
      </nav>
      <div className="today-shell">
        {tab === "today" && <TodayTab />}
        {tab === "players" && <PlayersTab />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Today
// ---------------------------------------------------------------------------

function TodayTab() {
  const [payload, setPayload] = useState<TodayResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchToday(controller.signal)
      .then((d) => setPayload(d))
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message || String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  if (loading) return <div className="t-card t-loading">Loading…</div>;
  if (error) return <div className="t-card t-error">{error}</div>;
  if (!payload) return null;
  return <Today payload={payload} />;
}

function Today({ payload }: { payload: TodayResponse }) {
  const h = payload.header;
  const wlPill = h.jays_won ? "W" : "L";
  return (
    <>
      <header className="t-header">
        <div className="t-header__date">{h.game_date}</div>
        <div className="t-scoreline">
          <ScoreSide
            abbr={h.away_abbr}
            score={h.away_score}
            isJays={h.away_abbr === "TOR"}
            won={h.jays_won === (h.away_abbr === "TOR")}
          />
          <span className="t-scoreline__at">@</span>
          <ScoreSide
            abbr={h.home_abbr}
            score={h.home_score}
            isJays={h.home_abbr === "TOR"}
            won={h.jays_won === (h.home_abbr === "TOR")}
          />
          <span className={`t-pill t-pill--${h.jays_won ? "win" : "loss"}`}>{wlPill}</span>
        </div>
        <div className="t-header__venue">{h.venue}</div>
      </header>

      <div className="t-grid">
        <div className="t-col t-col--left">
          <section className="t-card">
            <h2 className="t-card__title">Win expectancy (Toronto)</h2>
            <WPSparkline trajectory={payload.we_trajectory} />
          </section>

          <section className="t-card">
            <h2 className="t-card__title">Top leverage plays</h2>
            <ul className="t-leverage">
              {payload.leverage_plays.map((p) => (
                <LeverageRow key={p.play_index} play={p} />
              ))}
            </ul>
          </section>
        </div>

        <div className="t-col t-col--right">
          {payload.top_contributors.length > 0 && (
            <section className="t-card">
              <h2 className="t-card__title">Top contributors</h2>
              <ul className="t-contribs">
                {payload.top_contributors.map((c) => (
                  <ContribRow key={c.player_id} c={c} positive />
                ))}
              </ul>
            </section>
          )}

          {payload.negative_contributors.length > 0 && (
            <section className="t-card">
              <h2 className="t-card__title">Negative contributors</h2>
              <ul className="t-contribs">
                {payload.negative_contributors.map((c) => (
                  <ContribRow key={c.player_id} c={c} positive={false} />
                ))}
              </ul>
            </section>
          )}

          <section className="t-card">
            <h2 className="t-card__title">Pitching</h2>
            {payload.starter && <PitcherRow p={payload.starter} role="starter" />}
            {payload.relievers.map((p) => (
              <PitcherRow key={p.player_id} p={p} role="relief" />
            ))}
            {payload.relievers.length > 0 && (
              <div className="t-bullpen-total">
                Bullpen: {payload.relievers.length} · {payload.bullpen_pitches} pitches
              </div>
            )}
            {payload.opp_starter && (
              <div className="t-opp-starter">
                Opp starter — {payload.opp_starter.name}: {payload.opp_starter.ip} IP, {payload.opp_starter.h} H,{" "}
                {payload.opp_starter.er} ER, {payload.opp_starter.k} K
              </div>
            )}
          </section>
        </div>
      </div>

      <footer className="t-footer">
        WE table: {payload.we_table_meta.n_states ?? "—"} states · seasons{" "}
        {payload.we_table_meta.seasons?.join(", ") ?? "—"}
      </footer>
    </>
  );
}

function ScoreSide({
  abbr,
  score,
  isJays,
  won,
}: {
  abbr: string;
  score: number;
  isJays: boolean;
  won: boolean;
}) {
  return (
    <span className={`t-side ${isJays ? "t-side--jays" : ""} ${won ? "t-side--won" : ""}`}>
      <span className="t-side__abbr">{abbr}</span>
      <span className="t-side__score">{score}</span>
    </span>
  );
}

function WPSparkline({ trajectory }: { trajectory: WEPoint[] }) {
  const W = 320;
  const H = 96;
  const pad = { l: 4, r: 4, t: 4, b: 14 };
  const innerW = W - pad.l - pad.r;
  const innerH = H - pad.t - pad.b;

  const { path, fill, gridLines, ticks } = useMemo(() => {
    if (trajectory.length === 0)
      return { path: "", fill: "", gridLines: [] as number[], ticks: [] as { x: number; label: string }[] };
    const n = trajectory.length;
    const xOf = (i: number) => pad.l + (innerW * i) / Math.max(1, n - 1);
    const yOf = (we: number) => pad.t + innerH * (1 - we);

    let d = `M ${xOf(0)} ${yOf(trajectory[0].we_jays)}`;
    for (let i = 1; i < n; i++) {
      d += ` L ${xOf(i)} ${yOf(trajectory[i].we_jays)}`;
    }
    const baseline = yOf(0.5);
    let fillD = `M ${xOf(0)} ${baseline}`;
    for (let i = 0; i < n; i++) {
      fillD += ` L ${xOf(i)} ${yOf(trajectory[i].we_jays)}`;
    }
    fillD += ` L ${xOf(n - 1)} ${baseline} Z`;

    const seen = new Set<string>();
    const ticks: { x: number; label: string }[] = [];
    trajectory.forEach((p, i) => {
      const k = `${p.half}${p.inning}`;
      if (!seen.has(k)) {
        seen.add(k);
        ticks.push({ x: xOf(i), label: k });
      }
    });
    const reduced = ticks.filter((_, idx) => idx % 2 === 0);
    return { path: d, fill: fillD, gridLines: [0.5], ticks: reduced };
  }, [trajectory]);

  if (!path) return null;
  return (
    <svg
      className="t-spark"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Win expectancy trajectory"
    >
      {gridLines.map((g) => (
        <line
          key={g}
          x1={pad.l}
          y1={pad.t + innerH * (1 - g)}
          x2={W - pad.r}
          y2={pad.t + innerH * (1 - g)}
          className="t-spark__base"
        />
      ))}
      <path d={fill} className="t-spark__fill" />
      <path d={path} className="t-spark__line" />
      {ticks.map((t) => (
        <text key={t.label} x={t.x} y={H - 2} className="t-spark__tick" textAnchor="middle">
          {t.label}
        </text>
      ))}
    </svg>
  );
}

function LeverageRow({ play }: { play: LeveragePlay }) {
  const sign = play.wpa_jays >= 0 ? "+" : "−";
  return (
    <li className="t-lev">
      <div className="t-lev__head">
        <span className="t-lev__inn">
          {play.half}
          {play.inning}
        </span>
        <span className={`t-lev__wpa t-lev__wpa--${play.wpa_jays >= 0 ? "pos" : "neg"}`}>
          {sign}
          {Math.abs(play.wpa_jays).toFixed(3)}
        </span>
        <span className="t-lev__score">{play.score_before}</span>
      </div>
      <div className="t-lev__desc">{play.description}</div>
    </li>
  );
}

function ContribRow({ c, positive }: { c: Contributor; positive: boolean }) {
  const sign = positive ? "+" : "";
  const play = positive ? c.best_play : c.worst_play;
  return (
    <li className="t-contrib">
      <div className="t-contrib__head">
        <span className="t-contrib__name">{c.name}</span>
        <span className={`t-contrib__wpa t-contrib__wpa--${positive ? "pos" : "neg"}`}>
          {sign}
          {c.wpa.toFixed(3)}
        </span>
      </div>
      <div className="t-contrib__meta">
        PA {c.pa} · RBI {c.rbi}
      </div>
      {play && <div className="t-contrib__play">{play}</div>}
    </li>
  );
}

function PitcherRow({ p, role }: { p: PitcherLine; role: "starter" | "relief" }) {
  return (
    <div className={`t-pitcher t-pitcher--${role}`}>
      <div className="t-pitcher__head">
        <span className="t-pitcher__name">{p.name}</span>
        <span className="t-pitcher__line">
          {p.ip} IP · {p.h}H {p.r}R {p.er}ER · {p.k}K {p.bb}BB · {p.pitches}p
        </span>
      </div>
      {p.note && <div className="t-pitcher__note">{p.note}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Players
// ---------------------------------------------------------------------------

function PlayersTab() {
  const [payload, setPayload] = useState<PlayersResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [elapsed, setElapsed] = useState(0);
  const [side, setSide] = useState<"batters" | "pitchers">("batters");

  useEffect(() => {
    const controller = new AbortController();
    const t0 = Date.now();
    const tick = window.setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    setLoading(true);
    setError(null);
    fetchPlayers(DEFAULT_SEASON, controller.signal)
      .then((d) => setPayload(d))
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message || String(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
          window.clearInterval(tick);
        }
      });
    return () => {
      controller.abort();
      window.clearInterval(tick);
    };
  }, []);

  if (loading)
    return (
      <div className="t-card t-loading">
        Loading season…{" "}
        <span className="t-loading__elapsed" aria-live="polite">
          ({elapsed}s)
        </span>
      </div>
    );
  if (error) return <div className="t-card t-error">{error}</div>;
  if (!payload) return null;

  const batters = payload.batters;
  const pitchers = payload.pitchers;
  const showBatters = side === "batters";
  const list = showBatters ? batters : pitchers;
  const maxAbs = Math.max(0.001, ...list.map((p) => Math.abs(p.wpa)));

  return (
    <>
      <header className="t-header">
        <div className="t-header__date">Season {payload.season}</div>
        <div className="p-summary">
          <span className="p-summary__games">{payload.games_included} games</span>
          {payload.last_game_date && (
            <span className="p-summary__last">through {payload.last_game_date}</span>
          )}
        </div>
      </header>

      <div className="p-toggle" role="tablist">
        <button
          className={`p-toggle__btn ${showBatters ? "p-toggle__btn--active" : ""}`}
          onClick={() => setSide("batters")}
          role="tab"
          aria-selected={showBatters}
        >
          Batters ({batters.length})
        </button>
        <button
          className={`p-toggle__btn ${!showBatters ? "p-toggle__btn--active" : ""}`}
          onClick={() => setSide("pitchers")}
          role="tab"
          aria-selected={!showBatters}
        >
          Pitchers ({pitchers.length})
        </button>
      </div>

      <ul className="p-list">
        {showBatters
          ? batters.map((b) => <BatterCardRow key={b.player_id} c={b} maxAbs={maxAbs} />)
          : pitchers.map((p) => <PitcherCardRow key={p.player_id} c={p} maxAbs={maxAbs} />)}
      </ul>
    </>
  );
}

function WpaBar({ wpa, maxAbs }: { wpa: number; maxAbs: number }) {
  const pct = (Math.abs(wpa) / maxAbs) * 50; // 0..50% from center
  const left = wpa >= 0 ? 50 : 50 - pct;
  return (
    <div className="p-bar" aria-hidden="true">
      <div className="p-bar__center" />
      <div
        className={`p-bar__fill p-bar__fill--${wpa >= 0 ? "pos" : "neg"}`}
        style={{ left: `${left}%`, width: `${pct}%` }}
      />
    </div>
  );
}

function GameRefChip({ g, label }: { g: GameRef; label: string }) {
  const sign = g.wpa >= 0 ? "+" : "−";
  return (
    <span className={`p-ref p-ref--${g.wpa >= 0 ? "pos" : "neg"}`}>
      <span className="p-ref__label">{label}</span>
      <span className="p-ref__opp">
        {g.jays_won ? "W" : "L"} vs {g.opp_abbr}
      </span>
      <span className="p-ref__date">{g.game_date.slice(5)}</span>
      <span className="p-ref__wpa">
        {sign}
        {Math.abs(g.wpa).toFixed(2)}
      </span>
    </span>
  );
}

function BatterCardRow({ c, maxAbs }: { c: BatterCard; maxAbs: number }) {
  const sign = c.wpa >= 0 ? "+" : "−";
  return (
    <li className="p-card">
      <div className="p-card__head">
        <span className="p-card__name">{c.name}</span>
        <span className={`p-card__wpa p-card__wpa--${c.wpa >= 0 ? "pos" : "neg"}`}>
          {sign}
          {Math.abs(c.wpa).toFixed(3)}
        </span>
      </div>
      <WpaBar wpa={c.wpa} maxAbs={maxAbs} />
      <div className="p-card__meta">
        G {c.games} · PA {c.pa} · RBI {c.rbi}
      </div>
      <div className="p-card__refs">
        {c.best_game && <GameRefChip g={c.best_game} label="best" />}
        {c.worst_game && <GameRefChip g={c.worst_game} label="worst" />}
      </div>
    </li>
  );
}

function PitcherCardRow({ c, maxAbs }: { c: PitcherCard; maxAbs: number }) {
  const sign = c.wpa >= 0 ? "+" : "−";
  return (
    <li className="p-card">
      <div className="p-card__head">
        <span className="p-card__name">{c.name}</span>
        <span className={`p-card__wpa p-card__wpa--${c.wpa >= 0 ? "pos" : "neg"}`}>
          {sign}
          {Math.abs(c.wpa).toFixed(3)}
        </span>
      </div>
      <WpaBar wpa={c.wpa} maxAbs={maxAbs} />
      <div className="p-card__meta">
        G {c.games}
        {c.starts > 0 && ` · ${c.starts} starts`} · BF {c.bf} · {c.pitches}p
      </div>
      <div className="p-card__refs">
        {c.best_game && <GameRefChip g={c.best_game} label="best" />}
        {c.worst_game && <GameRefChip g={c.worst_game} label="worst" />}
      </div>
    </li>
  );
}
