import { useEffect, useMemo, useState } from "react";
import * as d3 from "d3";

import type { BarrelGrid, BarrelMonth } from "../api";

const VB_W = 240;
const VB_H = 240;
const PAD_L = 32;
const PAD_R = 12;
const PAD_T = 12;
const PAD_B = 28;
const MIN_BBE = 3;

interface BarrelScatterProps {
  grid: BarrelGrid;
  selectedMonth: number | null;
}

type AggCell = { x: number; y: number; n: number; brl: number };

function aggregateCells(months: BarrelMonth[]): AggCell[] {
  const map = new Map<string, AggCell>();
  for (const m of months) {
    for (const c of m.cells) {
      const k = `${c.x},${c.y}`;
      const existing = map.get(k);
      if (existing) {
        existing.n += c.n;
        existing.brl += c.brl;
      } else {
        map.set(k, { ...c });
      }
    }
  }
  return [...map.values()];
}

export function BarrelScatter({ grid, selectedMonth }: BarrelScatterProps) {
  const [entered, setEntered] = useState(false);
  const [hoveredCell, setHoveredCell] = useState<AggCell | null>(null);

  const cells = useMemo(() => {
    if (selectedMonth == null) return aggregateCells(grid.months);
    const found = grid.months.find((m) => m.month === selectedMonth);
    return found ? found.cells.map((c) => ({ ...c })) : [];
  }, [grid, selectedMonth]);

  const innerW = VB_W - PAD_L - PAD_R;
  const innerH = VB_H - PAD_T - PAD_B;
  const cellW = innerW / grid.nx;
  const cellH = innerH / grid.ny;

  // EV on x (left=slow, right=fast), LA on y (bottom=negative, top=positive)
  const evScale = useMemo(() => d3.scaleLinear().domain(grid.ev_range).range([PAD_L, PAD_L + innerW]), [grid.ev_range]);
  const laScale = useMemo(() => d3.scaleLinear().domain(grid.la_range).range([PAD_T + innerH, PAD_T]), [grid.la_range]);

  // Density color: more BBE = darker
  const maxN = useMemo(() => Math.max(...cells.map((c) => c.n), 1), [cells]);
  const densityScale = useMemo(() => d3.scaleSequential(d3.interpolateBlues).domain([0, maxN]).clamp(true), [maxN]);

  // Barrel zone polygon: EV ≥ 98, LA 26-30° (simplified rectangle for clarity)
  const barrelLeft = evScale(98);
  const barrelRight = PAD_L + innerW;
  const barrelTop = laScale(30);
  const barrelBot = laScale(26);

  useEffect(() => {
    setEntered(false);
    const t = requestAnimationFrame(() => { requestAnimationFrame(() => setEntered(true)); });
    return () => cancelAnimationFrame(t);
  }, [selectedMonth]);

  // Axis ticks
  const evTicks = [60, 70, 80, 90, 100, 110];
  const laTicks = [-20, 0, 20, 40, 60];

  return (
    <div className="barrel-scatter">
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="barrel-scatter__svg" preserveAspectRatio="xMidYMid meet">
        {/* Grid background */}
        <rect x={PAD_L} y={PAD_T} width={innerW} height={innerH} fill="rgba(0,0,0,0.02)" rx={3} />

        {/* Barrel zone highlight */}
        <rect
          x={barrelLeft} y={barrelTop}
          width={barrelRight - barrelLeft} height={barrelBot - barrelTop}
          fill="rgba(196, 91, 62, 0.12)" stroke="#c45b3e" strokeWidth={1} strokeDasharray="4 2"
          rx={2}
        />
        <text x={barrelLeft + 4} y={barrelTop - 3} className="barrel-scatter__zone-label" fill="#c45b3e">
          barrel zone
        </text>

        {/* Heatmap cells */}
        {cells.map((c) => {
          if (c.n < MIN_BBE) return null;
          const cx = PAD_L + c.x * cellW;
          const cy = PAD_T + (grid.ny - 1 - c.y) * cellH;
          const hasBrl = c.brl > 0;
          const fill = hasBrl ? "#c45b3e" : densityScale(c.n);
          const opacity = hasBrl
            ? Math.min(0.4 + (c.brl / c.n) * 0.6, 1)
            : Math.min(0.15 + (c.n / maxN) * 0.6, 0.7);

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

        {/* X axis (EV) */}
        {evTicks.map((v) => (
          <g key={v}>
            <line x1={evScale(v)} x2={evScale(v)} y1={PAD_T + innerH} y2={PAD_T + innerH + 4}
              stroke="var(--muted)" strokeWidth={0.5} />
            <text x={evScale(v)} y={PAD_T + innerH + 14} textAnchor="middle" className="barrel-scatter__tick">
              {v}
            </text>
          </g>
        ))}
        <text x={PAD_L + innerW / 2} y={VB_H - 2} textAnchor="middle" className="barrel-scatter__axis-label">
          Exit Velo (mph)
        </text>

        {/* Y axis (LA) */}
        {laTicks.map((v) => (
          <g key={v}>
            <line x1={PAD_L - 4} x2={PAD_L} y1={laScale(v)} y2={laScale(v)}
              stroke="var(--muted)" strokeWidth={0.5} />
            <text x={PAD_L - 6} y={laScale(v) + 3} textAnchor="end" className="barrel-scatter__tick">
              {v}°
            </text>
          </g>
        ))}

        {/* Hover tooltip */}
        {hoveredCell && (() => {
          const cx = PAD_L + hoveredCell.x * cellW + cellW / 2;
          const cy = PAD_T + (grid.ny - 1 - hoveredCell.y) * cellH;
          const tipW = 72; const tipH = 32;
          const tipX = Math.min(Math.max(cx - tipW / 2, 2), VB_W - tipW - 2);
          const tipY = cy - tipH - 6;
          return (
            <g pointerEvents="none">
              <rect x={tipX} y={tipY} width={tipW} height={tipH} rx={4}
                fill="var(--card)" stroke="var(--card-border)" strokeWidth={1} />
              <text x={tipX + tipW / 2} y={tipY + 13} textAnchor="middle" className="chase-zone-heatmap__tip-main">
                {hoveredCell.brl} barrel{hoveredCell.brl !== 1 ? "s" : ""}
              </text>
              <text x={tipX + tipW / 2} y={tipY + 25} textAnchor="middle" className="chase-zone-heatmap__tip-sub">
                {hoveredCell.n} BBE
              </text>
            </g>
          );
        })()}
      </svg>
    </div>
  );
}
