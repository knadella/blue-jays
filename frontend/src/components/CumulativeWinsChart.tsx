import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";

import type { SimulationDensityCell, WinPoint } from "../api";

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

function teamAccentColor(team: string) {
  if (team === "Toronto Blue Jays") {
    return "#134A8E";
  }
  return "#0d5c75";
}

function teamSecondaryColor(team: string) {
  if (team === "Toronto Blue Jays") {
    return "#E63946";
  }
  return "#083D4A";
}

function teamMarkerGlyph(team: string) {
  if (team === "Toronto Blue Jays") {
    return "🐦";
  }
  return "⚾";
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
    const accentColor = teamAccentColor(team);
    const secondaryColor = teamSecondaryColor(team);
    const tipGlyph = teamMarkerGlyph(team);

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

      tipGroup
        .append("text")
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "central")
        .attr("font-size", team === "Toronto Blue Jays" ? 18 : 16)
        .text(tipGlyph);

      tipGroup
        .append("rect")
        .attr("x", 18)
        .attr("y", -10)
        .attr("width", 42)
        .attr("height", 20)
        .attr("rx", 10)
        .attr("fill", accentColor)
        .attr("opacity", 0.96);

      tipGroup
        .append("text")
        .attr("x", 39)
        .attr("y", 0)
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "central")
        .attr("fill", "#ffffff")
        .style("fontSize", "10px")
        .style("fontWeight", "700")
        .text(team === "Toronto Blue Jays" ? "TOR" : "TEAM");
    }

    svg
      .append("text")
      .attr("x", margin.left)
      .attr("y", margin.top - 6)
      .attr("fill", "#6b5b4d")
      .style("fontSize", "12px")
      .text("Dark band: middle 50%. Light band: middle 80%.");

    svg
      .append("text")
      .attr("x", width - margin.right)
      .attr("y", margin.top - 6)
      .attr("text-anchor", "end")
      .attr("fill", "#1f1f1f")
      .style("fontSize", "12px")
      .style("fontWeight", "600")
      .text(team);

    const statsGroup = svg.append("g").attr("transform", `translate(${statX},${statY})`);
    const cardX = -14;
    const cardY = -18;
    const cardWidth = 222;
    const cardHeight = 130;

    statsGroup
      .append("rect")
      .attr("x", cardX)
      .attr("y", cardY)
      .attr("width", cardWidth)
      .attr("height", cardHeight)
      .attr("rx", 3)
      .attr("fill", "#ffffff")
      .attr("fill-opacity", 1)
      .attr("stroke", "#d8ccc0")
      .attr("stroke-width", 1);

    statsGroup
      .append("rect")
      .attr("x", cardX)
      .attr("y", cardY)
      .attr("width", cardWidth)
      .attr("height", 3)
      .attr("fill", accentColor)
      .attr("opacity", 0.75);

    statsGroup
      .append("text")
      .attr("x", 0)
      .attr("y", cardY + 12)
      .attr("dominant-baseline", "hanging")
      .attr("fill", "#7a6b5b")
      .style("fontSize", "11px")
      .style("fontWeight", "700")
      .style("letterSpacing", "0.08em")
      .text("CURRENT FORECAST");

    statsGroup
      .append("text")
      .attr("x", 0)
      .attr("y", cardY + 30)
      .attr("dominant-baseline", "hanging")
      .attr("fill", "#1f1f1f")
      .style("fontFamily", "Georgia, 'Times New Roman', serif")
      .style("fontSize", "46px")
      .style("fontWeight", "600")
      .text(`${projectedFinalWins} wins`);

    statsGroup
      .append("line")
      .attr("x1", 0)
      .attr("x2", 194)
      .attr("y1", cardY + 78)
      .attr("y2", cardY + 78)
      .attr("stroke", "#e1d8cf")
      .attr("stroke-width", 1);

    [
      ["Division finish", ordinal(projectedDivisionPlace)],
      ["Playoff odds", `${playoffProbability.toFixed(1)}%`],
    ].forEach(([label, value], index) => {
      const rowY = cardY + 88 + index * 20;
      statsGroup
        .append("text")
        .attr("x", 0)
        .attr("y", rowY)
        .attr("dominant-baseline", "hanging")
        .attr("fill", "#6b5b4d")
        .style("fontSize", "12px")
        .style("fontWeight", "500")
        .text(label);

      statsGroup
        .append("text")
        .attr("x", 194)
        .attr("y", rowY)
        .attr("text-anchor", "end")
        .attr("dominant-baseline", "hanging")
        .attr("fill", "#1f1f1f")
        .style("fontSize", "13px")
        .style("fontWeight", "700")
        .text(value);
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
