"""Pipeline that powers the React + D3 dashboard."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from functools import lru_cache

import numpy as np

from config import ALL_TEAMS, DIVISIONS, FORWARD_SIMULATIONS, LEAGUES, TEAM_TO_DIVISION
from data_source.mlb_api import build_record, completed_game_rows, fetch_schedule, split_schedule
from data_source.pitcher_stats import build_pitcher_quality

from ..schemas import (
    DashboardMeta,
    DashboardResponse,
    DivisionStanding,
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


def _copy_model(model):
    copy_fn = getattr(model, "model_copy", None)
    if callable(copy_fn):
        return copy_fn(deep=True)
    return model.copy(deep=True)


def _build_actual_points_by_team(
    schedule: list[dict],
    completed_games: list[dict],
) -> tuple[dict[str, list[WinPoint]], dict[str, int], list[str]]:
    season_dates = _season_dates(schedule)
    games_by_date: dict[str, list[dict]] = defaultdict(list)
    for game in completed_games:
        games_by_date[game["game_date"][:10]].append(game)

    wins_by_team = {team: 0 for team in ALL_TEAMS}
    actual_points_by_team = {team: [] for team in ALL_TEAMS}
    remaining_dates: list[str] = []
    completed_date_set = set(games_by_date)

    for game_date in season_dates:
        if game_date not in completed_date_set:
            remaining_dates.append(game_date)
            continue

        for game in games_by_date[game_date]:
            home_score = game.get("home_score")
            away_score = game.get("away_score")
            if home_score is None or away_score is None:
                continue
            home_team = game["home_name"]
            away_team = game["away_name"]
            if home_score > away_score:
                wins_by_team[home_team] += 1
            elif away_score > home_score:
                wins_by_team[away_team] += 1

        for team in ALL_TEAMS:
            actual_points_by_team[team].append(WinPoint(date=game_date, wins=wins_by_team[team]))

    return actual_points_by_team, wins_by_team, remaining_dates


def _build_team_ratings(
    snapshot: PosteriorSnapshot,
    ) -> tuple[TeamRatings, np.ndarray, dict[str, int]]:
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
    return TeamRatings(offense=offense_ratings, defense=defense_ratings), run_diff, team_to_idx


def _build_remaining_schedule_views(
    remaining_games: list[dict],
    run_diff: np.ndarray,
    team_to_idx: dict[str, int],
) -> dict[str, list[ScheduleGame]]:
    rd_min = float(run_diff.min())
    rd_max = float(run_diff.max())
    rd_range = rd_max - rd_min if rd_max > rd_min else 1.0
    schedules_by_team = {team: [] for team in ALL_TEAMS}

    for game in remaining_games:
        home_team = game["home_name"]
        away_team = game["away_name"]
        if home_team not in team_to_idx or away_team not in team_to_idx:
            continue

        away_strength = round((float(run_diff[team_to_idx[away_team]]) - rd_min) / rd_range, 3)
        home_strength = round((float(run_diff[team_to_idx[home_team]]) - rd_min) / rd_range, 3)
        game_date = game["game_date"][:10]

        schedules_by_team[home_team].append(
            ScheduleGame(
                date=game_date,
                opponent=away_team,
                is_home=True,
                opponent_strength=away_strength,
            )
        )
        schedules_by_team[away_team].append(
            ScheduleGame(
                date=game_date,
                opponent=home_team,
                is_home=False,
                opponent_strength=home_strength,
            )
        )

    return schedules_by_team


def _build_team_game_counts(games: list[dict]) -> dict[str, int]:
    counts = {team: 0 for team in ALL_TEAMS}
    for game in games:
        counts[game["home_name"]] += 1
        counts[game["away_name"]] += 1
    return counts


def _build_simulation_views(
    snapshot: PosteriorSnapshot,
    remaining_games: list[dict],
    actual_record: dict[str, dict[str, int]],
    actual_points_by_team: dict[str, list[WinPoint]],
    starting_wins_by_team: dict[str, int],
    season_dates: list[str],
    season: int = 0,
    n_sims: int = FORWARD_SIMULATIONS,
) -> dict[str, TeamSimulationView]:
    team_to_idx = {name: idx for idx, name in enumerate(snapshot.teams)}
    team_count = len(snapshot.teams)
    density_by_team = {team: [] for team in snapshot.teams}

    if not remaining_games:
        end_of_season_place: dict[str, int] = {}
        for division_teams in DIVISIONS.values():
            ranked = sorted(
                division_teams,
                key=lambda t: actual_record.get(t, {}).get("w", 0),
                reverse=True,
            )
            for place, t in enumerate(ranked, start=1):
                end_of_season_place[t] = place
        return {
            team: TeamSimulationView(
                team=team,
                division=TEAM_TO_DIVISION[team],
                actual_wins=actual_record.get(team, {}).get("w", 0),
                actual_losses=actual_record.get(team, {}).get("l", 0),
                actual_division_place=end_of_season_place[team],
                actual_points=actual_points_by_team[team],
                simulation_density=[],
                projected_final_wins=starting_wins_by_team.get(team, 0),
                projected_division_place=end_of_season_place[team],
                playoff_probability=0.0,
            )
            for team in snapshot.teams
        }

    rng = np.random.default_rng(seed=42)
    sample_idx = rng.integers(0, snapshot.draw_count, size=n_sims)
    mu_draws = snapshot.mu_array()[sample_idx]
    hfa_draws = snapshot.hfa_array()[sample_idx]
    offense_draws = snapshot.offense_array()[sample_idx]
    defense_draws = snapshot.defense_array()[sample_idx]
    park_draws = snapshot.park_array()[sample_idx]
    alpha_draws = snapshot.alpha_array()[sample_idx]
    bp_draws = snapshot.beta_pitcher_array()[sample_idx]
    bd_draws = snapshot.beta_division_array()[sample_idx]
    has_overdispersion = snapshot.alpha is not None

    if season == 0:
        season = snapshot.season
    all_pitcher_names = []
    for game in remaining_games:
        all_pitcher_names.append(game.get("home_probable_pitcher", ""))
        all_pitcher_names.append(game.get("away_probable_pitcher", ""))
    pq_map = build_pitcher_quality(season, tuple(sorted(set(all_pitcher_names))))

    cumulative_wins = np.zeros((n_sims, team_count), dtype=int)
    for team_name, record in actual_record.items():
        if team_name in team_to_idx:
            cumulative_wins[:, team_to_idx[team_name]] = record["w"]

    games_by_date: dict[str, list[dict]] = defaultdict(list)
    for game in remaining_games:
        games_by_date[game["game_date"][:10]].append(game)

    for game_date in season_dates:
        for game in games_by_date.get(game_date, []):
            home_name = game["home_name"]
            away_name = game["away_name"]

            home_idx = team_to_idx[home_name]
            away_idx = team_to_idx[away_name]
            hpq = pq_map.get(game.get("home_probable_pitcher", ""), 0.0)
            apq = pq_map.get(game.get("away_probable_pitcher", ""), 0.0)
            is_div = 1.0 if TEAM_TO_DIVISION.get(home_name) == TEAM_TO_DIVISION.get(away_name) else 0.0

            lambda_home = np.exp(
                mu_draws + hfa_draws + park_draws[:, home_idx]
                + offense_draws[:, home_idx] - defense_draws[:, away_idx]
                - bp_draws * apq
                + bd_draws * is_div
            )
            lambda_away = np.exp(
                mu_draws + park_draws[:, home_idx]
                + offense_draws[:, away_idx] - defense_draws[:, home_idx]
                - bp_draws * hpq
                + bd_draws * is_div
            )

            if has_overdispersion:
                rate_h = rng.gamma(alpha_draws, lambda_home / alpha_draws)
                rate_a = rng.gamma(alpha_draws, lambda_away / alpha_draws)
                home_runs = rng.poisson(rate_h)
                away_runs = rng.poisson(rate_a)
            else:
                home_runs = rng.poisson(lambda_home)
                away_runs = rng.poisson(lambda_away)

            home_wins = _resolve_ties(home_runs, away_runs, lambda_home, lambda_away, rng)
            cumulative_wins[:, home_idx] += home_wins
            cumulative_wins[:, away_idx] += ~home_wins

        for team_name, team_idx in team_to_idx.items():
            win_counts = np.bincount(cumulative_wins[:, team_idx], minlength=163)
            for wins in np.flatnonzero(win_counts):
                density_by_team[team_name].append(
                    SimulationDensityCell(
                        date=game_date,
                        wins=int(wins),
                        probability=round(int(win_counts[wins]) / n_sims, 6),
                    )
                )

    projected_final_wins = {
        team_name: int(round(float(np.median(cumulative_wins[:, team_idx]))))
        for team_name, team_idx in team_to_idx.items()
    }

    projected_division_place: dict[str, int] = {}
    for division_teams in DIVISIONS.values():
        ranked = sorted(division_teams, key=lambda t: projected_final_wins[t], reverse=True)
        for place, team_name in enumerate(ranked, start=1):
            projected_division_place[team_name] = place

    actual_division_place: dict[str, int] = {}
    for division_teams in DIVISIONS.values():
        ranked = sorted(
            division_teams,
            key=lambda t: actual_record.get(t, {}).get("w", 0),
            reverse=True,
        )
        for place, team_name in enumerate(ranked, start=1):
            actual_division_place[team_name] = place

    noisy_all_wins = cumulative_wins + rng.uniform(0, 0.01, size=cumulative_wins.shape)
    division_indices = {
        division_name: np.array([team_to_idx[name] for name in division_teams], dtype=int)
        for division_name, division_teams in DIVISIONS.items()
    }
    league_indices = {
        league_name: np.array(
            [team_to_idx[name] for division_name in division_names for name in DIVISIONS[division_name]],
            dtype=int,
        )
        for league_name, division_names in LEAGUES.items()
    }
    playoff_mask = np.zeros((n_sims, team_count), dtype=bool)
    for sim in range(n_sims):
        division_winners_by_league: dict[str, list[int]] = {"AL": [], "NL": []}
        for division_name, division_team_indices in division_indices.items():
            winner_idx = int(division_team_indices[np.argmax(noisy_all_wins[sim, division_team_indices])])
            playoff_mask[sim, winner_idx] = True
            division_winners_by_league[division_name[:2]].append(winner_idx)

        for league_name, league_team_indices in league_indices.items():
            division_winners = set(division_winners_by_league[league_name])
            wildcard_pool = np.array(
                [team_idx for team_idx in league_team_indices.tolist() if team_idx not in division_winners],
                dtype=int,
            )
            if wildcard_pool.size == 0:
                continue
            wildcard_order = np.argsort(-noisy_all_wins[sim, wildcard_pool])[:3]
            playoff_mask[sim, wildcard_pool[wildcard_order]] = True

    playoff_probability = {
        team_name: round(100.0 * float(playoff_mask[:, team_idx].mean()), 1)
        for team_name, team_idx in team_to_idx.items()
    }
    return {
        team_name: TeamSimulationView(
            team=team_name,
            division=TEAM_TO_DIVISION[team_name],
            actual_wins=actual_record.get(team_name, {}).get("w", 0),
            actual_losses=actual_record.get(team_name, {}).get("l", 0),
            actual_division_place=actual_division_place[team_name],
            actual_points=actual_points_by_team[team_name],
            simulation_density=density_by_team[team_name],
            projected_final_wins=projected_final_wins[team_name],
            projected_division_place=projected_division_place[team_name],
            playoff_probability=playoff_probability[team_name],
        )
        for team_name in snapshot.teams
    }


def _build_all_dashboard_payloads_uncached(
    season: int,
    force_refit: bool = False,
) -> dict[str, DashboardResponse]:
    schedule = fetch_schedule(season)
    completed, remaining = split_schedule(schedule)
    snapshot = fit_or_load_snapshot(
        season=season,
        completed_games=completed_game_rows(completed),
        teams=ALL_TEAMS,
        force_refit=force_refit,
    )
    actual_points_by_team, starting_wins_by_team, remaining_dates = _build_actual_points_by_team(
        schedule=schedule,
        completed_games=completed,
    )
    team_simulations = _build_simulation_views(
        snapshot=snapshot,
        remaining_games=remaining,
        actual_record=build_record(completed),
        actual_points_by_team=actual_points_by_team,
        starting_wins_by_team=starting_wins_by_team,
        season_dates=remaining_dates,
        season=season,
    )
    team_ratings, run_diff, team_to_idx = _build_team_ratings(snapshot)
    remaining_schedule_views = _build_remaining_schedule_views(remaining, run_diff, team_to_idx)
    completed_counts = _build_team_game_counts(completed)
    remaining_counts = _build_team_game_counts(remaining)
    generated_at = date.today().isoformat()

    division_standings_by_div: dict[str, list[DivisionStanding]] = {}
    for div_name, div_teams in DIVISIONS.items():
        division_standings_by_div[div_name] = sorted(
            [DivisionStanding(team=t, projected_wins=team_simulations[t].projected_final_wins)
             for t in div_teams],
            key=lambda s: s.projected_wins,
            reverse=True,
        )

    payloads: dict[str, DashboardResponse] = {}
    for team_name in snapshot.teams:
        payloads[team_name] = DashboardResponse(
            season=season,
            favorite_team=team_name,
            team_simulation=team_simulations[team_name],
            team_ratings=team_ratings,
            remaining_schedule=remaining_schedule_views[team_name],
            division_standings=division_standings_by_div,
            meta=DashboardMeta(
                generated_at=generated_at,
                games_completed=completed_counts[team_name],
                games_remaining=remaining_counts[team_name],
                model_source=snapshot.source,
                simulation_count=FORWARD_SIMULATIONS,
            ),
        )
    return payloads


@lru_cache(maxsize=4)
def _build_all_dashboard_payloads_cached(
    season: int,
) -> dict[str, DashboardResponse]:
    return _build_all_dashboard_payloads_uncached(
        season=season,
        force_refit=False,
    )


def clear_dashboard_cache() -> None:
    """Invalidate the in-memory dashboard payload cache."""
    _build_all_dashboard_payloads_cached.cache_clear()


def warm_dashboard_cache(season: int = DEFAULT_SEASON) -> None:
    """Materialize the LRU dashboard cache for *season* (may run a long MCMC fit)."""
    _build_all_dashboard_payloads_cached(season)


def build_dashboard_payload(
    season: int,
    favorite_team: str,
    force_refit: bool = False,
) -> DashboardResponse:
    if force_refit:
        _build_all_dashboard_payloads_cached.cache_clear()
        payloads = _build_all_dashboard_payloads_uncached(season=season, force_refit=True)
    else:
        payloads = _build_all_dashboard_payloads_cached(season=season)

    return _copy_model(payloads[favorite_team])
