"""Compute game-level features from schedule data for the Bayesian model.

Features:
  - rest_days: days since each team's previous game (capped, log-scaled)
  - momentum: rolling win rate over last N games for each team
  - is_division: whether the two teams share a division
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import numpy as np

from config import TEAM_TO_DIVISION

_REST_CAP = 7
_MOMENTUM_WINDOW = 10


def compute_rest_days(games: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Return (home_rest, away_rest) arrays of log-scaled rest days.

    Rest = days since team's last game. First game of season gets rest = _REST_CAP.
    Values are log(1 + rest_days) to compress the scale.
    """
    last_game_date: dict[str, str] = {}
    home_rest = np.zeros(len(games), dtype=float)
    away_rest = np.zeros(len(games), dtype=float)

    for i, g in enumerate(games):
        gd = g["game_date"][:10]
        home = g["home_team"]
        away = g["away_team"]

        for team, arr in [(home, home_rest), (away, away_rest)]:
            prev = last_game_date.get(team)
            if prev is None:
                rest = _REST_CAP
            else:
                rest = min(_date_diff(prev, gd), _REST_CAP)
            arr[i] = np.log1p(rest)
            last_game_date[team] = gd

    return home_rest, away_rest


def compute_momentum(games: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Return (home_momentum, away_momentum): rolling win rate over last N games.

    Values are centered at 0: momentum = win_rate - 0.5, so positive = hot streak.
    Before a team has enough games, returns 0.0 (neutral).
    """
    team_results: dict[str, list[float]] = defaultdict(list)
    home_mom = np.zeros(len(games), dtype=float)
    away_mom = np.zeros(len(games), dtype=float)

    for i, g in enumerate(games):
        home = g["home_team"]
        away = g["away_team"]
        hr = g["home_runs"]
        ar = g["away_runs"]

        for team, arr in [(home, home_mom), (away, away_mom)]:
            history = team_results[team]
            if len(history) >= _MOMENTUM_WINDOW:
                arr[i] = np.mean(history[-_MOMENTUM_WINDOW:]) - 0.5
            else:
                arr[i] = 0.0

        home_won = float(hr > ar)
        team_results[home].append(home_won)
        team_results[away].append(1.0 - home_won)

    return home_mom, away_mom


def compute_division_indicator(games: list[dict]) -> np.ndarray:
    """Return array of 1.0 if both teams share a division, 0.0 otherwise."""
    return np.array([
        1.0 if TEAM_TO_DIVISION.get(g["home_team"]) == TEAM_TO_DIVISION.get(g["away_team"])
        else 0.0
        for g in games
    ])


def _date_diff(d1: str, d2: str) -> int:
    """Days between two YYYY-MM-DD strings."""
    dt1 = datetime.strptime(d1, "%Y-%m-%d")
    dt2 = datetime.strptime(d2, "%Y-%m-%d")
    return (dt2 - dt1).days
