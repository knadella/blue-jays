import { useEffect, useRef } from "react";
import * as d3 from "d3";

import type { ScheduleGame } from "../api";
import { getTeamAbbrev, getTeamColor } from "../teamMetadata";

interface Props {
  schedule: ScheduleGame[];
  team: string;
  season: number;
}

function abbrev(team: string): string {
  return getTeamAbbrev(team);
}

interface Series {
  opponent: string;
  startDate: Date;
  games: ScheduleGame[];
  avgStrength: number;
  isHome: boolean;
}

function groupIntoSeries(schedule: ScheduleGame[]): Series[] {
  if (schedule.length === 0) return [];

  const series: Series[] = [];
  let current: ScheduleGame[] = [schedule[0]];

  for (let i = 1; i < schedule.length; i++) {
    const prev = schedule[i - 1];
    const curr = schedule[i];
    const prevDate = new Date(prev.date);
    const currDate = new Date(curr.date);
    const dayGap = (currDate.getTime() - prevDate.getTime()) / 86_400_000;

    if (curr.opponent === prev.opponent && curr.is_home === prev.is_home && dayGap <= 2) {
      current.push(curr);
    } else {
      series.push({
        opponent: current[0].opponent,
        startDate: new Date(current[0].date),
        games: current,
        avgStrength: d3.mean(current, (g) => g.opponent_strength) ?? 0,
        isHome: current[0].is_home,
      });
      current = [curr];
    }
  }

  series.push({
    opponent: current[0].opponent,
    startDate: new Date(current[0].date),
    games: current,
    avgStrength: d3.mean(current, (g) => g.opponent_strength) ?? 0,
    isHome: current[0].is_home,
  });

  return series;
}

export function ScheduleHeatmap({ schedule, team, season }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    if (!svgRef.current || schedule.length === 0) return;

    const seriesList = groupIntoSeries(schedule);
    const accent = getTeamColor(team);

    const width = 1120;
    const height = 140;
    const margin = { top: 8, right: 20, bottom: 28, left: 20 };
    const plotW = width - margin.left - margin.right;
    const rowH = height - margin.top - margin.bottom;
    const blockH = rowH - 16;

    const firstDate = new Date(`${season}-03-20`);
    const lastDate = new Date(`${season}-10-05`);

    const x = d3
      .scaleTime()
      .domain([firstDate, lastDate])
      .range([margin.left, width - margin.right]);

    const color = d3
      .scaleSequential(d3.interpolateRdYlGn)
      .domain([1, 0]);

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    svg.attr("viewBox", `0 0 ${width} ${height}`);

    const monthTicks = d3.timeMonth.range(
      new Date(`${season}-04-01`),
      new Date(`${season}-10-01`),
    );
    const monthFmt = d3.timeFormat("%b");

    svg
      .append("g")
      .attr("transform", `translate(0,${height - margin.bottom + 4})`)
      .call(
        d3
          .axisBottom<Date>(x)
          .tickValues(monthTicks)
          .tickSize(0)
          .tickFormat((d) => monthFmt(d as Date)),
      )
      .call((g) => g.select(".domain").remove())
      .call((g) =>
        g
          .selectAll("text")
          .attr("fill", "#6b5b4d")
          .style("font-size", "11px"),
      );

    monthTicks.forEach((tick) => {
      svg
        .append("line")
        .attr("x1", x(tick))
        .attr("x2", x(tick))
        .attr("y1", margin.top)
        .attr("y2", height - margin.bottom)
        .attr("stroke", "#e0d5c9")
        .attr("stroke-opacity", 0.5)
        .attr("stroke-dasharray", "3,3");
    });

    const blockY = margin.top + 8;

    seriesList.forEach((s) => {
      const lastGame = s.games[s.games.length - 1];
      const endDate = new Date(lastGame.date);
      endDate.setDate(endDate.getDate() + 1);

      const bx = x(s.startDate);
      const bw = Math.max(x(endDate) - bx - 1.5, 4);
      const fill = color(s.avgStrength);

      svg
        .append("rect")
        .attr("x", bx)
        .attr("y", blockY)
        .attr("width", bw)
        .attr("height", blockH)
        .attr("rx", 3)
        .attr("fill", fill)
        .attr("stroke", "#fffaf4")
        .attr("stroke-width", 1);

      if (bw > 22) {
        svg
          .append("text")
          .attr("x", bx + bw / 2)
          .attr("y", blockY + blockH / 2)
          .attr("text-anchor", "middle")
          .attr("dominant-baseline", "central")
          .attr("fill", s.avgStrength > 0.65 ? "#fff" : "#1d1d1d")
          .style("font-size", bw > 36 ? "9px" : "7.5px")
          .style("font-weight", "700")
          .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
          .text(abbrev(s.opponent));
      }

      if (bw > 36) {
        svg
          .append("text")
          .attr("x", bx + bw / 2)
          .attr("y", blockY + blockH - 5)
          .attr("text-anchor", "middle")
          .attr("fill", s.avgStrength > 0.65 ? "rgba(255,255,255,0.7)" : "rgba(0,0,0,0.35)")
          .style("font-size", "7px")
          .style("font-weight", "500")
          .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
          .text(s.isHome ? "HOME" : "AWAY");
      }
    });

    const legendW = 120;
    const legendH = 8;
    const legendX = width - margin.right - legendW;
    const legendY = margin.top - 2;

    const defs = svg.append("defs");
    const gradId = "sos-gradient";
    const grad = defs.append("linearGradient").attr("id", gradId);
    grad.append("stop").attr("offset", "0%").attr("stop-color", color(0));
    grad.append("stop").attr("offset", "50%").attr("stop-color", color(0.5));
    grad.append("stop").attr("offset", "100%").attr("stop-color", color(1));

    svg
      .append("rect")
      .attr("x", legendX)
      .attr("y", legendY)
      .attr("width", legendW)
      .attr("height", legendH)
      .attr("rx", 4)
      .attr("fill", `url(#${gradId})`);

    svg
      .append("text")
      .attr("x", legendX - 4)
      .attr("y", legendY + legendH / 2)
      .attr("text-anchor", "end")
      .attr("dominant-baseline", "central")
      .attr("fill", "#9a8b7c")
      .style("font-size", "8px")
      .style("font-weight", "600")
      .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
      .text("EASY");

    svg
      .append("text")
      .attr("x", legendX + legendW + 4)
      .attr("y", legendY + legendH / 2)
      .attr("dominant-baseline", "central")
      .attr("fill", "#9a8b7c")
      .style("font-size", "8px")
      .style("font-weight", "600")
      .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
      .text("TOUGH");
  }, [schedule, team, season]);

  return (
    <svg
      ref={svgRef}
      className="chart-svg"
      role="img"
      aria-label="Remaining schedule strength heatmap"
    />
  );
}
