import { useEffect, useRef } from "react";
import * as d3 from "d3";

import type { MonthlyRunRatePoint } from "../api";
import { getTeamAbbrev, getTeamColor } from "../teamMetadata";

interface Props {
  monthly: MonthlyRunRatePoint[];
  team: string;
}

const FONT = "'Inter', -apple-system, system-ui, sans-serif";
const LG_COLOR = "#9a8b7c";

interface LineDef {
  color: string;
  dash: string;
  width: number;
  dotR: number;
  filled: boolean;
  val: (d: MonthlyRunRatePoint) => number | null;
  legendLabel: string;
}

function makeLineDefs(accent: string, teamAbbr: string, mode: "scored" | "allowed"): LineDef[] {
  return [
    {
      color: LG_COLOR, dash: "3,3", width: 1.5, dotR: 3, filled: false,
      val: (d) => (mode === "scored" ? d.league_runs_scored_projected : d.league_runs_allowed_projected),
      legendLabel: "League proj.",
    },
    {
      color: LG_COLOR, dash: "", width: 2, dotR: 3.5, filled: true,
      val: (d) => (mode === "scored" ? d.league_runs_scored_actual : d.league_runs_allowed_actual),
      legendLabel: "League actual",
    },
    {
      color: accent, dash: "6,4", width: 2, dotR: 4, filled: false,
      val: (d) => (mode === "scored" ? d.runs_scored_projected : d.runs_allowed_projected),
      legendLabel: `${teamAbbr} proj.`,
    },
    {
      color: accent, dash: "", width: 2.5, dotR: 5, filled: true,
      val: (d) => (mode === "scored" ? d.runs_scored_actual : d.runs_allowed_actual),
      legendLabel: `${teamAbbr} actual`,
    },
  ];
}

function drawMonthlyChart(
  svg: d3.Selection<SVGSVGElement, unknown, null, undefined>,
  data: MonthlyRunRatePoint[],
  team: string,
  mode: "scored" | "allowed",
) {
  const accent = getTeamColor(team);
  const teamAbbr = getTeamAbbrev(team);
  const width = 520;
  const height = 230;
  const margin = { top: 44, right: 20, bottom: 28, left: 42 };

  svg.selectAll("*").remove();
  svg.attr("viewBox", `0 0 ${width} ${height}`);

  const title = mode === "scored" ? "Runs scored / game" : "Runs allowed / game";

  svg.append("text").attr("x", margin.left).attr("y", 18).attr("fill", "#1d1d1d")
    .style("font-size", "14px").style("font-weight", "600").style("font-family", FONT).text(title);
  svg.append("text").attr("x", margin.left).attr("y", 34).attr("fill", "#9a8b7c")
    .style("font-size", "10.5px").style("font-weight", "500").style("font-family", FONT)
    .text(`${teamAbbr} vs league · projection and actual per month`);

  if (data.length === 0) {
    svg.append("text").attr("x", width / 2).attr("y", height / 2).attr("text-anchor", "middle")
      .attr("fill", "#9a8b7c").style("font-size", "13px").style("font-family", FONT)
      .text("No monthly data yet.");
    return;
  }

  const lines = makeLineDefs(accent, teamAbbr, mode);

  const yVals: number[] = [];
  for (const d of data) for (const l of lines) { const v = l.val(d); if (v != null) yVals.push(v); }
  const yMin = Math.min(...yVals);
  const yMax = Math.max(...yVals);
  const yPad = Math.max((yMax - yMin) * 0.18, 0.25);

  const x = d3.scalePoint<string>().domain(data.map((d) => d.label))
    .range([margin.left, width - margin.right]).padding(0.3);
  const y = d3.scaleLinear().domain([yMin - yPad, yMax + yPad]).nice()
    .range([height - margin.bottom, margin.top]);

  // x-axis
  svg.append("g").attr("transform", `translate(0,${height - margin.bottom})`)
    .call(d3.axisBottom(x).tickSize(0).tickPadding(8))
    .call((g) => g.select(".domain").attr("stroke", "#ddd1c4"))
    .call((g) => g.selectAll("text").attr("fill", "#6b5b4d").style("font-size", "11px").style("font-weight", "600"));

  // y-axis
  svg.append("g").attr("transform", `translate(${margin.left},0)`)
    .call(d3.axisLeft(y).ticks(5).tickFormat((v) => d3.format(".2f")(v as number)))
    .call((g) => g.select(".domain").remove())
    .call((g) => g.selectAll(".tick line").attr("x2", width - margin.left - margin.right).attr("stroke", "#f0e8df").attr("stroke-opacity", 0.9))
    .call((g) => g.selectAll("text").attr("fill", "#6b5b4d").style("font-size", "10px"));

  // lines + dots
  for (const l of lines) {
    const gen = d3.line<MonthlyRunRatePoint>().defined((d) => l.val(d) != null)
      .x((d) => x(d.label)!).y((d) => y(l.val(d)!));
    svg.append("path").datum(data).attr("fill", "none").attr("stroke", l.color)
      .attr("stroke-width", l.width).attr("stroke-dasharray", l.dash).attr("d", gen);
    data.forEach((d) => {
      const v = l.val(d);
      if (v == null) return;
      svg.append("circle").attr("cx", x(d.label)!).attr("cy", y(v)).attr("r", l.dotR)
        .attr("fill", l.filled ? l.color : "#fffaf4")
        .attr("stroke", l.filled ? "#fffaf4" : l.color)
        .attr("stroke-width", 1.8);
    });
  }
}

function LegendItem({ color, dash, filled, label }: { color: string; dash: string; filled: boolean; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, marginRight: 16 }}>
      <svg width="22" height="12" style={{ flexShrink: 0 }}>
        <line x1="0" x2="16" y1="6" y2="6" stroke={color} strokeWidth={filled ? 2.5 : 2} strokeDasharray={dash} />
        <circle cx="8" cy="6" r={3} fill={filled ? color : "#fffaf4"} stroke={filled ? "#fffaf4" : color} strokeWidth={1.5} />
      </svg>
      <span style={{ fontSize: "10px", fontWeight: 500, color: "#6b5b4d", fontFamily: FONT, whiteSpace: "nowrap" }}>
        {label}
      </span>
    </span>
  );
}

export function TeamRatingCharts({ monthly, team }: Props) {
  const offenseRef = useRef<SVGSVGElement | null>(null);
  const defenseRef = useRef<SVGSVGElement | null>(null);
  const accent = getTeamColor(team);
  const teamAbbr = getTeamAbbrev(team);

  useEffect(() => {
    if (offenseRef.current) drawMonthlyChart(d3.select(offenseRef.current), monthly, team, "scored");
    if (defenseRef.current) drawMonthlyChart(d3.select(defenseRef.current), monthly, team, "allowed");
  }, [monthly, team]);

  return (
    <>
      <div className="rating-charts">
        <div className="rating-chart">
          <svg ref={offenseRef} className="chart-svg" role="img" aria-label="Runs scored: monthly projections and actuals" />
        </div>
        <div className="rating-chart">
          <svg ref={defenseRef} className="chart-svg" role="img" aria-label="Runs allowed: monthly projections and actuals" />
        </div>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "4px 0", marginTop: 6, padding: "0 20px" }}>
        <LegendItem color={LG_COLOR} dash="3,3" filled={false} label="League proj." />
        <LegendItem color={LG_COLOR} dash="" filled={true} label="League actual" />
        <LegendItem color={accent} dash="6,4" filled={false} label={`${teamAbbr} proj.`} />
        <LegendItem color={accent} dash="" filled={true} label={`${teamAbbr} actual`} />
      </div>
    </>
  );
}
