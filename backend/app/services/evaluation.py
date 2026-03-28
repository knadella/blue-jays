"""Model evaluation: retrodictive scoring, calibration, and diagnostics."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np

from config import ALL_TEAMS
from data_source.game_features import (
    compute_division_indicator,
    compute_momentum,
    compute_rest_days,
)
from data_source.mlb_api import completed_game_rows, fetch_schedule, split_schedule
from data_source.pitcher_stats import pitcher_quality_arrays

from .modeling import _fit_snapshot_from_games, _load_prior_seed, fit_or_load_snapshot
from .storage import PosteriorSnapshot

logger = logging.getLogger(__name__)


def retrodictive_evaluation(
    snapshot: PosteriorSnapshot,
    completed_games: list[dict],
    season: int = 0,
    n_posterior_samples: int = 500,
) -> dict:
    """Score the fitted posterior against the games it was trained on.

    This is an *in-sample* posterior predictive check.  It catches model
    misspecification (e.g. systematic bias, poor fit to high-scoring games)
    but will overstate true forecasting accuracy because the model has
    already seen these outcomes.
    """
    team_to_idx = {name: idx for idx, name in enumerate(snapshot.teams)}

    valid = [
        g for g in completed_games
        if g["home_team"] in team_to_idx and g["away_team"] in team_to_idx
    ]
    if not valid:
        return _empty_result()

    if season == 0:
        season = snapshot.season

    n_games = len(valid)
    home_idx = np.array([team_to_idx[g["home_team"]] for g in valid])
    away_idx = np.array([team_to_idx[g["away_team"]] for g in valid])
    actual_hr = np.array([g["home_runs"] for g in valid], dtype=float)
    actual_ar = np.array([g["away_runs"] for g in valid], dtype=float)
    actual_hw = (actual_hr > actual_ar).astype(float)

    home_pq, away_pq = pitcher_quality_arrays(valid, season)
    home_rest, away_rest = compute_rest_days(valid)
    home_mom, away_mom = compute_momentum(valid)
    is_div = compute_division_indicator(valid)

    rng = np.random.default_rng(42)
    draw_idx = rng.integers(0, snapshot.draw_count, size=n_posterior_samples)

    mu = snapshot.mu_array()[draw_idx]
    hfa = snapshot.hfa_array()[draw_idx]
    off = snapshot.offense_array()[draw_idx]
    dfn = snapshot.defense_array()[draw_idx]
    prk = snapshot.park_array()[draw_idx]
    alp = snapshot.alpha_array()[draw_idx]
    bp = snapshot.beta_pitcher_array()[draw_idx]
    br = snapshot.beta_rest_array()[draw_idx]
    bm = snapshot.beta_momentum_array()[draw_idx]
    bd = snapshot.beta_division_array()[draw_idx]
    has_overdispersion = snapshot.alpha is not None

    rest_diff = home_rest - away_rest
    lam_h = np.exp(
        mu[:, None] + hfa[:, None] + prk[:, home_idx]
        + off[:, home_idx] - dfn[:, away_idx]
        - bp[:, None] * away_pq[None, :]
        + br[:, None] * rest_diff[None, :]
        + bm[:, None] * home_mom[None, :]
        + bd[:, None] * is_div[None, :]
    )
    lam_a = np.exp(
        mu[:, None] + prk[:, home_idx]
        + off[:, away_idx] - dfn[:, home_idx]
        - bp[:, None] * home_pq[None, :]
        + br[:, None] * (-rest_diff[None, :])
        + bm[:, None] * away_mom[None, :]
        + bd[:, None] * is_div[None, :]
    )

    if has_overdispersion:
        rate_h = rng.gamma(alp[:, None], lam_h / alp[:, None])
        rate_a = rng.gamma(alp[:, None], lam_a / alp[:, None])
        sim_h = rng.poisson(rate_h)
        sim_a = rng.poisson(rate_a)
    else:
        sim_h = rng.poisson(lam_h)
        sim_a = rng.poisson(lam_a)

    p_home = (
        np.mean(sim_h > sim_a, axis=0)
        + 0.5 * np.mean(sim_h == sim_a, axis=0)
    )

    exp_hr = lam_h.mean(axis=0)
    exp_ar = lam_a.mean(axis=0)

    # ---- aggregate metrics ----
    eps = 1e-15
    pc = np.clip(p_home, eps, 1 - eps)
    log_loss = -float(np.mean(
        actual_hw * np.log(pc) + (1 - actual_hw) * np.log(1 - pc)
    ))
    brier = float(np.mean((p_home - actual_hw) ** 2))
    accuracy = float(np.mean((p_home > 0.5) == actual_hw))
    hw_rate = float(actual_hw.mean())

    runs_err = np.concatenate([exp_hr - actual_hr, exp_ar - actual_ar])
    runs_mae = float(np.mean(np.abs(runs_err)))
    runs_mae_home = float(np.mean(np.abs(exp_hr - actual_hr)))
    runs_mae_away = float(np.mean(np.abs(exp_ar - actual_ar)))

    # ---- baselines (always-predict-home-win-rate) ----
    bl_acc = max(hw_rate, 1 - hw_rate)
    bl_brier = float(np.mean((hw_rate - actual_hw) ** 2))
    bl_ll = -float(np.mean(
        actual_hw * np.log(max(hw_rate, eps))
        + (1 - actual_hw) * np.log(max(1 - hw_rate, eps))
    ))

    # ---- calibration bins ----
    n_bins = 10
    edges = np.linspace(0, 1, n_bins + 1)
    calibration: list[dict] = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p_home >= lo) & (p_home < hi) if i < n_bins - 1 else (p_home >= lo) & (p_home <= hi)
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        calibration.append({
            "bin_start": round(float(lo), 2),
            "bin_end": round(float(hi), 2),
            "predicted_mean": round(float(p_home[mask].mean()), 4),
            "observed_frequency": round(float(actual_hw[mask].mean()), 4),
            "count": cnt,
        })

    # ---- biggest surprises (top-50 by |p - outcome|) ----
    surprise = np.abs(p_home - actual_hw)
    top50 = np.argsort(-surprise)[:50]
    surprises: list[dict] = []
    for i in top50:
        g = valid[i]
        surprises.append({
            "game_date": g["game_date"],
            "home_team": g["home_team"],
            "away_team": g["away_team"],
            "predicted_home_win_prob": round(float(p_home[i]), 4),
            "actual_home_win": int(actual_hw[i]),
            "predicted_home_runs": round(float(exp_hr[i]), 2),
            "predicted_away_runs": round(float(exp_ar[i]), 2),
            "actual_home_runs": int(actual_hr[i]),
            "actual_away_runs": int(actual_ar[i]),
        })

    return {
        "n_games": n_games,
        "metrics": {
            "log_loss": round(log_loss, 4),
            "brier_score": round(brier, 4),
            "accuracy": round(accuracy, 4),
            "runs_mae": round(runs_mae, 2),
            "runs_mae_home": round(runs_mae_home, 2),
            "runs_mae_away": round(runs_mae_away, 2),
            "home_win_rate": round(hw_rate, 4),
        },
        "baselines": {
            "constant_accuracy": round(bl_acc, 4),
            "constant_brier": round(bl_brier, 4),
            "constant_log_loss": round(bl_ll, 4),
        },
        "calibration": calibration,
        "biggest_surprises": surprises,
    }


def _empty_result() -> dict:
    return {
        "n_games": 0,
        "metrics": {
            "log_loss": 0.0,
            "brier_score": 0.0,
            "accuracy": 0.0,
            "runs_mae": 0.0,
            "runs_mae_home": 0.0,
            "runs_mae_away": 0.0,
            "home_win_rate": 0.0,
        },
        "baselines": {
            "constant_accuracy": 0.0,
            "constant_brier": 0.0,
            "constant_log_loss": 0.0,
        },
        "calibration": [],
        "biggest_surprises": [],
    }


def build_evaluation(season: int) -> dict:
    """End-to-end evaluation for a season: fit/load model, then score."""
    schedule = fetch_schedule(season)
    completed, _ = split_schedule(schedule)
    games = completed_game_rows(completed)

    snapshot = fit_or_load_snapshot(
        season=season,
        completed_games=games,
        teams=ALL_TEAMS,
    )

    result = retrodictive_evaluation(snapshot, games, season=season)
    result["season"] = season
    result["model_source"] = snapshot.source
    result["mcmc_diagnostics"] = snapshot.diagnostics
    return result


# ---------------------------------------------------------------------------
# Walk-forward (out-of-sample) evaluation
# ---------------------------------------------------------------------------

_WF_DRAWS = 200
_WF_TUNE = 200
_WF_CHAINS = 2
_WF_POSTERIOR_SAMPLES = 300


class _PredictionResult:
    __slots__ = ("p_home", "exp_hr", "exp_ar", "actual_hr", "actual_ar", "actual_hw")

    def __init__(
        self,
        p_home: np.ndarray,
        exp_hr: np.ndarray,
        exp_ar: np.ndarray,
        actual_hr: np.ndarray,
        actual_ar: np.ndarray,
        actual_hw: np.ndarray,
    ):
        self.p_home = p_home
        self.exp_hr = exp_hr
        self.exp_ar = exp_ar
        self.actual_hr = actual_hr
        self.actual_ar = actual_ar
        self.actual_hw = actual_hw

    @property
    def empty(self) -> bool:
        return self.p_home.size == 0


def _predict_games(
    snapshot: PosteriorSnapshot,
    test_games: list[dict],
    season: int = 0,
    n_posterior_samples: int = _WF_POSTERIOR_SAMPLES,
) -> _PredictionResult:
    """Score a set of games against a fitted posterior snapshot."""
    team_to_idx = {name: idx for idx, name in enumerate(snapshot.teams)}
    valid = [
        g for g in test_games
        if g["home_team"] in team_to_idx and g["away_team"] in team_to_idx
    ]
    if not valid:
        empty = np.array([], dtype=float)
        return _PredictionResult(empty, empty, empty, empty, empty, empty)

    if season == 0:
        season = snapshot.season

    home_idx = np.array([team_to_idx[g["home_team"]] for g in valid])
    away_idx = np.array([team_to_idx[g["away_team"]] for g in valid])
    actual_hr = np.array([g["home_runs"] for g in valid], dtype=float)
    actual_ar = np.array([g["away_runs"] for g in valid], dtype=float)
    actual_hw = (actual_hr > actual_ar).astype(float)

    home_pq, away_pq = pitcher_quality_arrays(valid, season)
    home_rest, away_rest = compute_rest_days(valid)
    home_mom, away_mom = compute_momentum(valid)
    is_div = compute_division_indicator(valid)

    rng = np.random.default_rng(123)
    draw_idx = rng.integers(0, snapshot.draw_count, size=n_posterior_samples)

    mu = snapshot.mu_array()[draw_idx]
    hfa = snapshot.hfa_array()[draw_idx]
    off = snapshot.offense_array()[draw_idx]
    dfn = snapshot.defense_array()[draw_idx]
    prk = snapshot.park_array()[draw_idx]
    alp = snapshot.alpha_array()[draw_idx]
    bp = snapshot.beta_pitcher_array()[draw_idx]
    br = snapshot.beta_rest_array()[draw_idx]
    bm = snapshot.beta_momentum_array()[draw_idx]
    bd = snapshot.beta_division_array()[draw_idx]
    has_overdispersion = snapshot.alpha is not None

    rest_diff = home_rest - away_rest
    lam_h = np.exp(
        mu[:, None] + hfa[:, None] + prk[:, home_idx]
        + off[:, home_idx] - dfn[:, away_idx]
        - bp[:, None] * away_pq[None, :]
        + br[:, None] * rest_diff[None, :]
        + bm[:, None] * home_mom[None, :]
        + bd[:, None] * is_div[None, :]
    )
    lam_a = np.exp(
        mu[:, None] + prk[:, home_idx]
        + off[:, away_idx] - dfn[:, home_idx]
        - bp[:, None] * home_pq[None, :]
        + br[:, None] * (-rest_diff[None, :])
        + bm[:, None] * away_mom[None, :]
        + bd[:, None] * is_div[None, :]
    )

    if has_overdispersion:
        rate_h = rng.gamma(alp[:, None], lam_h / alp[:, None])
        rate_a = rng.gamma(alp[:, None], lam_a / alp[:, None])
        sim_h = rng.poisson(rate_h)
        sim_a = rng.poisson(rate_a)
    else:
        sim_h = rng.poisson(lam_h)
        sim_a = rng.poisson(lam_a)

    p_home = (
        np.mean(sim_h > sim_a, axis=0)
        + 0.5 * np.mean(sim_h == sim_a, axis=0)
    )
    exp_hr = lam_h.mean(axis=0)
    exp_ar = lam_a.mean(axis=0)

    return _PredictionResult(p_home, exp_hr, exp_ar, actual_hr, actual_ar, actual_hw)


def walk_forward_evaluation(
    season: int,
    step_days: int = 7,
    min_training_games: int = 100,
) -> dict:
    """True out-of-sample evaluation via rolling walk-forward backtest.

    Fits the model on all games before each cutoff date, then scores
    predictions on the next *step_days* window of unseen games.
    Uses lightweight MCMC settings for speed.
    """
    schedule = fetch_schedule(season)
    completed, _ = split_schedule(schedule)
    all_games = completed_game_rows(completed)

    if not all_games:
        return _empty_walkforward_result(season)

    teams = ALL_TEAMS
    rng = np.random.default_rng(seed=season)

    prior_snapshot = _load_prior_seed(
        season=season,
        teams=teams,
        draws=_WF_DRAWS,
        tune=_WF_TUNE,
        chains=_WF_CHAINS,
        rng=rng,
    )

    dates = sorted({g["game_date"] for g in all_games})
    first_date = datetime.strptime(dates[0], "%Y-%m-%d")
    last_date = datetime.strptime(dates[-1], "%Y-%m-%d")

    all_p_home: list[np.ndarray] = []
    all_actual_hw: list[np.ndarray] = []
    all_exp_hr: list[np.ndarray] = []
    all_exp_ar: list[np.ndarray] = []
    all_actual_hr: list[np.ndarray] = []
    all_actual_ar: list[np.ndarray] = []
    window_results: list[dict] = []

    cutoff = first_date + timedelta(days=30)
    n_windows = 0

    while cutoff <= last_date:
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        window_end_str = (cutoff + timedelta(days=step_days)).strftime("%Y-%m-%d")

        train_games = [g for g in all_games if g["game_date"] < cutoff_str]
        test_games = [
            g for g in all_games
            if cutoff_str <= g["game_date"] < window_end_str
        ]

        cutoff += timedelta(days=step_days)

        if len(train_games) < min_training_games or not test_games:
            continue

        step_rng = np.random.default_rng(seed=season * 1000 + n_windows)

        try:
            snapshot = _fit_snapshot_from_games(
                season=season,
                completed_games=train_games,
                teams=teams,
                prior_snapshot=prior_snapshot,
                draws=_WF_DRAWS,
                tune=_WF_TUNE,
                chains=_WF_CHAINS,
                rng=step_rng,
                source="walkforward-eval",
                skip_save=True,
            )
        except Exception as exc:
            logger.warning("Walk-forward fit failed at %s: %s", cutoff_str, exc)
            continue

        preds = _predict_games(snapshot, test_games, season=season)
        if preds.empty:
            continue

        all_p_home.append(preds.p_home)
        all_actual_hw.append(preds.actual_hw)
        all_exp_hr.append(preds.exp_hr)
        all_exp_ar.append(preds.exp_ar)
        all_actual_hr.append(preds.actual_hr)
        all_actual_ar.append(preds.actual_ar)

        eps = 1e-15
        pc = np.clip(preds.p_home, eps, 1 - eps)
        win_ll = -float(np.mean(
            preds.actual_hw * np.log(pc) + (1 - preds.actual_hw) * np.log(1 - pc)
        ))
        win_brier = float(np.mean((preds.p_home - preds.actual_hw) ** 2))
        win_acc = float(np.mean((preds.p_home > 0.5) == preds.actual_hw))

        window_results.append({
            "window_start": cutoff_str,
            "window_end": window_end_str,
            "train_games": len(train_games),
            "test_games": len(test_games),
            "log_loss": round(win_ll, 4),
            "brier_score": round(win_brier, 4),
            "accuracy": round(win_acc, 4),
        })
        n_windows += 1

    if not all_p_home:
        return _empty_walkforward_result(season)

    p_home_all = np.concatenate(all_p_home)
    actual_hw_all = np.concatenate(all_actual_hw)
    exp_hr_all = np.concatenate(all_exp_hr)
    exp_ar_all = np.concatenate(all_exp_ar)
    actual_hr_all = np.concatenate(all_actual_hr)
    actual_ar_all = np.concatenate(all_actual_ar)

    eps = 1e-15
    pc_all = np.clip(p_home_all, eps, 1 - eps)
    agg_log_loss = -float(np.mean(
        actual_hw_all * np.log(pc_all) + (1 - actual_hw_all) * np.log(1 - pc_all)
    ))
    agg_brier = float(np.mean((p_home_all - actual_hw_all) ** 2))
    agg_accuracy = float(np.mean((p_home_all > 0.5) == actual_hw_all))
    hw_rate = float(actual_hw_all.mean())

    runs_mae_home = float(np.mean(np.abs(exp_hr_all - actual_hr_all)))
    runs_mae_away = float(np.mean(np.abs(exp_ar_all - actual_ar_all)))
    runs_mae = float(np.mean(np.abs(
        np.concatenate([exp_hr_all - actual_hr_all, exp_ar_all - actual_ar_all])
    )))

    bl_acc = max(hw_rate, 1 - hw_rate)
    bl_brier = float(np.mean((hw_rate - actual_hw_all) ** 2))
    bl_ll = -float(np.mean(
        actual_hw_all * np.log(max(hw_rate, eps))
        + (1 - actual_hw_all) * np.log(max(1 - hw_rate, eps))
    ))

    n_bins = 10
    edges = np.linspace(0, 1, n_bins + 1)
    calibration: list[dict] = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (
            (p_home_all >= lo) & (p_home_all < hi) if i < n_bins - 1
            else (p_home_all >= lo) & (p_home_all <= hi)
        )
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        calibration.append({
            "bin_start": round(float(lo), 2),
            "bin_end": round(float(hi), 2),
            "predicted_mean": round(float(p_home_all[mask].mean()), 4),
            "observed_frequency": round(float(actual_hw_all[mask].mean()), 4),
            "count": cnt,
        })

    return {
        "season": season,
        "evaluation_type": "walk_forward",
        "step_days": step_days,
        "n_windows": n_windows,
        "n_games_scored": int(p_home_all.size),
        "metrics": {
            "log_loss": round(agg_log_loss, 4),
            "brier_score": round(agg_brier, 4),
            "accuracy": round(agg_accuracy, 4),
            "runs_mae": round(runs_mae, 2),
            "runs_mae_home": round(runs_mae_home, 2),
            "runs_mae_away": round(runs_mae_away, 2),
            "home_win_rate": round(hw_rate, 4),
        },
        "baselines": {
            "constant_accuracy": round(bl_acc, 4),
            "constant_brier": round(bl_brier, 4),
            "constant_log_loss": round(bl_ll, 4),
        },
        "calibration": calibration,
        "windows": window_results,
    }


def _empty_walkforward_result(season: int) -> dict:
    return {
        "season": season,
        "evaluation_type": "walk_forward",
        "step_days": 0,
        "n_windows": 0,
        "n_games_scored": 0,
        "metrics": {
            "log_loss": 0.0,
            "brier_score": 0.0,
            "accuracy": 0.0,
            "runs_mae": 0.0,
            "runs_mae_home": 0.0,
            "runs_mae_away": 0.0,
            "home_win_rate": 0.0,
        },
        "baselines": {
            "constant_accuracy": 0.0,
            "constant_brier": 0.0,
            "constant_log_loss": 0.0,
        },
        "calibration": [],
        "windows": [],
    }


def build_walk_forward_evaluation(season: int, step_days: int = 7) -> dict:
    """Public entry point for walk-forward evaluation."""
    return walk_forward_evaluation(season=season, step_days=step_days)
