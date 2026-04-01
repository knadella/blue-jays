"""Fast smoke tests: API wiring, data helpers, no full MCMC."""

from __future__ import annotations

import os

import numpy as np
import pytest
from starlette.testclient import TestClient

from data_source.game_features import (
    compute_division_indicator,
    compute_momentum,
    compute_rest_days,
)
from data_source.mlb_api import completed_game_rows


def test_schedule_strength_10_scales_opponent_run_diff():
    from backend.app.services.dashboard import schedule_strength_10

    # Two opponents: weak (run_diff 0) and strong (run_diff 10) → mean normalized strength 0.5 → 5.0
    run_diff = np.array([0.0, 10.0, 5.0], dtype=float)
    team_to_idx = {"Weak Team": 0, "Strong Team": 1, "Focus": 2}
    games = [
        {"home_name": "Focus", "away_name": "Weak Team"},
        {"home_name": "Strong Team", "away_name": "Focus"},
    ]
    assert schedule_strength_10(games, "Focus", run_diff, team_to_idx) == 5.0


def test_game_features_shapes_and_finite():
    games = [
        {
            "game_date": "2025-04-01",
            "home_team": "Toronto Blue Jays",
            "away_team": "New York Yankees",
            "home_runs": 5,
            "away_runs": 3,
            "home_pitcher": "A",
            "away_pitcher": "B",
        },
        {
            "game_date": "2025-04-03",
            "home_team": "New York Yankees",
            "away_team": "Toronto Blue Jays",
            "home_runs": 2,
            "away_runs": 4,
            "home_pitcher": "C",
            "away_pitcher": "D",
        },
    ]
    hr, ar = compute_rest_days(games)
    hm, am = compute_momentum(games)
    div = compute_division_indicator(games)
    assert hr.shape == (2,) and ar.shape == (2,)
    assert np.all(np.isfinite(hr)) and np.all(np.isfinite(ar))
    assert hm.shape == (2,) and am.shape == (2,)
    assert div.shape == (2,)


def test_completed_game_rows_includes_pitchers():
    raw = [
        {
            "home_name": "Toronto Blue Jays",
            "away_name": "New York Yankees",
            "home_score": 1,
            "away_score": 0,
            "game_date": "2025-04-01T00:00:00Z",
            "game_id": 1,
            "home_probable_pitcher": "Pitcher H",
            "away_probable_pitcher": "Pitcher A",
        }
    ]
    rows = completed_game_rows(raw)
    assert len(rows) == 1
    assert rows[0]["home_pitcher"] == "Pitcher H"
    assert rows[0]["away_pitcher"] == "Pitcher A"


@pytest.fixture
def api_client() -> TestClient:
    from backend.app.main import app

    return TestClient(app)


def test_api_health(api_client: TestClient):
    r = api_client.get("/api/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_api_teams(api_client: TestClient):
    r = api_client.get("/api/teams")
    assert r.status_code == 200
    teams = r.json()
    assert isinstance(teams, list)
    assert len(teams) == 30
    assert "Toronto Blue Jays" in teams


@pytest.mark.integration
def test_api_dashboard_no_refit(api_client: TestClient):
    """Hits real MLB API + cached or fresh posterior; can take minutes without cache."""
    if os.environ.get("MLB_RUN_INTEGRATION") != "1":
        pytest.skip("Set MLB_RUN_INTEGRATION=1 to run dashboard e2e (network + MCMC)")
    season = int(os.environ.get("MLB_E2E_SEASON", "2025"))
    r = api_client.get(
        "/api/dashboard",
        params={"season": season, "team": "Toronto Blue Jays", "force_refit": "false"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("season") == season
    assert body.get("favorite_team") == "Toronto Blue Jays"
    sim = body.get("team_simulation") or {}
    assert "projected_final_wins" in sim
    assert "playoff_probability" in sim
    vs = body.get("team_rating_vs_actual") or {}
    assert "runs_scored_per_game_projected" in vs
    assert "runs_allowed_per_game_projected" in vs
