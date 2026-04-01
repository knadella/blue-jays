import { useEffect, useRef } from "react";
import * as d3 from "d3";

import type { MonthlyRunRatePoint } from "../api";
import { getTeamAbbrev, getTeamColor } from "../teamMetadata";

interface Props {
  monthly: MonthlyRunRatePoint[];
  team: string;
}

function abbrev(team: string): string {
  return getTeamAbbrev(team);
}

function drawMonthlyChart(
  svg: d3.Selection<SVGSVGElement, unknown, null, undefined>,
  data: MonthlyRunRatePoint[],
  team: string,
  mode: "scored" | "allowed",
) {
  const accent = getTeamColor(team);
  const width = 520;
  const height = 268;
  const margin = { top: 44, right: 20, bottom: 52, left: 34 };

  svg.selectAll("*").remove();
  svg.attr("viewBox", `0 0 ${width} ${height}`);

  const title = mode === "scored" ? "Runs scored / game" : "Runs allowed / game";
  const subtitle = `${abbrev(team)}: projection at each month start vs season-to-date actual`;

  svg
    .append("text")
    .attr("x", margin.left)
    .attr("y", 18)
    .attr("fill", "#1d1d1d")
    .style("font-size", "14px")
    .style("font-weight", "600")
    .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
    .text(title);

  svg
    .append("text")
    .attr("x", margin.left)
    .attr("y", 34)
    .attr("fill", "#9a8b7c")
    .style("font-size", "11px")
    .style("font-weight", "500")
    .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
    .text(subtitle);

  if (data.length === 0) {
    svg
      .append("text")
      .attr("x", width / 2)
      .attr("y", height / 2)
      .attr("text-anchor", "middle")
      .attr("fill", "#9a8b7c")
      .style("font-size", "13px")
      .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
      .text("No monthly history yet for this season.");
    return;
  }

  const proj = (d: MonthlyRunRatePoint) =>
    mode === "scored" ? d.runs_scored_projected : d.runs_allowed_projected;
  const act = (d: MonthlyRunRatePoint) =>
    mode === "scored" ? d.runs_scored_actual_szn_to_date : d.runs_allowed_actual_szn_to_date;

  const yVals: number[] = [];
  for (const d of data) {
    yVals.push(proj(d));
    const a = act(d);
    if (a != null) yVals.push(a);
  }
  const yMin = Math.min(...yVals);
  const yMax = Math.max(...yVals);
  const yPad = Math.max((yMax - yMin) * 0.12, 0.2);

  const x = d3
    .scalePoint<string>()
    .domain(data.map((d) => d.label))
    .range([margin.left, width - margin.right])
    .padding(0.45);

  const y = d3
    .scaleLinear()
    .domain([yMin - yPad, yMax + yPad])
    .nice()
    .range([height - margin.bottom, margin.top]);

  svg
    .append("g")
    .attr("transform", `translate(0,${height - margin.bottom})`)
    .call(
      d3
        .axisBottom(x)
        .tickSize(0)
        .tickPadding(10),
    )
    .call((g) => g.select(".domain").attr("stroke", "#ddd1c4"))
    .call((g) =>
      g
        .selectAll("text")
        .attr("fill", "#6b5b4d")
        .style("font-size", "11px"),
    );

  svg
    .append("g")
    .attr("transform", `translate(${margin.left},0)`)
    .call(d3.axisLeft(y).ticks(5).tickFormat((v) => d3.format(".1f")(v as number)))
    .call((g) => g.select(".domain").remove())
    .call((g) =>
      g
        .selectAll(".tick line")
        .attr("x2", width - margin.left - margin.right)
        .attr("stroke", "#f0e8df")
        .attr("stroke-opacity", 0.9),
    )
    .call((g) =>
      g
        .selectAll("text")
        .attr("fill", "#6b5b4d")
        .style("font-size", "10px"),
    );

  const lineProj = d3
    .line<MonthlyRunRatePoint>()
    .x((d) => x(d.label)!)
    .y((d) => y(proj(d)));

  const lineAct = d3
    .line<MonthlyRunRatePoint>()
    .defined((d) => act(d) != null)
    .x((d) => x(d.label)!)
    .y((d) => y(act(d)!));

  svg
    .append("path")
    .datum(data)
    .attr("fill", "none")
    .attr("stroke", "#9a8b7c")
    .attr("stroke-width", 2)
    .attr("stroke-dasharray", "6,4")
    .attr("d", lineProj);

  svg
    .append("path")
    .datum(data)
    .attr("fill", "none")
    .attr("stroke", accent)
    .attr("stroke-width", 2.5)
    .attr("d", lineAct);

  data.forEach((d) => {
    const cx = x(d.label)!;
    svg
      .append("circle")
      .attr("cx", cx)
      .attr("cy", y(proj(d)))
      .attr("r", 4)
      .attr("fill", "#fffaf4")
      .attr("stroke", "#9a8b7c")
      .attr("stroke-width", 2);
    const av = act(d);
    if (av != null) {
      svg.append("circle").attr("cx", cx).attr("cy", y(av)).attr("r", 5).attr("fill", accent).attr("stroke", "#fffaf4").attr("stroke-width", 2);
    }
  });

  const legY = height - 14;
  svg.append("line").attr("x1", margin.left).attr("x2", margin.left + 18).attr("y1", legY - 3).attr("y2", legY - 3).attr("stroke", "#9a8b7c").attr("stroke-width", 2).attr("stroke-dasharray", "6,4");
  svg
    .append("text")
    .attr("x", margin.left + 24)
    .attr("y", legY)
    .attr("fill", "#6b5b4d")
    .style("font-size", "10px")
    .style("font-weight", "500")
    .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
    .text("Projected (month start)");

  svg.append("line").attr("x1", margin.left + 168).attr("x2", margin.left + 186).attr("y1", legY - 3).attr("y2", legY - 3).attr("stroke", accent).attr("stroke-width", 2.5);
  svg
    .append("text")
    .attr("x", margin.left + 192)
    .attr("y", legY)
    .attr("fill", "#6b5b4d")
    .style("font-size", "10px")
    .style("font-weight", "500")
    .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
    .text("Actual (season-to-date)");
}

export function TeamRatingCharts({ monthly, team }: Props) {
  const offenseRef = useRef<SVGSVGElement | null>(null);
  const defenseRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    if (offenseRef.current) {
      drawMonthlyChart(d3.select(offenseRef.current), monthly, team, "scored");
    }
    if (defenseRef.current) {
      drawMonthlyChart(d3.select(defenseRef.current), monthly, team, "allowed");
    }
  }, [monthly, team]);

  return (
    <div className="rating-charts">
      <div className="rating-chart">
        <svg
          ref={offenseRef}
          className="chart-svg"
          role="img"
          aria-label="Runs scored by month: projected versus actual"
        />
      </div>
      <div className="rating-chart">
        <svg
          ref={defenseRef}
          className="chart-svg"
          role="img"
          aria-label="Runs allowed by month: projected versus actual"
        />
      </div>
    </div>
  );
}
