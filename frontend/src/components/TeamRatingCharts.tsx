import { useEffect, useRef } from "react";
import * as d3 from "d3";

import type { MonthlyRunRatePoint } from "../api";
import { getTeamAbbrev, getTeamColor } from "../teamMetadata";

interface Props {
  monthly: MonthlyRunRatePoint[];
  team: string;
}

const FONT = "'Inter', -apple-system, system-ui, sans-serif";
const LEAGUE_COLOR = "#9a8b7c";

interface LineDef {
  key: string;
  color: string;
  dash: string;
  width: number;
  dotR: number;
  dotFill: (c: string) => string;
  dotStroke: (c: string) => string;
  val: (d: MonthlyRunRatePoint) => number | null;
  legendLabel: string;
}

function makeLineDefs(
  accent: string,
  teamAbbr: string,
  mode: "scored" | "allowed",
): LineDef[] {
  return [
    {
      key: "league-proj",
      color: LEAGUE_COLOR,
      dash: "3,3",
      width: 1.5,
      dotR: 3,
      dotFill: () => "#f5ede3",
      dotStroke: () => LEAGUE_COLOR,
      val: (d) => (mode === "scored" ? d.league_runs_scored_projected : d.league_runs_allowed_projected),
      legendLabel: "League proj.",
    },
    {
      key: "league-actual",
      color: LEAGUE_COLOR,
      dash: "",
      width: 2,
      dotR: 3.5,
      dotFill: () => LEAGUE_COLOR,
      dotStroke: () => "#fffaf4",
      val: (d) => (mode === "scored" ? d.league_runs_scored_actual : d.league_runs_allowed_actual),
      legendLabel: "League actual",
    },
    {
      key: "team-proj",
      color: accent,
      dash: "6,4",
      width: 2,
      dotR: 4,
      dotFill: () => "#fffaf4",
      dotStroke: () => accent,
      val: (d) => (mode === "scored" ? d.runs_scored_projected : d.runs_allowed_projected),
      legendLabel: `${teamAbbr} proj.`,
    },
    {
      key: "team-actual",
      color: accent,
      dash: "",
      width: 2.5,
      dotR: 5,
      dotFill: () => accent,
      dotStroke: () => "#fffaf4",
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
  const height = 280;
  const margin = { top: 44, right: 20, bottom: 56, left: 42 };

  svg.selectAll("*").remove();
  svg.attr("viewBox", `0 0 ${width} ${height}`);

  const title = mode === "scored" ? "Runs scored / game" : "Runs allowed / game";

  svg
    .append("text")
    .attr("x", margin.left)
    .attr("y", 18)
    .attr("fill", "#1d1d1d")
    .style("font-size", "14px")
    .style("font-weight", "600")
    .style("font-family", FONT)
    .text(title);

  svg
    .append("text")
    .attr("x", margin.left)
    .attr("y", 34)
    .attr("fill", "#9a8b7c")
    .style("font-size", "10.5px")
    .style("font-weight", "500")
    .style("font-family", FONT)
    .text(`${teamAbbr} vs league · projection and actual per month`);

  if (data.length === 0) {
    svg
      .append("text")
      .attr("x", width / 2)
      .attr("y", height / 2)
      .attr("text-anchor", "middle")
      .attr("fill", "#9a8b7c")
      .style("font-size", "13px")
      .style("font-family", FONT)
      .text("No monthly data yet.");
    return;
  }

  const lines = makeLineDefs(accent, teamAbbr, mode);

  const yVals: number[] = [];
  for (const d of data) {
    for (const l of lines) {
      const v = l.val(d);
      if (v != null) yVals.push(v);
    }
  }
  const yMin = Math.min(...yVals);
  const yMax = Math.max(...yVals);
  const yPad = Math.max((yMax - yMin) * 0.18, 0.25);

  const x = d3
    .scalePoint<string>()
    .domain(data.map((d) => d.label))
    .range([margin.left, width - margin.right])
    .padding(0.3);

  const y = d3
    .scaleLinear()
    .domain([yMin - yPad, yMax + yPad])
    .nice()
    .range([height - margin.bottom, margin.top]);

  // axes
  svg
    .append("g")
    .attr("transform", `translate(0,${height - margin.bottom})`)
    .call(d3.axisBottom(x).tickSize(0).tickPadding(8))
    .call((g) => g.select(".domain").attr("stroke", "#ddd1c4"))
    .call((g) =>
      g.selectAll("text").attr("fill", "#6b5b4d").style("font-size", "11px").style("font-weight", "600"),
    );

  svg
    .append("g")
    .attr("transform", `translate(${margin.left},0)`)
    .call(d3.axisLeft(y).ticks(5).tickFormat((v) => d3.format(".2f")(v as number)))
    .call((g) => g.select(".domain").remove())
    .call((g) =>
      g
        .selectAll(".tick line")
        .attr("x2", width - margin.left - margin.right)
        .attr("stroke", "#f0e8df")
        .attr("stroke-opacity", 0.9),
    )
    .call((g) => g.selectAll("text").attr("fill", "#6b5b4d").style("font-size", "10px"));

  // draw each line + dots
  for (const l of lines) {
    const lineGen = d3
      .line<MonthlyRunRatePoint>()
      .defined((d) => l.val(d) != null)
      .x((d) => x(d.label)!)
      .y((d) => y(l.val(d)!));

    svg
      .append("path")
      .datum(data)
      .attr("fill", "none")
      .attr("stroke", l.color)
      .attr("stroke-width", l.width)
      .attr("stroke-dasharray", l.dash)
      .attr("d", lineGen);

    data.forEach((d) => {
      const v = l.val(d);
      if (v == null) return;
      svg
        .append("circle")
        .attr("cx", x(d.label)!)
        .attr("cy", y(v))
        .attr("r", l.dotR)
        .attr("fill", l.dotFill(l.color))
        .attr("stroke", l.dotStroke(l.color))
        .attr("stroke-width", 1.8);
    });
  }

  // legend (2 × 2 grid below chart)
  const legStartY = height - 40;
  const col1 = margin.left;
  const col2 = margin.left + 180;
  const rowGap = 16;

  function drawLegItem(lx: number, ly: number, def: LineDef) {
    svg
      .append("line")
      .attr("x1", lx)
      .attr("x2", lx + 16)
      .attr("y1", ly - 2)
      .attr("y2", ly - 2)
      .attr("stroke", def.color)
      .attr("stroke-width", def.width)
      .attr("stroke-dasharray", def.dash);
    svg
      .append("circle")
      .attr("cx", lx + 8)
      .attr("cy", ly - 2)
      .attr("r", def.dotR * 0.7)
      .attr("fill", def.dotFill(def.color))
      .attr("stroke", def.dotStroke(def.color))
      .attr("stroke-width", 1.2);
    svg
      .append("text")
      .attr("x", lx + 22)
      .attr("y", ly)
      .attr("fill", "#6b5b4d")
      .style("font-size", "9px")
      .style("font-weight", "500")
      .style("font-family", FONT)
      .text(def.legendLabel);
  }

  drawLegItem(col1, legStartY, lines[0]);
  drawLegItem(col2, legStartY, lines[1]);
  drawLegItem(col1, legStartY + rowGap, lines[2]);
  drawLegItem(col2, legStartY + rowGap, lines[3]);
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
          aria-label="Runs scored: monthly projections and actuals"
        />
      </div>
      <div className="rating-chart">
        <svg
          ref={defenseRef}
          className="chart-svg"
          role="img"
          aria-label="Runs allowed: monthly projections and actuals"
        />
      </div>
    </div>
  );
}
