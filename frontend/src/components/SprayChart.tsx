import { useEffect, useMemo, useState } from "react";
import * as d3 from "d3";

import type { SprayGrid, SprayMonth } from "../api";

const VB_W = 240;
const VB_H = 240;
const PAD = 16;
const MIN_BBE = 3;

// Statcast hc_x/hc_y: home plate at ~(125, 200), field radiates upward
const HOME_X = 125;
const HOME_Y = 200;

interface SprayChartProps {
  grid: SprayGrid;
  selectedMonth: number | null;
}

type AggCell = { x: number; y: number; n: number; xw: number };

function aggregateCells(months: SprayMonth[]): AggCell[] {
  const map = new Map<string, AggCell>();
  for (const m of months) {
    for (const c of m.cells) {
      const k = `${c.x},${c.y}`;
      const existing = map.get(k);
      if (existing) {
        existing.n += c.n;
        existing.xw += c.xw;
      } else {
        map.set(k, { ...c });
      }
    }
  }
  return [...map.values()];
}

export function SprayChart({ grid, selectedMonth }: SprayChartProps) {
  const [entered, setEntered] = useState(false);
  const [hoveredCell, setHoveredCell] = useState<AggCell | null>(null);

  const cells = useMemo(() => {
    if (selectedMonth == null) return aggregateCells(grid.months);
    const found = grid.months.find((m) => m.month === selectedMonth);
    return found ? found.cells.map((c) => ({ ...c })) : [];
  }, [grid, selectedMonth]);

  const xScale = useMemo(() => d3.scaleLinear().domain(grid.x_range).range([PAD, VB_W - PAD]), [grid.x_range]);
  const yScale = useMemo(() => d3.scaleLinear().domain(grid.y_range).range([PAD, VB_H - PAD]), [grid.y_range]);

  const cellW = (VB_W - 2 * PAD) / grid.nx;
  const cellH = (VB_H - 2 * PAD) / grid.ny;

  // xwOBA color: cold (blue, low) → hot (red, high)
  const colorScale = useMemo(
    () => d3.scaleSequential(d3.interpolateRdYlBu).domain([0.6, 0.0]).clamp(true),
    [],
  );

  // Home plate position in SVG coords
  const hpX = xScale(HOME_X);
  const hpY = yScale(HOME_Y);

  // Field outline geometry (foul lines + outfield arc)
  const fieldRadius = Math.min(VB_W, VB_H) * 0.42;
  const foulLineLen = fieldRadius * 1.1;
  // Foul lines at 45° from home plate (Statcast coordinate system)
  const lfX = hpX - foulLineLen * Math.cos(Math.PI / 4);
  const lfY = hpY - foulLineLen * Math.sin(Math.PI / 4);
  const rfX = hpX + foulLineLen * Math.cos(Math.PI / 4);
  const rfY = hpY - foulLineLen * Math.sin(Math.PI / 4);

  // Outfield arc
  const arcPath = `M ${lfX} ${lfY} A ${fieldRadius} ${fieldRadius} 0 0 1 ${rfX} ${rfY}`;

  // Infield diamond
  const infieldR = fieldRadius * 0.28;
  const diamondPts = [
    [hpX, hpY],                              // home
    [hpX + infieldR * 0.7, hpY - infieldR * 0.7], // 1B
    [hpX, hpY - infieldR * 1.0],              // 2B
    [hpX - infieldR * 0.7, hpY - infieldR * 0.7], // 3B
  ].map((p) => p.join(",")).join(" ");

  useEffect(() => {
    setEntered(false);
    const t = requestAnimationFrame(() => { requestAnimationFrame(() => setEntered(true)); });
    return () => cancelAnimationFrame(t);
  }, [selectedMonth]);

  return (
    <div className="spray-chart">
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="spray-chart__svg" preserveAspectRatio="xMidYMid meet">
        {/* Field outline */}
        <path d={arcPath} fill="none" stroke="var(--ink)" strokeWidth={1} strokeOpacity={0.15} />
        <line x1={hpX} y1={hpY} x2={lfX} y2={lfY} stroke="var(--ink)" strokeWidth={1} strokeOpacity={0.15} />
        <line x1={hpX} y1={hpY} x2={rfX} y2={rfY} stroke="var(--ink)" strokeWidth={1} strokeOpacity={0.15} />

        {/* Infield diamond */}
        <polygon points={diamondPts} fill="none" stroke="var(--ink)" strokeWidth={0.7} strokeOpacity={0.12} />

        {/* Heatmap cells */}
        {cells.map((c) => {
          if (c.n < MIN_BBE) return null;
          const avgXw = c.xw / c.n;
          const cx = PAD + c.x * cellW;
          const cy = PAD + c.y * cellH; // y not inverted — hc_y increases downward in Statcast
          const fill = colorScale(avgXw);
          const opacity = Math.min(0.3 + (c.n / 40) * 0.7, 0.9);

          return (
            <rect
              key={`${c.x}-${c.y}`}
              x={cx} y={cy} width={cellW} height={cellH} rx={2}
              fill={fill} opacity={entered ? opacity : 0}
              style={{ transition: "opacity 0.4s ease, fill 0.4s ease" }}
              onMouseEnter={() => setHoveredCell(c)}
              onMouseLeave={() => setHoveredCell(null)}
            />
          );
        })}

        {/* Home plate marker */}
        <circle cx={hpX} cy={hpY} r={3} fill="var(--ink)" fillOpacity={0.2} />

        {/* Hover tooltip */}
        {hoveredCell && (() => {
          const cx = PAD + hoveredCell.x * cellW + cellW / 2;
          const cy = PAD + hoveredCell.y * cellH;
          const avgXw = hoveredCell.n > 0 ? hoveredCell.xw / hoveredCell.n : 0;
          const tipW = 76; const tipH = 32;
          const tipX = Math.min(Math.max(cx - tipW / 2, 2), VB_W - tipW - 2);
          const tipY = Math.max(cy - tipH - 6, 2);
          return (
            <g pointerEvents="none">
              <rect x={tipX} y={tipY} width={tipW} height={tipH} rx={4}
                fill="var(--card)" stroke="var(--card-border)" strokeWidth={1} />
              <text x={tipX + tipW / 2} y={tipY + 13} textAnchor="middle" className="chase-zone-heatmap__tip-main">
                .{Math.round(avgXw * 1000)} xwOBA
              </text>
              <text x={tipX + tipW / 2} y={tipY + 25} textAnchor="middle" className="chase-zone-heatmap__tip-sub">
                {hoveredCell.n} BBE
              </text>
            </g>
          );
        })()}
      </svg>
      <div className="chase-zone-heatmap__legend">
        <span className="chase-zone-heatmap__legend-label">.000</span>
        <div className="chase-zone-heatmap__legend-bar" style={{ background: "linear-gradient(to right, #4575b4, #ffffbf, #d73027)" }} />
        <span className="chase-zone-heatmap__legend-label">.600+</span>
      </div>
    </div>
  );
}
