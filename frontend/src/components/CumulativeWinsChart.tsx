import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";

import type { SimulationDensityCell, WinPoint } from "../api";
import { getTeamAbbrev, getTeamColor, getTeamLogoPath } from "../teamMetadata";

interface Props {
  actualPoints: WinPoint[];
  simulationDensity: SimulationDensityCell[];
  team: string;
  season: number;
  projectedFinalWins: number;
  projectedDivisionPlace: number;
  playoffProbability: number;
}

function ordinal(value: number) {
  const mod100 = value % 100;
  if (mod100 >= 11 && mod100 <= 13) {
    return `${value}th`;
  }
  switch (value % 10) {
    case 1:
      return `${value}st`;
    case 2:
      return `${value}nd`;
    case 3:
      return `${value}rd`;
    default:
      return `${value}th`;
  }
}

export function CumulativeWinsChart({
  actualPoints,
  simulationDensity,
  team,
  season,
  projectedFinalWins,
  projectedDivisionPlace,
  playoffProbability,
}: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);

  const forecastSummary = useMemo(() => {
    const byDate = d3.group(simulationDensity, (cell) => cell.date);

    const quantileFromCells = (cells: SimulationDensityCell[], target: number) => {
      let cumulative = 0;
      const sorted = [...cells].sort((a, b) => a.wins - b.wins);
      for (const cell of sorted) {
        cumulative += cell.probability;
        if (cumulative >= target) {
          return cell.wins;
        }
      }
      return sorted[sorted.length - 1]?.wins ?? 0;
    };

    return Array.from(byDate.entries())
      .sort(([dateA], [dateB]) => dateA.localeCompare(dateB))
      .map(([date, cells]) => ({
        date: new Date(date),
        p10: quantileFromCells(cells, 0.1),
        p25: quantileFromCells(cells, 0.25),
        p50: quantileFromCells(cells, 0.5),
        p75: quantileFromCells(cells, 0.75),
        p90: quantileFromCells(cells, 0.9),
      }));
  }, [simulationDensity]);

  useEffect(() => {
    setFrameIndex(0);
  }, [team, season, simulationDensity]);

  useEffect(() => {
    if (forecastSummary.length === 0) {
      return;
    }

    const durationMs = 1600;
    const maxFrame = forecastSummary.length - 1;
    let animationFrameId = 0;
    let startTime: number | null = null;

    const animate = (timestamp: number) => {
      if (startTime === null) {
        startTime = timestamp;
      }

      const elapsed = timestamp - startTime;
      const linearProgress = Math.min(elapsed / durationMs, 1);
      const easedProgress = d3.easeCubicOut(linearProgress);
      const nextFrame = Math.min(maxFrame, Math.floor(easedProgress * maxFrame));
      setFrameIndex(nextFrame);

      if (linearProgress < 1) {
        animationFrameId = window.requestAnimationFrame(animate);
      }
    };

    animationFrameId = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(animationFrameId);
  }, [forecastSummary]);

  useEffect(() => {
    if (!svgRef.current) {
      return;
    }

    const parsedActual = actualPoints.map((point) => ({
      date: new Date(point.date),
      wins: point.wins,
    }));
    const visibleForecast = forecastSummary.slice(0, frameIndex + 1);
    const allWins = [
      ...parsedActual.map((point) => point.wins),
      ...forecastSummary.flatMap((point) => [point.p10, point.p25, point.p50, point.p75, point.p90]),
    ];
    const yMin = d3.min(allWins) ?? 0;
    const yMax = d3.max(allWins) ?? 0;

    const width = 1120;
    const height = 620;
    const margin = { top: 24, right: 108, bottom: 36, left: 56 };
    const monthTicks = d3.timeMonth.range(new Date(`${season}-03-01`), new Date(`${season}-10-01`));
    const monthFormatter = d3.timeFormat("%b");

    const x = d3
      .scaleTime()
      .domain([new Date(`${season}-03-01`), new Date(`${season}-09-30`)])
      .range([margin.left, width - margin.right]);
    const y = d3
      .scaleLinear()
      .domain([Math.min(0, yMin), Math.max(yMax, 1)])
      .nice()
      .range([height - margin.bottom, margin.top]);
    const statX = x(new Date(`${season}-03-16`));
    const statY = y(80);
    const accentColor = getTeamColor(team);
    const teamAbbrev = getTeamAbbrev(team);
    const teamLogoPath = getTeamLogoPath(team);

    const line = d3
      .line<{ date: Date; wins: number }>()
      .x((point) => x(point.date))
      .y((point) => y(point.wins))
      .curve(d3.curveMonotoneX);

    const area80 = d3
      .area<{ date: Date; p10: number; p25: number; p50: number; p75: number; p90: number }>()
      .x((point) => x(point.date))
      .y0((point) => y(point.p10))
      .y1((point) => y(point.p90))
      .curve(d3.curveMonotoneX);

    const area50 = d3
      .area<{ date: Date; p10: number; p25: number; p50: number; p75: number; p90: number }>()
      .x((point) => x(point.date))
      .y0((point) => y(point.p25))
      .y1((point) => y(point.p75))
      .curve(d3.curveMonotoneX);

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    svg.attr("viewBox", `0 0 ${width} ${height}`);

    svg
      .append("g")
      .attr("transform", `translate(${margin.left},0)`)
      .call(
        d3
          .axisLeft(y)
          .ticks(8)
          .tickSize(-(width - margin.left - margin.right))
          .tickFormat(() => ""),
      )
      .call((group) =>
        group
          .selectAll("line")
          .attr("stroke", "#c9b9aa")
          .attr("stroke-opacity", 0.95)
          .attr("stroke-dasharray", "0"),
      )
      .call((group) => group.select(".domain").remove())
      .call((group) => group.selectAll("text").remove());

    svg
      .append("g")
      .attr("transform", `translate(0,${height - margin.bottom})`)
      .call(
        d3
          .axisBottom<Date>(x)
          .tickValues(monthTicks)
          .tickSize(-(height - margin.top - margin.bottom))
          .tickFormat(() => ""),
      )
      .call((group) =>
        group
          .selectAll("line")
          .attr("stroke", "#ece1d6")
          .attr("stroke-opacity", 0.35),
      )
      .call((group) => group.select(".domain").remove())
      .call((group) => group.selectAll("text").remove());

    svg
      .append("g")
      .attr("transform", `translate(0,${height - margin.bottom})`)
      .call(
        d3
          .axisBottom<Date>(x)
          .tickValues(monthTicks)
          .tickFormat((value) => monthFormatter(value as Date)),
      )
      .call((group) => group.select(".domain").remove());

    svg
      .append("g")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(y).ticks(8))
      .call((group) => group.select(".domain").remove());

    if (visibleForecast.length > 1) {
      svg
        .append("path")
        .datum(visibleForecast)
        .attr("fill", "#0d5c75")
        .attr("opacity", 0.14)
        .attr("d", area80(visibleForecast) ?? "");

      svg
        .append("path")
        .datum(visibleForecast)
        .attr("fill", "#0d5c75")
        .attr("opacity", 0.28)
        .attr("d", area50(visibleForecast) ?? "");

      svg
        .append("path")
        .datum(visibleForecast.map((point) => ({ date: point.date, wins: point.p50 })))
        .attr("fill", "none")
        .attr("stroke", accentColor)
        .attr("stroke-width", 3)
        .attr("d", line(visibleForecast.map((point) => ({ date: point.date, wins: point.p50 }))) ?? "");
    }

    svg
      .append("path")
      .datum(parsedActual)
      .attr("fill", "none")
      .attr("stroke", "#1f1f1f")
      .attr("stroke-width", 3)
      .attr("d", line(parsedActual) ?? "");

    const lastActualPoint = parsedActual[parsedActual.length - 1];
    if (lastActualPoint) {
      svg
        .append("circle")
        .attr("cx", x(lastActualPoint.date))
        .attr("cy", y(lastActualPoint.wins))
        .attr("r", 4)
        .attr("fill", "#1f1f1f");
    }

    const lastForecastPoint = visibleForecast[visibleForecast.length - 1];
    if (lastForecastPoint) {
      const tipX = x(lastForecastPoint.date);
      const tipY = y(lastForecastPoint.p50);
      const tipGroup = svg
        .append("g")
        .attr("transform", `translate(${tipX},${tipY})`);

      const outerPulse = tipGroup
        .append("circle")
        .attr("r", 18)
        .attr("fill", "none")
        .attr("stroke", accentColor)
        .attr("stroke-width", 2)
        .attr("opacity", 0.22);
      outerPulse
        .append("animate")
        .attr("attributeName", "r")
        .attr("values", "18;28;18")
        .attr("dur", "1.8s")
        .attr("repeatCount", "indefinite");
      outerPulse
        .append("animate")
        .attr("attributeName", "opacity")
        .attr("values", "0.22;0.02;0.22")
        .attr("dur", "1.8s")
        .attr("repeatCount", "indefinite");

      const innerPulse = tipGroup
        .append("circle")
        .attr("r", 18)
        .attr("fill", "none")
        .attr("stroke", accentColor)
        .attr("stroke-width", 1.5)
        .attr("opacity", 0.16);
      innerPulse
        .append("animate")
        .attr("attributeName", "r")
        .attr("values", "18;24;18")
        .attr("dur", "1.2s")
        .attr("repeatCount", "indefinite");
      innerPulse
        .append("animate")
        .attr("attributeName", "opacity")
        .attr("values", "0.16;0.03;0.16")
        .attr("dur", "1.2s")
        .attr("repeatCount", "indefinite");

      tipGroup
        .append("circle")
        .attr("r", 18)
        .attr("fill", "#fffaf4")
        .attr("opacity", 0.95)
        .attr("stroke", accentColor)
        .attr("stroke-width", 2.5);

      if (teamLogoPath) {
        tipGroup
          .append("image")
          .attr("href", teamLogoPath)
          .attr("x", -11)
          .attr("y", -11)
          .attr("width", 22)
          .attr("height", 22)
          .attr("preserveAspectRatio", "xMidYMid meet");
      } else {
        tipGroup
          .append("text")
          .attr("text-anchor", "middle")
          .attr("dominant-baseline", "central")
          .attr("font-size", "10px")
          .attr("font-weight", "700")
          .text(teamAbbrev);
      }

    }

    const defs = svg.append("defs");
    const shadowFilter = defs.append("filter")
      .attr("id", "stats-shadow")
      .attr("x", "-20%")
      .attr("y", "-20%")
      .attr("width", "160%")
      .attr("height", "160%");
    shadowFilter.append("feDropShadow")
      .attr("dx", 0)
      .attr("dy", 1)
      .attr("stdDeviation", 6)
      .attr("flood-color", "#1a1a1a")
      .attr("flood-opacity", 0.09);

    const cardClipId = "stats-clip";
    defs.append("clipPath").attr("id", cardClipId)
      .append("rect")
      .attr("width", 306)
      .attr("height", 88)
      .attr("rx", 8);

    const statsGroup = svg.append("g").attr("transform", `translate(${statX},${statY})`);
    const cardW = 306;
    const cardH = 88;
    const colW = cardW / 3;

    statsGroup.append("rect")
      .attr("width", cardW)
      .attr("height", cardH)
      .attr("rx", 8)
      .attr("fill", "#ffffff")
      .attr("filter", "url(#stats-shadow)");

    const clipped = statsGroup.append("g").attr("clip-path", `url(#${cardClipId})`);
    clipped.append("rect")
      .attr("width", 4)
      .attr("height", cardH)
      .attr("fill", accentColor);

    const stats = [
      { value: `${projectedFinalWins}`, label: "PROJ. WINS", isHero: true },
      { value: ordinal(projectedDivisionPlace), label: "DIVISION", isHero: false },
      { value: `${Math.round(playoffProbability)}%`, label: "PLAYOFFS", isHero: false },
    ];

    stats.forEach((stat, i) => {
      const colCenter = i === 0 ? (4 + colW) / 2 : colW * i + colW / 2;

      statsGroup.append("text")
        .attr("x", colCenter)
        .attr("y", 22)
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "hanging")
        .attr("fill", stat.isHero ? accentColor : "#1a1a1a")
        .style("font-size", stat.isHero ? "30px" : "22px")
        .style("font-weight", "700")
        .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
        .text(stat.value);

      statsGroup.append("text")
        .attr("x", colCenter)
        .attr("y", 58)
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "hanging")
        .attr("fill", "#9a9a9a")
        .style("font-size", "9.5px")
        .style("font-weight", "600")
        .style("letter-spacing", "0.07em")
        .style("font-family", "'Inter', -apple-system, system-ui, sans-serif")
        .text(stat.label);

      if (i < stats.length - 1) {
        const dx = (i + 1) * colW;
        statsGroup.append("line")
          .attr("x1", dx)
          .attr("y1", 16)
          .attr("x2", dx)
          .attr("y2", cardH - 16)
          .attr("stroke", "#ebebeb")
          .attr("stroke-width", 1);
      }
    });
  }, [
    actualPoints,
    forecastSummary,
    frameIndex,
    playoffProbability,
    projectedDivisionPlace,
    projectedFinalWins,
    season,
    team,
  ]);

  return (
    <svg
      ref={svgRef}
      className="chart-svg"
      role="img"
      aria-label="Actual cumulative wins with projected confidence bands"
    />
  );
}
