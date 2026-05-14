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

from config import APP_CACHE_DIR

from ..schemas import (
    BatterCard,
    BatterWindow,
    PitcherCard,
    PitcherWindow,
    PlayersResponse,
)
from .wpa import compute_wpa_for_game

logger = logging.getLogger(__name__)

JAYS_TEAM_ID = 141
_CACHE_DIR: Path = APP_CACHE_DIR / "game_wpa"
# Bump when adding fields the aggregator depends on. Files written under an
# older version are treated as missing so they get refetched on next request.
_CACHE_SCHEMA_VERSION = 2


def _cache_path(game_pk: int) -> Path:
    return _CACHE_DIR / f"{game_pk}.json"


def _load_cached(game_pk: int) -> dict[str, Any] | None:
    p = _cache_path(game_pk)
    if not p.is_file():
        return None
    try:
        with p.open() as f:
            data = json.load(f)
    except json.JSONDecodeError:
        logger.warning("corrupt cache %s; deleting", p)
        p.unlink(missing_ok=True)
        return None
    if data.get("schema_version") != _CACHE_SCHEMA_VERSION:
        return None  # stale; caller will rebuild
    return data


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

    # Round + augment pitchers from boxscore (pitches + starter flag + line)
    for rec in batters.values():
        rec["wpa"] = round(rec["wpa"], 5)
    jays_side = "home" if jays_are_home else "away"
    box_team = box["teams"][jays_side]
    box_players = box_team.get("players", {})

    # Augment batters with per-game line stats from the boxscore.
    for bid, rec in batters.items():
        bp = box_players.get(f"ID{bid}", {})
        st = bp.get("stats", {}).get("batting", {})
        rec["ab"] = int(st.get("atBats", 0) or 0)
        rec["h"] = int(st.get("hits", 0) or 0)
        rec["doubles"] = int(st.get("doubles", 0) or 0)
        rec["triples"] = int(st.get("triples", 0) or 0)
        rec["hr"] = int(st.get("homeRuns", 0) or 0)
        rec["bb"] = int(st.get("baseOnBalls", 0) or 0)
        rec["hbp"] = int(st.get("hitByPitch", 0) or 0)
        rec["sf"] = int(st.get("sacFlies", 0) or 0)
        rec["k"] = int(st.get("strikeOuts", 0) or 0)

    box_pids = box_team.get("pitchers", [])
    for idx, pid in enumerate(box_pids):
        rec = pitchers.get(int(pid))
        if rec is None:
            continue
        rec["is_starter"] = idx == 0
        bp = box_players.get(f"ID{pid}", {})
        st = bp.get("stats", {}).get("pitching", {})
        rec["pitches"] = int(st.get("numberOfPitches", st.get("pitchesThrown", 0)) or 0)
        # IP comes as "7.0" / "7.1" / "7.2" — store as outs for clean aggregation.
        ip_str = str(st.get("inningsPitched", "0.0") or "0.0")
        try:
            whole, _, frac = ip_str.partition(".")
            rec["outs"] = int(whole or 0) * 3 + int(frac or 0)
        except ValueError:
            rec["outs"] = 0
        rec["er"] = int(st.get("earnedRuns", 0) or 0)
        rec["k"] = int(st.get("strikeOuts", 0) or 0)
        rec["bb"] = int(st.get("baseOnBalls", 0) or 0)
    for rec in pitchers.values():
        rec["wpa"] = round(rec["wpa"], 5)

    return {
        "schema_version": _CACHE_SCHEMA_VERSION,
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
    finals = [
        g for g in sched
        if g.get("status") == "Final" and g.get("game_type") == "R"
    ]
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

        for pid_s, rec in tallies.get("batters", {}).items():
            pid = int(pid_s)
            agg = batter_agg.setdefault(
                pid,
                {"name": rec["name"], "series": []},
            )
            agg["name"] = rec["name"]  # latest spelling wins
            game_wpa = float(rec["wpa"])
            agg["series"].append(
                {
                    "date": tallies["game_date"],
                    "wpa": game_wpa,
                    "pa": int(rec.get("pa", 0)),
                    "rbi": int(rec.get("rbi", 0)),
                    "ab": int(rec.get("ab", 0)),
                    "h": int(rec.get("h", 0)),
                    "doubles": int(rec.get("doubles", 0)),
                    "triples": int(rec.get("triples", 0)),
                    "hr": int(rec.get("hr", 0)),
                    "bb": int(rec.get("bb", 0)),
                    "hbp": int(rec.get("hbp", 0)),
                    "sf": int(rec.get("sf", 0)),
                    "k": int(rec.get("k", 0)),
                }
            )

        for pid_s, rec in tallies.get("pitchers", {}).items():
            pid = int(pid_s)
            agg = pitcher_agg.setdefault(
                pid,
                {"name": rec["name"], "series": []},
            )
            agg["name"] = rec["name"]
            game_wpa = float(rec["wpa"])
            agg["series"].append(
                {
                    "date": tallies["game_date"],
                    "wpa": game_wpa,
                    "bf": int(rec.get("bf", 0)),
                    "pitches": int(rec.get("pitches", 0)),
                    "is_starter": bool(rec.get("is_starter", False)),
                    "outs": int(rec.get("outs", 0)),
                    "er": int(rec.get("er", 0)),
                    "k": int(rec.get("k", 0)),
                    "bb": int(rec.get("bb", 0)),
                }
            )

    cutoff_30 = ""
    if last_date:
        try:
            cutoff_30 = (
                dt.date.fromisoformat(last_date) - dt.timedelta(days=30)
            ).isoformat()
        except ValueError:
            cutoff_30 = ""

    def _outs_to_ip(outs: int) -> str:
        return f"{outs // 3}.{outs % 3}"

    def _batter_window(series: list[dict[str, Any]]) -> BatterWindow | None:
        if not series:
            return None
        ab = sum(s["ab"] for s in series)
        h = sum(s["h"] for s in series)
        doubles = sum(s["doubles"] for s in series)
        triples = sum(s["triples"] for s in series)
        hr = sum(s["hr"] for s in series)
        bb = sum(s["bb"] for s in series)
        hbp = sum(s["hbp"] for s in series)
        sf = sum(s["sf"] for s in series)
        so = sum(s["k"] for s in series)
        avg = round(h / ab, 3) if ab else None
        obp_den = ab + bb + hbp + sf
        obp = round((h + bb + hbp) / obp_den, 3) if obp_den else None
        singles = h - doubles - triples - hr
        tb = singles + 2 * doubles + 3 * triples + 4 * hr
        slg = round(tb / ab, 3) if ab else None
        return BatterWindow(
            wpa=round(sum(s["wpa"] for s in series), 5),
            games=len(series),
            pa=sum(s["pa"] for s in series),
            rbi=sum(s["rbi"] for s in series),
            ab=ab,
            h=h,
            hr=hr,
            so=so,
            bb=bb,
            avg=avg,
            obp=obp,
            slg=slg,
        )

    def _pitcher_window(series: list[dict[str, Any]]) -> PitcherWindow | None:
        if not series:
            return None
        outs = sum(s["outs"] for s in series)
        er = sum(s["er"] for s in series)
        era = round(9.0 * er / (outs / 3.0), 2) if outs else None
        return PitcherWindow(
            wpa=round(sum(s["wpa"] for s in series), 5),
            games=len(series),
            starts=sum(1 for s in series if s["is_starter"]),
            bf=sum(s["bf"] for s in series),
            pitches=sum(s["pitches"] for s in series),
            ip=_outs_to_ip(outs),
            er=er,
            so=sum(s["k"] for s in series),
            bb=sum(s["bb"] for s in series),
            era=era,
        )

    def _spark(series: list[dict[str, Any]]) -> list[float]:
        return [round(s["wpa"], 5) for s in sorted(series, key=lambda s: s["date"])]

    batters: list[BatterCard] = []
    for pid, v in batter_agg.items():
        series = v["series"]
        season_win = _batter_window(series)
        if season_win is None:
            continue
        recent = [s for s in series if s["date"] >= cutoff_30] if cutoff_30 else series
        batters.append(
            BatterCard(
                player_id=pid,
                name=v["name"],
                wpa=season_win.wpa,
                games=season_win.games,
                pa=season_win.pa,
                rbi=season_win.rbi,
                ab=season_win.ab,
                h=season_win.h,
                hr=season_win.hr,
                so=season_win.so,
                bb=season_win.bb,
                avg=season_win.avg,
                obp=season_win.obp,
                slg=season_win.slg,
                recent30=_batter_window(recent),
                spark_30=_spark(recent),
            )
        )

    pitchers: list[PitcherCard] = []
    for pid, v in pitcher_agg.items():
        series = v["series"]
        season_win = _pitcher_window(series)
        if season_win is None:
            continue
        recent = [s for s in series if s["date"] >= cutoff_30] if cutoff_30 else series
        pitchers.append(
            PitcherCard(
                player_id=pid,
                name=v["name"],
                wpa=season_win.wpa,
                games=season_win.games,
                starts=season_win.starts,
                bf=season_win.bf,
                pitches=season_win.pitches,
                ip=season_win.ip,
                er=season_win.er,
                so=season_win.so,
                bb=season_win.bb,
                era=season_win.era,
                recent30=_pitcher_window(recent),
                spark_30=_spark(recent),
            )
        )

    # "Full-time" filter: scale thresholds with games played so the cut stays
    # consistent through the season. Batters need ~0.8 PA/team-game (a regular
    # who starts most days). Pitchers need either a meaningful reliever
    # workload (~0.4 BF/team-game) or any rotation start (>=2 starts).
    min_batter_pa = max(25, int(games_included * 0.8))
    min_pitcher_bf = max(15, int(games_included * 0.4))
    batters = [b for b in batters if b.pa >= min_batter_pa]
    pitchers = [p for p in pitchers if p.bf >= min_pitcher_bf or p.starts >= 2]

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
