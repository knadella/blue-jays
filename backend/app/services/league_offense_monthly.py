"""League-relative monthly offense ranks (Apr–Sep) from local Statcast extracts."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from config import TEAM_ABBREVS

from data_source.statcast_weekly import build_weekly_frames, try_load_statcast_local

SEASON_MONTHS = (4, 5, 6, 7, 8, 9)

# (offense dict key, "higher" | "lower")
METRIC_SPECS: tuple[tuple[str, str], ...] = (
    ("xwoba_on_contact", "higher"),
    ("chase_rate", "lower"),
    ("whiff_rate", "lower"),
    ("hard_hit_rate", "higher"),
)

# New metrics for faceted chart (rank-based)
RANK_METRIC_SPECS: tuple[tuple[str, str, str], ...] = (
    ("xwoba", "higher", "xwoba_rank"),
    ("barrel_rate", "higher", "barrel_rank"),
    ("chase_rate", "lower", "chase_rank"),
    ("whiff_rate", "lower", "whiff_rank"),
)

# Pitching/defense ranks (from run_prevention side)
# For pitching: lower xwOBA/barrel allowed = better, higher chase/whiff generated = better
PITCHING_RANK_SPECS: tuple[tuple[str, str, str], ...] = (
    ("xwoba", "lower", "p_xwoba_rank"),
    ("barrel_rate", "lower", "p_barrel_rank"),
    ("chase_rate", "higher", "p_chase_rank"),
    ("whiff_rate", "higher", "p_whiff_rank"),
)


def _calendar_month_from_week_end(week_end: str) -> int | None:
    s = (week_end or "").strip()[:10]
    if len(s) != 10:
        return None
    try:
        m = int(s[5:7])
    except ValueError:
        return None
    return m if m in SEASON_MONTHS else None


def _aggregate_weeks_side(week_rows: list[dict[str, Any]], side: str = "offense") -> dict[str, Any]:
    """PA-weighted metrics for a given side (offense or run_prevention)."""
    rows = [w[side] for w in week_rows]
    pa_sum = sum(max(0, int(r.get("plate_appearances") or 0)) for r in rows)
    if pa_sum <= 0:
        return {
            "plate_appearances": 0,
            "xwoba_on_contact": None,
            "xwoba": None,
            "chase_rate": None,
            "whiff_rate": None,
            "hard_hit_rate": None,
            "barrel_rate": None,
        }

    def wavg(getter: Any) -> float | None:
        s = 0.0
        w = 0.0
        for r in rows:
            pa = max(0, int(r.get("plate_appearances") or 0))
            if pa <= 0:
                continue
            v = getter(r)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isnan(fv):
                continue
            s += fv * pa
            w += float(pa)
        return (s / w) if w > 0 else None

    return {
        "plate_appearances": pa_sum,
        "xwoba_on_contact": wavg(lambda r: r.get("xwoba_on_contact")),
        "xwoba": wavg(lambda r: r.get("xwoba")),
        "chase_rate": wavg(lambda r: r.get("chase_rate")),
        "whiff_rate": wavg(lambda r: r.get("whiff_rate")),
        "hard_hit_rate": wavg(lambda r: r.get("hard_hit_rate")),
        "barrel_rate": wavg(lambda r: r.get("barrel_rate")),
    }


def _bucket_weeks_by_season_month(raw_weeks: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    by_m: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for w in raw_weeks:
        m = _calendar_month_from_week_end(str(w.get("week_end") or ""))
        if m is None:
            continue
        by_m[m].append(w)
    return by_m


def _sample_percentile(values: list[float], current: float, sense: str) -> int:
    """Mid-rank percentile in [1, 99], same convention as the SPA."""
    n = len(values)
    if n == 0:
        return 50
    sorted_vals = sorted(values)
    below = sum(1 for x in sorted_vals if x < current)
    equal = sum(1 for x in sorted_vals if x == current)
    frac = (below + 0.5 * (equal or 1)) / n
    raw_pct = frac * 100 if sense == "higher" else (1.0 - frac) * 100
    return int(max(1, min(99, round(raw_pct))))


def _compute_rank(values: list[float], current: float, sense: str) -> int:
    """1-based rank where 1 = best.  For 'higher' sense, highest value = rank 1."""
    if not values:
        return 1
    if sense == "higher":
        # Count how many are strictly better (higher)
        better = sum(1 for v in values if v > current)
    else:
        # Count how many are strictly better (lower)
        better = sum(1 for v in values if v < current)
    return better + 1


def _load_raw_weeks_for_abbrev(abbrev: str, season: int) -> list[dict[str, Any]] | None:
    df = try_load_statcast_local(abbrev, season)
    if df is None or len(df) == 0:
        return None
    return build_weekly_frames(df, abbrev)


def _rank_or_none(pool: dict, month: int, key: str, agg: dict | None, sense: str) -> int | None:
    if agg is None:
        return None
    cur = agg.get(key)
    if cur is None:
        return None
    try:
        cur_f = float(cur)
    except (TypeError, ValueError):
        return None
    if math.isnan(cur_f):
        return None
    league_vals = pool.get((month, key), [])
    if len(league_vals) < 2:
        return None
    return _compute_rank(league_vals, cur_f, sense)


def build_offense_monthly_league_shape(
    *,
    season: int,
    focal_abbrev: str,
    focal_raw_weeks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Return six rows (Apr–Sep) with league percentiles/ranks + count of teams used."""
    off_pool: dict[tuple[int, str], list[float]] = defaultdict(list)
    def_pool: dict[tuple[int, str], list[float]] = defaultdict(list)
    abbrevs_seen: set[str] = set()

    all_off_metrics = set(k for k, _ in METRIC_SPECS) | set(k for k, _, _ in RANK_METRIC_SPECS)
    all_def_metrics = set(k for k, _, _ in PITCHING_RANK_SPECS)

    def ingest(abbrev: str, weeks: list[dict[str, Any]]) -> None:
        if not weeks:
            return
        abbrevs_seen.add(abbrev)
        by_m = _bucket_weeks_by_season_month(weeks)
        for month in SEASON_MONTHS:
            wks = by_m.get(month) or []
            if not wks:
                continue
            # Offense
            off_agg = _aggregate_weeks_side(wks, "offense")
            for key in all_off_metrics:
                v = off_agg.get(key)
                if v is None:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if math.isnan(fv):
                    continue
                off_pool[(month, key)].append(fv)
            # Defense
            def_agg = _aggregate_weeks_side(wks, "run_prevention")
            for key in all_def_metrics:
                v = def_agg.get(key)
                if v is None:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if math.isnan(fv):
                    continue
                def_pool[(month, key)].append(fv)

    ingest(focal_abbrev, focal_raw_weeks)

    for ab in sorted(set(TEAM_ABBREVS.values())):
        if ab == focal_abbrev:
            continue
        weeks = _load_raw_weeks_for_abbrev(ab, season)
        if weeks:
            ingest(ab, weeks)

    focal_by_m = _bucket_weeks_by_season_month(focal_raw_weeks)
    rows: list[dict[str, Any]] = []
    for month in SEASON_MONTHS:
        wks = focal_by_m.get(month) or []
        focal_off = _aggregate_weeks_side(wks, "offense") if wks else None
        focal_def = _aggregate_weeks_side(wks, "run_prevention") if wks else None
        out: dict[str, Any] = {"month": month}

        # Legacy percentile fields (offense)
        for key, sense in METRIC_SPECS:
            pct_key = {
                "xwoba_on_contact": "xwoba_pct",
                "chase_rate": "chase_pct",
                "whiff_rate": "whiff_pct",
                "hard_hit_rate": "hard_hit_pct",
            }[key]
            league_vals = off_pool.get((month, key), [])
            if focal_off is None:
                out[pct_key] = None
                continue
            cur = focal_off.get(key)
            if cur is None:
                out[pct_key] = None
                continue
            try:
                cur_f = float(cur)
            except (TypeError, ValueError):
                out[pct_key] = None
                continue
            if math.isnan(cur_f):
                out[pct_key] = None
                continue
            if len(league_vals) < 2:
                out[pct_key] = None
            else:
                out[pct_key] = _sample_percentile(league_vals, cur_f, sense)

        # Offense rank fields
        for key, sense, rank_key in RANK_METRIC_SPECS:
            out[rank_key] = _rank_or_none(off_pool, month, key, focal_off, sense)

        # Pitching/defense rank fields
        for key, sense, rank_key in PITCHING_RANK_SPECS:
            out[rank_key] = _rank_or_none(def_pool, month, key, focal_def, sense)

        rows.append(out)

    return rows, len(abbrevs_seen)
