"""Walk-forward benchmark with all features: pitcher quality + rest + momentum + division."""

import sys
import time
import json
import logging
from datetime import datetime, timedelta

sys.path.insert(0, ".")
sys.path.insert(0, "backend")

logging.basicConfig(level=logging.WARNING)

import numpy as np

from data_source.mlb_api import completed_game_rows, fetch_schedule, split_schedule
from data_source.pitcher_stats import build_pitcher_quality
from config import ALL_TEAMS
from backend.app.services.modeling import _fit_snapshot_from_games, _load_prior_seed
from backend.app.services.evaluation import _predict_games


def main():
    season = 2025
    schedule = fetch_schedule(season)
    completed, _ = split_schedule(schedule)
    all_games = completed_game_rows(completed)

    all_names = set()
    for g in all_games:
        if g.get("home_pitcher"):
            all_names.add(g["home_pitcher"])
        if g.get("away_pitcher"):
            all_names.add(g["away_pitcher"])
    build_pitcher_quality(season, tuple(sorted(all_names)))
    print(f"Pitcher quality cache warmed for {len(all_names)} pitchers")

    checkpoints = [
        ("2025-05-15", "~6 weeks"),
        ("2025-06-15", "~10 weeks"),
        ("2025-07-15", "All-Star"),
        ("2025-08-15", "~4 months"),
        ("2025-09-15", "September"),
    ]

    results = []
    for cutoff_str, label in checkpoints:
        cutoff = datetime.strptime(cutoff_str, "%Y-%m-%d")
        train = [g for g in all_games if g["game_date"] < cutoff_str]
        test_end = (cutoff + timedelta(days=7)).strftime("%Y-%m-%d")
        test = [g for g in all_games if cutoff_str <= g["game_date"] < test_end]

        if len(train) < 100 or len(test) < 10:
            print(f"  {cutoff_str} ({label}): skipping - train={len(train)} test={len(test)}")
            continue

        print(f"  {cutoff_str} ({label}): train={len(train)} test={len(test)}", end=" ", flush=True)

        rng = np.random.default_rng(season)
        prior = _load_prior_seed(season, ALL_TEAMS, draws=200, tune=200, chains=2, rng=rng)

        t0 = time.time()
        snapshot = _fit_snapshot_from_games(
            season=season,
            completed_games=train,
            teams=ALL_TEAMS,
            prior_snapshot=prior,
            draws=200,
            tune=200,
            chains=2,
            rng=rng,
            source="full-model-eval",
            skip_save=True,
        )
        fit_time = time.time() - t0

        preds = _predict_games(snapshot, test, season=season)
        if preds.empty:
            print("-> no valid predictions")
            continue

        eps = 1e-15
        pc = np.clip(preds.p_home, eps, 1 - eps)
        log_loss = -float(np.mean(
            preds.actual_hw * np.log(pc) + (1 - preds.actual_hw) * np.log(1 - pc)
        ))
        brier = float(np.mean((preds.p_home - preds.actual_hw) ** 2))
        accuracy = float(np.mean((preds.p_home > 0.5) == preds.actual_hw))
        hw_rate = float(preds.actual_hw.mean())
        baseline_ll = -float(np.mean(
            preds.actual_hw * np.log(max(hw_rate, eps))
            + (1 - preds.actual_hw) * np.log(max(1 - hw_rate, eps))
        ))

        bp_mean = float(np.mean(snapshot.beta_pitcher)) if snapshot.beta_pitcher else 0.0
        br_mean = float(np.mean(snapshot.beta_rest)) if snapshot.beta_rest else 0.0
        bm_mean = float(np.mean(snapshot.beta_momentum)) if snapshot.beta_momentum else 0.0
        bd_mean = float(np.mean(snapshot.beta_division)) if snapshot.beta_division else 0.0

        print(
            f"-> acc={accuracy:.3f} ll={log_loss:.4f} bl={baseline_ll:.4f} "
            f"bp={bp_mean:.3f} br={br_mean:.3f} bm={bm_mean:.3f} bd={bd_mean:.3f} ({fit_time:.0f}s)"
        )
        results.append({
            "date": cutoff_str,
            "label": label,
            "train_games": len(train),
            "test_games": len(test),
            "accuracy": round(accuracy, 4),
            "log_loss": round(log_loss, 4),
            "brier": round(brier, 4),
            "baseline_log_loss": round(baseline_ll, 4),
            "lift_vs_baseline": round(baseline_ll - log_loss, 4),
            "coefficients": {
                "beta_pitcher": round(bp_mean, 4),
                "beta_rest": round(br_mean, 4),
                "beta_momentum": round(bm_mean, 4),
                "beta_division": round(bd_mean, 4),
            },
            "fit_seconds": round(fit_time, 1),
        })

    # Compute averages
    if results:
        avg_acc = np.mean([r["accuracy"] for r in results])
        avg_ll = np.mean([r["log_loss"] for r in results])
        avg_lift = np.mean([r["lift_vs_baseline"] for r in results])
        beats_baseline = sum(1 for r in results if r["lift_vs_baseline"] > 0)

        print("\n=== Summary (Full Model with All Features) ===")
        for r in results:
            lift = "+" if r["lift_vs_baseline"] > 0 else ""
            print(
                f"  {r['date']} ({r['label']}): acc={r['accuracy']:.3f} "
                f"ll={r['log_loss']:.4f} lift={lift}{r['lift_vs_baseline']:.4f}"
            )
        print(f"\n  Average accuracy: {avg_acc:.3f}")
        print(f"  Average log loss: {avg_ll:.4f}")
        print(f"  Average lift vs baseline: {'+' if avg_lift > 0 else ''}{avg_lift:.4f}")
        print(f"  Beats baseline: {beats_baseline}/{len(results)} checkpoints")

    output = {
        "model_version": "v2-full-features",
        "features": ["team_offense_defense", "park_effects", "pitcher_quality", "rest_days", "momentum", "division_indicator"],
        "mcmc_config": {"draws": 200, "tune": 200, "chains": 2},
        "season": season,
        "checkpoints": results,
    }
    with open("benchmarks/full_model_benchmark_2025.json", "w") as f:
        json.dump(output, f, indent=2)
    print("\nResults saved to benchmarks/full_model_benchmark_2025.json")


if __name__ == "__main__":
    main()
