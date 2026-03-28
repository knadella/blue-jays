"""Fetch, cache, and score starting pitcher quality from the MLB Stats API."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import statsapi

from config import POSTERIOR_CACHE_DIR

logger = logging.getLogger(__name__)

_PITCHER_CACHE_DIR = POSTERIOR_CACHE_DIR.parent / "pitcher_stats"
_MIN_IP_FOR_QUALITY = 20.0
_BATCH_SIZE = 40


def _cache_path(season: int) -> Path:
    _PITCHER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _PITCHER_CACHE_DIR / f"{season}.json"


def _load_cache(season: int) -> dict[str, dict]:
    path = _cache_path(season)
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_cache(season: int, data: dict[str, dict]) -> None:
    _cache_path(season).write_text(json.dumps(data, indent=2))


@lru_cache(maxsize=4)
def _roster_name_map(season: int) -> dict[str, int]:
    """Build a comprehensive name -> player ID map from all team rosters."""
    try:
        teams = statsapi.get("teams", {"sportId": 1, "season": season})
        team_ids = [t["id"] for t in teams.get("teams", [])]
    except Exception:
        return {}

    name_to_id: dict[str, int] = {}
    for tid in team_ids:
        for roster_type in ("depthChart", "fullSeason"):
            try:
                raw = statsapi.get(
                    "team_roster",
                    {"teamId": tid, "rosterType": roster_type, "season": season},
                )
                for entry in raw.get("roster", []):
                    person = entry.get("person", {})
                    name = person.get("fullName", "")
                    pid = person.get("id")
                    if name and pid and name not in name_to_id:
                        name_to_id[name] = pid
            except Exception:
                continue
    return name_to_id


def _resolve_pitcher_id(name: str, season: int) -> Optional[int]:
    """Resolve a pitcher name to a player ID using roster data + fallback."""
    roster_map = _roster_name_map(season)
    pid = roster_map.get(name)
    if pid is not None:
        return pid

    if season > 2000:
        prev_map = _roster_name_map(season - 1)
        pid = prev_map.get(name)
        if pid is not None:
            return pid

    try:
        results = statsapi.lookup_player(name)
        for r in results:
            if r.get("primaryPosition", {}).get("abbreviation") == "P":
                return r["id"]
        if results:
            return results[0]["id"]
    except Exception:
        pass
    return None


def _fetch_stats_batch(
    player_ids: list[int], season: int,
) -> dict[int, dict]:
    """Fetch pitching season stats for a batch of player IDs."""
    out: dict[int, dict] = {}
    ids_str = ",".join(str(pid) for pid in player_ids)
    try:
        raw = statsapi.get(
            "people",
            {
                "personIds": ids_str,
                "hydrate": f"stats(group=[pitching],type=[season],season={season})",
            },
        )
        for person in raw.get("people", []):
            pid = person["id"]
            stat_groups = person.get("stats", [])
            if not stat_groups:
                continue
            splits = stat_groups[0].get("splits", [])
            if not splits:
                continue
            s = splits[0].get("stat", {})
            ip_str = s.get("inningsPitched", "0")
            try:
                ip = float(ip_str)
            except (ValueError, TypeError):
                ip = 0.0
            era_str = s.get("era", "")
            try:
                era = float(era_str)
            except (ValueError, TypeError):
                era = None
            out[pid] = {
                "era": era,
                "ip": ip,
                "whip": s.get("whip"),
                "wins": s.get("wins"),
                "losses": s.get("losses"),
                "strikeouts": s.get("strikeOuts"),
                "walks": s.get("baseOnBalls"),
                "home_runs_allowed": s.get("homeRuns"),
                "hits": s.get("hits"),
            }
    except Exception as exc:
        logger.warning("Batch pitcher stat fetch failed: %s", exc)
    return out


@lru_cache(maxsize=4)
def build_pitcher_quality(
    season: int,
    pitcher_names: tuple[str, ...],
) -> dict[str, float]:
    """Return a dict mapping pitcher name -> quality score.

    Quality is z-scored so that 0 = league average, positive = better.
    Uses the specified season's stats; falls back to season-1 for missing
    pitchers, then to 0.0 (league average) for unknowns.
    """
    cache = _load_cache(season)
    names_needing_ids = [n for n in set(pitcher_names) if n and n not in cache]

    if names_needing_ids:
        logger.info("Resolving %d new pitcher names for season %d", len(names_needing_ids), season)
        new_ids: dict[str, int] = {}
        for name in names_needing_ids:
            pid = _resolve_pitcher_id(name, season)
            if pid is not None:
                new_ids[name] = pid

        all_ids = list(new_ids.values())
        stats_by_id: dict[int, dict] = {}
        for i in range(0, len(all_ids), _BATCH_SIZE):
            batch = all_ids[i : i + _BATCH_SIZE]
            stats_by_id.update(_fetch_stats_batch(batch, season))

        prev_stats_by_id: dict[int, dict] = {}
        ids_missing_current = [
            pid for pid in all_ids if pid not in stats_by_id or (stats_by_id[pid].get("ip") or 0) < _MIN_IP_FOR_QUALITY
        ]
        if ids_missing_current:
            for i in range(0, len(ids_missing_current), _BATCH_SIZE):
                batch = ids_missing_current[i : i + _BATCH_SIZE]
                prev_stats_by_id.update(_fetch_stats_batch(batch, season - 1))

        for name, pid in new_ids.items():
            s = stats_by_id.get(pid, {})
            ip = s.get("ip", 0) or 0
            if ip >= _MIN_IP_FOR_QUALITY and s.get("era") is not None:
                cache[name] = {"id": pid, "season": season, **s}
            else:
                ps = prev_stats_by_id.get(pid, {})
                pip = ps.get("ip", 0) or 0
                if pip >= _MIN_IP_FOR_QUALITY and ps.get("era") is not None:
                    cache[name] = {"id": pid, "season": season - 1, **ps}
                else:
                    cache[name] = {"id": pid, "season": None, "era": None, "ip": 0}

        for name in names_needing_ids:
            if name not in cache:
                cache[name] = {"id": None, "season": None, "era": None, "ip": 0}

        _save_cache(season, cache)

    eras = [
        cache[n]["era"]
        for n in set(pitcher_names)
        if n and n in cache and cache[n].get("era") is not None
    ]
    if eras:
        league_mean_era = float(np.mean(eras))
        league_std_era = max(float(np.std(eras)), 0.3)
    else:
        league_mean_era = 4.2
        league_std_era = 1.0

    quality: dict[str, float] = {}
    for name in set(pitcher_names):
        if not name:
            continue
        entry = cache.get(name)
        if entry and entry.get("era") is not None:
            quality[name] = (league_mean_era - entry["era"]) / league_std_era
        else:
            quality[name] = 0.0

    return quality


def pitcher_quality_arrays(
    games: list[dict],
    season: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (home_pitcher_quality, away_pitcher_quality) arrays aligned to games.

    Positive values = better pitcher (lower ERA than average).
    """
    all_pitcher_names = []
    for g in games:
        all_pitcher_names.append(g.get("home_pitcher", ""))
        all_pitcher_names.append(g.get("away_pitcher", ""))

    quality_map = build_pitcher_quality(season, tuple(sorted(set(all_pitcher_names))))

    home_q = np.array([quality_map.get(g.get("home_pitcher", ""), 0.0) for g in games])
    away_q = np.array([quality_map.get(g.get("away_pitcher", ""), 0.0) for g in games])
    return home_q, away_q
