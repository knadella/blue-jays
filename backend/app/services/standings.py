"""Division standings, momentum, and quality-of-competition for the Blue Jays.

Everything is derived from the same regular-season schedule the rest of the app
already uses (and caches), so there is a single source of truth: completed games
in/out, no extra MLB endpoint shapes to maintain.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from config import DIVISIONS, TEAM_ABBREVS, TEAM_TO_DIVISION
from data_source.mlb_api import fetch_schedule, split_schedule

from ..schemas import QualityRecord, StandingsResponse, TeamStanding

FAVORITE_TEAM = "Toronto Blue Jays"

# Win% at/above which an opponent counts as a "good" team for quality-of-wins.
WINNING_THRESHOLD = 0.500


def _team_results(completed: list[dict]) -> dict[str, list[tuple[str, str, int]]]:
    """Per team: chronological list of (date, 'W'|'L', signed_run_margin)."""
    by_team: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for g in completed:
        hs, as_ = g.get("home_score"), g.get("away_score")
        if hs is None or as_ is None or hs == as_:
            continue  # skip ties / unscored
        d = g["game_date"][:10]
        home, away = g["home_name"], g["away_name"]
        margin = abs(hs - as_)
        if hs > as_:
            by_team[home].append((d, "W", margin))
            by_team[away].append((d, "L", -margin))
        else:
            by_team[away].append((d, "W", margin))
            by_team[home].append((d, "L", -margin))
    for t in by_team:
        by_team[t].sort(key=lambda r: r[0])
    return by_team


def _streak(results: list[str]) -> str:
    if not results:
        return "—"
    last = results[-1]
    n = 0
    for r in reversed(results):
        if r != last:
            break
        n += 1
    return f"{last}{n}"


def _last10(results: list[str]) -> tuple[str, list[str]]:
    tail = results[-10:]
    w = tail.count("W")
    return f"{w}-{len(tail) - w}", tail


def build_standings_payload(season: int) -> StandingsResponse:
    schedule = fetch_schedule(season)
    completed, _ = split_schedule(schedule)
    by_team = _team_results(completed)

    # Season-to-date win% for every team — used to grade quality of competition.
    win_pct: dict[str, float] = {}
    for team, recs in by_team.items():
        res = [r[1] for r in recs]
        win_pct[team] = res.count("W") / len(res) if res else 0.0

    division = TEAM_TO_DIVISION[FAVORITE_TEAM]
    rows: list[dict] = []
    for team in DIVISIONS[division]:
        recs = by_team.get(team, [])
        res = [r[1] for r in recs]
        w, l = res.count("W"), res.count("L")
        last10_str, last10_res = _last10(res)
        rows.append(
            {
                "team": team,
                "abbrev": TEAM_ABBREVS[team],
                "w": w,
                "l": l,
                "pct": round(w / (w + l), 3) if (w + l) else 0.0,
                "streak": _streak(res),
                "last10": last10_str,
                "last10_results": last10_res,
                "run_diff": sum(r[2] for r in recs),
                "is_favorite": team == FAVORITE_TEAM,
            }
        )

    rows.sort(key=lambda r: (-r["pct"], -r["w"], r["l"]))

    # Games back versus the division leader.
    leader = rows[0]
    teams: list[TeamStanding] = []
    for r in rows:
        gb = ((leader["w"] - r["w"]) + (r["l"] - leader["l"])) / 2
        teams.append(TeamStanding(gb=round(gb, 1), **r))

    # Favorite momentum.
    fav = by_team.get(FAVORITE_TEAM, [])
    fav_res = [r[1] for r in fav]
    fav_last10, _ = _last10(fav_res)
    last_game_date: Optional[str] = fav[-1][0] if fav else None

    # Quality of competition: grade each Jays decision by the opponent's win%.
    vs_w = {"w": 0, "l": 0}
    vs_l = {"w": 0, "l": 0}
    for g in completed:
        home, away = g["home_name"], g["away_name"]
        if FAVORITE_TEAM not in (home, away):
            continue
        hs, as_ = g.get("home_score"), g.get("away_score")
        if hs is None or as_ is None or hs == as_:
            continue
        opp = away if home == FAVORITE_TEAM else home
        jays_score = hs if home == FAVORITE_TEAM else as_
        opp_score = as_ if home == FAVORITE_TEAM else hs
        bucket = vs_w if win_pct.get(opp, 0.0) >= WINNING_THRESHOLD else vs_l
        bucket["w" if jays_score > opp_score else "l"] += 1

    def _quality(label: str, b: dict) -> QualityRecord:
        n = b["w"] + b["l"]
        return QualityRecord(
            label=label,
            w=b["w"],
            l=b["l"],
            pct=round(b["w"] / n, 3) if n else 0.0,
        )

    return StandingsResponse(
        season=season,
        division=division,
        last_game_date=last_game_date,
        teams=teams,
        favorite_streak=_streak(fav_res),
        favorite_last10=fav_last10,
        favorite_run_diff=sum(r[2] for r in fav),
        favorite_results=fav_res[-20:],
        vs_winning=_quality("vs winning teams (.500+)", vs_w),
        vs_losing=_quality("vs losing teams", vs_l),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
