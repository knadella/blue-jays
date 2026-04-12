import { useEffect, useMemo, useState } from "react";
import * as d3 from "d3";

import type { WhiffZoneGrid, WhiffZoneMonth } from "../api";

const VB_W = 240;
const VB_H = 280;
const PAD = 20;
const MIN_SWINGS = 5;

interface WhiffZoneHeatmapProps {
  grid: WhiffZoneGrid;
  selectedMonth: number | null;
}

type AggCell = { x: number; y: number; n: number; wh: number };

function aggregateCells(months: WhiffZoneMonth[]): AggCell[] {
  const map = new Map<string, AggCell>();
  for (const m of months) {
    for (const c of m.cells) {
      const k = `${c.x},${c.y}`;
      const existing = map.get(k);
      if (existing) {
        existing.n += c.n;
        existing.wh += c.wh;
      } else {
        map.set(k, { ...c });
      }
    }
  }
  return [...map.values()];
}

export function WhiffZoneHeatmap({ grid, selectedMonth }: WhiffZoneHeatmapProps) {
  const [entered, setEntered] = useState(false);
  const [hoveredCell, setHoveredCell] = useState<AggCell | null>(null);

  const cells = useMemo(() => {
    if (selectedMonth == null) return aggregateCells(grid.months);
    const found = grid.months.find((m) => m.month === selectedMonth);
    return found ? found.cells.map((c) => ({ ...c })) : [];
  }, [grid, selectedMonth]);

  const xScale = useMemo(() => d3.scaleLinear().domain(grid.x_range).range([PAD, VB_W - PAD]), [grid.x_range]);
  const yScale = useMemo(() => d3.scaleLinear().domain(grid.y_range).range([VB_H - PAD, PAD]), [grid.y_range]);

  const cellW = (VB_W - 2 * PAD) / grid.nx;
  const cellH = (VB_H - 2 * PAD) / grid.ny;

  const zoneLeft = xScale(-grid.zone_width);
  const zoneRight = xScale(grid.zone_width);
  const zoneTop = yScale(grid.sz_top);
  const zoneBot = yScale(grid.sz_bot);

  const colorScale = useMemo(() => d3.scaleSequential(d3.interpolateOranges).domain([0, 0.5]).clamp(true), []);

  useEffect(() => {
    setEntered(false);
    const t = requestAnimationFrame(() => { requestAnimationFrame(() => setEntered(true)); });
    return () => cancelAnimationFrame(t);
  }, [selectedMonth]);

  const zoneCx = (zoneLeft + zoneRight) / 2;
  const zoneCy = (zoneTop + zoneBot) / 2;

  return (
    <div className="chase-zone-heatmap">
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="chase-zone-heatmap__svg" preserveAspectRatio="xMidYMid meet">
        {cells.map((c) => {
          const rate = c.n > 0 ? c.wh / c.n : 0;
          const cx = PAD + c.x * cellW;
          const cy = PAD + (grid.ny - 1 - c.y) * cellH;
          const dist = Math.sqrt((cx + cellW / 2 - zoneCx) ** 2 + (cy + cellH / 2 - zoneCy) ** 2);
          const delay = Math.min(dist * 2.5, 500);

          let fill: string;
          let opacity: number;
          if (c.n < MIN_SWINGS) {
            fill = "#94a3b8";
            opacity = 0.04;
          } else {
            fill = colorScale(rate);
            opacity = Math.min(0.25 + (c.n / 60) * 0.75, 1);
          }

          return (
            <rect
              key={`${c.x}-${c.y}`}
              x={cx} y={cy} width={cellW} height={cellH} rx={2}
              fill={fill} opacity={entered ? opacity : 0}
              style={{ transition: `opacity 0.4s ease ${delay}ms, fill 0.4s ease` }}
              onMouseEnter={() => c.n >= MIN_SWINGS ? setHoveredCell(c) : undefined}
              onMouseLeave={() => setHoveredCell(null)}
            />
          );
        })}

        {/* Strike zone */}
        <rect x={zoneLeft} y={zoneTop} width={zoneRight - zoneLeft} height={zoneBot - zoneTop}
          fill="none" stroke="var(--ink)" strokeWidth={1.5} strokeOpacity={0.3} rx={2} />
        {[1, 2].map((i) => (
          <g key={i}>
            <line x1={zoneLeft + ((zoneRight - zoneLeft) * i) / 3} x2={zoneLeft + ((zoneRight - zoneLeft) * i) / 3}
              y1={zoneTop} y2={zoneBot} stroke="var(--ink)" strokeWidth={0.5} strokeOpacity={0.12} />
            <line x1={zoneLeft} x2={zoneRight}
              y1={zoneTop + ((zoneBot - zoneTop) * i) / 3} y2={zoneTop + ((zoneBot - zoneTop) * i) / 3}
              stroke="var(--ink)" strokeWidth={0.5} strokeOpacity={0.12} />
          </g>
        ))}

        {/* Home plate */}
        <polygon
          points={`${xScale(0) - 8},${VB_H - PAD + 6} ${xScale(0)},${VB_H - PAD + 2} ${xScale(0) + 8},${VB_H - PAD + 6} ${xScale(0) + 6},${VB_H - PAD + 12} ${xScale(0) - 6},${VB_H - PAD + 12}`}
          fill="none" stroke="var(--ink)" strokeWidth={1} strokeOpacity={0.2} />

        {/* Hover tooltip */}
        {hoveredCell && (() => {
          const cx = PAD + hoveredCell.x * cellW + cellW / 2;
          const cy = PAD + (grid.ny - 1 - hoveredCell.y) * cellH;
          const rate = hoveredCell.n > 0 ? hoveredCell.wh / hoveredCell.n : 0;
          const tipW = 76; const tipH = 32;
          const tipX = Math.min(cx - tipW / 2, VB_W - tipW - 4);
          const tipY = cy - tipH - 6;
          return (
            <g pointerEvents="none">
              <rect x={tipX} y={tipY} width={tipW} height={tipH} rx={4}
                fill="var(--card)" stroke="var(--card-border)" strokeWidth={1} />
              <text x={tipX + tipW / 2} y={tipY + 13} textAnchor="middle" className="chase-zone-heatmap__tip-main">
                {Math.round(rate * 100)}% whiff
              </text>
              <text x={tipX + tipW / 2} y={tipY + 25} textAnchor="middle" className="chase-zone-heatmap__tip-sub">
                {hoveredCell.n} swings
              </text>
            </g>
          );
        })()}
      </svg>
      <div className="chase-zone-heatmap__legend">
        <span className="chase-zone-heatmap__legend-label">0%</span>
        <div className="chase-zone-heatmap__legend-bar" style={{ background: "linear-gradient(to right, #fff5eb, #fd8d3c, #8c2d04)" }} />
        <span className="chase-zone-heatmap__legend-label">50%+</span>
      </div>
    </div>
  );
}
