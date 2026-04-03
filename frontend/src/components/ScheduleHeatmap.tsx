import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";

import type { ScheduleGame } from "../api";
import { CHART, CHART_FONT } from "../chartTheme";
import { getTeamAbbrev, getTeamColor } from "../teamMetadata";

interface Props {
  schedule: ScheduleGame[];
  team: string;
  season: number;
  scheduleStrengthPlayed: number | null;
  scheduleStrengthRemaining: number | null;
}

const REDUCED_MOTION = typeof window !== "undefined"
  && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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

const SOS_CARD_W = 252;
const SOS_CARD_GAP = 16;

function appendSosMetricCard(
  root: d3.Selection<SVGSVGElement, unknown, null, undefined>,
  xPos: number,
  label: string,
  value: number | null,
  accent: string,
  delayMs: number,
) {
  const w = SOS_CARD_W;
  const h = 34;
  const g = root.append("g").attr("transform", `translate(${xPos}, 2)`);

  if (!REDUCED_MOTION) {
    g.attr("opacity", 0)
      .transition()
      .duration(500)
      .delay(delayMs)
      .ease(d3.easeCubicOut)
      .attr("opacity", 1);
  }

  g.append("rect")
    .attr("width", w)
    .attr("height", h)
    .attr("rx", 8)
    .attr("fill", CHART.cardFill)
    .attr("stroke", CHART.cardStroke);

  const text = g
    .append("text")
    .attr("x", 12)
    .attr("y", 22)
    .style("font-size", "13px")
    .style("font-family", CHART_FONT);

  text.append("tspan").attr("fill", CHART.inkMuted).style("font-weight", "600").text(`${label} `);
  text
    .append("tspan")
    .attr("fill", accent)
    .style("font-weight", "700")
    .text(value != null ? value.toFixed(1) : "—");
  text.append("tspan").attr("fill", CHART.inkMuted).style("font-weight", "600").text(" / 10");
}

function drawHeatmap(
  svgEl: SVGSVGElement,
  schedule: ScheduleGame[],
  team: string,
  season: number,
  scheduleStrengthPlayed: number | null,
  scheduleStrengthRemaining: number | null,
) {
  const accent = getTeamColor(team);
  const width = 1120;
  const chartOffsetY = 44;
  const chartHeight = 140;
  const height = chartHeight + chartOffsetY;

  const svg = d3.select(svgEl);
  svg.selectAll("*").remove();
  const viewW = width + 36;
  svg.attr("viewBox", `0 0 ${viewW} ${height}`);

  const sosRowW = SOS_CARD_W * 2 + SOS_CARD_GAP;
  const sosRowX = (width - sosRowW) / 2;
  appendSosMetricCard(svg, sosRowX, "SOS played", scheduleStrengthPlayed, accent, 0);
  appendSosMetricCard(
    svg,
    sosRowX + SOS_CARD_W + SOS_CARD_GAP,
    "SOS remaining",
    scheduleStrengthRemaining,
    accent,
    100,
  );

  const chart = svg.append("g").attr("transform", `translate(0,${chartOffsetY})`);

  if (schedule.length === 0) {
    chart
      .append("text")
      .attr("x", width / 2)
      .attr("y", chartHeight / 2)
      .attr("text-anchor", "middle")
      .attr("fill", CHART.legendMuted)
      .style("font-size", "14px")
      .style("font-family", CHART_FONT)
      .text("No games remaining — see SOS played above for the season so far.");
    return;
  }

  const seriesList = groupIntoSeries(schedule);

  const margin = { top: 8, right: 20, bottom: 28, left: 20 };
  const blockH = chartHeight - margin.top - margin.bottom - 16;

  const firstDate = new Date(`${season}-03-20`);
  const lastDate = new Date(`${season}-10-05`);

  const x = d3
    .scaleTime()
    .domain([firstDate, lastDate])
    .range([margin.left, width - margin.right]);

  const color = d3.scaleSequential(d3.interpolateRdYlGn).domain([1, 0]);

  const monthTicks = d3.timeMonth.range(
    new Date(`${season}-04-01`),
    new Date(`${season}-10-01`),
  );
  const monthFmt = d3.timeFormat("%b");

  chart
    .append("g")
    .attr("transform", `translate(0,${chartHeight - margin.bottom + 4})`)
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
        .attr("fill", CHART.inkMuted)
        .style("font-size", "11px"),
    );

  monthTicks.forEach((tick) => {
    chart
      .append("line")
      .attr("x1", x(tick))
      .attr("x2", x(tick))
      .attr("y1", margin.top)
      .attr("y2", chartHeight - margin.bottom)
      .attr("stroke", CHART.gridMajor)
      .attr("stroke-opacity", 0.45)
      .attr("stroke-dasharray", "3,3");
  });

  const blockY = margin.top + 8;

  seriesList.forEach((s, seriesIdx) => {
    const lastGame = s.games[s.games.length - 1];
    const endDate = new Date(lastGame.date);
    endDate.setDate(endDate.getDate() + 1);

    const bx = x(s.startDate);
    const bw = Math.max(x(endDate) - bx - 1.5, 4);
    const fill = color(s.avgStrength);
    const cascadeDelay = REDUCED_MOTION ? 0 : seriesIdx * 28 + 150;

    const blockRect = chart
      .append("rect")
      .attr("x", bx)
      .attr("y", blockY)
      .attr("width", bw)
      .attr("height", blockH)
      .attr("rx", 3)
      .attr("fill", fill)
      .attr("stroke", CHART.heatmapBlockStroke)
      .attr("stroke-width", 1);

    if (!REDUCED_MOTION) {
      blockRect
        .attr("opacity", 0)
        .attr("y", blockY + 10)
        .transition()
        .duration(350)
        .delay(cascadeDelay)
        .ease(d3.easeCubicOut)
        .attr("opacity", 1)
        .attr("y", blockY);
    }

    if (bw > 22) {
      const teamLabel = chart
        .append("text")
        .attr("x", bx + bw / 2)
        .attr("y", blockY + blockH / 2)
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "central")
        .attr("fill", s.avgStrength > 0.65 ? "#fff" : CHART.inkDark)
        .style("font-size", bw > 36 ? "9px" : "7.5px")
        .style("font-weight", "700")
        .style("font-family", CHART_FONT)
        .text(abbrev(s.opponent));

      if (!REDUCED_MOTION) {
        teamLabel
          .attr("opacity", 0)
          .transition()
          .duration(250)
          .delay(cascadeDelay + 180)
          .attr("opacity", 1);
      }
    }

    if (bw > 36) {
      const homeLabel = chart
        .append("text")
        .attr("x", bx + bw / 2)
        .attr("y", blockY + blockH - 5)
        .attr("text-anchor", "middle")
        .attr("fill", s.avgStrength > 0.65 ? "rgba(255,255,255,0.7)" : "rgba(0,0,0,0.35)")
        .style("font-size", "7px")
        .style("font-weight", "500")
        .style("font-family", CHART_FONT)
        .text(s.isHome ? "HOME" : "AWAY");

      if (!REDUCED_MOTION) {
        homeLabel
          .attr("opacity", 0)
          .transition()
          .duration(250)
          .delay(cascadeDelay + 210)
          .attr("opacity", 1);
      }
    }
  });

  const legendW = 120;
  const legendH = 8;
  const legendX = width - margin.right - legendW;
  const legendY = margin.top - 2;

  const defs = chart.append("defs");
  const gradId = "sos-gradient";
  const grad = defs.append("linearGradient").attr("id", gradId);
  grad.append("stop").attr("offset", "0%").attr("stop-color", color(0));
  grad.append("stop").attr("offset", "50%").attr("stop-color", color(0.5));
  grad.append("stop").attr("offset", "100%").attr("stop-color", color(1));

  chart
    .append("rect")
    .attr("x", legendX)
    .attr("y", legendY)
    .attr("width", legendW)
    .attr("height", legendH)
    .attr("rx", 4)
    .attr("fill", `url(#${gradId})`);

  chart
    .append("text")
    .attr("x", legendX - 4)
    .attr("y", legendY + legendH / 2)
    .attr("text-anchor", "end")
    .attr("dominant-baseline", "central")
    .attr("fill", CHART.legendMuted)
    .style("font-size", "8px")
    .style("font-weight", "600")
    .style("font-family", CHART_FONT)
    .text("EASY");

  chart
    .append("text")
    .attr("x", legendX + legendW + 4)
    .attr("y", legendY + legendH / 2)
    .attr("dominant-baseline", "central")
    .attr("fill", CHART.legendMuted)
    .style("font-size", "8px")
    .style("font-weight", "600")
    .style("font-family", CHART_FONT)
    .text("HARD");
}

export function ScheduleHeatmap({
  schedule,
  team,
  season,
  scheduleStrengthPlayed,
  scheduleStrengthRemaining,
}: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) setVisible(true); },
      { threshold: 0.12 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    setVisible(false);
  }, [schedule, team, season, scheduleStrengthPlayed, scheduleStrengthRemaining]);

  useEffect(() => {
    if (!visible || !svgRef.current) return;
    drawHeatmap(svgRef.current, schedule, team, season, scheduleStrengthPlayed, scheduleStrengthRemaining);
  }, [visible, schedule, team, season, scheduleStrengthPlayed, scheduleStrengthRemaining]);

  return (
    <div ref={wrapperRef}>
      <svg
        ref={svgRef}
        className="chart-svg schedule-heatmap-svg"
        role="img"
        aria-label="Strength of schedule: played and remaining scores and remaining schedule heatmap"
      />
    </div>
  );
}
