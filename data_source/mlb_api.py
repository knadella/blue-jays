"""Fetch MLB schedule and game results via the MLB Stats API."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import statsapi

from config import TEAM_NAME_ALIASES, TEAM_TO_DIVISION


def _normalize_team_name(name: str) -> str:
    return TEAM_NAME_ALIASES.get(name, name)


def _is_known_team(name: str) -> bool:
    return _normalize_team_name(name) in TEAM_TO_DIVISION


@lru_cache(maxsize=4)
def fetch_schedule(season: int) -> list[dict]:
    """Return every regular-season game for *season* as a list of dicts.

    Each dict has keys: game_id, game_date, status, home_name, away_name,
    home_score, away_score, game_type, etc.
    """
    raw = statsapi.schedule(season=season, sportId=1)
    games = []
    for g in raw:
        if g.get("game_type") != "R":
            continue
        g["home_name"] = _normalize_team_name(g["home_name"])
        g["away_name"] = _normalize_team_name(g["away_name"])
        if not (_is_known_team(g["home_name"]) and _is_known_team(g["away_name"])):
            continue
        games.append(g)
    games.sort(key=lambda g: g["game_date"])
    return games


def split_schedule(games: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split a full schedule into (completed, remaining) game lists."""
    completed = [g for g in games if g.get("status") == "Final"]
    remaining = [g for g in games if g.get("status") != "Final"]
    return completed, remaining


def detect_season() -> int:
    """Pick the best season to display.

    If any 2026 regular-season games are already Final, use 2026.
    Otherwise fall back to 2025 (completed season for demo).
    """
    current_year = date.today().year
    try:
        today_str = date.today().isoformat()
        recent = statsapi.schedule(
            start_date=f"{current_year}-01-01",
            end_date=today_str,
            sportId=1,
        )
        finals = [
            g for g in recent
            if g.get("game_type") == "R" and g.get("status") == "Final"
        ]
        if finals:
            return current_year
    except Exception:
        pass
    return current_year - 1


def get_team_upcoming_games(
    remaining_games: list[dict], team: str, limit: int = 5
) -> list[dict]:
    """Return the next *limit* games for *team* from the remaining schedule."""
    upcoming = [
        g for g in remaining_games
        if g["home_name"] == team or g["away_name"] == team
    ]
    return upcoming[:limit]


def build_record(completed_games: list[dict]) -> dict[str, dict[str, int]]:
    """Compute current W-L for every team from completed games."""
    record: dict[str, dict[str, int]] = {}
    for g in completed_games:
        home, away = g["home_name"], g["away_name"]
        record.setdefault(home, {"w": 0, "l": 0})
        record.setdefault(away, {"w": 0, "l": 0})
        hs, as_ = g.get("home_score", 0), g.get("away_score", 0)
        if hs > as_:
            record[home]["w"] += 1
            record[away]["l"] += 1
        elif as_ > hs:
            record[away]["w"] += 1
            record[home]["l"] += 1
    return record


def completed_game_rows(completed_games: list[dict]) -> list[dict]:
    """Return normalized game-level rows for model fitting."""
    rows: list[dict] = []
    for game in completed_games:
        home = game["home_name"]
        away = game["away_name"]
        home_score = game.get("home_score")
        away_score = game.get("away_score")
        if home_score is None or away_score is None:
            continue
        rows.append(
            {
                "game_id": game.get("game_id"),
                "game_date": game["game_date"][:10],
                "home_team": home,
                "away_team": away,
                "home_runs": int(home_score),
                "away_runs": int(away_score),
            }
        )
    return rows


def summarize_team_performance(completed_games: list[dict]) -> dict[str, dict[str, float]]:
    """Aggregate wins and run environment stats for each team."""
    summary: dict[str, dict[str, float]] = {}
    for game in completed_games:
        home = game["home_name"]
        away = game["away_name"]
        home_score = game.get("home_score")
        away_score = game.get("away_score")
        if home_score is None or away_score is None:
            continue

        for team in (home, away):
            summary.setdefault(
                team,
                {
                    "games": 0.0,
                    "wins": 0.0,
                    "losses": 0.0,
                    "runs_for": 0.0,
                    "runs_against": 0.0,
                },
            )

        summary[home]["games"] += 1
        summary[away]["games"] += 1
        summary[home]["runs_for"] += float(home_score)
        summary[home]["runs_against"] += float(away_score)
        summary[away]["runs_for"] += float(away_score)
        summary[away]["runs_against"] += float(home_score)

        if home_score > away_score:
            summary[home]["wins"] += 1
            summary[away]["losses"] += 1
        elif away_score > home_score:
            summary[away]["wins"] += 1
            summary[home]["losses"] += 1

    for team, values in summary.items():
        games = max(values["games"], 1.0)
        values["win_pct"] = values["wins"] / games
        values["runs_for_per_game"] = values["runs_for"] / games
        values["runs_against_per_game"] = values["runs_against"] / games

    return summary
