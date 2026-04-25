"""Compose Statcast-backed weekly progression for the SPA (Blue Jays only)."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from config import TEAM_ABBREVS

from data_source.mlb_api import build_record, fetch_schedule, split_schedule
from data_source.statcast_weekly import (
    _add_roles,
    build_barrel_grid,
    build_chase_zone_grid,
    build_spray_xwoba_grid,
    build_team_record_from_statcast,
    build_weekly_frames,
    build_whiff_zone_grid,
    load_team_statcast_frame,
    statcast_require_local_only,
    try_load_statcast_local,
)

from ..schemas import (
    BarrelCell,
    BarrelGrid,
    BarrelMonth,
    ChaseZoneCell,
    ChaseZoneGrid,
    ChaseZoneMonth,
    PitchTypeRow,
    SprayCell,
    SprayGrid,
    SprayMonth,
    WeekSideMetrics,
    WeeklyActualsResponse,
    WeeklyBucket,
    WhiffZoneCell,
    WhiffZoneGrid,
    WhiffZoneMonth,
)

FAVORITE_TEAM = "Toronto Blue Jays"


def build_weekly_actuals_payload(*, season: int, team: str | None = None, skip_cache: bool = False) -> WeeklyActualsResponse:
    favorite = FAVORITE_TEAM
    abbrev = TEAM_ABBREVS[favorite]

    # Check disk cache first for instant response
    if not skip_cache:
        from .weekly_cache import read_weekly_cache
        cached = read_weekly_cache(season, abbrev)
        if cached is not None:
            return cached

    note: str | None = None
    df = None
    local_df = try_load_statcast_local(abbrev, season)
    offline = statcast_require_local_only()

    if local_df is not None and len(local_df):
        df = local_df
        rec = build_team_record_from_statcast(df, abbrev)
    elif offline:
        rec = {"w": 0, "l": 0}
        note = (
            f"No local Statcast extract for {abbrev} {season} under the configured STATCAST_LOCAL_DIR "
            "(MLB_LOCAL_SITE / STATCAST_REQUIRE_LOCAL disables live Savant downloads)."
        )
    else:
        sched = fetch_schedule(season)
        completed, _ = split_schedule(sched)
        rec = build_record(completed).get(favorite, {"w": 0, "l": 0})
        try:
            df = load_team_statcast_frame(abbrev, season)
        except Exception as exc:
            note = str(exc)

    if df is None or len(df) == 0:
        return WeeklyActualsResponse(
            season=season,
            team=favorite,
            team_abbrev=abbrev,
            wins=rec["w"],
            losses=rec["l"],
            weeks=[],
            statcast_rows=0,
            data_through=None,
            generated_at=datetime.now(timezone.utc).isoformat(),
            note=note or "No Statcast rows returned for this club and season yet.",
        )

    raw_weeks = build_weekly_frames(df, abbrev)

    buckets: list[WeeklyBucket] = []
    for w in raw_weeks:
        buckets.append(
            WeeklyBucket(
                week_key=w["week_key"],
                week_start=w["week_start"],
                week_end=w["week_end"],
                offense=WeekSideMetrics(**w["offense"]),
                run_prevention=WeekSideMetrics(**w["run_prevention"]),
                hitting_vs_pitch_types=[PitchTypeRow(**r) for r in w["hitting_vs_pitch_types"]],
                pitching_pitch_types=[PitchTypeRow(**r) for r in w["pitching_pitch_types"]],
            )
        )

    runs_scored = 0.0
    runs_allowed = 0.0
    games_played = 0

    def _rpg(frame: pd.DataFrame, team: str) -> tuple[float, float, int]:
        gms = frame.groupby("game_pk").agg(
            home_team=("home_team", "first"),
            away_team=("away_team", "first"),
            home_score=("home_score", "max"),
            away_score=("away_score", "max"),
        ).reset_index()
        is_home = gms["home_team"].astype(str) == team
        n = len(gms)
        if n == 0:
            return 0.0, 0.0, 0
        rs = float(
            pd.to_numeric(gms.loc[is_home, "home_score"], errors="coerce").sum()
            + pd.to_numeric(gms.loc[~is_home, "away_score"], errors="coerce").sum()
        ) / n
        ra = float(
            pd.to_numeric(gms.loc[is_home, "away_score"], errors="coerce").sum()
            + pd.to_numeric(gms.loc[~is_home, "home_score"], errors="coerce").sum()
        ) / n
        return round(rs, 2), round(ra, 2), n

    try:
        runs_scored, runs_allowed, games_played = _rpg(df, abbrev)
    except Exception:
        pass

    run_diff = int(round(runs_scored * games_played - runs_allowed * games_played)) if games_played else 0

    streak_str = ""
    try:
        _gms = df.groupby("game_pk").agg(
            game_date=("game_date", "first"),
            home_team=("home_team", "first"),
            away_team=("away_team", "first"),
            home_score=("home_score", "max"),
            away_score=("away_score", "max"),
        ).reset_index()
        _gms = _gms.sort_values("game_date")
        _is_home = _gms["home_team"].astype(str) == abbrev
        _team_rs = pd.to_numeric(_gms["home_score"].where(_is_home, _gms["away_score"]), errors="coerce")
        _team_ra = pd.to_numeric(_gms["away_score"].where(_is_home, _gms["home_score"]), errors="coerce")
        _wins = (_team_rs > _team_ra).values
        if len(_wins) > 0:
            last = _wins[-1]
            count = 0
            for i in range(len(_wins) - 1, -1, -1):
                if _wins[i] == last:
                    count += 1
                else:
                    break
            streak_str = f"{'W' if last else 'L'}{count}"
    except Exception:
        pass

    data_through: str | None = None
    if "game_date" in df.columns:
        try:
            gd = pd.to_datetime(df["game_date"], errors="coerce")
            if gd.notna().any():
                mx = gd.max()
                data_through = mx.date().isoformat() if hasattr(mx, "date") else str(mx)[:10]
        except Exception:
            data_through = None

    raw_grid = build_chase_zone_grid(df)
    chase_grid: ChaseZoneGrid | None = None
    if raw_grid:
        chase_grid = ChaseZoneGrid(
            sz_top=raw_grid["sz_top"],
            sz_bot=raw_grid["sz_bot"],
            zone_width=raw_grid["zone_width"],
            nx=raw_grid["nx"],
            ny=raw_grid["ny"],
            x_range=raw_grid["x_range"],
            y_range=raw_grid["y_range"],
            months=[
                ChaseZoneMonth(
                    month=m["month"],
                    cells=[ChaseZoneCell(**c) for c in m["cells"]],
                )
                for m in raw_grid["months"]
            ],
        )

    raw_whiff = build_whiff_zone_grid(df)
    whiff_grid: WhiffZoneGrid | None = None
    if raw_whiff:
        whiff_grid = WhiffZoneGrid(
            sz_top=raw_whiff["sz_top"], sz_bot=raw_whiff["sz_bot"],
            zone_width=raw_whiff["zone_width"], nx=raw_whiff["nx"], ny=raw_whiff["ny"],
            x_range=raw_whiff["x_range"], y_range=raw_whiff["y_range"],
            months=[WhiffZoneMonth(month=m["month"], cells=[WhiffZoneCell(**c) for c in m["cells"]]) for m in raw_whiff["months"]],
        )

    raw_barrel = build_barrel_grid(df)
    brl_grid: BarrelGrid | None = None
    if raw_barrel:
        brl_grid = BarrelGrid(
            nx=raw_barrel["nx"], ny=raw_barrel["ny"],
            ev_range=raw_barrel["ev_range"], la_range=raw_barrel["la_range"],
            months=[BarrelMonth(month=m["month"], cells=[BarrelCell(**c) for c in m["cells"]]) for m in raw_barrel["months"]],
        )

    raw_spray = build_spray_xwoba_grid(df)
    spr_grid: SprayGrid | None = None
    if raw_spray:
        spr_grid = SprayGrid(
            nx=raw_spray["nx"], ny=raw_spray["ny"],
            x_range=raw_spray["x_range"], y_range=raw_spray["y_range"],
            months=[SprayMonth(month=m["month"], cells=[SprayCell(**c) for c in m["cells"]]) for m in raw_spray["months"]],
        )

    df_roles = _add_roles(df, abbrev)
    df_def = df_roles.loc[df_roles["defense_row"]]

    p_chase_raw = build_chase_zone_grid(df_def) if len(df_def) > 50 else None
    p_whiff_raw = build_whiff_zone_grid(df_def) if len(df_def) > 50 else None
    p_barrel_raw = build_barrel_grid(df_def) if len(df_def) > 50 else None
    p_spray_raw = build_spray_xwoba_grid(df_def) if len(df_def) > 50 else None

    p_chase_grid = ChaseZoneGrid(
        sz_top=p_chase_raw["sz_top"], sz_bot=p_chase_raw["sz_bot"],
        zone_width=p_chase_raw["zone_width"], nx=p_chase_raw["nx"], ny=p_chase_raw["ny"],
        x_range=p_chase_raw["x_range"], y_range=p_chase_raw["y_range"],
        months=[ChaseZoneMonth(month=m["month"], cells=[ChaseZoneCell(**c) for c in m["cells"]]) for m in p_chase_raw["months"]],
    ) if p_chase_raw else None

    p_whiff_grid = WhiffZoneGrid(
        sz_top=p_whiff_raw["sz_top"], sz_bot=p_whiff_raw["sz_bot"],
        zone_width=p_whiff_raw["zone_width"], nx=p_whiff_raw["nx"], ny=p_whiff_raw["ny"],
        x_range=p_whiff_raw["x_range"], y_range=p_whiff_raw["y_range"],
        months=[WhiffZoneMonth(month=m["month"], cells=[WhiffZoneCell(**c) for c in m["cells"]]) for m in p_whiff_raw["months"]],
    ) if p_whiff_raw else None

    p_brl_grid = BarrelGrid(
        nx=p_barrel_raw["nx"], ny=p_barrel_raw["ny"],
        ev_range=p_barrel_raw["ev_range"], la_range=p_barrel_raw["la_range"],
        months=[BarrelMonth(month=m["month"], cells=[BarrelCell(**c) for c in m["cells"]]) for m in p_barrel_raw["months"]],
    ) if p_barrel_raw else None

    p_spr_grid = SprayGrid(
        nx=p_spray_raw["nx"], ny=p_spray_raw["ny"],
        x_range=p_spray_raw["x_range"], y_range=p_spray_raw["y_range"],
        months=[SprayMonth(month=m["month"], cells=[SprayCell(**c) for c in m["cells"]]) for m in p_spray_raw["months"]],
    ) if p_spray_raw else None

    return WeeklyActualsResponse(
        season=season,
        team=favorite,
        team_abbrev=abbrev,
        wins=rec["w"],
        losses=rec["l"],
        runs_per_game=runs_scored,
        runs_allowed_per_game=runs_allowed,
        run_differential=run_diff,
        streak=streak_str,
        weeks=buckets,
        statcast_rows=len(df),
        data_through=data_through,
        generated_at=datetime.now(timezone.utc).isoformat(),
        note=note,
        chase_zone_grid=chase_grid,
        whiff_zone_grid=whiff_grid,
        barrel_grid=brl_grid,
        spray_grid=spr_grid,
        pitching_chase_zone_grid=p_chase_grid,
        pitching_whiff_zone_grid=p_whiff_grid,
        pitching_barrel_grid=p_brl_grid,
        pitching_spray_grid=p_spr_grid,
    )
