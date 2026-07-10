"""Build the static site data the frontend fetches from GitHub Pages.

This replaces the FastAPI backend: every payload the frontend needs is
precomputed here — one JSON file per (view, team, season) — and published
alongside the app bundle. The GitHub Actions Pages workflow runs this on a
cron after games complete; locally it feeds the Vite dev server via
``frontend/public/data/``.

Files written (per team in ``config.SELECTABLE_TEAMS``):

    today_{ABBREV}.json                most recent completed game story
    players_{ABBREV}_{season}.json     season-long net WPA per player
    standings_{ABBREV}_{season}.json   division table + momentum + quality

Per-game WPA tallies are cached under ``APP_CACHE_DIR/game_wpa/`` (restored
via actions/cache in CI), so only newly completed games are recomputed.

Any exception aborts the build with a non-zero exit so a failed CI run keeps
serving the previous deploy instead of publishing partial data.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Callable, TypeVar

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from config import DEFAULT_SEASON, SELECTABLE_TEAMS, resolve_team  # noqa: E402

logger = logging.getLogger("build_site_data")

DEFAULT_OUT_DIR = REPO_ROOT / "frontend" / "public" / "data"


def output_names(season: int, teams: list[str] | None = None) -> list[str]:
    """Filenames this script writes — keep in sync with frontend/src/api.ts."""
    names: list[str] = []
    for ab in teams if teams is not None else SELECTABLE_TEAMS:
        names += [
            f"today_{ab}.json",
            f"players_{ab}_{season}.json",
            f"standings_{ab}_{season}.json",
        ]
    return names


T = TypeVar("T")


def _with_retry(fn: Callable[[], T], what: str, attempts: int = 3, delay_s: float = 20.0) -> T:
    """StatsAPI throws transient 503s (esp. the league-wide schedule call)."""
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if i == attempts:
                raise
            logger.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.0fs", what, i, attempts, exc, delay_s
            )
            time.sleep(delay_s)
    raise AssertionError("unreachable")


def _write(out_dir: Path, name: str, content: bytes) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f"{name}.tmp"
    tmp.write_bytes(content)
    tmp.replace(out_dir / name)
    logger.info("wrote %s (%d bytes)", name, len(content))


def build_all(season: int, out_dir: Path) -> None:
    # Imported here so `output_names` stays importable without the heavy deps.
    from backend.app.services.game_story import build_today_payload
    from backend.app.services.player_season import serve_players_payload
    from backend.app.services.standings import build_standings_payload

    for ab in SELECTABLE_TEAMS:
        abbrev, name, team_id = resolve_team(ab)
        logger.info("=== %s (%s) ===", name, abbrev)

        today = _with_retry(lambda: build_today_payload(team_id=team_id), f"today {abbrev}")
        if today is None:
            # Off-season / season not started: no file → the frontend shows
            # its "no game" error state, same as the old API's 404.
            logger.warning("no completed game for %s — skipping today_%s.json", name, abbrev)
        else:
            _write(out_dir, f"today_{abbrev}.json", today.model_dump_json().encode("utf-8"))

        players_raw = _with_retry(
            lambda: serve_players_payload(season, team_id=team_id, abbrev=abbrev),
            f"players {abbrev}",
        )
        players = json.loads(players_raw)  # sanity: must be valid JSON
        logger.info(
            "players: %d games, %d batters, %d pitchers",
            players.get("games_included", 0),
            len(players.get("batters", [])),
            len(players.get("pitchers", [])),
        )
        _write(out_dir, f"players_{abbrev}_{season}.json", players_raw)

        standings = _with_retry(
            lambda: build_standings_payload(season, favorite=name), f"standings {abbrev}"
        )
        _write(
            out_dir,
            f"standings_{abbrev}_{season}.json",
            standings.model_dump_json().encode("utf-8"),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--season",
        type=int,
        default=DEFAULT_SEASON,
        help=f"season to build (default: {DEFAULT_SEASON}, from MLB_SEASON env)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"output directory (default: {DEFAULT_OUT_DIR})",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    build_all(args.season, args.out_dir)
    logger.info("done → %s", args.out_dir)


if __name__ == "__main__":
    main()
