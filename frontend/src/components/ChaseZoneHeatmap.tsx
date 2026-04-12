import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";

import type { ChaseZoneGrid, ChaseZoneMonth } from "../api";

const VB_W = 240;
const VB_H = 280;
const PAD = 20;
const MIN_PITCHES = 5;
const PULSE_MIN_PITCHES = 10;

interface ChaseZoneHeatmapProps {
  grid: ChaseZoneGrid;
  selectedMonth: number | null; // 4–9 or null for season aggregate
}

type AggCell = { x: number; y: number; n: number; sw: number; iz: number };

function aggregateCells(months: ChaseZoneMonth[]): AggCell[] {
  const map = new Map<string, AggCell>();
  for (const m of months) {
    for (const c of m.cells) {
      const k = `${c.x},${c.y}`;
      const existing = map.get(k);
      if (existing) {
        existing.n += c.n;
        existing.sw += c.sw;
        existing.iz += c.iz;
      } else {
        map.set(k, { ...c });
      }
    }
  }
  return [...map.values()];
}

export function ChaseZoneHeatmap({ grid, selectedMonth }: ChaseZoneHeatmapProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hoveredCell, setHoveredCell] = useState<AggCell | null>(null);

  const cells = useMemo(() => {
    if (selectedMonth == null) {
      return aggregateCells(grid.months);
    }
    const found = grid.months.find((m) => m.month === selectedMonth);
    return found ? found.cells.map((c) => ({ ...c })) : [];
  }, [grid, selectedMonth]);

  // Scales: map pitch coordinates → SVG pixels
  const xScale = useMemo(
    () => d3.scaleLinear().domain(grid.x_range).range([PAD, VB_W - PAD]),
    [grid.x_range],
  );
  const yScale = useMemo(
    () => d3.scaleLinear().domain(grid.y_range).range([VB_H - PAD, PAD]), // inverted: higher z = higher on screen
    [grid.y_range],
  );

  const cellW = (VB_W - 2 * PAD) / grid.nx;
  const cellH = (VB_H - 2 * PAD) / grid.ny;

  // Strike zone rect in SVG coords
  const zoneLeft = xScale(-grid.zone_width);
  const zoneRight = xScale(grid.zone_width);
  const zoneTop = yScale(grid.sz_top);
  const zoneBot = yScale(grid.sz_bot);

  // Color scale: 0% chase → transparent, 50%+ chase → hot red
  const colorScale = useMemo(
    () =>
      d3
        .scaleSequential(d3.interpolateReds)
        .domain([0, 0.5])
        .clamp(true),
    [],
  );

  // Find the hottest cell for pulse
  const hottestCell = useMemo(() => {
    let best: AggCell | null = null;
    let bestRate = 0;
    for (const c of cells) {
      if (c.iz > 0) continue; // skip in-zone
      if (c.n < PULSE_MIN_PITCHES) continue;
      const rate = c.sw / c.n;
      if (rate > bestRate) {
        bestRate = rate;
        best = c;
      }
    }
    return best;
  }, [cells]);

  // Entry animation
  const [entered, setEntered] = useState(false);
  useEffect(() => {
    setEntered(false);
    const t = requestAnimationFrame(() => {
      requestAnimationFrame(() => setEntered(true));
    });
    return () => cancelAnimationFrame(t);
  }, [selectedMonth]);

  // Center of the zone for stagger distance
  const zoneCx = (zoneLeft + zoneRight) / 2;
  const zoneCy = (zoneTop + zoneBot) / 2;

  return (
    <div className="chase-zone-heatmap">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        className="chase-zone-heatmap__svg"
        preserveAspectRatio="xMidYMid meet"
      >
        {/* Heatmap cells */}
        {cells.map((c) => {
          const isOutOfZone = c.iz === 0;
          const chaseRate = c.n > 0 ? c.sw / c.n : 0;
          const cx = PAD + c.x * cellW;
          const cy = PAD + (grid.ny - 1 - c.y) * cellH; // flip y

          // Stagger delay based on distance from zone center
          const dist = Math.sqrt((cx + cellW / 2 - zoneCx) ** 2 + (cy + cellH / 2 - zoneCy) ** 2);
          const delay = Math.min(dist * 2.5, 500);

          const isHottest = hottestCell && c.x === hottestCell.x && c.y === hottestCell.y;

          let fill: string;
          let opacity: number;
          if (!isOutOfZone) {
            fill = "#94a3b8";
            opacity = 0.08;
          } else if (c.n < MIN_PITCHES) {
            fill = "#94a3b8";
            opacity = 0.04;
          } else {
            fill = colorScale(chaseRate);
            opacity = Math.min(0.25 + (c.n / 80) * 0.75, 1);
          }

          return (
            <g key={`${c.x}-${c.y}`}>
              <rect
                x={cx}
                y={cy}
                width={cellW}
                height={cellH}
                rx={2}
                fill={fill}
                opacity={entered ? opacity : 0}
                style={{
                  transition: `opacity 0.4s ease ${delay}ms, fill 0.4s ease`,
                }}
                onMouseEnter={() => isOutOfZone && c.n >= MIN_PITCHES ? setHoveredCell(c) : undefined}
                onMouseLeave={() => setHoveredCell(null)}
              />
              {isHottest && entered && (
                <rect
                  x={cx}
                  y={cy}
                  width={cellW}
                  height={cellH}
                  rx={2}
                  fill={fill}
                  className="chase-zone-heatmap__pulse"
                  pointerEvents="none"
                />
              )}
            </g>
          );
        })}

        {/* Strike zone rectangle */}
        <rect
          x={zoneLeft}
          y={zoneTop}
          width={zoneRight - zoneLeft}
          height={zoneBot - zoneTop}
          fill="none"
          stroke="var(--ink)"
          strokeWidth={1.5}
          strokeOpacity={0.3}
          rx={2}
        />

        {/* Zone cross-hairs (9-zone grid lines) */}
        {[1, 2].map((i) => {
          const xFrac = zoneLeft + ((zoneRight - zoneLeft) * i) / 3;
          const yFrac = zoneTop + ((zoneBot - zoneTop) * i) / 3;
          return (
            <g key={i}>
              <line x1={xFrac} x2={xFrac} y1={zoneTop} y2={zoneBot} stroke="var(--ink)" strokeWidth={0.5} strokeOpacity={0.12} />
              <line x1={zoneLeft} x2={zoneRight} y1={yFrac} y2={yFrac} stroke="var(--ink)" strokeWidth={0.5} strokeOpacity={0.12} />
            </g>
          );
        })}

        {/* Home plate */}
        <polygon
          points={`${xScale(0) - 8},${VB_H - PAD + 6} ${xScale(0)},${VB_H - PAD + 2} ${xScale(0) + 8},${VB_H - PAD + 6} ${xScale(0) + 6},${VB_H - PAD + 12} ${xScale(0) - 6},${VB_H - PAD + 12}`}
          fill="none"
          stroke="var(--ink)"
          strokeWidth={1}
          strokeOpacity={0.2}
        />

        {/* Hover tooltip */}
        {hoveredCell && (() => {
          const cx = PAD + hoveredCell.x * cellW + cellW / 2;
          const cy = PAD + (grid.ny - 1 - hoveredCell.y) * cellH;
          const rate = hoveredCell.n > 0 ? hoveredCell.sw / hoveredCell.n : 0;
          const label = `${Math.round(rate * 100)}% chase`;
          const subLabel = `${hoveredCell.n} pitches`;
          const tipW = 76;
          const tipH = 32;
          const tipX = Math.min(cx - tipW / 2, VB_W - tipW - 4);
          const tipY = cy - tipH - 6;
          return (
            <g pointerEvents="none">
              <rect x={tipX} y={tipY} width={tipW} height={tipH} rx={4}
                fill="var(--card)" stroke="var(--card-border)" strokeWidth={1} />
              <text x={tipX + tipW / 2} y={tipY + 13} textAnchor="middle"
                className="chase-zone-heatmap__tip-main">
                {label}
              </text>
              <text x={tipX + tipW / 2} y={tipY + 25} textAnchor="middle"
                className="chase-zone-heatmap__tip-sub">
                {subLabel}
              </text>
            </g>
          );
        })()}
      </svg>

      {/* Color legend */}
      <div className="chase-zone-heatmap__legend">
        <span className="chase-zone-heatmap__legend-label">0%</span>
        <div className="chase-zone-heatmap__legend-bar" />
        <span className="chase-zone-heatmap__legend-label">50%+</span>
      </div>
    </div>
  );
}
