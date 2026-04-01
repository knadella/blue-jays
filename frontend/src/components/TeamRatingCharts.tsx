import { useEffect, useRef } from "react";
import * as d3 from "d3";

import type { TeamRatingVsActual } from "../api";
import { getTeamAbbrev, getTeamColor } from "../teamMetadata";

interface Props {
  comparison: TeamRatingVsActual;
  team: string;
}

function abbrev(team: string): string {
  return getTeamAbbrev(team);
}

interface Marker {
  value: number;
  label: string;
  fill: string;
  r: number;
}

function drawComparisonStrip(
  svg: d3.Selection<SVGSVGElement, unknown, null, undefined>,
  params: {
    title: string;
    projected: number;
    actual: number | null;
    team: string;
    higherIsBetter: boolean;
  },
) {
  const { title, projected, actual, team, higherIsBetter } = params;
  const accent = getTeamColor(team);
  const width = 520;
  const height = 208;
  const margin = { top: 44, right: 24, bottom: 58, left: 24 };

  svg.selectAll("*").remove();
  svg.attr("viewBox", `0 0 ${width} ${height}`);

  const subtitle =
    actual != null
      ? `${abbrev(team)}: model projection vs games played to date`
      : `${abbrev(team)}: no completed games yet — projection only`;

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

  const markers: Marker[] = [
    { value: projected, label: "Projected", fill: "#9a8b7c", r: 6 },
  ];
  if (actual != null) {
    markers.push({ value: actual, label: "Actual", fill: accent, r: 7 });
  }

  const values = markers.map((m) => m.value);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (hi - lo < 0.25) {
    const mid = (lo + hi) / 2;
    lo = mid - 0.35;
    hi = mid + 0.35;
  } else {
    const pad = (hi - lo) * 0.18;
    lo -= pad;
    hi += pad;
  }

  const x = d3.scaleLinear().domain([lo, hi]).range([margin.left, width - margin.right]);

  const axisY = height - margin.bottom + 8;
  const centerY = margin.top + (axisY - margin.top) / 2 + 2;

  svg
    .append("g")
    .attr("transform", `translate(0,${axisY})`)
    .call(
      d3
        .axisBottom(x)
        .ticks(5)
        .tickFormat((d) => d3.format(".1f")(d as number)),
    )
    .call((g) => g.select(".domain").attr("stroke", "#ddd1c4"))
    .call((g) =>
      g
        .selectAll(".tick line")
        .attr("stroke", "#e8dfd6")
        .attr("stroke-opacity", 0.9),
    )
    .call((g) =>
      g
        .selectAll("text")
        .attr("fill", "#6b5b4d")
        .style("font-size", "11px"),
    );

  const cys = markers.map(() => centerY);
  if (markers.length === 2) {
    const cx0 = x(markers[0].value);
    const cx1 = x(markers[1].value);
    if (Math.abs(cx0 - cx1) < 18) {
      cys[0] = centerY - 12;
      cys[1] = centerY + 12;
    }
  }

  const projectedMarker = markers.find((m) => m.label === "Projected")!;

  markers.forEach((m, i) => {
    const cx = x(m.value);
    const cy = cys[i];

    svg
      .append("line")
      .attr("x1", cx)
      .attr("x2", cx)
      .attr("y1", axisY)
      .attr("y2", cy + m.r)
      .attr("stroke", m.fill)
      .attr("stroke-opacity", 0.35)
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", "3,2");

    svg
      .append("circle")
      .attr("cx", cx)
      .attr("cy", cy)
      .attr("r", m.r)
      .attr("fill", m.fill)
      .attr("stroke", "#fffaf4")
      .attr("stroke-width", 2);

    svg
      .append("text")
      .attr("x", cx)
      .attr("y", cy - m.r - 6)
      .attr("text-anchor", "middle")
      .attr("fill", m.fill)
      .style("font-size", "10px")
      .style("font-weight", "700")
      .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
      .text(m.label);

    svg
      .append("text")
      .attr("x", cx)
      .attr("y", cy + m.r + 14)
      .attr("text-anchor", "middle")
      .attr("fill", "#1d1d1d")
      .style("font-size", "12px")
      .style("font-weight", "700")
      .style("font-family", "Georgia, 'Times New Roman', serif")
      .text(m.value.toFixed(2));

    if (m.label === "Actual" && markers.length === 2) {
      const delta = m.value - projectedMarker.value;
      const sign = delta > 0 ? "+" : "";
      const good = higherIsBetter ? delta >= 0 : delta <= 0;
      svg
        .append("text")
        .attr("x", cx)
        .attr("y", cy + m.r + 30)
        .attr("text-anchor", "middle")
        .attr("fill", good ? "#2d6a4f" : "#9b2226")
        .style("font-size", "10px")
        .style("font-weight", "600")
        .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
        .text(`${sign}${delta.toFixed(2)} vs proj.`);
    }
  });

  const legY = height - 10;
  svg.append("circle").attr("cx", margin.left + 6).attr("cy", legY - 3).attr("r", 4).attr("fill", "#9a8b7c");
  svg
    .append("text")
    .attr("x", margin.left + 16)
    .attr("y", legY)
    .attr("fill", "#6b5b4d")
    .style("font-size", "10px")
    .style("font-weight", "500")
    .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
    .text("Projected = model estimate (runs / game)");

  if (actual != null) {
    svg.append("circle").attr("cx", margin.left + 248).attr("cy", legY - 3).attr("r", 4).attr("fill", accent);
    svg
      .append("text")
      .attr("x", margin.left + 258)
      .attr("y", legY)
      .attr("fill", "#6b5b4d")
      .style("font-size", "10px")
      .style("font-weight", "500")
      .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
      .text("Actual = season to date");
  }
}

export function TeamRatingCharts({ comparison, team }: Props) {
  const offenseRef = useRef<SVGSVGElement | null>(null);
  const defenseRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    if (offenseRef.current) {
      drawComparisonStrip(d3.select(offenseRef.current), {
        title: "Runs scored / game",
        projected: comparison.runs_scored_per_game_projected,
        actual: comparison.runs_scored_per_game_actual,
        team,
        higherIsBetter: true,
      });
    }
    if (defenseRef.current) {
      drawComparisonStrip(d3.select(defenseRef.current), {
        title: "Runs allowed / game",
        projected: comparison.runs_allowed_per_game_projected,
        actual: comparison.runs_allowed_per_game_actual,
        team,
        higherIsBetter: false,
      });
    }
  }, [comparison, team]);

  return (
    <div className="rating-charts">
      <div className="rating-chart">
        <svg
          ref={offenseRef}
          className="chart-svg"
          role="img"
          aria-label="Runs scored: actual versus projected"
        />
      </div>
      <div className="rating-chart">
        <svg
          ref={defenseRef}
          className="chart-svg"
          role="img"
          aria-label="Runs allowed: actual versus projected"
        />
      </div>
    </div>
  );
}
