"""Build the post-game "Today" payload for the most recent completed Blue Jays game.

Wraps MLB StatsAPI play-by-play and boxscore, computes per-play WPA via
``backend.app.services.wpa``, and returns a structured ``TodayResponse``.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from typing import Any

import statsapi  # type: ignore[import-untyped]

from ..schemas import (
    Contributor,
    GameHeader,
    LeveragePlay,
    PitcherLine,
    TodayResponse,
    WEPoint,
)
from .wpa import compute_wpa_for_game, we_table_meta

logger = logging.getLogger(__name__)

JAYS_TEAM_ID = 141


def _shorten(desc: str, n: int = 110) -> str:
    desc = (desc or "").strip().rstrip(".")
    if len(desc) <= n:
        return desc
    return desc[: n - 1] + "…"


def _half_letter(about: dict[str, Any]) -> str:
    return "T" if about.get("isTopInning") else "B"


def _find_latest_jays_final(lookback_days: int = 30) -> dict[str, Any] | None:
    today = dt.date.today()
    start = (today - dt.timedelta(days=lookback_days)).isoformat()
    try:
        sched = statsapi.schedule(
            team=JAYS_TEAM_ID, start_date=start, end_date=today.isoformat()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("StatsAPI schedule failed: %s", exc)
        return None
    finals = [g for g in sched if g.get("status") == "Final"]
    if not finals:
        return None
    finals.sort(key=lambda g: g["game_date"])
    return finals[-1]


def build_today_payload() -> TodayResponse | None:
    """Return the Today payload, or None if no recent Final game can be found."""
    game = _find_latest_jays_final()
    if game is None:
        return None

    gid = game["game_id"]
    full = statsapi.get("game", {"gamePk": gid})
    gd = full["gameData"]
    ld = full["liveData"]

    home = gd["teams"]["home"]
    away = gd["teams"]["away"]
    home_id = home["id"]
    away_id = away["id"]
    jays_are_home = home_id == JAYS_TEAM_ID

    linescore = ld["linescore"]
    final_home = linescore["teams"]["home"].get("runs", game.get("home_score", 0)) or 0
    final_away = linescore["teams"]["away"].get("runs", game.get("away_score", 0)) or 0

    jays_score = final_home if jays_are_home else final_away
    opp_score = final_away if jays_are_home else final_home

    venue = gd.get("venue", {}).get("name", "")
    game_date = gd.get("datetime", {}).get("officialDate", game["game_date"])

    header = GameHeader(
        game_pk=int(gid),
        game_date=game_date,
        venue=venue,
        home_team=home["name"],
        home_abbr=home.get("abbreviation", home["name"][:3].upper()),
        away_team=away["name"],
        away_abbr=away.get("abbreviation", away["name"][:3].upper()),
        home_score=int(final_home),
        away_score=int(final_away),
        jays_won=jays_score > opp_score,
        jays_score=int(jays_score),
        opp_score=int(opp_score),
    )

    plays: list[dict[str, Any]] = ld["plays"]["allPlays"]
    wpa_rows = compute_wpa_for_game(plays, home_team_id=home_id)

    # ------ trajectory + leverage --------------------------------------
    trajectory: list[WEPoint] = []
    leverage_candidates: list[tuple[int, dict[str, Any], dict[str, Any], dict[str, Any]]] = []

    prev_home, prev_away = 0, 0
    for i, play in enumerate(plays):
        about = play.get("about") or {}
        result = play.get("result") or {}
        wp = wpa_rows[i] if i < len(wpa_rows) else None
        if wp is None:
            continue

        about_top = about.get("isTopInning", False)
        batter_is_home = not about_top
        batter_is_jays = batter_is_home == jays_are_home

        # WE_after from the BATTING side; convert to Jays-perspective
        we_after_bat = wp["we_after"]
        we_after_jays = we_after_bat if batter_is_jays else (1.0 - we_after_bat)

        trajectory.append(
            WEPoint(
                play_index=i,
                inning=int(about.get("inning", 0) or 0),
                half=_half_letter(about),
                we_jays=round(we_after_jays, 5),
            )
        )

        # WPA from Jays perspective
        wpa_bat = wp["wpa_batter"]
        wpa_jays = wpa_bat if batter_is_jays else -wpa_bat

        leverage_candidates.append(
            (
                i,
                {
                    "wpa_jays": wpa_jays,
                    "we_before_jays": wp["we_before"]
                    if batter_is_jays
                    else (1.0 - wp["we_before"]),
                    "we_after_jays": we_after_jays,
                    "score_before": (prev_away, prev_home),
                },
                about,
                result,
            )
        )

        prev_home = result.get("homeScore", prev_home)
        prev_away = result.get("awayScore", prev_away)

    leverage_candidates.sort(key=lambda t: abs(t[1]["wpa_jays"]), reverse=True)

    leverage_plays: list[LeveragePlay] = []
    for play_idx, ext, about, result in leverage_candidates[:5]:
        a, h = ext["score_before"]
        score_str = f"{header.away_abbr} {a}-{h} {header.home_abbr}"
        leverage_plays.append(
            LeveragePlay(
                play_index=play_idx,
                inning=int(about.get("inning", 0) or 0),
                half=_half_letter(about),
                score_before=score_str,
                description=_shorten(result.get("description", "")),
                wpa_jays=round(ext["wpa_jays"], 5),
                we_before_jays=round(ext["we_before_jays"], 5),
                we_after_jays=round(ext["we_after_jays"], 5),
            )
        )

    # ------ contributors ----------------------------------------------
    batter_tally: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "name": "",
            "team_is_jays": False,
            "wpa": 0.0,
            "rbi": 0,
            "pa": 0,
            "best": (-1e9, "", 0),
            "worst": (1e9, "", 0),
        }
    )

    for i, play in enumerate(plays):
        about = play.get("about") or {}
        result = play.get("result") or {}
        wp = wpa_rows[i] if i < len(wpa_rows) else None
        if wp is None:
            continue
        m = play.get("matchup") or {}
        batter = m.get("batter") or {}
        bid = batter.get("id")
        if not bid:
            continue
        about_top = about.get("isTopInning", False)
        batter_is_home = not about_top
        batter_is_jays = batter_is_home == jays_are_home
        wpa_bat = wp["wpa_batter"]

        rec = batter_tally[bid]
        rec["name"] = batter.get("fullName", "?")
        rec["team_is_jays"] = batter_is_jays
        rec["wpa"] += wpa_bat
        rec["rbi"] += result.get("rbi", 0) or 0
        rec["pa"] += 1
        inn = int(about.get("inning", 0) or 0)
        desc = _shorten(result.get("description", ""), 80)
        if wpa_bat > rec["best"][0]:
            rec["best"] = (wpa_bat, desc, inn)
        if wpa_bat < rec["worst"][0]:
            rec["worst"] = (wpa_bat, desc, inn)

    jays_batters = [
        (bid, v) for bid, v in batter_tally.items() if v["team_is_jays"]
    ]
    jays_pos = sorted(jays_batters, key=lambda t: t[1]["wpa"], reverse=True)
    jays_neg = sorted(jays_batters, key=lambda t: t[1]["wpa"])

    def _contrib(bid: int, v: dict[str, Any], use_best: bool) -> Contributor:
        if use_best:
            w, desc, inn = v["best"]
            best_play = f"(+{w:.3f} I{inn}) {desc}" if desc else None
            worst_play = None
        else:
            w, desc, inn = v["worst"]
            worst_play = f"({w:.3f} I{inn}) {desc}" if desc else None
            best_play = None
        return Contributor(
            player_id=bid,
            name=v["name"],
            wpa=round(v["wpa"], 5),
            pa=v["pa"],
            rbi=v["rbi"],
            best_play=best_play,
            worst_play=worst_play,
        )

    top_contribs = [_contrib(bid, v, True) for bid, v in jays_pos[:3] if v["wpa"] > 0]
    neg_contribs = [_contrib(bid, v, False) for bid, v in jays_neg[:3] if v["wpa"] < 0]

    # ------ pitching from boxscore -------------------------------------
    box = statsapi.get("game_boxscore", {"gamePk": gid})
    jays_side = "home" if jays_are_home else "away"
    opp_side = "away" if jays_are_home else "home"
    jays_box = box["teams"][jays_side]
    jays_pitcher_ids = jays_box.get("pitchers", [])
    jays_players = jays_box.get("players", {})

    def _pline(pid: int, role: str, players: dict[str, Any]) -> PitcherLine | None:
        p = players.get(f"ID{pid}")
        if not p:
            return None
        st = p.get("stats", {}).get("pitching", {})
        person = p.get("person", {})
        return PitcherLine(
            player_id=int(pid),
            name=person.get("fullName", "?"),
            role=role,
            ip=str(st.get("inningsPitched", "0")),
            h=int(st.get("hits", 0) or 0),
            r=int(st.get("runs", 0) or 0),
            er=int(st.get("earnedRuns", 0) or 0),
            k=int(st.get("strikeOuts", 0) or 0),
            bb=int(st.get("baseOnBalls", 0) or 0),
            pitches=int(st.get("numberOfPitches", st.get("pitchesThrown", 0)) or 0),
            note=st.get("note", "") or "",
        )

    starter = _pline(jays_pitcher_ids[0], "starter", jays_players) if jays_pitcher_ids else None
    relievers = [
        line
        for rid in jays_pitcher_ids[1:]
        if (line := _pline(rid, "relief", jays_players)) is not None
    ]
    bullpen_pitches = sum(r.pitches for r in relievers)

    opp_box = box["teams"][opp_side]
    opp_pitcher_ids = opp_box.get("pitchers", [])
    opp_starter = (
        _pline(opp_pitcher_ids[0], "starter", opp_box.get("players", {}))
        if opp_pitcher_ids
        else None
    )

    return TodayResponse(
        header=header,
        we_trajectory=trajectory,
        leverage_plays=leverage_plays,
        top_contributors=top_contribs,
        negative_contributors=neg_contribs,
        starter=starter,
        relievers=relievers,
        bullpen_pitches=bullpen_pitches,
        opp_starter=opp_starter,
        we_table_meta=we_table_meta(),
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
