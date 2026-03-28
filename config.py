"""Shared configuration for MLB Forecast V2."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_SEASON = 2026
POSTERIOR_RETENTION = 2 / 3
POSTERIOR_DRAWS = 1000
POSTERIOR_TUNE = 1000
POSTERIOR_CHAINS = 4
FORWARD_SIMULATIONS = int(os.getenv("FORWARD_SIMULATIONS", "2500"))
POSTERIOR_CACHE_DIR = Path(".cache/posteriors")
FRONTEND_DIST_DIR = Path("frontend/dist")
LEAGUE_BASELINE_RUNS = 4.5
DEFAULT_HFA_LOG_RUNS = 0.05

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
