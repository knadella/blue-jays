import { useEffect, useRef } from "react";
import * as d3 from "d3";

import type { WeekSideMetrics, WeeklyBucket } from "../api";

type Role = "offense" | "run_prevention";

interface WeeklyProgressChartsProps {
  weeks: WeeklyBucket[];
  teamLabel: string;
  accent: string;
  role: Role;
}

type TrendPoint = {
  week: string;
  t: Date;
  chase?: number;
  whiff?: number;
  xwoba?: number;
  hard?: number;
};

const CHART_W = 720;
const CHART_H = 300;

function pickMetrics(side: WeekSideMetrics): Omit<TrendPoint, "week" | "t"> {
  return {
    chase: side.chase_rate ?? undefined,
    whiff: side.whiff_rate ?? undefined,
    xwoba: side.xwoba_on_contact ?? undefined,
    hard: side.hard_hit_rate ?? undefined,
  };
}

/** Monotone curves need ≥2 points; pad domain so one-week seasons still scale. */
function paddedTimeDomain(data: TrendPoint[]): [Date, Date] {
  const times = data.map((d) => d.t.getTime());
  let t0 = d3.min(times)!;
  let t1 = d3.max(times)!;
  if (!Number.isFinite(t0) || !Number.isFinite(t1)) {
    const now = Date.now();
    return [new Date(now - 7 * 86400000), new Date(now)];
  }
  if (t0 === t1) {
    const day = 86400000;
    return [new Date(t0 - 3 * day), new Date(t1 + 3 * day)];
  }
  const span = Math.max(t1 - t0, 86400000);
  const pad = span * 0.12;
  return [new Date(t0 - pad), new Date(t1 + pad)];
}

export function WeeklyProgressCharts({ weeks, teamLabel, accent, role }: WeeklyProgressChartsProps) {
  const ref = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || weeks.length === 0) {
      return;
    }

    const data: TrendPoint[] = weeks.map((wk) => ({
      week: wk.week_key,
      t: new Date(wk.week_end),
      ...pickMetrics(role === "offense" ? wk.offense : wk.run_prevention),
    }));

    const margin = { top: 26, right: 14, bottom: 34, left: 42 };
    const innerW = CHART_W - margin.left - margin.right;
    const innerH = CHART_H - margin.top - margin.bottom;

    d3.select(el).selectAll("*").remove();
    const svg = d3
      .select(el)
      .attr("viewBox", `0 0 ${CHART_W} ${CHART_H}`)
      .attr("width", CHART_W)
      .attr("height", CHART_H)
      .attr("role", "img")
      .attr(
        "aria-label",
        `${role === "offense" ? "Offense" : "Run prevention"} trends by week for ${teamLabel}`,
      );

    const [dom0, dom1] = paddedTimeDomain(data);
    const x = d3.scaleTime().domain([dom0, dom1]).range([0, innerW]);

    const series: {
      key: keyof Omit<TrendPoint, "week" | "t">;
      label: string;
      color: string;
      fmt: (n: number) => string;
    }[] =
      role === "offense"
        ? [
            { key: "xwoba", label: "xwOBA on contact", color: accent, fmt: (n) => n.toFixed(3) },
            { key: "chase", label: "Chase (O-swing)", color: "#2d7a5a", fmt: (n) => `${(n * 100).toFixed(1)}%` },
            { key: "whiff", label: "Whiff / swing", color: "#5b6a8a", fmt: (n) => `${(n * 100).toFixed(1)}%` },
            { key: "hard", label: "Hard-hit (95+ mph)", color: "#c45b3e", fmt: (n) => `${(n * 100).toFixed(1)}%` },
          ]
        : [
            { key: "xwoba", label: "xwOBA allowed (contact)", color: accent, fmt: (n) => n.toFixed(3) },
            { key: "chase", label: "Opp. chase rate", color: "#2d7a5a", fmt: (n) => `${(n * 100).toFixed(1)}%` },
            { key: "whiff", label: "Opp. whiff / swing", color: "#5b6a8a", fmt: (n) => `${(n * 100).toFixed(1)}%` },
            { key: "hard", label: "Hard contact allowed", color: "#c45b3e", fmt: (n) => `${(n * 100).toFixed(1)}%` },
          ];

    const paneH = innerH / series.length;

    series.forEach((s, i) => {
      const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top + i * paneH})`);

      const vals = data.map((d) => d[s.key]).filter((v): v is number => typeof v === "number" && !Number.isNaN(v));
      if (vals.length === 0) {
        g.append("text")
          .attr("x", innerW / 2)
          .attr("y", paneH / 2)
          .attr("text-anchor", "middle")
          .attr("fill", "#7c8494")
          .attr("font-size", "12px")
          .text("No data for this split.");
        return;
      }

      const yPad = (d3.max(vals)! - d3.min(vals)!) * 0.12 || 0.02;
      const y0 = d3.min(vals)! - yPad;
      const y1 = d3.max(vals)! + yPad;
      const y = d3.scaleLinear().domain([y0, y1]).range([paneH - 8, 4]);

      const definedRows = data.filter((d) => typeof d[s.key] === "number");
      const curve = definedRows.length >= 3 ? d3.curveMonotoneX : d3.curveLinear;

      const line = d3
        .line<TrendPoint>()
        .defined((d) => typeof d[s.key] === "number")
        .x((d) => x(d.t))
        .y((d) => y(d[s.key] as number))
        .curve(curve);

      const dPath = line(data);
      if (dPath) {
        g.append("path").datum(data).attr("fill", "none").attr("stroke", s.color).attr("stroke-width", 2.25).attr("d", dPath);
      }

      /* Monotone line is null for a single point — draw a visible marker instead. */
      if (definedRows.length === 1) {
        const d0 = definedRows[0]!;
        g.append("circle")
          .attr("cx", x(d0.t))
          .attr("cy", y(d0[s.key] as number))
          .attr("r", 9)
          .attr("fill", s.color)
          .attr("opacity", 0.35);
        g.append("circle")
          .attr("cx", x(d0.t))
          .attr("cy", y(d0[s.key] as number))
          .attr("r", 5)
          .attr("fill", s.color)
          .attr("stroke", "#fff")
          .attr("stroke-width", 1.5)
          .append("title")
          .text(`${d0.week}\n${s.label}: ${s.fmt(d0[s.key] as number)}`);
      }

      definedRows.forEach((d) => {
        const cx = x(d.t);
        const cy = y(d[s.key] as number);
        if (!Number.isFinite(cx) || !Number.isFinite(cy)) {
          return;
        }
        if (definedRows.length === 1) {
          return;
        }
        g.append("circle")
          .attr("class", "pt")
          .attr("cx", cx)
          .attr("cy", cy)
          .attr("r", 4)
          .attr("fill", s.color)
          .attr("stroke", "#fff")
          .attr("stroke-width", 1)
          .append("title")
          .text(`${d.week}\n${s.label}: ${s.fmt(d[s.key] as number)}`);
      });

      g.append("text")
        .attr("x", 0)
        .attr("y", -5)
        .attr("fill", "#2d3348")
        .attr("font-size", "11px")
        .attr("font-weight", "600")
        .text(s.label);

      const yAxis = d3
        .axisLeft(y)
        .ticks(3)
        .tickFormat((v) => (s.key === "xwoba" ? Number(v).toFixed(2) : `${Math.round(Number(v) * 100)}`));
      g.append("g").attr("opacity", 0.55).call(yAxis.tickSize(3)).selectAll("text").attr("font-size", "9px");

      if (i === series.length - 1) {
        const xAxis = d3
          .axisBottom(x)
          .ticks(Math.min(8, data.length))
          .tickFormat(d3.timeFormat("%b %d") as unknown as null);
        g.append("g").attr("transform", `translate(0,${paneH})`).call(xAxis).selectAll("text").attr("font-size", "9px");
      }
    });
  }, [weeks, teamLabel, accent, role]);

  if (weeks.length === 0) {
    return (
      <div className="weekly-chart-empty" role="status">
        <p>No weekly Statcast buckets yet for this season.</p>
        <p className="weekly-chart-empty-hint">Try a completed year (for example 2025) if the schedule has not started.</p>
      </div>
    );
  }

  return (
    <div className="weekly-chart-wrap">
      <svg ref={ref} className="weekly-chart-svg" preserveAspectRatio="xMidYMid meet" />
    </div>
  );
}
