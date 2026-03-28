"""Bayesian hierarchical Poisson model fitting and summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from config import (
    COLD_START_POSTERIOR_CHAINS,
    COLD_START_POSTERIOR_DRAWS,
    COLD_START_POSTERIOR_TUNE,
    DEFAULT_HFA_LOG_RUNS,
    LEAGUE_BASELINE_RUNS,
    POSTERIOR_CHAINS,
    POSTERIOR_DRAWS,
    POSTERIOR_TUNE,
    PRIOR_BACKFILL_CHAINS,
    PRIOR_BACKFILL_DRAWS,
    PRIOR_BACKFILL_TUNE,
    RECENCY_HALF_LIFE_DAYS,
    compute_prior_retention,
)
from data_source.game_features import (
    compute_division_indicator,
    compute_momentum,
    compute_rest_days,
)
from data_source.mlb_api import (
    completed_game_rows,
    fetch_schedule,
    split_schedule,
    summarize_team_performance,
)
from data_source.pitcher_stats import pitcher_quality_arrays

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


def _extract_diagnostics(idata) -> dict | None:
    """Pull R-hat, ESS, and divergence counts from an InferenceData object."""
    try:
        import arviz as az

        var_names = ["mu", "hfa", "sigma_off", "sigma_def", "sigma_park",
                     "alpha", "beta_pitcher", "beta_rest", "beta_momentum",
                     "beta_division", "offense_offset", "defense_offset", "park_offset"]
        summary_df = az.summary(idata, var_names=var_names)
        divergences = int(idata.sample_stats["diverging"].values.sum())
        rhat_max = float(summary_df["r_hat"].max())
        ess_bulk_min = float(summary_df["ess_bulk"].min())
        ess_tail_min = float(summary_df["ess_tail"].min())

        warnings: list[str] = []
        if rhat_max > 1.01:
            warnings.append(f"High R-hat ({rhat_max:.3f}): chains may not have converged")
        if ess_bulk_min < 400:
            warnings.append(f"Low bulk ESS ({ess_bulk_min:.0f}): consider more draws or tuning")
        if ess_tail_min < 400:
            warnings.append(f"Low tail ESS ({ess_tail_min:.0f}): tail quantiles may be unreliable")
        if divergences > 0:
            warnings.append(f"{divergences} divergent transitions detected")

        return {
            "rhat_max": round(rhat_max, 4),
            "ess_bulk_min": round(ess_bulk_min, 1),
            "ess_tail_min": round(ess_tail_min, 1),
            "divergences": divergences,
            "warnings": warnings,
        }
    except Exception:
        return None


def _sample_prior_snapshot(
    season: int,
    teams: list[str],
    prior_snapshot: Optional[PosteriorSnapshot],
    draws: int,
    rng: np.random.Generator,
    source: str,
    n_current_games: int = 0,
    skip_save: bool = False,
) -> PosteriorSnapshot:
    team_count = len(teams)
    baseline_mu = np.log(LEAGUE_BASELINE_RUNS)
    baseline_hfa = DEFAULT_HFA_LOG_RUNS

    prior_offense_mean = np.zeros(team_count)
    prior_defense_mean = np.zeros(team_count)
    mu_mean = baseline_mu
    hfa_mean = baseline_hfa

    prior_park_mean = np.zeros(team_count)

    if prior_snapshot is not None and prior_snapshot.teams == teams:
        retention = compute_prior_retention(n_current_games)
        prior_offense_mean = retention * prior_snapshot.offense_array().mean(axis=0)
        prior_defense_mean = retention * prior_snapshot.defense_array().mean(axis=0)
        prior_park_mean = retention * prior_snapshot.park_array().mean(axis=0)
        mu_mean = (
            retention * prior_snapshot.mu_array().mean()
            + (1 - retention) * baseline_mu
        )
        hfa_mean = (
            retention * prior_snapshot.hfa_array().mean()
            + (1 - retention) * baseline_hfa
        )

    offense = rng.normal(loc=prior_offense_mean, scale=0.08, size=(draws, team_count))
    defense = rng.normal(loc=prior_defense_mean, scale=0.08, size=(draws, team_count))
    offense -= offense.mean(axis=1, keepdims=True)
    defense -= defense.mean(axis=1, keepdims=True)

    park = rng.normal(loc=prior_park_mean, scale=0.05, size=(draws, team_count))
    park -= park.mean(axis=1, keepdims=True)

    alpha_samples = rng.gamma(shape=4.0, scale=1.0, size=draws)

    snapshot = PosteriorSnapshot(
        season=season,
        generated_at=datetime.now(timezone.utc).isoformat(),
        source=source,
        teams=teams,
        mu=rng.normal(loc=mu_mean, scale=0.08, size=draws).tolist(),
        hfa=rng.normal(loc=hfa_mean, scale=0.02, size=draws).tolist(),
        offense=offense.tolist(),
        defense=defense.tolist(),
        park=park.tolist(),
        alpha=alpha_samples.tolist(),
    )
    if not skip_save:
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

    park = rng.normal(loc=0, scale=0.03, size=(draws, len(teams)))
    park -= park.mean(axis=1, keepdims=True)

    return PosteriorSnapshot(
        season=season - 1,
        generated_at=datetime.now(timezone.utc).isoformat(),
        source="prior-season-proxy",
        teams=teams,
        mu=rng.normal(loc=baseline_mu, scale=0.04, size=draws).tolist(),
        hfa=rng.normal(loc=hfa_mean, scale=0.01, size=draws).tolist(),
        offense=offense.tolist(),
        defense=defense.tolist(),
        park=park.tolist(),
        alpha=rng.gamma(shape=4.0, scale=1.0, size=draws).tolist(),
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

    # Prior-season fit is only a seed for the current season; use lighter MCMC.
    return _fit_snapshot_from_games(
        season=season - 1,
        completed_games=completed_game_rows(completed),
        teams=teams,
        prior_snapshot=older_snapshot,
        draws=min(draws, PRIOR_BACKFILL_DRAWS),
        tune=min(tune, PRIOR_BACKFILL_TUNE),
        chains=min(chains, max(1, PRIOR_BACKFILL_CHAINS)),
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
    skip_save: bool = False,
) -> PosteriorSnapshot:
    n_games = len(completed_games)

    if n_games < 10:
        return _sample_prior_snapshot(
            season=season,
            teams=teams,
            prior_snapshot=prior_snapshot,
            draws=draws,
            rng=rng,
            source="prior-bootstrap" if prior_snapshot is None else f"{prior_snapshot.source}-bootstrap",
            n_current_games=n_games,
            skip_save=skip_save,
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
            n_current_games=n_games,
            skip_save=skip_save,
        )

    team_index = {team: idx for idx, team in enumerate(teams)}
    home_team_idx = np.asarray([team_index[g["home_team"]] for g in completed_games], dtype=int)
    away_team_idx = np.asarray([team_index[g["away_team"]] for g in completed_games], dtype=int)
    home_runs = np.asarray([g["home_runs"] for g in completed_games], dtype=int)
    away_runs = np.asarray([g["away_runs"] for g in completed_games], dtype=int)

    # Starting pitcher quality (z-scored ERA, positive = better)
    home_pq, away_pq = pitcher_quality_arrays(completed_games, season)

    # Rest days (log-scaled), momentum (centered win rate), division indicator
    home_rest, away_rest = compute_rest_days(completed_games)
    home_mom, away_mom = compute_momentum(completed_games)
    is_div = compute_division_indicator(completed_games)

    # Recency weighting: exponential decay so recent games matter more
    game_dates = np.array([g["game_date"] for g in completed_games])
    unique_dates = np.unique(game_dates)
    date_to_day = {d: i for i, d in enumerate(sorted(unique_dates))}
    game_days = np.array([date_to_day[d] for d in game_dates], dtype=float)
    decay_rate = np.log(2) / RECENCY_HALF_LIFE_DAYS
    weights = np.exp(-decay_rate * (game_days.max() - game_days))

    baseline_mu = np.log(LEAGUE_BASELINE_RUNS)
    prior_offense_mean = np.zeros(len(teams))
    prior_defense_mean = np.zeros(len(teams))
    prior_park_mean = np.zeros(len(teams))
    mu_mean = baseline_mu
    hfa_mean = DEFAULT_HFA_LOG_RUNS

    if prior_snapshot is not None and prior_snapshot.teams == teams:
        retention = compute_prior_retention(n_games)
        prior_offense_mean = retention * prior_snapshot.offense_array().mean(axis=0)
        prior_defense_mean = retention * prior_snapshot.defense_array().mean(axis=0)
        prior_park_mean = retention * prior_snapshot.park_array().mean(axis=0)
        mu_mean = (
            retention * prior_snapshot.mu_array().mean()
            + (1 - retention) * baseline_mu
        )
        hfa_mean = (
            retention * prior_snapshot.hfa_array().mean()
            + (1 - retention) * DEFAULT_HFA_LOG_RUNS
        )

    coords = {"team": teams, "game": np.arange(n_games)}
    with pm.Model(coords=coords):
        mu = pm.Normal("mu", mu=mu_mean, sigma=0.2)
        hfa = pm.Normal("hfa", mu=hfa_mean, sigma=0.02)

        sigma_off = pm.HalfNormal("sigma_off", sigma=0.12)
        sigma_def = pm.HalfNormal("sigma_def", sigma=0.12)

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

        sigma_park = pm.HalfNormal("sigma_park", sigma=0.1)
        park_offset = pm.Normal(
            "park_offset",
            mu=prior_park_mean,
            sigma=sigma_park,
            dims="team",
        )
        park = pm.Deterministic(
            "park",
            park_offset - pt.mean(park_offset),
            dims="team",
        )

        alpha = pm.Gamma("alpha", mu=4.0, sigma=2.0)

        # Game-level covariates
        beta_pitcher = pm.HalfNormal("beta_pitcher", sigma=0.1)
        beta_rest = pm.Normal("beta_rest", mu=0.0, sigma=0.05)
        beta_momentum = pm.Normal("beta_momentum", mu=0.0, sigma=0.1)
        beta_division = pm.Normal("beta_division", mu=0.0, sigma=0.05)

        log_lambda_home = (
            mu + hfa + park[home_team_idx]
            + offense[home_team_idx] - defense[away_team_idx]
            - beta_pitcher * away_pq
            + beta_rest * (home_rest - away_rest)
            + beta_momentum * home_mom
            + beta_division * is_div
        )
        log_lambda_away = (
            mu + park[home_team_idx]
            + offense[away_team_idx] - defense[home_team_idx]
            - beta_pitcher * home_pq
            + beta_rest * (away_rest - home_rest)
            + beta_momentum * away_mom
            + beta_division * is_div
        )

        # Recency-weighted likelihood via pm.Potential
        home_dist = pm.NegativeBinomial.dist(
            mu=pm.math.exp(log_lambda_home), alpha=alpha,
        )
        away_dist = pm.NegativeBinomial.dist(
            mu=pm.math.exp(log_lambda_away), alpha=alpha,
        )
        pm.Potential("home_weighted", weights * pm.logp(home_dist, home_runs))
        pm.Potential("away_weighted", weights * pm.logp(away_dist, away_runs))

        idata = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            target_accept=0.90,
            progressbar=False,
            random_seed=season,
        )

    diagnostics = _extract_diagnostics(idata)

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
        park=posterior["park"].transpose("sample", "team").values.tolist(),
        alpha=posterior["alpha"].values.tolist(),
        beta_pitcher=posterior["beta_pitcher"].values.tolist(),
        beta_rest=posterior["beta_rest"].values.tolist(),
        beta_momentum=posterior["beta_momentum"].values.tolist(),
        beta_division=posterior["beta_division"].values.tolist(),
        diagnostics=diagnostics,
    )
    if not skip_save:
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
    dashboard_instant_bootstrap: bool = False,
) -> PosteriorSnapshot:
    """Fit the PyMC model or reuse the latest stored snapshot."""
    if not force_refit:
        existing = load_latest_snapshot(season)
        if existing is not None and existing.teams == teams:
            return existing
        if dashboard_instant_bootstrap:
            rng = np.random.default_rng(seed=season)
            prior_snap = _proxy_prior_snapshot(
                season=season,
                teams=teams,
                draws=min(draws, COLD_START_POSTERIOR_DRAWS),
                rng=rng,
            )
            return _sample_prior_snapshot(
                season=season,
                teams=teams,
                prior_snapshot=prior_snap,
                draws=min(draws, COLD_START_POSTERIOR_DRAWS),
                rng=rng,
                source="prior-bootstrap-instant",
                n_current_games=len(completed_games),
                skip_save=False,
            )
        fit_draws = min(draws, COLD_START_POSTERIOR_DRAWS)
        fit_tune = min(tune, COLD_START_POSTERIOR_TUNE)
        fit_chains = min(chains, max(1, COLD_START_POSTERIOR_CHAINS))
        source = "pymc-fit-cold-start"
    else:
        fit_draws, fit_tune, fit_chains = draws, tune, chains
        source = "pymc-fit"

    rng = np.random.default_rng(seed=season)
    prior_snapshot = _load_prior_seed(
        season=season,
        teams=teams,
        draws=fit_draws,
        tune=fit_tune,
        chains=fit_chains,
        rng=rng,
    )
    return _fit_snapshot_from_games(
        season=season,
        completed_games=completed_games,
        teams=teams,
        prior_snapshot=prior_snapshot,
        draws=fit_draws,
        tune=fit_tune,
        chains=fit_chains,
        rng=rng,
        source=source,
    )
