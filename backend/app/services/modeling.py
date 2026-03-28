"""Bayesian hierarchical Poisson model fitting and summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from config import (
    DEFAULT_HFA_LOG_RUNS,
    LEAGUE_BASELINE_RUNS,
    POSTERIOR_CHAINS,
    POSTERIOR_DRAWS,
    POSTERIOR_RETENTION,
    POSTERIOR_TUNE,
)
from data_source.mlb_api import (
    completed_game_rows,
    fetch_schedule,
    split_schedule,
    summarize_team_performance,
)

from .storage import PosteriorSnapshot, load_latest_snapshot, save_snapshot


@dataclass
class TeamIntervals:
    low: float
    median: float
    high: float


def credible_interval(samples: np.ndarray) -> TeamIntervals:
    return TeamIntervals(
        low=float(np.percentile(samples, 10)),
        median=float(np.percentile(samples, 50)),
        high=float(np.percentile(samples, 90)),
    )


def _sample_prior_snapshot(
    season: int,
    teams: list[str],
    prior_snapshot: Optional[PosteriorSnapshot],
    draws: int,
    rng: np.random.Generator,
    source: str,
) -> PosteriorSnapshot:
    team_count = len(teams)
    baseline_mu = np.log(LEAGUE_BASELINE_RUNS)
    baseline_hfa = DEFAULT_HFA_LOG_RUNS

    prior_offense_mean = np.zeros(team_count)
    prior_defense_mean = np.zeros(team_count)
    mu_mean = baseline_mu
    hfa_mean = baseline_hfa

    if prior_snapshot is not None and prior_snapshot.teams == teams:
        prior_offense_mean = POSTERIOR_RETENTION * prior_snapshot.offense_array().mean(axis=0)
        prior_defense_mean = POSTERIOR_RETENTION * prior_snapshot.defense_array().mean(axis=0)
        mu_mean = (
            POSTERIOR_RETENTION * prior_snapshot.mu_array().mean()
            + (1 - POSTERIOR_RETENTION) * baseline_mu
        )
        hfa_mean = (
            POSTERIOR_RETENTION * prior_snapshot.hfa_array().mean()
            + (1 - POSTERIOR_RETENTION) * baseline_hfa
        )

    offense = rng.normal(loc=prior_offense_mean, scale=0.08, size=(draws, team_count))
    defense = rng.normal(loc=prior_defense_mean, scale=0.08, size=(draws, team_count))
    offense -= offense.mean(axis=1, keepdims=True)
    defense -= defense.mean(axis=1, keepdims=True)

    snapshot = PosteriorSnapshot(
        season=season,
        generated_at=datetime.now(timezone.utc).isoformat(),
        source=source,
        teams=teams,
        mu=rng.normal(loc=mu_mean, scale=0.08, size=draws).tolist(),
        hfa=rng.normal(loc=hfa_mean, scale=0.02, size=draws).tolist(),
        offense=offense.tolist(),
        defense=defense.tolist(),
    )
    save_snapshot(snapshot)
    return snapshot


def _proxy_prior_snapshot(
    season: int,
    teams: list[str],
    draws: int,
    rng: np.random.Generator,
) -> Optional[PosteriorSnapshot]:
    """Build a proxy prior from the previous season's team run profile."""
    if season <= 2000:
        return None

    try:
        prior_schedule = fetch_schedule(season - 1)
        completed, _ = split_schedule(prior_schedule)
        performance = summarize_team_performance(completed)
    except Exception:
        return None

    if len(completed) < 1000:
        return None

    league_runs_for = []
    home_runs = []
    away_runs = []
    for game in completed:
        hs = game.get("home_score")
        as_ = game.get("away_score")
        if hs is None or as_ is None:
            continue
        home_runs.append(float(hs))
        away_runs.append(float(as_))
        league_runs_for.extend([float(hs), float(as_)])

    if not league_runs_for:
        return None

    baseline_mu = np.log(float(np.mean(league_runs_for)))
    home_rate = max(float(np.mean(home_runs)), 0.1)
    away_rate = max(float(np.mean(away_runs)), 0.1)
    hfa_mean = float(np.clip(np.log(home_rate / away_rate), 0.0, 0.15))

    offense_means = []
    defense_means = []
    for team in teams:
        team_stats = performance.get(team)
        if not team_stats:
            offense_means.append(0.0)
            defense_means.append(0.0)
            continue

        runs_for = max(team_stats["runs_for_per_game"], 0.25)
        runs_against = max(team_stats["runs_against_per_game"], 0.25)
        offense_means.append(np.log(runs_for / np.exp(baseline_mu)))
        defense_means.append(np.log(np.exp(baseline_mu) / runs_against))

    offense_mean = np.asarray(offense_means, dtype=float)
    defense_mean = np.asarray(defense_means, dtype=float)
    offense_mean -= offense_mean.mean()
    defense_mean -= defense_mean.mean()

    offense = rng.normal(loc=offense_mean, scale=0.05, size=(draws, len(teams)))
    defense = rng.normal(loc=defense_mean, scale=0.05, size=(draws, len(teams)))
    offense -= offense.mean(axis=1, keepdims=True)
    defense -= defense.mean(axis=1, keepdims=True)

    return PosteriorSnapshot(
        season=season - 1,
        generated_at=datetime.now(timezone.utc).isoformat(),
        source="prior-season-proxy",
        teams=teams,
        mu=rng.normal(loc=baseline_mu, scale=0.04, size=draws).tolist(),
        hfa=rng.normal(loc=hfa_mean, scale=0.01, size=draws).tolist(),
        offense=offense.tolist(),
        defense=defense.tolist(),
    )


def _load_prior_seed(
    season: int,
    teams: list[str],
    draws: int,
    tune: int,
    chains: int,
    rng: np.random.Generator,
) -> Optional[PosteriorSnapshot]:
    prior_snapshot = load_latest_snapshot(season - 1)
    if prior_snapshot is not None and prior_snapshot.teams == teams:
        return prior_snapshot

    if season <= 2000:
        return None

    try:
        prior_schedule = fetch_schedule(season - 1)
        completed, _ = split_schedule(prior_schedule)
    except Exception:
        return _proxy_prior_snapshot(season=season, teams=teams, draws=draws, rng=rng)

    if len(completed) < 1000:
        return _proxy_prior_snapshot(season=season, teams=teams, draws=draws, rng=rng)

    older_snapshot = load_latest_snapshot(season - 2)
    if older_snapshot is None or older_snapshot.teams != teams:
        older_snapshot = _proxy_prior_snapshot(season=season - 1, teams=teams, draws=draws, rng=rng)

    return _fit_snapshot_from_games(
        season=season - 1,
        completed_games=completed_game_rows(completed),
        teams=teams,
        prior_snapshot=older_snapshot,
        draws=draws,
        tune=tune,
        chains=chains,
        rng=rng,
        source="pymc-fit-prior-backfill",
    )


def _fit_snapshot_from_games(
    season: int,
    completed_games: list[dict],
    teams: list[str],
    prior_snapshot: Optional[PosteriorSnapshot],
    draws: int,
    tune: int,
    chains: int,
    rng: np.random.Generator,
    source: str,
) -> PosteriorSnapshot:
    if len(completed_games) < 10:
        return _sample_prior_snapshot(
            season=season,
            teams=teams,
            prior_snapshot=prior_snapshot,
            draws=draws,
            rng=rng,
            source="prior-bootstrap" if prior_snapshot is None else f"{prior_snapshot.source}-bootstrap",
        )

    try:
        import pymc as pm
        import pytensor.tensor as pt
        if not hasattr(pm, "Model"):
            raise RuntimeError("PyMC import did not expose Model.")
    except (ImportError, RuntimeError):
        return _sample_prior_snapshot(
            season=season,
            teams=teams,
            prior_snapshot=prior_snapshot,
            draws=draws,
            rng=rng,
            source="prior-fallback" if prior_snapshot is None else f"{prior_snapshot.source}-fallback",
        )

    team_index = {team: idx for idx, team in enumerate(teams)}
    home_team_idx = np.asarray([team_index[g["home_team"]] for g in completed_games], dtype=int)
    away_team_idx = np.asarray([team_index[g["away_team"]] for g in completed_games], dtype=int)
    home_runs = np.asarray([g["home_runs"] for g in completed_games], dtype=int)
    away_runs = np.asarray([g["away_runs"] for g in completed_games], dtype=int)

    baseline_mu = np.log(LEAGUE_BASELINE_RUNS)
    prior_offense_mean = np.zeros(len(teams))
    prior_defense_mean = np.zeros(len(teams))
    mu_mean = baseline_mu
    hfa_mean = DEFAULT_HFA_LOG_RUNS

    if prior_snapshot is not None and prior_snapshot.teams == teams:
        prior_offense_mean = POSTERIOR_RETENTION * prior_snapshot.offense_array().mean(axis=0)
        prior_defense_mean = POSTERIOR_RETENTION * prior_snapshot.defense_array().mean(axis=0)
        mu_mean = (
            POSTERIOR_RETENTION * prior_snapshot.mu_array().mean()
            + (1 - POSTERIOR_RETENTION) * baseline_mu
        )
        hfa_mean = (
            POSTERIOR_RETENTION * prior_snapshot.hfa_array().mean()
            + (1 - POSTERIOR_RETENTION) * DEFAULT_HFA_LOG_RUNS
        )

    coords = {"team": teams, "game": np.arange(len(completed_games))}
    with pm.Model(coords=coords):
        mu = pm.Normal("mu", mu=mu_mean, sigma=0.2)
        hfa = pm.Normal("hfa", mu=hfa_mean, sigma=0.02)
        sigma_off = pm.HalfNormal("sigma_off", sigma=0.15)
        sigma_def = pm.HalfNormal("sigma_def", sigma=0.15)

        offense_offset = pm.Normal(
            "offense_offset",
            mu=prior_offense_mean,
            sigma=sigma_off,
            dims="team",
        )
        defense_offset = pm.Normal(
            "defense_offset",
            mu=prior_defense_mean,
            sigma=sigma_def,
            dims="team",
        )
        offense = pm.Deterministic(
            "offense",
            offense_offset - pt.mean(offense_offset),
            dims="team",
        )
        defense = pm.Deterministic(
            "defense",
            defense_offset - pt.mean(defense_offset),
            dims="team",
        )

        log_lambda_home = mu + hfa + offense[home_team_idx] - defense[away_team_idx]
        log_lambda_away = mu + offense[away_team_idx] - defense[home_team_idx]

        pm.Poisson("home_runs", mu=pm.math.exp(log_lambda_home), observed=home_runs, dims="game")
        pm.Poisson("away_runs", mu=pm.math.exp(log_lambda_away), observed=away_runs, dims="game")

        idata = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            target_accept=0.9,
            progressbar=False,
            random_seed=season,
        )

    posterior = idata.posterior.stack(sample=("chain", "draw"))
    snapshot = PosteriorSnapshot(
        season=season,
        generated_at=datetime.now(timezone.utc).isoformat(),
        source=source,
        teams=teams,
        mu=posterior["mu"].values.tolist(),
        hfa=posterior["hfa"].values.tolist(),
        offense=posterior["offense"].transpose("sample", "team").values.tolist(),
        defense=posterior["defense"].transpose("sample", "team").values.tolist(),
    )
    save_snapshot(snapshot)
    return snapshot


def fit_or_load_snapshot(
    season: int,
    completed_games: list[dict],
    teams: list[str],
    force_refit: bool = False,
    draws: int = POSTERIOR_DRAWS,
    tune: int = POSTERIOR_TUNE,
    chains: int = POSTERIOR_CHAINS,
) -> PosteriorSnapshot:
    """Fit the PyMC model or reuse the latest stored snapshot."""
    if not force_refit:
        existing = load_latest_snapshot(season)
        if existing is not None and existing.teams == teams:
            return existing

    rng = np.random.default_rng(seed=season)
    prior_snapshot = _load_prior_seed(
        season=season,
        teams=teams,
        draws=draws,
        tune=tune,
        chains=chains,
        rng=rng,
    )
    return _fit_snapshot_from_games(
        season=season,
        completed_games=completed_games,
        teams=teams,
        prior_snapshot=prior_snapshot,
        draws=draws,
        tune=tune,
        chains=chains,
        rng=rng,
        source="pymc-fit",
    )
