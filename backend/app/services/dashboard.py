"""Pipeline that powers the React + D3 dashboard."""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date
from functools import lru_cache

import numpy as np

from config import (
    ALL_TEAMS,
    DEFAULT_SEASON,
    DIVISIONS,
    FORWARD_SIMULATIONS,
    INSTANT_DASHBOARD_PRIOR,
    LEAGUES,
    PRIOR_BACKFILL_CHAINS,
    PRIOR_BACKFILL_DRAWS,
    PRIOR_BACKFILL_TUNE,
    TEAM_TO_DIVISION,
)
from data_source.mlb_api import (
    build_record,
    completed_game_rows,
    fetch_schedule,
    split_schedule,
    summarize_team_performance,
)
from data_source.pitcher_stats import build_pitcher_quality

from ..schemas import (
    DashboardMeta,
    DashboardResponse,
    DivisionStanding,
    MonthlyRunRatePoint,
    ScheduleGame,
    SimulationDensityCell,
    TeamRating,
    TeamRatings,
    TeamRatingVsActual,
    TeamSimulationView,
    WinPoint,
)
from .modeling import _load_prior_seed, fit_or_load_monthly_snapshot, fit_or_load_snapshot
from .storage import PosteriorSnapshot

_MONTH_LABEL: dict[int, str] = {
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
}


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


def _team_rating_vs_actual(
    team_name: str,
    team_ratings: TeamRatings,
    perf_summary: dict[str, dict[str, float]],
) -> TeamRatingVsActual:
    def pick_value(ratings: list[TeamRating], name: str) -> float:
        for r in ratings:
            if r.team == name:
                return r.value
        raise KeyError(name)

    off_proj = pick_value(team_ratings.offense, team_name)
    def_proj = pick_value(team_ratings.defense, team_name)
    row = perf_summary.get(team_name, {})
    games = float(row.get("games", 0.0))
    actual_off: float | None = None
    actual_def: float | None = None
    if games > 0:
        actual_off = round(float(row["runs_for_per_game"]), 2)
        actual_def = round(float(row["runs_against_per_game"]), 2)
    return TeamRatingVsActual(
        runs_scored_per_game_projected=off_proj,
        runs_scored_per_game_actual=actual_off,
        runs_allowed_per_game_projected=def_proj,
        runs_allowed_per_game_actual=actual_def,
    )


def _season_as_of_calendar(season: int, completed: list[dict], today: date) -> date:
    """Latest calendar day used for in-season monthly cutoffs (through September)."""
    in_year: list[date] = []
    prefix = str(season)
    for g in completed:
        gd = g["game_date"][:10]
        if gd.startswith(prefix):
            in_year.append(date.fromisoformat(gd))
    cap = date(season, 9, 30)
    if not in_year:
        return min(today, cap)
    last_played = max(in_year)
    return min(max(today, last_played), cap)


def _team_run_rates_from_snapshot(snap: PosteriorSnapshot, team: str) -> tuple[float, float]:
    idx = {n: i for i, n in enumerate(snap.teams)}[team]
    mu_m = float(np.median(snap.mu_array()))
    off_m = np.median(snap.offense_array(), axis=0)
    def_m = np.median(snap.defense_array(), axis=0)
    scored = round(float(np.exp(mu_m + off_m[idx])), 2)
    allowed = round(float(np.exp(mu_m - def_m[idx])), 2)
    return scored, allowed


def _team_ytd_run_rates_through(
    completed: list[dict],
    team: str,
    end: date,
    season: int,
) -> tuple[float | None, float | None, int]:
    end_s = end.isoformat()
    lo = f"{season}-02-20"
    subset = [g for g in completed if lo <= g["game_date"][:10] <= end_s]
    perf = summarize_team_performance(subset)
    row = perf.get(team)
    if not row or row["games"] <= 0:
        return None, None, 0
    return (
        round(float(row["runs_for_per_game"]), 2),
        round(float(row["runs_against_per_game"]), 2),
        int(row["games"]),
    )


def _build_league_monthly_projection_templates(
    season: int,
    completed: list[dict],
    completed_rows: list[dict],
    as_of_cal: date,
) -> list[tuple[int, dict[str, tuple[float, float]]]]:
    rng0 = np.random.default_rng(season * 99_001)
    prior = _load_prior_seed(
        season,
        ALL_TEAMS,
        PRIOR_BACKFILL_DRAWS,
        PRIOR_BACKFILL_TUNE,
        PRIOR_BACKFILL_CHAINS,
        rng0,
    )
    templates: list[tuple[int, dict[str, tuple[float, float]]]] = []
    for month in range(4, 10):
        if date(season, month, 1) > as_of_cal:
            break
        m_rng = np.random.default_rng(season * 1000 + month)
        snap = fit_or_load_monthly_snapshot(
            season,
            month,
            completed_rows,
            ALL_TEAMS,
            prior,
            m_rng,
        )
        prior = snap
        rates = {t: _team_run_rates_from_snapshot(snap, t) for t in snap.teams}
        templates.append((month, rates))
    return templates


def _monthly_run_rate_points_for_team(
    team: str,
    season: int,
    completed: list[dict],
    as_of_cal: date,
    templates: list[tuple[int, dict[str, tuple[float, float]]]],
) -> list[MonthlyRunRatePoint]:
    pts: list[MonthlyRunRatePoint] = []
    for month, rates in templates:
        if team not in rates:
            continue
        po, pa = rates[team]
        last_d = date(season, month, calendar.monthrange(season, month)[1])
        cutoff = min(last_d, as_of_cal)
        ao, ad, ngames = _team_ytd_run_rates_through(completed, team, cutoff, season)
        pts.append(
            MonthlyRunRatePoint(
                month=month,
                label=_MONTH_LABEL[month],
                runs_scored_projected=po,
                runs_allowed_projected=pa,
                runs_scored_actual_szn_to_date=ao,
                runs_allowed_actual_szn_to_date=ad,
                games_played_through=ngames,
            )
        )
    return pts


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


def _opponent_strength_values_for_team(
    games: list[dict],
    team: str,
    run_diff: np.ndarray,
    team_to_idx: dict[str, int],
) -> list[float]:
    """Per-game opponent difficulty in [0, 1], same scaling as ScheduleGame.opponent_strength."""
    rd_min = float(run_diff.min())
    rd_max = float(run_diff.max())
    rd_range = rd_max - rd_min if rd_max > rd_min else 1.0
    values: list[float] = []
    for game in games:
        home_team = game["home_name"]
        away_team = game["away_name"]
        if home_team == team:
            opponent = away_team
        elif away_team == team:
            opponent = home_team
        else:
            continue
        if opponent not in team_to_idx:
            continue
        opp_idx = team_to_idx[opponent]
        values.append((float(run_diff[opp_idx]) - rd_min) / rd_range)
    return values


def schedule_strength_10(
    games: list[dict],
    team: str,
    run_diff: np.ndarray,
    team_to_idx: dict[str, int],
) -> float | None:
    """Mean opponent difficulty on a 0–10 scale (higher = harder). None if no games."""
    strengths = _opponent_strength_values_for_team(games, team, run_diff, team_to_idx)
    if not strengths:
        return None
    return round(10.0 * float(np.mean(strengths)), 2)


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


def _build_streaks(completed_games: list[dict]) -> dict[str, str]:
    """Compute current streak string (e.g. 'W3', 'L1') for each team."""
    # Build chronological list of (winner, loser) per game
    team_results: dict[str, list[str]] = {team: [] for team in ALL_TEAMS}
    sorted_games = sorted(completed_games, key=lambda g: g.get("game_date", ""))
    for g in sorted_games:
        home, away = g["home_name"], g["away_name"]
        hs, as_ = g.get("home_score"), g.get("away_score")
        if hs is None or as_ is None:
            continue
        if hs > as_:
            team_results[home].append("W")
            team_results[away].append("L")
        elif as_ > hs:
            team_results[away].append("W")
            team_results[home].append("L")

    streaks: dict[str, str] = {}
    for team, results in team_results.items():
        if not results:
            streaks[team] = "-"
            continue
        last = results[-1]
        count = 0
        for r in reversed(results):
            if r == last:
                count += 1
            else:
                break
        streaks[team] = f"{last}{count}"
    return streaks


def _build_run_differentials(completed_games: list[dict]) -> dict[str, int]:
    """Compute total run differential (runs scored - runs allowed) per team."""
    runs_for: dict[str, int] = {team: 0 for team in ALL_TEAMS}
    runs_against: dict[str, int] = {team: 0 for team in ALL_TEAMS}
    for g in completed_games:
        home, away = g["home_name"], g["away_name"]
        hs, as_ = g.get("home_score"), g.get("away_score")
        if hs is None or as_ is None:
            continue
        runs_for[home] += hs
        runs_against[home] += as_
        runs_for[away] += as_
        runs_against[away] += hs
    return {team: runs_for[team] - runs_against[team] for team in ALL_TEAMS}


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
        dashboard_instant_bootstrap=INSTANT_DASHBOARD_PRIOR,
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
    streaks = _build_streaks(completed)
    run_differentials = _build_run_differentials(completed)
    for team_name, sim in team_simulations.items():
        sim.streak = streaks.get(team_name, "-")
        sim.run_differential = run_differentials.get(team_name, 0)
    for team_name in snapshot.teams:
        sim = team_simulations[team_name]
        team_simulations[team_name] = sim.model_copy(
            update={
                "schedule_strength_played": schedule_strength_10(
                    completed, team_name, run_diff, team_to_idx
                ),
                "schedule_strength_remaining": schedule_strength_10(
                    remaining, team_name, run_diff, team_to_idx
                ),
            },
        )
    generated_at = date.today().isoformat()

    division_standings_by_div: dict[str, list[DivisionStanding]] = {}
    for div_name, div_teams in DIVISIONS.items():
        division_standings_by_div[div_name] = sorted(
            [DivisionStanding(team=t, projected_wins=team_simulations[t].projected_final_wins)
             for t in div_teams],
            key=lambda s: s.projected_wins,
            reverse=True,
        )

    perf_summary = summarize_team_performance(completed)
    completed_rows = completed_game_rows(completed)
    as_of_cal = _season_as_of_calendar(season, completed, date.today())
    try:
        month_templates = _build_league_monthly_projection_templates(
            season, completed, completed_rows, as_of_cal
        )
    except Exception:
        month_templates = []

    payloads: dict[str, DashboardResponse] = {}
    for team_name in snapshot.teams:
        payloads[team_name] = DashboardResponse(
            season=season,
            favorite_team=team_name,
            team_simulation=team_simulations[team_name],
            team_ratings=team_ratings,
            team_rating_vs_actual=_team_rating_vs_actual(team_name, team_ratings, perf_summary),
            monthly_run_rates=_monthly_run_rate_points_for_team(
                team_name, season, completed, as_of_cal, month_templates
            ),
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
