"""Load Statcast pitch-level data for one club and aggregate by ISO week."""

from __future__ import annotations

import concurrent.futures
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
STATCAST_CACHE_DIR = Path(os.getenv("STATCAST_CACHE_DIR", ".cache/statcast_frames"))
STATCAST_CACHE_TTL_SEC = int(os.getenv("STATCAST_CACHE_TTL_SEC", "86400"))
# Offline-first: Parquet or pickle named ``{season}_{TEAM}.parquet`` in this directory (see ``scripts/download_statcast_extracts.py``).
STATCAST_LOCAL_DIR = Path(os.getenv("STATCAST_LOCAL_DIR", str(_REPO_ROOT / "data" / "statcast_local")))

# Rulebook zone width in feet (17 in plate) — used when sz_top/sz_bot + plate location exist.
ZONE_WIDTH_FT = 17.0 / 24.0

_SWING_DESCRIPTIONS = frozenset(
    {
        "swinging_strike",
        "swinging_strike_blocked",
        "foul",
        "foul_tip",
        "foul_bunt",
        "missed_bunt",
        "hit_into_play",
        "hit_into_play_no_out",
        "hit_into_play_score",
    }
)


def _is_swing(description: pd.Series) -> pd.Series:
    s = description.astype(str).str.lower()
    exact = s.isin(_SWING_DESCRIPTIONS)
    prefix = s.str.startswith("hit_into_play")
    return exact | prefix


def _is_whiff(description: pd.Series) -> pd.Series:
    s = description.astype(str).str.lower()
    return s.str.startswith("swinging_strike")


def _in_strike_zone(df: pd.DataFrame) -> pd.Series:
    """Approximate strike zone from plate location + Statcast sz, else fall back to zones 1–9."""
    px = pd.to_numeric(df["plate_x"], errors="coerce")
    pz = pd.to_numeric(df["plate_z"], errors="coerce")
    szt = pd.to_numeric(df["sz_top"], errors="coerce")
    szb = pd.to_numeric(df["sz_bot"], errors="coerce")
    m = px.notna() & pz.notna() & szt.notna() & szb.notna()
    inside = pd.Series(False, index=df.index)
    inside.loc[m] = (
        px[m].abs() <= ZONE_WIDTH_FT
    ) & (pz[m] >= szb[m]) & (pz[m] <= szt[m])
    zn = pd.to_numeric(df["zone"], errors="coerce")
    fallback = zn.isin(range(1, 10))
    return inside | (~m & fallback)


def _bbe_mask(df: pd.DataFrame) -> pd.Series:
    d = df["description"].astype(str).str.lower()
    return d.str.startswith("hit_into_play")


def _pitch_type(df: pd.DataFrame) -> pd.Series:
    pt = df["pitch_type"].astype(str).str.strip()
    pt = pt.replace({"nan": "UN", "": "UN"})
    pt = pt.fillna("UN")
    return pt


def _pitch_label(df: pd.DataFrame) -> pd.Series:
    if "pitch_name" in df.columns:
        pn = df["pitch_name"].astype(str)
        return pn.where(pn.str.len() > 0, _pitch_type(df))
    return _pitch_type(df)


def _add_roles(df: pd.DataFrame, team_abbrev: str) -> pd.DataFrame:
    out = df.copy()
    top = out["inning_topbot"].astype(str).str.startswith("Top")
    out["batting_team"] = np.where(top, out["away_team"], out["home_team"])
    out["fielding_team"] = np.where(top, out["home_team"], out["away_team"])
    out["offense_row"] = out["batting_team"] == team_abbrev
    out["defense_row"] = out["fielding_team"] == team_abbrev
    return out


def _regular_season_mask(game_type: pd.Series) -> pd.Series:
    """Savant usually uses ``R`` for regular season; tolerate stray whitespace."""
    return game_type.astype(str).str.strip().str.upper().eq("R")


def _season_bounds(season: int) -> tuple[str, str]:
    today = date.today()
    start = f"{season}-03-15"
    if season < today.year:
        end = f"{season}-11-15"
    elif season == today.year:
        end = min(today.isoformat(), f"{season}-11-15")
    else:
        # Future season — still query a short spring window so callers get an empty frame fast.
        end = min(today.isoformat(), f"{season}-04-30")
    return start, end


def _apply_regular_season_filter(raw: pd.DataFrame) -> pd.DataFrame:
    if "game_type" not in raw.columns:
        return raw
    reg = _regular_season_mask(raw["game_type"])
    filtered = raw.loc[reg].copy()
    if len(filtered) == 0 and len(raw) > 0:
        logger.warning(
            "Regular-season filter matched no rows (%d raw rows); using Savant payload as-is.",
            len(raw),
        )
        return raw
    return filtered


def expand_statcast_team_frame_to_full_games(df: pd.DataFrame, team_abbrev: str) -> pd.DataFrame:
    """Savant ``team=`` Statcast pulls are pitcher-centric: every row is a pitch thrown by that club's staff.

    That excludes plate appearances where the club is batting, so ``_add_roles`` never marks ``offense_row``.
    Merge full per-``game_pk`` logs (both halves) so offense and run-prevention both populate.
    """
    if df is None or len(df) == 0:
        return df
    ta = str(team_abbrev).strip().upper()
    if "game_pk" not in df.columns:
        return df
    if bool(_add_roles(df, ta)["offense_row"].any()):
        return df

    game_pks = sorted({int(x) for x in pd.unique(df["game_pk"].dropna())})
    if not game_pks:
        return df

    logger.info(
        "Team-scoped Statcast has no batting rows for %s; merging full-game pitch logs for %d games.",
        ta,
        len(game_pks),
    )

    try:
        from pybaseball import statcast_single_game
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pybaseball is required to expand Statcast extracts to full games. Install requirements.txt.",
        ) from exc

    def fetch_game(gpk: int) -> pd.DataFrame:
        try:
            g = statcast_single_game(gpk)
        except Exception:
            logger.exception("statcast_single_game failed for game_pk=%s", gpk)
            return pd.DataFrame()
        return g if g is not None and len(g) else pd.DataFrame()

    max_workers = max(1, int(os.getenv("STATCAST_EXPAND_MAX_WORKERS", "6")))
    frames: list[pd.DataFrame] = []
    if max_workers <= 1:
        for gpk in game_pks:
            frames.append(fetch_game(gpk))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(fetch_game, gpk) for gpk in game_pks]
            for fut in concurrent.futures.as_completed(futs):
                frames.append(fut.result())

    good = [f for f in frames if len(f)]
    if not good:
        logger.warning("Full-game expansion produced no rows; keeping original Statcast frame.")
        return df

    merged = pd.concat(good, axis=0, ignore_index=True)
    dedupe_cols = [c for c in ("game_pk", "at_bat_number", "pitch_number") if c in merged.columns]
    if len(dedupe_cols) == 3:
        merged = merged.drop_duplicates(subset=dedupe_cols, keep="last")

    merged = _apply_regular_season_filter(merged)
    if not bool(_add_roles(merged, ta)["offense_row"].any()):
        logger.warning("After full-game merge, still no offense rows for %s; keeping original.", ta)
        return df

    logger.info("Expanded Statcast for %s: %d -> %d pitch rows.", ta, len(df), len(merged))
    return merged


def download_team_season_statcast(team_abbrev: str, season: int) -> pd.DataFrame:
    """Pull Statcast for one club-season from Savant (chunked HTTP). Same filtering as the on-disk cache."""
    try:
        from pybaseball import cache

        cache.enable()
    except Exception:
        pass

    try:
        from pybaseball import statcast
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pybaseball is required to download Statcast. Install requirements.txt.",
        ) from exc

    start, end = _season_bounds(season)
    if start > end:
        return pd.DataFrame()

    logger.info("Statcast fetch %s %s..%s (first load can take a few minutes)", team_abbrev, start, end)
    try:
        raw = statcast(start, end, team=team_abbrev, verbose=False)
    except Exception as exc:
        logger.exception("Statcast download failed for %s %s", team_abbrev, season)
        raise RuntimeError(
            "Could not download Statcast from Baseball Savant (network, rate limit, or Savant error). "
            f"Details: {exc}",
        ) from exc

    if raw is None or len(raw) == 0:
        logger.warning("Statcast returned no rows for %s between %s and %s", team_abbrev, start, end)
        return pd.DataFrame()

    filtered = _apply_regular_season_filter(raw)
    return expand_statcast_team_frame_to_full_games(filtered, team_abbrev)


def statcast_require_local_only() -> bool:
    """If true, never download Statcast from Savant (local Parquet/pickle only).

    ``MLB_LOCAL_SITE=1`` implies the same behavior for iteration without network I/O.
    """
    if os.getenv("STATCAST_REQUIRE_LOCAL", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    if os.getenv("MLB_LOCAL_SITE", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return False


def try_load_statcast_local(team_abbrev: str, season: int) -> pd.DataFrame | None:
    """Return a frame from ``STATCAST_LOCAL_DIR`` if a non-empty extract exists."""
    for ext, read_fn in ((".parquet", pd.read_parquet), (".pkl", pd.read_pickle)):
        path = STATCAST_LOCAL_DIR / f"{season}_{team_abbrev}{ext}"
        if not path.is_file():
            continue
        try:
            df = read_fn(path)
        except Exception:
            logger.exception("Failed reading Statcast extract %s", path)
            continue
        if df is not None and len(df) > 0:
            logger.info("Loaded Statcast from local extract %s", path)
            return df
    return None


def build_team_record_from_statcast(df: pd.DataFrame, team_abbrev: str) -> dict[str, int]:
    """W–L for *team_abbrev* from final pitch scores in a Statcast frame (one row per game_pk)."""
    wins = losses = 0
    if df is None or len(df) == 0:
        return {"w": 0, "l": 0}
    need = ("game_pk", "home_team", "away_team", "post_home_score", "post_away_score")
    if not all(c in df.columns for c in need):
        return {"w": 0, "l": 0}
    ta = str(team_abbrev).strip().upper()
    for _, g in df.groupby("game_pk", sort=False):
        hs = pd.to_numeric(g["post_home_score"], errors="coerce").max()
        aws = pd.to_numeric(g["post_away_score"], errors="coerce").max()
        if pd.isna(hs) or pd.isna(aws):
            continue
        home = str(g["home_team"].iloc[0]).strip().upper()
        away = str(g["away_team"].iloc[0]).strip().upper()
        if home != ta and away != ta:
            continue
        hi, ai = int(hs), int(aws)
        if hi > ai:
            if home == ta:
                wins += 1
            else:
                losses += 1
        elif ai > hi:
            if away == ta:
                wins += 1
            else:
                losses += 1
    return {"w": wins, "l": losses}


def load_team_statcast_frame(team_abbrev: str, season: int) -> pd.DataFrame:
    """Load pitch-level Statcast: local extract first, then pickle cache, then Savant."""
    STATCAST_LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    local = try_load_statcast_local(team_abbrev, season)
    if local is not None:
        return local

    if statcast_require_local_only():
        raise RuntimeError(
            "Statcast is local-only (MLB_LOCAL_SITE or STATCAST_REQUIRE_LOCAL) but no extract exists "
            f"for {team_abbrev} {season} under {STATCAST_LOCAL_DIR}. "
            f"Run: python scripts/download_statcast_extracts.py --seasons {season} --abbrev {team_abbrev}",
        )

    try:
        from pybaseball import cache

        cache.enable()
    except Exception:
        pass

    try:
        import pybaseball  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "pybaseball is not installed and no local Statcast extract was found under "
            f"{STATCAST_LOCAL_DIR}. Run: pip install -r requirements.txt "
            f"or: python scripts/download_statcast_extracts.py --seasons {season} --abbrev {team_abbrev}",
        ) from exc

    STATCAST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = STATCAST_CACHE_DIR / f"{season}_{team_abbrev}.pkl"
    if cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < STATCAST_CACHE_TTL_SEC:
            cached = pd.read_pickle(cache_path)
            if len(cached) > 0:
                logger.info("Statcast cache hit %s", cache_path)
                return cached
            logger.info("Ignoring empty Statcast cache (will refetch): %s", cache_path)
            try:
                cache_path.unlink()
            except OSError:
                pass

    raw = download_team_season_statcast(team_abbrev, season)

    if len(raw) == 0:
        return raw

    raw.to_pickle(cache_path)
    return raw


def _pa_key(df: pd.DataFrame) -> pd.Series:
    return (
        df["game_pk"].astype(str)
        + "_"
        + df["inning"].astype(str)
        + "_"
        + df["inning_topbot"].astype(str)
        + "_"
        + df["at_bat_number"].astype(str)
    )


def _aggregate_pitch_rows(
    sub: pd.DataFrame,
    *,
    perspective: str,
) -> dict[str, Any]:
    """perspective: 'offense' (this team batting) or 'defense' (this team pitching/fielding)."""
    if len(sub) == 0:
        return {
            "pitches": 0,
            "plate_appearances": 0,
            "swing_rate": None,
            "whiff_rate": None,
            "zone_swing_rate": None,
            "chase_rate": None,
            "contact_rate": None,
            "called_strike_rate": None,
            "xwoba_on_contact": None,
            "avg_exit_velo_bip": None,
            "hard_hit_rate": None,
            "avg_launch_angle_bip": None,
            "groundball_rate": None,
            "flyball_rate": None,
            "popup_rate": None,
            "avg_iso_value_bip": None,
            "if_standard_pct": None,
            "if_strategic_pct": None,
            "of_strategic_pct": None,
        }

    desc = sub["description"]
    swing = _is_swing(desc)
    whiff = _is_whiff(desc)
    in_zone = _in_strike_zone(sub)
    called_k = desc.astype(str).str.lower() == "called_strike"
    bbe = _bbe_mask(sub)

    pitches = len(sub)
    swings = int(swing.sum())
    whiffs = int(whiff.sum())
    out_zone = ~in_zone
    swings_out = int((swing & out_zone).sum())
    pitches_out = int(out_zone.sum())
    swings_in = int((swing & in_zone).sum())
    pitches_in = int((in_zone).sum())
    contacts = int((swing & ~whiff).sum())

    xw = pd.to_numeric(sub.get("estimated_woba_using_speedangle"), errors="coerce")
    ev = pd.to_numeric(sub.get("launch_speed"), errors="coerce")
    iso_v = pd.to_numeric(sub.get("iso_value"), errors="coerce")
    la = pd.to_numeric(sub.get("launch_angle"), errors="coerce")
    bb_type = sub.get("bb_type")
    if bb_type is None:
        bb_type = pd.Series(np.nan, index=sub.index)
    else:
        bb_type = bb_type.astype(str).str.lower()

    pa_n = int(_pa_key(sub).nunique())

    hard_hit = bbe & ev.notna() & (ev >= 95.0)
    gb = bbe & bb_type.str.contains("ground", na=False)
    fb = bbe & (bb_type.str.contains("fly", na=False) | bb_type.str.contains("line", na=False))
    pu = bbe & bb_type.str.contains("popup", na=False)

    # Barrel rate: launch_speed_angle == 6 is the Statcast barrel bucket
    lsa = pd.to_numeric(sub.get("launch_speed_angle"), errors="coerce")
    barrel = bbe & (lsa == 6)

    # Full xwOBA: xwOBA on BBE, woba_value for walks/HBP/K (non-contact PAs)
    woba_val = pd.to_numeric(sub.get("woba_value"), errors="coerce")
    woba_den = pd.to_numeric(sub.get("woba_denom"), errors="coerce")
    pa_mask = woba_den == 1  # PAs that count for wOBA
    if pa_mask.any():
        # For BBE: use expected (xwOBA); for non-BBE PAs: use actual woba_value
        xwoba_full = pd.Series(np.nan, index=sub.index)
        xwoba_full.loc[bbe & xw.notna()] = xw.loc[bbe & xw.notna()]
        non_bbe_pa = pa_mask & ~bbe
        xwoba_full.loc[non_bbe_pa] = woba_val.loc[non_bbe_pa].fillna(0.0)
        xwoba_denom = pa_mask & xwoba_full.notna()
        full_xwoba = float(xwoba_full.loc[xwoba_denom].mean()) if xwoba_denom.any() else None
    else:
        full_xwoba = None

    if_standard = if_strategic = of_strategic = None
    if "if_fielding_alignment" in sub.columns and perspective == "defense":
        ifa = sub["if_fielding_alignment"].astype(str)
        if_standard = float((ifa == "Standard").mean()) if len(ifa) else None
        if_strategic = float((ifa.isin(["Strategic", "Infield shade"])).mean()) if len(ifa) else None
    if "of_fielding_alignment" in sub.columns and perspective == "defense":
        ofa = sub["of_fielding_alignment"].astype(str)
        of_strategic = float((ofa == "Strategic").mean()) if len(ofa) else None

    return {
        "pitches": pitches,
        "plate_appearances": pa_n,
        "swing_rate": float(swings / pitches) if pitches else None,
        "whiff_rate": float(whiffs / swings) if swings else None,
        "zone_swing_rate": float(swings_in / pitches_in) if pitches_in else None,
        "chase_rate": float(swings_out / pitches_out) if pitches_out else None,
        "contact_rate": float(contacts / swings) if swings else None,
        "called_strike_rate": float(called_k.sum() / pitches) if pitches else None,
        "xwoba_on_contact": float(xw.loc[bbe].mean()) if bbe.any() else None,
        "avg_exit_velo_bip": float(ev.loc[bbe].mean()) if bbe.any() else None,
        "hard_hit_rate": float(hard_hit.sum() / bbe.sum()) if bbe.any() else None,
        "barrel_rate": float(barrel.sum() / bbe.sum()) if bbe.any() else None,
        "xwoba": full_xwoba,
        "avg_launch_angle_bip": float(la.loc[bbe].mean()) if bbe.any() else None,
        "groundball_rate": float(gb.sum() / bbe.sum()) if bbe.any() else None,
        "flyball_rate": float(fb.sum() / bbe.sum()) if bbe.any() else None,
        "popup_rate": float(pu.sum() / bbe.sum()) if bbe.any() else None,
        "avg_iso_value_bip": float(iso_v.loc[bbe].mean()) if bbe.any() else None,
        "if_standard_pct": if_standard,
        "if_strategic_pct": if_strategic,
        "of_strategic_pct": of_strategic,
    }


def _pitch_type_table(sub: pd.DataFrame, *, min_pitches: int = 10) -> list[dict[str, Any]]:
    if len(sub) == 0:
        return []
    sub = sub.copy()
    sub["_pt"] = _pitch_type(sub)
    sub["_pl"] = _pitch_label(sub)
    desc = sub["description"]
    swing = _is_swing(desc)
    whiff = _is_whiff(desc)
    in_zone = _in_strike_zone(sub)
    out_zone = ~in_zone
    bbe = _bbe_mask(sub)
    xw = pd.to_numeric(sub.get("estimated_woba_using_speedangle"), errors="coerce")

    rows: list[dict[str, Any]] = []
    for pt, g in sub.groupby("_pt", sort=False):
        n = len(g)
        if n < min_pitches:
            continue
        sw = swing.loc[g.index]
        wf = whiff.loc[g.index]
        pitches_out = int(out_zone.loc[g.index].sum())
        swings_out = int((sw & out_zone.loc[g.index]).sum())
        bb = bbe.loc[g.index]
        label = str(g["_pl"].iloc[0])
        whiff_on_swings = wf.loc[g.index] & sw
        rows.append(
            {
                "pitch_type": str(pt),
                "pitch_label": label,
                "pitches": n,
                "swing_rate": float(sw.mean()),
                "whiff_rate": float(whiff_on_swings.sum() / sw.sum()) if sw.any() else None,
                "chase_rate": float(swings_out / pitches_out) if pitches_out else None,
                "xwoba_on_contact": float(xw.loc[g.index][bb].mean()) if bb.any() else None,
            }
        )
    rows.sort(key=lambda r: r["pitches"], reverse=True)
    return rows


def build_weekly_frames(df: pd.DataFrame, team_abbrev: str) -> list[dict[str, Any]]:
    """Return sorted weekly summaries (ISO week) for offense, pitching, defense context."""
    if df is None or len(df) == 0:
        return []

    d = _add_roles(df, team_abbrev)
    d["game_date"] = pd.to_datetime(d["game_date"], errors="coerce")
    d = d.loc[d["game_date"].notna()].copy()
    iso = d["game_date"].dt.isocalendar()
    d["_iy"] = iso.year.astype(int)
    d["_iw"] = iso.week.astype(int)
    d["_wk"] = d["_iy"].astype(str) + "-W" + d["_iw"].astype(str).str.zfill(2)

    weeks: list[dict[str, Any]] = []
    for wk, g in d.groupby("_wk", sort=True):
        g_off = g.loc[g["offense_row"]]
        g_def = g.loc[g["defense_row"]]
        w0 = g["game_date"].min()
        w1 = g["game_date"].max()
        weeks.append(
            {
                "week_key": str(wk),
                "week_start": w0.date().isoformat() if hasattr(w0, "date") else str(w0),
                "week_end": w1.date().isoformat() if hasattr(w1, "date") else str(w1),
                "offense": _aggregate_pitch_rows(g_off, perspective="offense"),
                "run_prevention": _aggregate_pitch_rows(g_def, perspective="defense"),
                "hitting_vs_pitch_types": _pitch_type_table(g_off),
                "pitching_pitch_types": _pitch_type_table(g_def),
            }
        )
    return weeks


# ---------------------------------------------------------------------------
# Chase-zone 2-D grid for heatmap visualisation
# ---------------------------------------------------------------------------

_GRID_NX = 12
_GRID_NY = 16
_GRID_X_RANGE = (-2.0, 2.0)
_GRID_Y_RANGE = (-0.5, 4.5)
_CHASE_SEASON_MONTHS = (4, 5, 6, 7, 8, 9)


def build_chase_zone_grid(df: pd.DataFrame) -> dict[str, Any] | None:
    """Bin pitches into a spatial grid by calendar month for chase-rate heatmap.

    Returns a dict suitable for JSON serialisation, or None if data is missing.
    """
    required = {"plate_x", "plate_z", "sz_top", "sz_bot", "description", "game_date"}
    if not required.issubset(df.columns):
        return None

    px = pd.to_numeric(df["plate_x"], errors="coerce")
    pz = pd.to_numeric(df["plate_z"], errors="coerce")
    valid = px.notna() & pz.notna()
    if valid.sum() < 50:
        return None

    szt = pd.to_numeric(df["sz_top"], errors="coerce")
    szb = pd.to_numeric(df["sz_bot"], errors="coerce")
    avg_sz_top = float(szt[valid].mean())
    avg_sz_bot = float(szb[valid].mean())

    swing = _is_swing(df["description"])
    in_zone = _in_strike_zone(df)

    # Bin indices (0-based, clipped to grid)
    x_edges = np.linspace(_GRID_X_RANGE[0], _GRID_X_RANGE[1], _GRID_NX + 1)
    y_edges = np.linspace(_GRID_Y_RANGE[0], _GRID_Y_RANGE[1], _GRID_NY + 1)
    xi = np.clip(np.digitize(px.values, x_edges) - 1, 0, _GRID_NX - 1)
    yi = np.clip(np.digitize(pz.values, y_edges) - 1, 0, _GRID_NY - 1)

    # Calendar month
    gd = pd.to_datetime(df["game_date"], errors="coerce")
    month = gd.dt.month.values

    months_out: list[dict[str, Any]] = []
    for mo in _CHASE_SEASON_MONTHS:
        mask = valid.values & (month == mo)
        if mask.sum() == 0:
            continue
        # Aggregate by (xi, yi) within this month
        cells: list[dict[str, Any]] = []
        cell_key = yi[mask] * _GRID_NX + xi[mask]
        sw_vals = swing.values[mask]
        iz_vals = in_zone.values[mask]
        for ck in np.unique(cell_key):
            sel = cell_key == ck
            n = int(sel.sum())
            sw = int(sw_vals[sel].sum())
            iz = int(iz_vals[sel].sum())
            cy = int(ck // _GRID_NX)
            cx = int(ck % _GRID_NX)
            cells.append({"x": cx, "y": cy, "n": n, "sw": sw, "iz": iz})
        months_out.append({"month": int(mo), "cells": cells})

    if not months_out:
        return None

    return {
        "sz_top": avg_sz_top,
        "sz_bot": avg_sz_bot,
        "zone_width": ZONE_WIDTH_FT,
        "nx": _GRID_NX,
        "ny": _GRID_NY,
        "x_range": list(_GRID_X_RANGE),
        "y_range": list(_GRID_Y_RANGE),
        "months": months_out,
    }


# ---------------------------------------------------------------------------
# Whiff-zone grid (same spatial grid as chase, but tracking whiffs on swings)
# ---------------------------------------------------------------------------


def build_whiff_zone_grid(df: pd.DataFrame) -> dict[str, Any] | None:
    """12x16 zone grid of whiff rate by pitch location."""
    required = {"plate_x", "plate_z", "sz_top", "sz_bot", "description", "game_date"}
    if not required.issubset(df.columns):
        return None

    px = pd.to_numeric(df["plate_x"], errors="coerce")
    pz = pd.to_numeric(df["plate_z"], errors="coerce")
    valid = px.notna() & pz.notna()
    if valid.sum() < 50:
        return None

    szt = pd.to_numeric(df["sz_top"], errors="coerce")
    szb = pd.to_numeric(df["sz_bot"], errors="coerce")
    avg_sz_top = float(szt[valid].mean())
    avg_sz_bot = float(szb[valid].mean())

    swing = _is_swing(df["description"])
    whiff = _is_whiff(df["description"])

    x_edges = np.linspace(_GRID_X_RANGE[0], _GRID_X_RANGE[1], _GRID_NX + 1)
    y_edges = np.linspace(_GRID_Y_RANGE[0], _GRID_Y_RANGE[1], _GRID_NY + 1)
    xi = np.clip(np.digitize(px.values, x_edges) - 1, 0, _GRID_NX - 1)
    yi = np.clip(np.digitize(pz.values, y_edges) - 1, 0, _GRID_NY - 1)

    gd = pd.to_datetime(df["game_date"], errors="coerce")
    month = gd.dt.month.values

    months_out: list[dict[str, Any]] = []
    for mo in _CHASE_SEASON_MONTHS:
        # Only count swings for whiff rate
        mask = valid.values & (month == mo) & swing.values
        if mask.sum() == 0:
            continue
        cells: list[dict[str, Any]] = []
        cell_key = yi[mask] * _GRID_NX + xi[mask]
        wh_vals = whiff.values[mask]
        for ck in np.unique(cell_key):
            sel = cell_key == ck
            n = int(sel.sum())
            wh = int(wh_vals[sel].sum())
            cy = int(ck // _GRID_NX)
            cx = int(ck % _GRID_NX)
            cells.append({"x": cx, "y": cy, "n": n, "wh": wh})
        months_out.append({"month": int(mo), "cells": cells})

    if not months_out:
        return None

    return {
        "sz_top": avg_sz_top,
        "sz_bot": avg_sz_bot,
        "zone_width": ZONE_WIDTH_FT,
        "nx": _GRID_NX,
        "ny": _GRID_NY,
        "x_range": list(_GRID_X_RANGE),
        "y_range": list(_GRID_Y_RANGE),
        "months": months_out,
    }


# ---------------------------------------------------------------------------
# Barrel grid: exit velo × launch angle
# ---------------------------------------------------------------------------

_BARREL_NX = 10  # EV bins
_BARREL_NY = 18  # LA bins
_BARREL_EV_RANGE = (60.0, 110.0)
_BARREL_LA_RANGE = (-30.0, 60.0)


def build_barrel_grid(df: pd.DataFrame) -> dict[str, Any] | None:
    """2D grid of EV × LA for barrel-rate heatmap."""
    required = {"launch_speed", "launch_angle", "launch_speed_angle", "type", "game_date"}
    if not required.issubset(df.columns):
        return None

    bbe = df[df["type"].astype(str).str.upper() == "X"].copy()
    ev = pd.to_numeric(bbe["launch_speed"], errors="coerce")
    la = pd.to_numeric(bbe["launch_angle"], errors="coerce")
    lsa = pd.to_numeric(bbe["launch_speed_angle"], errors="coerce")
    valid = ev.notna() & la.notna()
    if valid.sum() < 30:
        return None

    x_edges = np.linspace(_BARREL_EV_RANGE[0], _BARREL_EV_RANGE[1], _BARREL_NX + 1)
    y_edges = np.linspace(_BARREL_LA_RANGE[0], _BARREL_LA_RANGE[1], _BARREL_NY + 1)
    xi = np.clip(np.digitize(ev.values, x_edges) - 1, 0, _BARREL_NX - 1)
    yi = np.clip(np.digitize(la.values, y_edges) - 1, 0, _BARREL_NY - 1)

    barrel = (lsa == 6).values

    gd = pd.to_datetime(bbe["game_date"], errors="coerce")
    month = gd.dt.month.values

    months_out: list[dict[str, Any]] = []
    for mo in _CHASE_SEASON_MONTHS:
        mask = valid.values & (month == mo)
        if mask.sum() == 0:
            continue
        cells: list[dict[str, Any]] = []
        cell_key = yi[mask] * _BARREL_NX + xi[mask]
        brl_vals = barrel[mask]
        for ck in np.unique(cell_key):
            sel = cell_key == ck
            n = int(sel.sum())
            brl = int(brl_vals[sel].sum())
            cy = int(ck // _BARREL_NX)
            cx = int(ck % _BARREL_NX)
            cells.append({"x": cx, "y": cy, "n": n, "brl": brl})
        months_out.append({"month": int(mo), "cells": cells})

    if not months_out:
        return None

    return {
        "nx": _BARREL_NX,
        "ny": _BARREL_NY,
        "ev_range": list(_BARREL_EV_RANGE),
        "la_range": list(_BARREL_LA_RANGE),
        "months": months_out,
    }


# ---------------------------------------------------------------------------
# Spray-chart xwOBA grid: hc_x × hc_y
# ---------------------------------------------------------------------------

_SPRAY_N = 12
_SPRAY_X_RANGE = (0.0, 250.0)
_SPRAY_Y_RANGE = (0.0, 250.0)


def build_spray_xwoba_grid(df: pd.DataFrame) -> dict[str, Any] | None:
    """12x12 grid of hit coordinates colored by average xwOBA."""
    required = {"hc_x", "hc_y", "estimated_woba_using_speedangle", "type", "game_date"}
    if not required.issubset(df.columns):
        return None

    bbe = df[df["type"].astype(str).str.upper() == "X"].copy()
    hx = pd.to_numeric(bbe["hc_x"], errors="coerce")
    hy = pd.to_numeric(bbe["hc_y"], errors="coerce")
    xw = pd.to_numeric(bbe["estimated_woba_using_speedangle"], errors="coerce")
    valid = hx.notna() & hy.notna() & xw.notna()
    if valid.sum() < 30:
        return None

    x_edges = np.linspace(_SPRAY_X_RANGE[0], _SPRAY_X_RANGE[1], _SPRAY_N + 1)
    y_edges = np.linspace(_SPRAY_Y_RANGE[0], _SPRAY_Y_RANGE[1], _SPRAY_N + 1)
    xi = np.clip(np.digitize(hx.values, x_edges) - 1, 0, _SPRAY_N - 1)
    yi = np.clip(np.digitize(hy.values, y_edges) - 1, 0, _SPRAY_N - 1)

    gd = pd.to_datetime(bbe["game_date"], errors="coerce")
    month = gd.dt.month.values

    months_out: list[dict[str, Any]] = []
    for mo in _CHASE_SEASON_MONTHS:
        mask = valid.values & (month == mo)
        if mask.sum() == 0:
            continue
        cells: list[dict[str, Any]] = []
        cell_key = yi[mask] * _SPRAY_N + xi[mask]
        xw_vals = xw.values[mask]
        for ck in np.unique(cell_key):
            sel = cell_key == ck
            n = int(sel.sum())
            xw_sum = float(xw_vals[sel].sum())
            cy = int(ck // _SPRAY_N)
            cx = int(ck % _SPRAY_N)
            cells.append({"x": cx, "y": cy, "n": n, "xw": round(xw_sum, 4)})
        months_out.append({"month": int(mo), "cells": cells})

    if not months_out:
        return None

    return {
        "nx": _SPRAY_N,
        "ny": _SPRAY_N,
        "x_range": list(_SPRAY_X_RANGE),
        "y_range": list(_SPRAY_Y_RANGE),
        "months": months_out,
    }
