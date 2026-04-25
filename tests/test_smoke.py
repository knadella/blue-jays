"""Fast smoke tests: API wiring + data helpers."""

from __future__ import annotations

import pandas as pd
import pytest
from starlette.testclient import TestClient

from data_source.mlb_api import completed_game_rows
from data_source.statcast_weekly import build_team_record_from_statcast


def test_build_team_record_from_statcast_counts_wins():
    df = pd.DataFrame(
        [
            {
                "game_pk": 100,
                "home_team": "TOR",
                "away_team": "NYY",
                "post_home_score": 5,
                "post_away_score": 3,
            },
            {
                "game_pk": 100,
                "home_team": "TOR",
                "away_team": "NYY",
                "post_home_score": 5,
                "post_away_score": 3,
            },
            {
                "game_pk": 200,
                "home_team": "NYY",
                "away_team": "TOR",
                "post_home_score": 1,
                "post_away_score": 4,
            },
        ]
    )
    assert build_team_record_from_statcast(df, "TOR") == {"w": 2, "l": 0}
    assert build_team_record_from_statcast(df, "NYY") == {"w": 0, "l": 2}


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


def test_api_team(api_client: TestClient):
    r = api_client.get("/api/team")
    assert r.status_code == 200
    assert r.json().get("team") == "Toronto Blue Jays"
