"""Season-long per-player WPA aggregation for the Blue Jays.

For each completed Blue Jays game, computes per-player WPA tallies (batter
and pitcher) and caches the result to ``.cache/game_wpa/<game_pk>.json``.
The aggregator reads every cached game and returns sorted ``BatterCard`` /
``PitcherCard`` lists with best/worst single-game contributions.

First call after a new game lands does the heavy lifting (one StatsAPI
``game`` + ``game_boxscore`` call per uncached game). Repeat calls are
cheap: just JSON reads.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

import statsapi  # type: ignore[import-untyped]

from ..schemas import BatterCard, GameRef, PitcherCard, PlayersResponse
from .wpa import compute_wpa_for_game

logger = logging.getLogger(__name__)

JAYS_TEAM_ID = 141
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CACHE_DIR = _REPO_ROOT / ".cache" / "game_wpa"


def _cache_path(game_pk: int) -> Path:
    return _CACHE_DIR / f"{game_pk}.json"


def _load_cached(game_pk: int) -> dict[str, Any] | None:
    p = _cache_path(game_pk)
    if not p.is_file():
        return None
    try:
        with p.open() as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.warning("corrupt cache %s; deleting", p)
        p.unlink(missing_ok=True)
        return None


def _save_cached(game_pk: int, payload: dict[str, Any]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _cache_path(game_pk).with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(payload, f, separators=(",", ":"))
    tmp.replace(_cache_path(game_pk))


def _build_game_tallies(game_pk: int) -> dict[str, Any] | None:
    """Fetch one game from StatsAPI, run WPA, return per-player tallies."""
    try:
        full = statsapi.get("game", {"gamePk": game_pk})
        box = statsapi.get("game_boxscore", {"gamePk": game_pk})
    except Exception as exc:  # noqa: BLE001
        logger.warning("StatsAPI fetch failed for %s: %s", game_pk, exc)
        return None

    gd = full["gameData"]
    ld = full["liveData"]
    home = gd["teams"]["home"]
    away = gd["teams"]["away"]
    home_id = home["id"]
    away_id = away["id"]
    jays_are_home = home_id == JAYS_TEAM_ID
    opp = away if jays_are_home else home
    opp_abbr = opp.get("abbreviation", opp["name"][:3].upper())
    game_date = gd.get("datetime", {}).get("officialDate", "")

    linescore = ld["linescore"]
    final_home = int(linescore["teams"]["home"].get("runs", 0) or 0)
    final_away = int(linescore["teams"]["away"].get("runs", 0) or 0)
    jays_score = final_home if jays_are_home else final_away
    opp_score = final_away if jays_are_home else final_home
    jays_won = jays_score > opp_score

    plays: list[dict[str, Any]] = ld["plays"]["allPlays"]
    wpa_rows = compute_wpa_for_game(plays, home_team_id=home_id)

    # Per-game per-player tallies.
    batters: dict[int, dict[str, Any]] = {}
    pitchers: dict[int, dict[str, Any]] = {}

    for i, play in enumerate(plays):
        about = play.get("about") or {}
        result = play.get("result") or {}
        wp = wpa_rows[i] if i < len(wpa_rows) else None
        if wp is None:
            continue
        m = play.get("matchup") or {}
        batter = m.get("batter") or {}
        pitcher = m.get("pitcher") or {}
        bid = batter.get("id")
        pid = pitcher.get("id")

        batter_is_home = not about.get("isTopInning", False)
        batter_is_jays = batter_is_home == jays_are_home
        pitcher_is_jays = not batter_is_jays

        wpa_bat = wp["wpa_batter"]

        if bid and batter_is_jays:
            rec = batters.setdefault(
                int(bid),
                {"name": batter.get("fullName", "?"), "wpa": 0.0, "pa": 0, "rbi": 0},
            )
            rec["wpa"] += wpa_bat
            rec["pa"] += 1
            rec["rbi"] += result.get("rbi", 0) or 0

        if pid and pitcher_is_jays:
            rec = pitchers.setdefault(
                int(pid),
                {
                    "name": pitcher.get("fullName", "?"),
                    "wpa": 0.0,
                    "bf": 0,
                    "pitches": 0,
                    "is_starter": False,
                },
            )
            rec["wpa"] += -wpa_bat
            rec["bf"] += 1

    # Round + augment pitchers from boxscore (pitches + starter flag)
    for rec in batters.values():
        rec["wpa"] = round(rec["wpa"], 5)
    jays_side = "home" if jays_are_home else "away"
    box_team = box["teams"][jays_side]
    box_pids = box_team.get("pitchers", [])
    box_players = box_team.get("players", {})
    for idx, pid in enumerate(box_pids):
        rec = pitchers.get(int(pid))
        if rec is None:
            continue
        rec["is_starter"] = idx == 0
        bp = box_players.get(f"ID{pid}", {})
        st = bp.get("stats", {}).get("pitching", {})
        rec["pitches"] = int(st.get("numberOfPitches", st.get("pitchesThrown", 0)) or 0)
    for rec in pitchers.values():
        rec["wpa"] = round(rec["wpa"], 5)

    return {
        "game_pk": int(game_pk),
        "game_date": game_date,
        "opp_abbr": opp_abbr,
        "jays_won": bool(jays_won),
        "jays_score": int(jays_score),
        "opp_score": int(opp_score),
        "batters": {str(k): v for k, v in batters.items()},
        "pitchers": {str(k): v for k, v in pitchers.items()},
        "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def _completed_jays_games(season: int) -> list[dict[str, Any]]:
    today = dt.date.today().isoformat()
    start = f"{season}-03-01"
    try:
        sched = statsapi.schedule(
            team=JAYS_TEAM_ID, start_date=start, end_date=today
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("schedule fetch failed: %s", exc)
        return []
    finals = [g for g in sched if g.get("status") == "Final"]
    finals.sort(key=lambda g: g["game_date"])
    return finals


def _ensure_cached(game_pk: int) -> dict[str, Any] | None:
    cached = _load_cached(game_pk)
    if cached is not None:
        return cached
    payload = _build_game_tallies(game_pk)
    if payload is not None:
        _save_cached(game_pk, payload)
    return payload


def build_players_payload(season: int) -> PlayersResponse:
    games = _completed_jays_games(season)
    if not games:
        return PlayersResponse(
            season=season,
            games_included=0,
            batters=[],
            pitchers=[],
            generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        )

    batter_agg: dict[int, dict[str, Any]] = {}
    pitcher_agg: dict[int, dict[str, Any]] = {}
    last_date = ""
    games_included = 0

    for g in games:
        gpk = int(g["game_id"])
        tallies = _ensure_cached(gpk)
        if tallies is None:
            continue
        games_included += 1
        last_date = max(last_date, tallies.get("game_date", ""))
        gref_base = {
            "game_pk": tallies["game_pk"],
            "game_date": tallies["game_date"],
            "opp_abbr": tallies["opp_abbr"],
            "jays_won": tallies["jays_won"],
        }

        for pid_s, rec in tallies.get("batters", {}).items():
            pid = int(pid_s)
            agg = batter_agg.setdefault(
                pid,
                {
                    "name": rec["name"],
                    "wpa": 0.0,
                    "games": 0,
                    "pa": 0,
                    "rbi": 0,
                    "best": None,
                    "worst": None,
                },
            )
            agg["name"] = rec["name"]  # latest spelling wins
            game_wpa = float(rec["wpa"])
            agg["wpa"] += game_wpa
            agg["games"] += 1
            agg["pa"] += int(rec.get("pa", 0))
            agg["rbi"] += int(rec.get("rbi", 0))
            gref = {**gref_base, "wpa": round(game_wpa, 5)}
            if agg["best"] is None or game_wpa > agg["best"]["wpa"]:
                agg["best"] = gref
            if agg["worst"] is None or game_wpa < agg["worst"]["wpa"]:
                agg["worst"] = gref

        for pid_s, rec in tallies.get("pitchers", {}).items():
            pid = int(pid_s)
            agg = pitcher_agg.setdefault(
                pid,
                {
                    "name": rec["name"],
                    "wpa": 0.0,
                    "games": 0,
                    "starts": 0,
                    "bf": 0,
                    "pitches": 0,
                    "best": None,
                    "worst": None,
                },
            )
            agg["name"] = rec["name"]
            game_wpa = float(rec["wpa"])
            agg["wpa"] += game_wpa
            agg["games"] += 1
            if rec.get("is_starter"):
                agg["starts"] += 1
            agg["bf"] += int(rec.get("bf", 0))
            agg["pitches"] += int(rec.get("pitches", 0))
            gref = {**gref_base, "wpa": round(game_wpa, 5)}
            if agg["best"] is None or game_wpa > agg["best"]["wpa"]:
                agg["best"] = gref
            if agg["worst"] is None or game_wpa < agg["worst"]["wpa"]:
                agg["worst"] = gref

    batters = [
        BatterCard(
            player_id=pid,
            name=v["name"],
            wpa=round(v["wpa"], 5),
            games=v["games"],
            pa=v["pa"],
            rbi=v["rbi"],
            best_game=GameRef(**v["best"]) if v["best"] else None,
            worst_game=GameRef(**v["worst"]) if v["worst"] else None,
        )
        for pid, v in batter_agg.items()
    ]
    pitchers = [
        PitcherCard(
            player_id=pid,
            name=v["name"],
            wpa=round(v["wpa"], 5),
            games=v["games"],
            starts=v["starts"],
            bf=v["bf"],
            pitches=v["pitches"],
            best_game=GameRef(**v["best"]) if v["best"] else None,
            worst_game=GameRef(**v["worst"]) if v["worst"] else None,
        )
        for pid, v in pitcher_agg.items()
    ]

    batters.sort(key=lambda c: c.wpa, reverse=True)
    pitchers.sort(key=lambda c: c.wpa, reverse=True)

    return PlayersResponse(
        season=season,
        games_included=games_included,
        last_game_date=last_date or None,
        batters=batters,
        pitchers=pitchers,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
