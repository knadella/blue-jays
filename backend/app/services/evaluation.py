"""Model evaluation: retrodictive scoring, calibration, and diagnostics."""

from __future__ import annotations

import numpy as np

from config import ALL_TEAMS
from data_source.mlb_api import completed_game_rows, fetch_schedule, split_schedule

from .modeling import fit_or_load_snapshot
from .storage import PosteriorSnapshot


def retrodictive_evaluation(
    snapshot: PosteriorSnapshot,
    completed_games: list[dict],
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

    n_games = len(valid)
    home_idx = np.array([team_to_idx[g["home_team"]] for g in valid])
    away_idx = np.array([team_to_idx[g["away_team"]] for g in valid])
    actual_hr = np.array([g["home_runs"] for g in valid], dtype=float)
    actual_ar = np.array([g["away_runs"] for g in valid], dtype=float)
    actual_hw = (actual_hr > actual_ar).astype(float)

    rng = np.random.default_rng(42)
    draw_idx = rng.integers(0, snapshot.draw_count, size=n_posterior_samples)

    mu = snapshot.mu_array()[draw_idx]
    hfa = snapshot.hfa_array()[draw_idx]
    off = snapshot.offense_array()[draw_idx]
    dfn = snapshot.defense_array()[draw_idx]
    prk = snapshot.park_array()[draw_idx]
    alp = snapshot.alpha_array()[draw_idx]
    has_overdispersion = snapshot.alpha is not None

    # (n_samples, n_games) -- park indexed by home team (venue)
    lam_h = np.exp(
        mu[:, None] + hfa[:, None] + prk[:, home_idx]
        + off[:, home_idx] - dfn[:, away_idx]
    )
    lam_a = np.exp(
        mu[:, None] + prk[:, home_idx]
        + off[:, away_idx] - dfn[:, home_idx]
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

    result = retrodictive_evaluation(snapshot, games)
    result["season"] = season
    result["model_source"] = snapshot.source
    result["mcmc_diagnostics"] = snapshot.diagnostics
    return result
