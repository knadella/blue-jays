import { useEffect, useRef } from "react";
import * as d3 from "d3";

import type { TeamRating } from "../api";
import { getTeamAbbrev, getTeamColor, getTeamLogoPath } from "../teamMetadata";

interface Props {
  offense: TeamRating[];
  defense: TeamRating[];
  team: string;
}

function abbrev(team: string): string {
  return getTeamAbbrev(team);
}

function accentFor(team: string): string {
  return getTeamColor(team);
}

interface PlacedDot {
  team: string;
  value: number;
  cx: number;
  cy: number;
}

function resolvePositions(
  ratings: TeamRating[],
  x: d3.ScaleLinear<number, number>,
  centerY: number,
  rowHeight: number,
  minXGap: number,
): PlacedDot[] {
  const sorted = [...ratings].sort((a, b) => a.value - b.value);
  const rows: number[] = [];

  const placed = sorted.map((r) => {
    const cx = x(r.value);
    let row = 0;
    while (row < rows.length && cx - rows[row] < minXGap) {
      row++;
    }
    if (row >= rows.length) rows.push(-Infinity);
    rows[row] = cx;
    return { team: r.team, value: r.value, cx, row };
  });

  const totalRows = rows.length;
  return placed.map((p) => ({
    team: p.team,
    value: p.value,
    cx: p.cx,
    cy: centerY + (p.row - (totalRows - 1) / 2) * rowHeight,
  }));
}

function drawStrip(
  svg: d3.Selection<SVGSVGElement, unknown, null, undefined>,
  ratings: TeamRating[],
  selectedTeam: string,
  title: string,
  subtitle: string,
) {
  const width = 520;
  const height = 180;
  const margin = { top: 48, right: 24, bottom: 32, left: 24 };
  const plotW = width - margin.left - margin.right;

  svg.selectAll("*").remove();
  svg.attr("viewBox", `0 0 ${width} ${height}`);

  const values = ratings.map((r) => r.value);
  const extent = d3.extent(values) as [number, number];
  const pad = (extent[1] - extent[0]) * 0.12;

  const x = d3
    .scaleLinear()
    .domain([extent[0] - pad, extent[1] + pad])
    .range([margin.left, width - margin.right]);

  const stripCenterY = (margin.top + height - margin.bottom) / 2 + 4;
  const dots = resolvePositions(ratings, x, stripCenterY, 14, 12);
  const avg = d3.mean(values) ?? 0;
  const accent = accentFor(selectedTeam);

  svg
    .append("text")
    .attr("x", margin.left)
    .attr("y", 20)
    .attr("fill", "#1d1d1d")
    .style("font-size", "14px")
    .style("font-weight", "600")
    .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
    .text(title);

  svg
    .append("text")
    .attr("x", margin.left)
    .attr("y", 36)
    .attr("fill", "#9a8b7c")
    .style("font-size", "11px")
    .style("font-weight", "500")
    .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
    .text(subtitle);

  svg
    .append("g")
    .attr("transform", `translate(0,${height - margin.bottom})`)
    .call(
      d3
        .axisBottom(x)
        .ticks(6)
        .tickSize(-(height - margin.top - margin.bottom))
        .tickFormat((d) => d3.format(".1f")(d as number)),
    )
    .call((g) =>
      g
        .selectAll("line")
        .attr("stroke", "#ddd1c4")
        .attr("stroke-opacity", 0.5),
    )
    .call((g) => g.select(".domain").remove())
    .call((g) =>
      g
        .selectAll("text")
        .attr("fill", "#6b5b4d")
        .style("font-size", "11px"),
    );

  svg
    .append("line")
    .attr("x1", x(avg))
    .attr("x2", x(avg))
    .attr("y1", margin.top)
    .attr("y2", height - margin.bottom)
    .attr("stroke", "#8a7a6a")
    .attr("stroke-width", 1.5)
    .attr("stroke-dasharray", "4,3");

  svg
    .append("text")
    .attr("x", x(avg))
    .attr("y", margin.top - 4)
    .attr("text-anchor", "middle")
    .attr("fill", "#8a7a6a")
    .style("font-size", "9px")
    .style("font-weight", "600")
    .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
    .text("AVG");

  const others = dots.filter((d) => d.team !== selectedTeam);
  const selected = dots.find((d) => d.team === selectedTeam);

  others.forEach((d) => {
    svg
      .append("circle")
      .attr("cx", d.cx)
      .attr("cy", d.cy)
      .attr("r", 4)
      .attr("fill", "#c9b9aa")
      .attr("opacity", 0.7);
  });

  if (selected) {
    const teamLogoPath = getTeamLogoPath(selectedTeam);

    svg
      .append("circle")
      .attr("cx", selected.cx)
      .attr("cy", selected.cy)
      .attr("r", 7)
      .attr("fill", accent)
      .attr("stroke", "#ffffff")
      .attr("stroke-width", 2);

    if (teamLogoPath) {
      svg
        .append("image")
        .attr("href", teamLogoPath)
        .attr("x", selected.cx - 10)
        .attr("y", selected.cy - 30)
        .attr("width", 20)
        .attr("height", 20)
        .attr("preserveAspectRatio", "xMidYMid meet");
    } else {
      const labelY = selected.cy - 14;
      svg
        .append("text")
        .attr("x", selected.cx)
        .attr("y", labelY)
        .attr("text-anchor", "middle")
        .attr("fill", accent)
        .style("font-size", "10px")
        .style("font-weight", "700")
        .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
        .text(abbrev(selectedTeam));
    }

    const valueY = selected.cy + 18;
    svg
      .append("text")
      .attr("x", selected.cx)
      .attr("y", valueY)
      .attr("text-anchor", "middle")
      .attr("fill", "#1d1d1d")
      .style("font-size", "11px")
      .style("font-weight", "700")
      .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
      .text(selected.value.toFixed(1));
  }
}

export function TeamRatingCharts({ offense, defense, team }: Props) {
  const offenseRef = useRef<SVGSVGElement | null>(null);
  const defenseRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    if (offenseRef.current) {
      const selectedRating = offense.find((r) => r.team === team);
      const sub = selectedRating
        ? `${abbrev(team)} scores ${selectedRating.value.toFixed(1)} runs / game`
        : "";
      drawStrip(
        d3.select(offenseRef.current),
        offense,
        team,
        "Runs Scored / Game",
        sub,
      );
    }
    if (defenseRef.current) {
      const selectedRating = defense.find((r) => r.team === team);
      const sub = selectedRating
        ? `${abbrev(team)} allows ${selectedRating.value.toFixed(1)} runs / game`
        : "";
      drawStrip(
        d3.select(defenseRef.current),
        defense,
        team,
        "Runs Allowed / Game",
        sub,
      );
    }
  }, [offense, defense, team]);

  return (
    <div className="rating-charts">
      <div className="rating-chart">
        <svg
          ref={offenseRef}
          className="chart-svg"
          role="img"
          aria-label="Offense rating relative to league"
        />
      </div>
      <div className="rating-chart">
        <svg
          ref={defenseRef}
          className="chart-svg"
          role="img"
          aria-label="Defense rating relative to league"
        />
      </div>
    </div>
  );
}
