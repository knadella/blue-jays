"""Pipeline that powers the React + D3 dashboard."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import numpy as np

from config import ALL_TEAMS, DIVISIONS, FORWARD_SIMULATIONS, LEAGUES, TEAM_TO_DIVISION
from data_source.mlb_api import build_record, completed_game_rows, fetch_schedule, split_schedule

from ..schemas import (
    DashboardMeta,
    DashboardResponse,
    ScheduleGame,
    SimulationDensityCell,
    TeamRating,
    TeamRatings,
    TeamSimulationView,
    WinPoint,
)
from .modeling import fit_or_load_snapshot
from .storage import PosteriorSnapshot


def _resolve_ties(
    home_runs: np.ndarray,
    away_runs: np.ndarray,
    lambda_home: np.ndarray,
    lambda_away: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    ties = home_runs == away_runs
    if not np.any(ties):
        return home_runs > away_runs
    tie_prob = lambda_home[ties] / (lambda_home[ties] + lambda_away[ties])
    home_runs[ties] += rng.random(np.count_nonzero(ties)) < tie_prob
    away_runs[ties] += home_runs[ties] == away_runs[ties]
    return home_runs > away_runs


def _season_dates(schedule: list[dict]) -> list[str]:
    return sorted({game["game_date"][:10] for game in schedule})


def _build_actual_points_for_team(
    schedule: list[dict],
    completed_games: list[dict],
    team: str,
) -> tuple[list[WinPoint], int, list[str]]:
    season_dates = _season_dates(schedule)
    games_by_date: dict[str, list[dict]] = defaultdict(list)
    for game in completed_games:
        games_by_date[game["game_date"][:10]].append(game)

    wins = 0
    actual_points: list[WinPoint] = []
    remaining_dates: list[str] = []
    completed_date_set = set(games_by_date)

    for game_date in season_dates:
        if game_date not in completed_date_set:
            remaining_dates.append(game_date)
            continue

        for game in games_by_date[game_date]:
            if team not in {game["home_name"], game["away_name"]}:
                continue
            home_score = game.get("home_score")
            away_score = game.get("away_score")
            if home_score is None or away_score is None:
                continue
            if game["home_name"] == team and home_score > away_score:
                wins += 1
            elif game["away_name"] == team and away_score > home_score:
                wins += 1

        actual_points.append(WinPoint(date=game_date, wins=wins))

    return actual_points, wins, remaining_dates


def _build_simulation_density_for_team(
    snapshot: PosteriorSnapshot,
    remaining_games: list[dict],
    actual_record: dict[str, dict[str, int]],
    team: str,
    starting_wins: int,
    season_dates: list[str],
    n_sims: int = FORWARD_SIMULATIONS,
) -> tuple[list[SimulationDensityCell], int, int, float]:
    team_to_idx = {name: idx for idx, name in enumerate(snapshot.teams)}
    if not remaining_games:
        return [], starting_wins, 1, 0.0

    rng = np.random.default_rng(seed=42)
    sample_idx = rng.integers(0, snapshot.draw_count, size=n_sims)
    mu_draws = snapshot.mu_array()[sample_idx]
    hfa_draws = snapshot.hfa_array()[sample_idx]
    offense_draws = snapshot.offense_array()[sample_idx]
    defense_draws = snapshot.defense_array()[sample_idx]

    team_idx = team_to_idx[team]
    cumulative_wins = np.zeros((n_sims, len(snapshot.teams)), dtype=int)
    for team_name, record in actual_record.items():
        if team_name in team_to_idx:
            cumulative_wins[:, team_to_idx[team_name]] = record["w"]

    games_by_date: dict[str, list[dict]] = defaultdict(list)
    for game in remaining_games:
        games_by_date[game["game_date"][:10]].append(game)

    density_cells: list[SimulationDensityCell] = []
    for game_date in season_dates:
        for game in games_by_date.get(game_date, []):
            home_name = game["home_name"]
            away_name = game["away_name"]

            home_idx = team_to_idx[home_name]
            away_idx = team_to_idx[away_name]
            lambda_home = np.exp(
                mu_draws + hfa_draws + offense_draws[:, home_idx] - defense_draws[:, away_idx]
            )
            lambda_away = np.exp(
                mu_draws + offense_draws[:, away_idx] - defense_draws[:, home_idx]
            )
            home_runs = rng.poisson(lambda_home)
            away_runs = rng.poisson(lambda_away)
            home_wins = _resolve_ties(home_runs, away_runs, lambda_home, lambda_away, rng)
            cumulative_wins[:, home_idx] += home_wins
            cumulative_wins[:, away_idx] += ~home_wins

        unique_wins, counts = np.unique(cumulative_wins[:, team_idx], return_counts=True)
        for wins, count in zip(unique_wins.tolist(), counts.tolist()):
            density_cells.append(
                SimulationDensityCell(
                    date=game_date,
                    wins=int(wins),
                    probability=round(count / n_sims, 6),
                )
            )

    final_team_wins = cumulative_wins[:, team_idx]
    projected_final_wins = int(round(float(np.median(final_team_wins))))

    division = TEAM_TO_DIVISION[team]
    division_team_indices = np.array([team_to_idx[name] for name in DIVISIONS[division]], dtype=int)
    noisy_division_wins = cumulative_wins[:, division_team_indices] + rng.uniform(
        0,
        0.01,
        size=(n_sims, len(division_team_indices)),
    )
    division_order = np.argsort(-noisy_division_wins, axis=1)
    division_places = []
    target_local_index = int(np.where(division_team_indices == team_idx)[0][0])
    for sim in range(n_sims):
        place = int(np.where(division_order[sim] == target_local_index)[0][0]) + 1
        division_places.append(place)
    place_counts = np.bincount(division_places, minlength=len(division_team_indices) + 1)
    projected_division_place = int(np.argmax(place_counts[1:]) + 1)

    playoff_count = 0
    for sim in range(n_sims):
        division_winners: set[str] = set()
        for league_divisions in LEAGUES.values():
            for division_name in league_divisions:
                division_teams = DIVISIONS[division_name]
                winner = max(
                    division_teams,
                    key=lambda name: cumulative_wins[sim, team_to_idx[name]] + rng.uniform(0, 0.01),
                )
                division_winners.add(winner)

        if team in division_winners:
            playoff_count += 1
            continue

        league_prefix = TEAM_TO_DIVISION[team][:2]
        league_teams = [
            name for name in snapshot.teams if TEAM_TO_DIVISION[name].startswith(league_prefix)
        ]
        wildcard_pool = [name for name in league_teams if name not in division_winners]
        wildcard_pool.sort(
            key=lambda name: cumulative_wins[sim, team_to_idx[name]] + rng.uniform(0, 0.01),
            reverse=True,
        )
        if team in wildcard_pool[:3]:
            playoff_count += 1

    playoff_probability = round(100.0 * playoff_count / n_sims, 1)
    return density_cells, projected_final_wins, projected_division_place, playoff_probability


def build_dashboard_payload(
    season: int,
    favorite_team: str,
    force_refit: bool = False,
) -> DashboardResponse:
    schedule = fetch_schedule(season)
    completed, remaining = split_schedule(schedule)
    snapshot = fit_or_load_snapshot(
        season=season,
        completed_games=completed_game_rows(completed),
        teams=ALL_TEAMS,
        force_refit=force_refit,
    )
    actual_points, starting_wins, remaining_dates = _build_actual_points_for_team(
        schedule=schedule,
        completed_games=completed,
        team=favorite_team,
    )
    simulation_density = _build_simulation_density_for_team(
        snapshot=snapshot,
        remaining_games=remaining,
        actual_record=build_record(completed),
        team=favorite_team,
        starting_wins=starting_wins,
        season_dates=remaining_dates,
    )
    density_cells, projected_final_wins, projected_division_place, playoff_probability = simulation_density

    def _team_game(g: dict) -> bool:
        return favorite_team in {g["home_name"], g["away_name"]}

    team_completed = sum(1 for g in completed if _team_game(g))
    team_remaining = sum(1 for g in remaining if _team_game(g))

    mu_median = float(np.median(snapshot.mu_array()))
    offense_medians = np.median(snapshot.offense_array(), axis=0)
    defense_medians = np.median(snapshot.defense_array(), axis=0)
    offense_runs = np.exp(mu_median + offense_medians)
    defense_runs = np.exp(mu_median - defense_medians)

    offense_ratings = sorted(
        [TeamRating(team=name, value=round(float(offense_runs[i]), 2))
         for i, name in enumerate(snapshot.teams)],
        key=lambda r: r.value,
        reverse=True,
    )
    defense_ratings = sorted(
        [TeamRating(team=name, value=round(float(defense_runs[i]), 2))
         for i, name in enumerate(snapshot.teams)],
        key=lambda r: r.value,
    )

    team_to_idx = {name: idx for idx, name in enumerate(snapshot.teams)}
    run_diff = offense_runs - defense_runs
    rd_min = float(run_diff.min())
    rd_max = float(run_diff.max())
    rd_range = rd_max - rd_min if rd_max > rd_min else 1.0

    schedule_games: list[ScheduleGame] = []
    for g in remaining:
        if favorite_team not in {g["home_name"], g["away_name"]}:
            continue
        is_home = g["home_name"] == favorite_team
        opponent = g["away_name"] if is_home else g["home_name"]
        if opponent not in team_to_idx:
            continue
        opp_idx = team_to_idx[opponent]
        strength = round((float(run_diff[opp_idx]) - rd_min) / rd_range, 3)
        schedule_games.append(ScheduleGame(
            date=g["game_date"][:10],
            opponent=opponent,
            is_home=is_home,
            opponent_strength=strength,
        ))

    return DashboardResponse(
        season=season,
        favorite_team=favorite_team,
        team_simulation=TeamSimulationView(
            team=favorite_team,
            division=TEAM_TO_DIVISION[favorite_team],
            actual_points=actual_points,
            simulation_density=density_cells,
            projected_final_wins=projected_final_wins,
            projected_division_place=projected_division_place,
            playoff_probability=playoff_probability,
        ),
        team_ratings=TeamRatings(
            offense=offense_ratings,
            defense=defense_ratings,
        ),
        remaining_schedule=schedule_games,
        meta=DashboardMeta(
            generated_at=date.today().isoformat(),
            games_completed=team_completed,
            games_remaining=team_remaining,
            model_source=snapshot.source,
            simulation_count=FORWARD_SIMULATIONS,
        ),
    )
