"""Fast smoke tests: site-data build wiring + data helpers."""

from __future__ import annotations

import pandas as pd

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


def test_build_site_data_output_names_match_frontend():
    """The filenames the build script writes must match what api.ts fetches."""
    from scripts.build_site_data import output_names

    names = output_names(2026, teams=["TOR", "NYY"])
    assert "today_TOR.json" in names
    assert "players_TOR_2026.json" in names
    assert "standings_TOR_2026.json" in names
    assert "players_NYY_2026.json" in names
    assert len(names) == 6


def test_build_site_data_covers_selectable_teams():
    from config import SELECTABLE_TEAMS
    from scripts.build_site_data import output_names

    names = output_names(2026)
    for ab in SELECTABLE_TEAMS:
        assert f"today_{ab}.json" in names
