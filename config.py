"""Shared configuration — Blue-Jays-only, descriptive Statcast view."""

from __future__ import annotations

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


_RUNNING_ON_FLY = bool(os.getenv("FLY_ALLOC_ID", "").strip())

DEFAULT_SEASON = _env_int("MLB_SEASON", 2026)

# If set, POST /api/admin/* requires header X-Admin-Key: <value> (recommended in production).
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip() or None


def _normalize_cors_origin(raw: str) -> str:
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


CORS_ORIGINS = _parse_cors_origins()

MLB_LOCAL_SITE = _env_bool("MLB_LOCAL_SITE", default=False)

_gh_pages_env = os.getenv("ENABLE_GITHUB_PAGES_CORS", "").strip().lower()
if MLB_LOCAL_SITE:
    _ENABLE_GH_PAGES = False
elif _gh_pages_env in ("1", "true", "yes", "on"):
    _ENABLE_GH_PAGES = True
elif _gh_pages_env in ("0", "false", "no", "off"):
    _ENABLE_GH_PAGES = False
else:
    _ENABLE_GH_PAGES = _RUNNING_ON_FLY

GITHUB_PAGES_CORS_ORIGIN_REGEX = (
    r"^https://[a-zA-Z0-9-]+\.github\.io$"
    if _ENABLE_GH_PAGES
    else None
)

# Generic per-app cache root (overridden when a Fly volume is mounted at /data).
_CACHE_ENV = os.getenv("APP_CACHE_DIR", "").strip()
APP_CACHE_DIR = Path(_CACHE_ENV).expanduser() if _CACHE_ENV else Path(".cache")

# ---------------------------------------------------------------------------
# Team metadata — Blue Jays + their opponents (still need division/abbrev/colors
# for game results and league-relative monthly ranks).
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

TEAM_TO_DIVISION: dict[str, str] = {}
for _div, _teams in DIVISIONS.items():
    for _team in _teams:
        TEAM_TO_DIVISION[_team] = _div

ALL_TEAMS = sorted(TEAM_TO_DIVISION.keys())

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

TEAM_NAME_ALIASES = {
    "Athletics": "Oakland Athletics",
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

# MLB StatsAPI numeric team ids, keyed by abbreviation.
TEAM_IDS = {
    "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111, "CHC": 112, "CHW": 145,
    "CIN": 113, "CLE": 114, "COL": 115, "DET": 116, "HOU": 117, "KC": 118,
    "LAA": 108, "LAD": 119, "MIA": 146, "MIL": 158, "MIN": 142, "NYM": 121,
    "NYY": 147, "OAK": 133, "PHI": 143, "PIT": 134, "SD": 135, "SF": 137,
    "SEA": 136, "STL": 138, "TB": 139, "TEX": 140, "TOR": 141, "WSH": 120,
}

# Reverse of TEAM_ABBREVS: abbreviation -> full name.
ABBREV_TO_NAME = {abbrev: name for name, abbrev in TEAM_ABBREVS.items()}

# The team shown by default, and the set offered in the team picker.
DEFAULT_TEAM_ABBREV = "TOR"
SELECTABLE_TEAMS = ["TOR", "NYY"]


def resolve_team(abbrev: str | None) -> tuple[str, str, int]:
    """Map a team abbreviation to ``(abbrev, full_name, mlb_id)``.

    Falls back to the default team for unknown/missing input so callers can
    pass an untrusted query param straight through.
    """
    ab = (abbrev or DEFAULT_TEAM_ABBREV).upper()
    if ab not in TEAM_IDS or ab not in ABBREV_TO_NAME:
        ab = DEFAULT_TEAM_ABBREV
    return ab, ABBREV_TO_NAME[ab], TEAM_IDS[ab]
