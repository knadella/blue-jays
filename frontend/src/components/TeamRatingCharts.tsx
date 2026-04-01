import { useEffect, useRef } from "react";
import * as d3 from "d3";

import type { MonthlyRunRatePoint, TeamRatingVsActual } from "../api";
import { getTeamAbbrev, getTeamColor } from "../teamMetadata";

interface Props {
  monthly: MonthlyRunRatePoint[];
  team: string;
  teamVsActual: TeamRatingVsActual;
  leagueActualScored: number | null;
  leagueActualAllowed: number | null;
}

function abbrev(team: string): string {
  return getTeamAbbrev(team);
}

function drawMonthlyChart(
  svg: d3.Selection<SVGSVGElement, unknown, null, undefined>,
  data: MonthlyRunRatePoint[],
  team: string,
  teamVsActual: TeamRatingVsActual,
  leagueYtd: number | null,
  mode: "scored" | "allowed",
) {
  const accent = getTeamColor(team);
  const width = 520;
  const height = 292;
  const margin = { top: 44, right: 20, bottom: 72, left: 34 };

  svg.selectAll("*").remove();
  svg.attr("viewBox", `0 0 ${width} ${height}`);

  const title = mode === "scored" ? "Runs scored / game" : "Runs allowed / game";
  const subtitle =
    "Monthly projections (team vs league); horizontal lines = season-to-date actuals";

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
    .text(`${abbrev(team)} · ${subtitle}`);

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

  const projTeam = (d: MonthlyRunRatePoint) =>
    mode === "scored" ? d.runs_scored_projected : d.runs_allowed_projected;
  const projLeague = (d: MonthlyRunRatePoint) =>
    mode === "scored" ? d.league_runs_scored_projected : d.league_runs_allowed_projected;

  const teamYtd =
    mode === "scored" ? teamVsActual.runs_scored_per_game_actual : teamVsActual.runs_allowed_per_game_actual;

  const yVals: number[] = [];
  for (const d of data) {
    yVals.push(projTeam(d), projLeague(d));
  }
  if (teamYtd != null) yVals.push(teamYtd);
  if (leagueYtd != null) yVals.push(leagueYtd);

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

  const x1 = margin.left;
  const x2 = width - margin.right;

  if (leagueYtd != null) {
    svg
      .append("line")
      .attr("x1", x1)
      .attr("x2", x2)
      .attr("y1", y(leagueYtd))
      .attr("y2", y(leagueYtd))
      .attr("stroke", "#8b7355")
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", "5,4")
      .attr("opacity", 0.85);
  }

  if (teamYtd != null) {
    svg
      .append("line")
      .attr("x1", x1)
      .attr("x2", x2)
      .attr("y1", y(teamYtd))
      .attr("y2", y(teamYtd))
      .attr("stroke", accent)
      .attr("stroke-width", 2.25)
      .attr("opacity", 0.95);
  }

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

  const lineLeague = d3
    .line<MonthlyRunRatePoint>()
    .x((d) => x(d.label)!)
    .y((d) => y(projLeague(d)));

  const lineTeam = d3
    .line<MonthlyRunRatePoint>()
    .x((d) => x(d.label)!)
    .y((d) => y(projTeam(d)));

  svg
    .append("path")
    .datum(data)
    .attr("fill", "none")
    .attr("stroke", "#b5a090")
    .attr("stroke-width", 2)
    .attr("stroke-dasharray", "2,3")
    .attr("d", lineLeague);

  svg
    .append("path")
    .datum(data)
    .attr("fill", "none")
    .attr("stroke", accent)
    .attr("stroke-width", 2.5)
    .attr("stroke-dasharray", "7,4")
    .attr("d", lineTeam);

  data.forEach((d) => {
    const cx = x(d.label)!;
    svg
      .append("circle")
      .attr("cx", cx)
      .attr("cy", y(projLeague(d)))
      .attr("r", 3.5)
      .attr("fill", "#f2e8dc")
      .attr("stroke", "#9a8575")
      .attr("stroke-width", 1.5);
    svg
      .append("circle")
      .attr("cx", cx)
      .attr("cy", y(projTeam(d)))
      .attr("r", 4.5)
      .attr("fill", "#fffaf4")
      .attr("stroke", accent)
      .attr("stroke-width", 2);
  });

  const leg: [number, string][] = [
    [margin.left, "League proj. (month start)"],
    [margin.left + 200, `${abbrev(team)} proj.`],
    [margin.left, "League actual YTD"],
    [margin.left + 200, `${abbrev(team)} actual YTD`],
  ];
  const legY0 = height - 58;
  svg
    .append("line")
    .attr("x1", leg[0][0])
    .attr("x2", leg[0][0] + 16)
    .attr("y1", legY0 - 2)
    .attr("y2", legY0 - 2)
    .attr("stroke", "#b5a090")
    .attr("stroke-width", 2)
    .attr("stroke-dasharray", "2,3");
  svg
    .append("text")
    .attr("x", leg[0][0] + 22)
    .attr("y", legY0)
    .attr("fill", "#6b5b4d")
    .style("font-size", "9px")
    .style("font-weight", "500")
    .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
    .text(leg[0][1]);

  svg
    .append("line")
    .attr("x1", leg[1][0])
    .attr("x2", leg[1][0] + 16)
    .attr("y1", legY0 - 2)
    .attr("y2", legY0 - 2)
    .attr("stroke", accent)
    .attr("stroke-width", 2.5)
    .attr("stroke-dasharray", "7,4");
  svg
    .append("text")
    .attr("x", leg[1][0] + 22)
    .attr("y", legY0)
    .attr("fill", "#6b5b4d")
    .style("font-size", "9px")
    .style("font-weight", "500")
    .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
    .text(leg[1][1]);

  const legY1 = height - 38;
  svg
    .append("line")
    .attr("x1", leg[2][0])
    .attr("x2", leg[2][0] + 18)
    .attr("y1", legY1 - 2)
    .attr("y2", legY1 - 2)
    .attr("stroke", "#8b7355")
    .attr("stroke-width", 1.5)
    .attr("stroke-dasharray", "5,4");
  svg
    .append("text")
    .attr("x", leg[2][0] + 24)
    .attr("y", legY1)
    .attr("fill", "#6b5b4d")
    .style("font-size", "9px")
    .style("font-weight", "500")
    .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
    .text(leg[2][1]);

  svg
    .append("line")
    .attr("x1", leg[3][0])
    .attr("x2", leg[3][0] + 18)
    .attr("y1", legY1 - 2)
    .attr("y2", legY1 - 2)
    .attr("stroke", accent)
    .attr("stroke-width", 2.25);
  svg
    .append("text")
    .attr("x", leg[3][0] + 24)
    .attr("y", legY1)
    .attr("fill", "#6b5b4d")
    .style("font-size", "9px")
    .style("font-weight", "500")
    .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
    .text(leg[3][1]);
}

export function TeamRatingCharts({
  monthly,
  team,
  teamVsActual,
  leagueActualScored,
  leagueActualAllowed,
}: Props) {
  const offenseRef = useRef<SVGSVGElement | null>(null);
  const defenseRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    if (offenseRef.current) {
      drawMonthlyChart(
        d3.select(offenseRef.current),
        monthly,
        team,
        teamVsActual,
        leagueActualScored,
        "scored",
      );
    }
    if (defenseRef.current) {
      drawMonthlyChart(
        d3.select(defenseRef.current),
        monthly,
        team,
        teamVsActual,
        leagueActualAllowed,
        "allowed",
      );
    }
  }, [monthly, team, teamVsActual, leagueActualScored, leagueActualAllowed]);

  return (
    <div className="rating-charts">
      <div className="rating-chart">
        <svg
          ref={offenseRef}
          className="chart-svg"
          role="img"
          aria-label="Runs scored: monthly projections and season-to-date actuals"
        />
      </div>
      <div className="rating-chart">
        <svg
          ref={defenseRef}
          className="chart-svg"
          role="img"
          aria-label="Runs allowed: monthly projections and season-to-date actuals"
        />
      </div>
    </div>
  );
}
