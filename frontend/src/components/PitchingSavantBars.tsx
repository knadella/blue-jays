/**
 * Pitching/defense faceted cards — mirrors OffenseSavantBars but from the pitching perspective.
 * Metrics: xwOBA allowed (lower=better), Barrel% allowed (lower=better),
 *          Opp chase rate (higher=better), Opp whiff rate (higher=better).
 */
import { useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";

import type { BarrelGrid, ChaseZoneGrid, OffenseMonthLeagueShape, SprayGrid, WeekSideMetrics, WeeklyBucket, WhiffZoneGrid } from "../api";
import { BarrelScatter } from "./BarrelScatter";
import { ChaseZoneHeatmap } from "./ChaseZoneHeatmap";
import { SprayChart } from "./SprayChart";
import { WhiffZoneHeatmap } from "./WhiffZoneHeatmap";

const SEASON_MONTHS = [4, 5, 6, 7, 8, 9] as const;
const MONTH_SHORT = ["Apr", "May", "Jun", "Jul", "Aug", "Sep"] as const;

const FACET_W = 720;
const FACET_PAD_L = 12;
const FACET_PAD_R = 12;
const FACET_PAD_T = 8;
const FACET_PAD_B = 24;
const FACET_INNER_H = 80;
const FACET_H = FACET_PAD_T + FACET_INNER_H + FACET_PAD_B;

type MetricSense = "higher" | "lower";

type PitchingMetricRow = {
  key: keyof Pick<WeekSideMetrics, "xwoba" | "barrel_rate" | "chase_rate" | "whiff_rate">;
  label: string;
  sense: MetricSense; // from the pitcher's perspective: 1st rank = best pitcher
  stroke: string;
  rankKey: keyof OffenseMonthLeagueShape;
};

const METRICS: PitchingMetricRow[] = [
  { key: "xwoba", label: "xwOBA allowed", sense: "lower", stroke: "#2f67b8", rankKey: "p_xwoba_rank" },
  { key: "barrel_rate", label: "Barrel % allowed", sense: "lower", stroke: "#c45b3e", rankKey: "p_barrel_rank" },
  { key: "chase_rate", label: "Opp chase rate", sense: "higher", stroke: "#2d7a5a", rankKey: "p_chase_rank" },
  { key: "whiff_rate", label: "Opp whiff rate", sense: "higher", stroke: "#5b6a8a", rankKey: "p_whiff_rank" },
];

type Agg = {
  plate_appearances: number;
  xwoba: number | null;
  barrel_rate: number | null;
  chase_rate: number | null;
  whiff_rate: number | null;
};

function pickAgg(a: Agg, key: PitchingMetricRow["key"]): number | null {
  const v = a[key];
  return v == null || Number.isNaN(v) ? null : v;
}

function calendarMonth(isoDate: string): number {
  const s = isoDate.trim();
  const d = new Date(s.length <= 10 ? `${s}T12:00:00Z` : s);
  return Number.isNaN(d.getTime()) ? NaN : d.getUTCMonth() + 1;
}

function aggregateDefense(rows: WeekSideMetrics[]): Agg | null {
  let paSum = 0;
  for (const o of rows) paSum += Math.max(0, o.plate_appearances);
  if (paSum <= 0) return null;

  const wa = (get: (o: WeekSideMetrics) => number | null): number | null => {
    let s = 0, w = 0;
    for (const o of rows) {
      const pa = Math.max(0, o.plate_appearances);
      if (pa <= 0) continue;
      const v = get(o);
      if (v == null || Number.isNaN(v)) continue;
      s += v * pa;
      w += pa;
    }
    return w > 0 ? s / w : null;
  };

  return {
    plate_appearances: paSum,
    xwoba: wa((o) => o.xwoba),
    barrel_rate: wa((o) => o.barrel_rate),
    chase_rate: wa((o) => o.chase_rate),
    whiff_rate: wa((o) => o.whiff_rate),
  };
}

function buildMonthlyAggs(weeks: WeeklyBucket[]): (Agg | null)[] {
  const byMonth = new Map<number, WeeklyBucket[]>();
  for (const mo of SEASON_MONTHS) byMonth.set(mo, []);
  for (const w of weeks) {
    const mo = calendarMonth(w.week_end);
    if (!Number.isFinite(mo) || !SEASON_MONTHS.includes(mo as (typeof SEASON_MONTHS)[number])) continue;
    byMonth.get(mo)!.push(w);
  }
  return SEASON_MONTHS.map((mo) => {
    const ws = byMonth.get(mo)!;
    return ws.length === 0 ? null : aggregateDefense(ws.map((x) => x.run_prevention));
  });
}

function samplePercentile(history: number[], current: number, sense: MetricSense): number {
  const n = history.length;
  if (n === 0) return 50;
  const sorted = [...history].sort((a, b) => a - b);
  let below = 0, equal = 0;
  for (const x of sorted) {
    if (x < current) below += 1;
    else if (x === current) equal += 1;
  }
  const frac = (below + 0.5 * (equal || 1)) / n;
  const rawPct = sense === "higher" ? frac * 100 : (1 - frac) * 100;
  return Math.round(Math.min(99, Math.max(1, rawPct)));
}

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function tierColors(rank: number | null, total: number): string {
  if (rank == null || total < 2) return "#c5cad4";
  const third = total / 3;
  if (rank <= third) return "#2f67b8";
  if (rank <= third * 2) return "#8b95a8";
  return "#d62828";
}

function tierWord(rank: number | null, total: number): string {
  if (rank == null || total < 2) return "—";
  const third = total / 3;
  if (rank <= third) return "Great";
  if (rank <= third * 2) return "Average";
  return "Poor";
}

function lastDefined(series: (number | null)[]): number | null {
  for (let i = series.length - 1; i >= 0; i--) {
    if (series[i] != null && !Number.isNaN(series[i])) return series[i];
  }
  return null;
}

function buildSeries(aggs: (Agg | null)[]): (number | null)[][] {
  return METRICS.map((m) =>
    SEASON_MONTHS.map((_, mo) => {
      const a = aggs[mo];
      if (!a) return null;
      const history = aggs
        .map((ag) => (ag == null ? null : pickAgg(ag, m.key)))
        .filter((x): x is number => x != null);
      const cur = pickAgg(a, m.key);
      return cur != null ? samplePercentile(history, cur, m.sense) : null;
    }),
  );
}

function seriesFromLeagueShape(shape: OffenseMonthLeagueShape[]): (number | null)[][] | null {
  if (!shape.length) return null;
  const byMonth = new Map<number, OffenseMonthLeagueShape>();
  for (const r of shape) byMonth.set(r.month, r);
  const s = METRICS.map((m) =>
    SEASON_MONTHS.map((mo) => {
      const row = byMonth.get(mo);
      if (!row) return null;
      const v = row[m.rankKey];
      return typeof v === "number" && !Number.isNaN(v) ? v : null;
    }),
  );
  return s.some((row) => row.some((v) => v != null)) ? s : null;
}

function measurePathLength(path: SVGPathElement): number {
  try {
    path.getBoundingClientRect();
    const len = path.getTotalLength();
    return Number.isFinite(len) && len > 0 ? len : 0;
  } catch { return 0; }
}

function animateStrokeDraw(path: SVGPathElement | null, delayMs: number): (() => void) | undefined {
  if (!path) return undefined;
  const d = path.getAttribute("d");
  if (!d || d.length < 4) return undefined;
  const run = (): boolean => {
    const len = measurePathLength(path);
    if (len <= 0) return false;
    path.style.strokeDasharray = String(len);
    path.style.strokeDashoffset = String(len);
    path.getAnimations().forEach((a) => a.cancel());
    path.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }], {
      duration: 1350, delay: delayMs, easing: "cubic-bezier(0.33, 1, 0.68, 1)", fill: "forwards",
    });
    return true;
  };
  if (run()) return undefined;
  const t = window.setTimeout(() => run(), 48);
  return () => window.clearTimeout(t);
}

function animateFade(el: SVGGraphicsElement | null, delayMs: number) {
  if (!el) return;
  el.style.opacity = "0";
  el.getAnimations().forEach((a) => a.cancel());
  el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 320, delay: delayMs, easing: "ease-out", fill: "forwards" });
}

type FacetLayout = {
  x: d3.ScalePoint<string>;
  monthXs: number[];
  y: d3.ScaleLinear<number, number>;
  y33: number;
  y67: number;
  top: number;
  bot: number;
  pts: { x: number; y: number; p: number }[];
  linePath: string | null;
  areaPath: string | null;
  lastPt: { x: number; y: number; p: number } | null;
};

function buildFacetLayout(metricSeries: (number | null)[], totalTeams: number): FacetLayout {
  const x = d3.scalePoint<string>().domain([...MONTH_SHORT]).range([FACET_PAD_L, FACET_W - FACET_PAD_R]).padding(0.45);
  const top = FACET_PAD_T;
  const bot = FACET_PAD_T + FACET_INNER_H;
  const n = Math.max(totalTeams, 3);
  const y = d3.scaleLinear().domain([n, 1]).range([bot, top]).clamp(true);
  const third = n / 3;
  const y33 = y(Math.round(third * 2));
  const y67 = y(Math.round(third));
  const monthXs = MONTH_SHORT.map((lab) => x(lab)!);
  const pts: { x: number; y: number; p: number }[] = [];
  for (let i = 0; i < MONTH_SHORT.length; i++) {
    const p = metricSeries[i];
    if (p == null) continue;
    const xv = x(MONTH_SHORT[i]);
    if (xv == null) continue;
    pts.push({ x: xv, y: y(p), p });
  }
  const lineGen = d3.line<{ x: number; y: number }>().x((d) => d.x).y((d) => d.y).curve(d3.curveMonotoneX);
  const linePath = pts.length >= 2 ? lineGen(pts) : null;
  const areaGen = d3.area<{ x: number; y: number }>().x((d) => d.x).y0(bot).y1((d) => d.y).curve(d3.curveMonotoneX);
  const areaPath = pts.length >= 2 ? areaGen(pts) : null;
  const lastPt = pts.length > 0 ? pts[pts.length - 1]! : null;
  return { x, monthXs, y, y33, y67, top, bot, pts, linePath, areaPath, lastPt };
}

/* ── Facet card (identical structure to offense) ──────────────── */

interface FacetCardProps {
  mi: number; metric: PitchingMetricRow; facet: FacetLayout; metricSeries: (number | null)[];
  uid: string; totalTeams: number; hoveredMonth: number | null;
  setHoveredMonth: (v: number | null) => void;
  pathRef: (el: SVGPathElement | null) => void;
  areaRef: (el: SVGPathElement | null) => void;
  dotGroupRef: (el: SVGGElement | null) => void;
}

function FacetCard({ mi, metric, facet, metricSeries, uid, totalTeams, hoveredMonth, setHoveredMonth, pathRef, areaRef, dotGroupRef }: FacetCardProps) {
  const lastRank = lastDefined(metricSeries);
  const word = tierWord(lastRank, totalTeams);
  const wordColor = tierColors(lastRank, totalTeams);
  const bandW = FACET_W - FACET_PAD_L - FACET_PAD_R;
  const halfGap = facet.monthXs.length >= 2 ? (facet.monthXs[1]! - facet.monthXs[0]!) / 2 : 40;

  return (
    <div className="savant-facet" style={{ "--facet-stroke": metric.stroke } as React.CSSProperties}>
      <div className="savant-facet__header">
        <span className="savant-facet__label">{metric.label}</span>
        <span className="savant-facet__badge" style={{ color: wordColor, borderColor: wordColor }}>
          {lastRank != null && totalTeams >= 2 ? `${ordinal(lastRank)} of ${totalTeams}` : word}
        </span>
      </div>
      <svg className="savant-facet__svg" viewBox={`0 0 ${FACET_W} ${FACET_H}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label={`${metric.label} trend`}>
        <defs>
          <linearGradient id={`${uid}-bp-${mi}`} x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="rgba(214,40,40,0.10)" /><stop offset="100%" stopColor="rgba(214,40,40,0.03)" /></linearGradient>
          <linearGradient id={`${uid}-bm-${mi}`} x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="rgba(139,149,168,0.08)" /><stop offset="100%" stopColor="rgba(139,149,168,0.03)" /></linearGradient>
          <linearGradient id={`${uid}-bg-${mi}`} x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="rgba(47,103,184,0.10)" /><stop offset="100%" stopColor="rgba(47,103,184,0.03)" /></linearGradient>
          <linearGradient id={`${uid}-ar-${mi}`} x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor={metric.stroke} stopOpacity={0.22} /><stop offset="100%" stopColor={metric.stroke} stopOpacity={0.02} /></linearGradient>
        </defs>
        <rect x={FACET_PAD_L} y={facet.top} width={bandW} height={facet.y67 - facet.top} rx={4} fill={`url(#${uid}-bg-${mi})`} />
        <rect x={FACET_PAD_L} y={facet.y67} width={bandW} height={facet.y33 - facet.y67} fill={`url(#${uid}-bm-${mi})`} />
        <rect x={FACET_PAD_L} y={facet.y33} width={bandW} height={facet.bot - facet.y33} rx={4} fill={`url(#${uid}-bp-${mi})`} />
        {facet.monthXs.map((xv, xi) => <line key={xi} x1={xv} x2={xv} y1={facet.top} y2={facet.bot} stroke="rgba(45,51,72,0.06)" strokeWidth={1} />)}
        {facet.areaPath && <path ref={areaRef} d={facet.areaPath} fill={`url(#${uid}-ar-${mi})`} stroke="none" />}
        {facet.linePath ? <path ref={pathRef} d={facet.linePath} fill="none" stroke={metric.stroke} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" /> : <path ref={pathRef} d="" fill="none" />}
        <g ref={dotGroupRef}>
          {facet.lastPt && <circle cx={facet.lastPt.x} cy={facet.lastPt.y} r={5} fill={tierColors(facet.lastPt.p, totalTeams)} className="savant-tier-trend__pulse" />}
          {facet.pts.map((pt, j) => <circle key={j} cx={pt.x} cy={pt.y} r={5} fill={tierColors(pt.p, totalTeams)} stroke="#fff" strokeWidth={1.5} />)}
        </g>
        {hoveredMonth != null && facet.monthXs[hoveredMonth] != null && (
          <line x1={facet.monthXs[hoveredMonth]!} x2={facet.monthXs[hoveredMonth]!} y1={facet.top} y2={facet.bot} stroke="rgba(26,26,46,0.25)" strokeWidth={1} strokeDasharray="4 3" pointerEvents="none" />
        )}
        <g>{MONTH_SHORT.map((lab, xi) => <text key={lab} x={facet.monthXs[xi]!} y={facet.bot + 16} textAnchor="middle" className="savant-tier-trend__xlab">{lab}</text>)}</g>
        <g>{MONTH_SHORT.map((lab, xi) => <rect key={lab} x={facet.monthXs[xi]! - halfGap} y={facet.top} width={halfGap * 2} height={FACET_INNER_H + FACET_PAD_B} fill="transparent" onMouseEnter={() => setHoveredMonth(xi)} onMouseLeave={() => setHoveredMonth(null)} />)}</g>
        {hoveredMonth != null && (() => {
          const p = metricSeries[hoveredMonth]; if (p == null) return null;
          const px = facet.monthXs[hoveredMonth]!; const py = facet.y(p);
          const color = tierColors(p, totalTeams); const label = `${ordinal(p)}`;
          const labelW = label.length * 7 + 14;
          return (<g pointerEvents="none"><rect x={px + 8} y={py - 12} width={labelW} height={20} rx={4} fill="var(--card)" stroke={color} strokeWidth={1} opacity={0.95} /><text x={px + 8 + labelW / 2} y={py + 1} textAnchor="middle" fill={color} className="savant-facet__hover-val">{label}</text></g>);
        })()}
      </svg>
    </div>
  );
}

/* ── Main component ──────────────────────────────────────────── */

interface PitchingSavantBarsProps {
  weeks: WeeklyBucket[];
  teamLabel: string;
  leagueShape?: OffenseMonthLeagueShape[];
  leagueTeams?: number;
  chaseZoneGrid?: ChaseZoneGrid;
  whiffZoneGrid?: WhiffZoneGrid;
  barrelGrid?: BarrelGrid;
  sprayGrid?: SprayGrid;
}

export function PitchingSavantBars({ weeks, teamLabel, leagueShape, leagueTeams = 0, chaseZoneGrid, whiffZoneGrid, barrelGrid, sprayGrid }: PitchingSavantBarsProps) {
  const uid = useId().replace(/:/g, "");
  const pathRefs = useRef<(SVGPathElement | null)[]>([]);
  const areaRefs = useRef<(SVGPathElement | null)[]>([]);
  const dotGroupRefs = useRef<(SVGGElement | null)[]>([]);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [hoveredMonth, setHoveredMonth] = useState<number | null>(null);

  const selectedCalMonth = hoveredMonth != null ? hoveredMonth + 4 : null;

  const vizMap: Record<string, { component: React.ReactNode } | null> = {
    xwoba: sprayGrid ? { component: <SprayChart grid={sprayGrid} selectedMonth={selectedCalMonth} /> } : null,
    barrel_rate: barrelGrid ? { component: <BarrelScatter grid={barrelGrid} selectedMonth={selectedCalMonth} /> } : null,
    chase_rate: chaseZoneGrid ? { component: <ChaseZoneHeatmap grid={chaseZoneGrid} selectedMonth={selectedCalMonth} /> } : null,
    whiff_rate: whiffZoneGrid ? { component: <WhiffZoneHeatmap grid={whiffZoneGrid} selectedMonth={selectedCalMonth} /> } : null,
  };

  const aggs = useMemo(() => buildMonthlyAggs(weeks), [weeks]);
  const innerSeries = useMemo(() => buildSeries(aggs), [aggs]);
  const leagueSeries = useMemo(() => seriesFromLeagueShape(leagueShape ?? []), [leagueShape]);
  const series = leagueSeries ?? innerSeries;

  const facets = useMemo(
    () => METRICS.map((_, mi) => buildFacetLayout(series[mi]!, leagueTeams)),
    [series, leagueTeams],
  );

  useLayoutEffect(() => {
    let cancelled = false;
    const cleanups: Array<() => void> = [];
    const kickoff = () => {
      if (cancelled) return;
      pathRefs.current.forEach((p, i) => { const c = animateStrokeDraw(p, i * 160); if (c) cleanups.push(c); });
      areaRefs.current.forEach((a, i) => {
        if (a) { a.style.opacity = "0"; a.getAnimations().forEach((an) => an.cancel()); a.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: i * 160 + 1100, easing: "ease-out", fill: "forwards" }); }
      });
      dotGroupRefs.current.forEach((g, i) => { const last = facets[i]?.pts.length ?? 0; animateFade(g, i * 160 + (last >= 2 ? 1050 : 220)); });
    };
    let raf0 = 0, raf1 = 0;
    raf0 = requestAnimationFrame(() => { raf1 = requestAnimationFrame(() => kickoff()); });
    return () => { cancelled = true; cancelAnimationFrame(raf0); cancelAnimationFrame(raf1); cleanups.forEach((fn) => fn()); pathRefs.current.forEach((p) => p?.getAnimations().forEach((a) => a.cancel())); areaRefs.current.forEach((a) => a?.getAnimations().forEach((an) => an.cancel())); dotGroupRefs.current.forEach((g) => g?.getAnimations().forEach((a) => a.cancel())); };
  }, [facets]);

  if (weeks.length === 0) return null;

  return (
    <div className="savant-offense savant-tier-trend" role="region" aria-label={`Pitching tier trend for ${teamLabel}`}>
      <div className="savant-facet-grid">
        {METRICS.map((m, mi) => {
          const viz = vizMap[m.key];
          const hasViz = !!viz;
          const expanded = expandedKey === m.key && hasViz;
          return (
            <div key={m.key} className={`savant-facet-slot${expanded ? " savant-facet-slot--expanded" : ""}${hasViz ? " savant-facet-slot--expandable" : ""}`}
              onClick={hasViz ? () => setExpandedKey((k) => k === m.key ? null : m.key) : undefined}>
              {expanded ? (
                <div className="savant-facet savant-facet--expanded">
                  <div className="savant-facet__zone-split">
                    <div className="savant-facet__zone-trend">
                      <FacetCard mi={mi} metric={m} facet={facets[mi]!} metricSeries={series[mi]!} uid={uid} totalTeams={leagueTeams} hoveredMonth={hoveredMonth} setHoveredMonth={setHoveredMonth} pathRef={(el) => { pathRefs.current[mi] = el; }} areaRef={(el) => { areaRefs.current[mi] = el; }} dotGroupRef={(el) => { dotGroupRefs.current[mi] = el; }} />
                    </div>
                    <div className="savant-facet__zone-heatmap">{viz!.component}</div>
                  </div>
                </div>
              ) : (
                <FacetCard mi={mi} metric={m} facet={facets[mi]!} metricSeries={series[mi]!} uid={uid} totalTeams={leagueTeams} hoveredMonth={hoveredMonth} setHoveredMonth={setHoveredMonth} pathRef={(el) => { pathRefs.current[mi] = el; }} areaRef={(el) => { areaRefs.current[mi] = el; }} dotGroupRef={(el) => { dotGroupRefs.current[mi] = el; }} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
