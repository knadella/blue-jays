"""Shared configuration for MLB Forecast V2."""

from __future__ import annotations

import math
import os
from pathlib import Path
from urllib.parse import urlparse

def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


# Fly Machines set FLY_ALLOC_ID; used to default friendlier dashboard behavior in production.
_RUNNING_ON_FLY = bool(os.getenv("FLY_ALLOC_ID", "").strip())

# When there is no saved posterior yet, GET /api/dashboard can skip PyMC and use a fast
# prior bootstrap, then save it so later requests stay fast. Admin refit still runs full MCMC.
# Default ON when running on Fly; set INSTANT_DASHBOARD_PRIOR=false to force cold-start MCMC.
INSTANT_DASHBOARD_PRIOR = _env_bool(
    "INSTANT_DASHBOARD_PRIOR",
    default=_RUNNING_ON_FLY,
)


DEFAULT_SEASON = _env_int("MLB_SEASON", 2026)
POSTERIOR_RETENTION = 2 / 3

# If set, POST /api/admin/* requires header X-Admin-Key: <value> (recommended in production).
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip() or None

# If true, do not background-warm the dashboard on API startup (local dev only).
SKIP_DASHBOARD_WARMUP = os.getenv("SKIP_DASHBOARD_WARMUP", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

def _normalize_cors_origin(raw: str) -> str:
    """Strip whitespace/quotes and reduce to scheme://host[:port] (no path).

    Browsers send Origin without a path. If CORS_ORIGINS mistakenly includes
    e.g. https://user.github.io/repo-name, the match would fail.
    """
    o = raw.strip().strip('"').strip("'")
    if not o:
        return ""
    if "://" not in o:
        o = f"https://{o}"
    p = urlparse(o)
    if p.scheme in ("http", "https") and p.netloc:
        return f"{p.scheme}://{p.netloc}"
    return o.rstrip("/")


def _parse_cors_origins() -> list[str]:
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    seen: set[str] = set()
    out: list[str] = []
    for part in raw.split(","):
        n = _normalize_cors_origin(part)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


# Comma-separated origins for CORS (production frontend URL(s)).
CORS_ORIGINS = _parse_cors_origins()

# GitHub Pages sends Origin https://<user>.github.io (no /repo path). Allowing this regex
# avoids a silent production failure when Fly has data but CORS_ORIGINS was not set.
# Set ENABLE_GITHUB_PAGES_CORS=0 to disable. Custom GitHub Pages domains still need CORS_ORIGINS.
_ENABLE_GH_PAGES = os.getenv("ENABLE_GITHUB_PAGES_CORS", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "",
)
GITHUB_PAGES_CORS_ORIGIN_REGEX = (
    r"^https://[a-zA-Z0-9-]+\.github\.io$"
    if _ENABLE_GH_PAGES
    else None
)

# MCMC length for the main season fit (override on Fly for faster refits).
POSTERIOR_DRAWS = _env_int("POSTERIOR_DRAWS", 750)
POSTERIOR_TUNE = _env_int("POSTERIOR_TUNE", 750)
POSTERIOR_CHAINS = _env_int("POSTERIOR_CHAINS", 2)

# Lighter sampling for prior-season backfill (only seeds the current season).
PRIOR_BACKFILL_DRAWS = _env_int("PRIOR_BACKFILL_DRAWS", 400)
PRIOR_BACKFILL_TUNE = _env_int("PRIOR_BACKFILL_TUNE", 400)
PRIOR_BACKFILL_CHAINS = _env_int("PRIOR_BACKFILL_CHAINS", 1)

# Monthly “projection at month start” fits (cached under posteriors/<season>/monthly/).
MONTHLY_PROJECTION_DRAWS = _env_int("MONTHLY_PROJECTION_DRAWS", 280)
MONTHLY_PROJECTION_TUNE = _env_int("MONTHLY_PROJECTION_TUNE", 280)
MONTHLY_PROJECTION_CHAINS = _env_int("MONTHLY_PROJECTION_CHAINS", 1)

# First dashboard request with no saved snapshot: lighter MCMC so the HTTP
# request returns in minutes, not tens of minutes. Weekly admin refit uses full POSTERIOR_*.
COLD_START_POSTERIOR_DRAWS = _env_int("COLD_START_POSTERIOR_DRAWS", 400)
COLD_START_POSTERIOR_TUNE = _env_int("COLD_START_POSTERIOR_TUNE", 400)
COLD_START_POSTERIOR_CHAINS = _env_int("COLD_START_POSTERIOR_CHAINS", 2)

FORWARD_SIMULATIONS = int(os.getenv("FORWARD_SIMULATIONS", "2500"))
# Persistent disk on Fly.io: set POSTERIOR_CACHE_DIR=/data/posteriors and mount a volume on /data
_POSTERIOR_CACHE_ENV = os.getenv("POSTERIOR_CACHE_DIR", "").strip()
POSTERIOR_CACHE_DIR = (
    Path(_POSTERIOR_CACHE_ENV).expanduser()
    if _POSTERIOR_CACHE_ENV
    else Path(".cache/posteriors")
)
FRONTEND_DIST_DIR = Path("frontend/dist")
LEAGUE_BASELINE_RUNS = 4.5
DEFAULT_HFA_LOG_RUNS = 0.05

# ---------------------------------------------------------------------------
# Adaptive prior retention: prior-season influence decays as games accumulate
# ---------------------------------------------------------------------------
PRIOR_RETENTION_HALF_LIFE_GAMES = 400


def compute_prior_retention(
    n_games: int,
    half_life_games: int = PRIOR_RETENTION_HALF_LIFE_GAMES,
) -> float:
    """Prior-season retention that decays with current-season sample size.

    At 0 games: ~1.0  (lean heavily on prior season)
    At 400 games (~1/6 of season): ~0.5
    At 2400 games (full season): ~0.02
    """
    return math.exp(-math.log(2) * n_games / half_life_games)


# ---------------------------------------------------------------------------
# Recency weighting: recent games count more than early-season games
# ---------------------------------------------------------------------------
RECENCY_HALF_LIFE_DAYS = 30

# ---------------------------------------------------------------------------
# 2024 final regular-season records  (W, L)
# Source: baseball-reference.com/leagues/majors/2024-standings.shtml
# ---------------------------------------------------------------------------
RECORDS_2024 = {
    # AL East
    "New York Yankees":      (94, 68),
    "Baltimore Orioles":     (91, 71),
    "Boston Red Sox":        (81, 81),
    "Tampa Bay Rays":        (80, 82),
    "Toronto Blue Jays":     (74, 88),
    # AL Central
    "Cleveland Guardians":   (92, 69),
    "Kansas City Royals":    (86, 76),
    "Detroit Tigers":        (86, 76),
    "Minnesota Twins":       (82, 80),
    "Chicago White Sox":     (41, 121),
    # AL West
    "Houston Astros":        (88, 73),
    "Seattle Mariners":      (85, 77),
    "Texas Rangers":         (78, 84),
    "Oakland Athletics":     (69, 93),
    "Los Angeles Angels":    (63, 99),
    # NL East
    "Philadelphia Phillies": (95, 67),
    "Atlanta Braves":        (89, 73),
    "New York Mets":         (89, 73),
    "Washington Nationals":  (71, 91),
    "Miami Marlins":         (62, 100),
    # NL Central
    "Milwaukee Brewers":     (93, 69),
    "Chicago Cubs":          (83, 79),
    "St. Louis Cardinals":   (83, 79),
    "Cincinnati Reds":       (77, 85),
    "Pittsburgh Pirates":    (76, 86),
    # NL West
    "Los Angeles Dodgers":   (98, 64),
    "San Diego Padres":      (93, 69),
    "Arizona Diamondbacks":  (89, 73),
    "San Francisco Giants":  (80, 82),
    "Colorado Rockies":      (61, 101),
}

# ---------------------------------------------------------------------------
# Division / league structure
# ---------------------------------------------------------------------------
DIVISIONS = {
    "AL East":    ["New York Yankees", "Baltimore Orioles", "Boston Red Sox",
                   "Tampa Bay Rays", "Toronto Blue Jays"],
    "AL Central": ["Cleveland Guardians", "Kansas City Royals", "Detroit Tigers",
                   "Minnesota Twins", "Chicago White Sox"],
    "AL West":    ["Houston Astros", "Seattle Mariners", "Texas Rangers",
                   "Oakland Athletics", "Los Angeles Angels"],
    "NL East":    ["Philadelphia Phillies", "Atlanta Braves", "New York Mets",
                   "Washington Nationals", "Miami Marlins"],
    "NL Central": ["Milwaukee Brewers", "Chicago Cubs", "St. Louis Cardinals",
                   "Cincinnati Reds", "Pittsburgh Pirates"],
    "NL West":    ["Los Angeles Dodgers", "San Diego Padres", "Arizona Diamondbacks",
                   "San Francisco Giants", "Colorado Rockies"],
}

LEAGUES = {
    "AL": ["AL East", "AL Central", "AL West"],
    "NL": ["NL East", "NL Central", "NL West"],
}

# Reverse lookups (built once at import time)
TEAM_TO_DIVISION: dict[str, str] = {}
TEAM_TO_LEAGUE: dict[str, str] = {}
for _league, _divs in LEAGUES.items():
    for _div in _divs:
        for _team in DIVISIONS[_div]:
            TEAM_TO_DIVISION[_team] = _div
            TEAM_TO_LEAGUE[_team] = _league

ALL_TEAMS = sorted(RECORDS_2024.keys())

# ---------------------------------------------------------------------------
# Abbreviations & display helpers
# ---------------------------------------------------------------------------
TEAM_ABBREVS = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC", "Chicago White Sox": "CHW",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET",
    "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB", "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}

# Handle API name variations (e.g. Oakland moved to Sacramento in 2025)
TEAM_NAME_ALIASES = {
    "Athletics": "Oakland Athletics",
}

# ---------------------------------------------------------------------------
# Colors for frontend charts
# ---------------------------------------------------------------------------
DIVISION_COLORS = {
    "AL East":    "#1B5E7B",
    "AL Central": "#C45B3E",
    "AL West":    "#4A7C59",
    "NL East":    "#8B3A3A",
    "NL Central": "#5B6A8A",
    "NL West":    "#8A7340",
}

TEAM_COLORS = {
    "Arizona Diamondbacks": "#A71930", "Atlanta Braves": "#CE1141",
    "Baltimore Orioles": "#DF4601", "Boston Red Sox": "#BD3039",
    "Chicago Cubs": "#0E3386", "Chicago White Sox": "#27251F",
    "Cincinnati Reds": "#C6011F", "Cleveland Guardians": "#00385D",
    "Colorado Rockies": "#333366", "Detroit Tigers": "#0C2340",
    "Houston Astros": "#002D62", "Kansas City Royals": "#004687",
    "Los Angeles Angels": "#BA0021", "Los Angeles Dodgers": "#005A9C",
    "Miami Marlins": "#00A3E0", "Milwaukee Brewers": "#FFC52F",
    "Minnesota Twins": "#002B5C", "New York Mets": "#002D72",
    "New York Yankees": "#003087", "Oakland Athletics": "#003831",
    "Philadelphia Phillies": "#E81828", "Pittsburgh Pirates": "#FDB827",
    "San Diego Padres": "#2F241D", "San Francisco Giants": "#FD5A1E",
    "Seattle Mariners": "#0C2C56", "St. Louis Cardinals": "#C41E3A",
    "Tampa Bay Rays": "#092C5C", "Texas Rangers": "#003278",
    "Toronto Blue Jays": "#134A8E", "Washington Nationals": "#AB0003",
}
