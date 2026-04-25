"""Spike: build a 'game story' view for the most recent completed Blue Jays game.

Throwaway. One-shot. Prints to stdout.

Now uses real WPA (backend/app/services/wpa.py) backed by an empirical Win
Expectancy table built from historical Statcast seasons.

Run: .venv/bin/python scripts/blue_jays_game_story.py
"""
from __future__ import annotations

import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import statsapi

# Make backend importable when running this script directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.app.services.wpa import compute_wpa_for_game, we_table_meta  # noqa: E402

JAYS_TEAM_ID = 141


# ----- helpers -----------------------------------------------------------

def find_latest_jays_final() -> dict[str, Any]:
    """Walk back from today until we find the most recent Final Jays game."""
    today = dt.date.today()
    start = (today - dt.timedelta(days=30)).isoformat()
    sched = statsapi.schedule(
        team=JAYS_TEAM_ID, start_date=start, end_date=today.isoformat()
    )
    finals = [g for g in sched if g.get("status") == "Final"]
    if not finals:
        raise SystemExit("No Final Blue Jays games in the last 30 days.")
    finals.sort(key=lambda g: g["game_date"])
    return finals[-1]


def fmt_inning(about: dict) -> str:
    half = "T" if about.get("isTopInning") else "B"
    return f"{half}{about.get('inning', '?')}"


def shorten(desc: str, n: int = 110) -> str:
    desc = (desc or "").strip().rstrip(".")
    if len(desc) <= n:
        return desc
    return desc[: n - 1] + "…"


# ----- main --------------------------------------------------------------

def main() -> None:
    game = find_latest_jays_final()
    gid = game["game_id"]

    full = statsapi.get("game", {"gamePk": gid})
    gd = full["gameData"]
    ld = full["liveData"]

    home_name = gd["teams"]["home"]["name"]
    away_name = gd["teams"]["away"]["name"]
    home_abbr = gd["teams"]["home"].get("abbreviation", home_name[:3].upper())
    away_abbr = gd["teams"]["away"].get("abbreviation", away_name[:3].upper())
    venue = gd.get("venue", {}).get("name", "Unknown venue")
    game_date = gd.get("datetime", {}).get("officialDate", game["game_date"])

    linescore = ld["linescore"]
    final_home = linescore["teams"]["home"].get("runs", game.get("home_score", 0))
    final_away = linescore["teams"]["away"].get("runs", game.get("away_score", 0))

    jays_are_home = gd["teams"]["home"]["id"] == JAYS_TEAM_ID
    jays_score = final_home if jays_are_home else final_away
    opp_score = final_away if jays_are_home else final_home
    jays_won = jays_score > opp_score

    plays = ld["plays"]["allPlays"]

    # ---- header ---------------------------------------------------------
    print("=" * 78)
    print(f"BLUE JAYS GAME STORY  |  {game_date}  |  {venue}")
    print(
        f"{away_name} ({away_abbr}) {final_away}  @  "
        f"{home_name} ({home_abbr}) {final_home}"
    )
    result_word = "WIN" if jays_won else "LOSS"
    print(f"Toronto: {result_word}  ({jays_score}-{opp_score})")
    meta = we_table_meta()
    if meta:
        seasons = meta.get("seasons", [])
        n_states = meta.get("n_states", 0)
        print(
            f"WE table: {n_states} states from seasons {seasons}"
        )
    print("=" * 78)

    # ---- compute real WPA per play --------------------------------------
    home_team_id = gd["teams"]["home"]["id"]
    wpa_rows = compute_wpa_for_game(plays, home_team_id=home_team_id)

    # Build an enriched list of (play, wpa_row, prev_score) for downstream tallies.
    enriched = []
    prev_home, prev_away = 0, 0
    for i, p in enumerate(plays):
        res = p.get("result", {})
        wp = wpa_rows[i] if i < len(wpa_rows) else None
        enriched.append(
            {
                "play": p,
                "wpa": wp,
                "score_before": (prev_away, prev_home),
            }
        )
        prev_home = res.get("homeScore", prev_home)
        prev_away = res.get("awayScore", prev_away)

    # Top-leverage plays = largest |WPA|.
    by_leverage = sorted(
        enriched, key=lambda e: abs((e["wpa"] or {}).get("wpa_batter", 0)), reverse=True
    )[:5]

    print()
    print("--- TOP LEVERAGE PLAYS (by |WPA|) " + "-" * 44)
    for e in by_leverage:
        p = e["play"]
        about = p["about"]
        res = p["result"]
        a, h = e["score_before"]
        score_str = f"{away_abbr} {a}-{h} {home_abbr}"
        wp = e["wpa"] or {}
        wpa_b = wp.get("wpa_batter", 0.0)
        we_b = wp.get("we_before", 0.0)
        we_a = wp.get("we_after", 0.0)
        # Express WPA as Jays-perspective so + means good for Toronto.
        about_top = about.get("isTopInning", False)
        batter_is_home = not about_top
        batter_is_jays = batter_is_home == jays_are_home
        wpa_jays = wpa_b if batter_is_jays else -wpa_b
        sign = "+" if wpa_jays >= 0 else "-"
        print(
            f"  {fmt_inning(about):>3}  WPA(TOR)={sign}{abs(wpa_jays):.3f}  "
            f"WE bat: {we_b:.2f} -> {we_a:.2f}  ({score_str})"
        )
        print(f"        {shorten(res.get('description', ''))}")

    # ---- contributor tally (real WPA) -----------------------------------
    # For each play, batter gets +wpa_batter. Pitcher gets -wpa_batter.
    # We tally separately for Jays batters and Jays pitchers.
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
    pitcher_tally: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"name": "", "team_is_jays": False, "wpa": 0.0, "bf": 0}
    )

    for e in enriched:
        p = e["play"]
        about = p["about"]
        res = p["result"]
        wp = e["wpa"] or {}
        wpa_b = wp.get("wpa_batter", 0.0)
        m = p.get("matchup", {})
        batter = m.get("batter", {}) or {}
        pitcher = m.get("pitcher", {}) or {}
        bid = batter.get("id")
        pid = pitcher.get("id")
        if not bid:
            continue

        batter_is_home = not about.get("isTopInning", False)
        batter_is_jays = batter_is_home == jays_are_home
        pitcher_is_jays = not batter_is_jays

        rec = batter_tally[bid]
        rec["name"] = batter.get("fullName", "?")
        rec["team_is_jays"] = batter_is_jays
        rec["wpa"] += wpa_b
        rec["rbi"] += res.get("rbi", 0) or 0
        rec["pa"] += 1
        inn = about.get("inning", 0) or 0
        desc = shorten(res.get("description", ""), 80)
        if wpa_b > rec["best"][0]:
            rec["best"] = (wpa_b, desc, inn)
        if wpa_b < rec["worst"][0]:
            rec["worst"] = (wpa_b, desc, inn)

        if pid:
            pr = pitcher_tally[pid]
            pr["name"] = pitcher.get("fullName", "?")
            pr["team_is_jays"] = pitcher_is_jays
            pr["wpa"] += -wpa_b  # pitcher WPA = -batter WPA
            pr["bf"] += 1

    jays_batters = [v for v in batter_tally.values() if v["team_is_jays"]]
    jays_batters_sorted = sorted(jays_batters, key=lambda v: v["wpa"], reverse=True)

    print()
    print("--- BLUE JAYS — TOP CONTRIBUTORS (sum WPA) " + "-" * 35)
    for v in jays_batters_sorted[:3]:
        if v["wpa"] <= 0:
            continue
        best_w, best_desc, best_inn = v["best"]
        print(
            f"  {v['name']:<24} WPA=+{v['wpa']:.3f}  RBI={v['rbi']}  PA={v['pa']}"
        )
        if best_desc:
            print(f"        best (+{best_w:.3f} I{best_inn}): {best_desc}")

    # Negative contributors: Jays batters with most-negative summed WPA.
    jays_neg = sorted(jays_batters, key=lambda v: v["wpa"])[:3]
    jays_neg = [v for v in jays_neg if v["wpa"] < 0]

    if jays_neg:
        print()
        print("--- BLUE JAYS — NEGATIVE CONTRIBUTORS (sum WPA) " + "-" * 30)
        for v in jays_neg:
            worst_w, worst_desc, worst_inn = v["worst"]
            print(
                f"  {v['name']:<24} WPA={v['wpa']:.3f}  RBI={v['rbi']}  PA={v['pa']}"
            )
            if worst_desc:
                print(f"        worst ({worst_w:.3f} I{worst_inn}): {worst_desc}")

    # ---- pitching summary from boxscore ---------------------------------
    box = statsapi.get("game_boxscore", {"gamePk": gid})
    jays_side = "home" if jays_are_home else "away"
    opp_side = "away" if jays_are_home else "home"
    jays_box = box["teams"][jays_side]
    jays_pitcher_ids = jays_box.get("pitchers", [])
    jays_players = jays_box.get("players", {})

    print()
    print("--- BLUE JAYS PITCHING " + "-" * 55)

    starter_id = jays_pitcher_ids[0] if jays_pitcher_ids else None
    if starter_id:
        p = jays_players.get(f"ID{starter_id}", {})
        st = p.get("stats", {}).get("pitching", {})
        person = p.get("person", {})
        ip = st.get("inningsPitched", "0")
        h = st.get("hits", 0)
        r = st.get("runs", 0)
        er = st.get("earnedRuns", 0)
        k = st.get("strikeOuts", 0)
        bb = st.get("baseOnBalls", 0)
        pitches = st.get("numberOfPitches", st.get("pitchesThrown", 0))
        note = st.get("note", "")
        print(
            f"  STARTER  {person.get('fullName', '?')}: "
            f"{ip} IP, {h} H, {r} R, {er} ER, {k} K, {bb} BB, {pitches} pitches "
            f"{note}".rstrip()
        )

    # bullpen
    relievers = jays_pitcher_ids[1:]
    total_bp_pitches = 0
    bp_lines = []
    high_lev_relief = []
    for rid in relievers:
        p = jays_players.get(f"ID{rid}", {})
        st = p.get("stats", {}).get("pitching", {})
        person = p.get("person", {})
        ip = st.get("inningsPitched", "0")
        pitches = st.get("numberOfPitches", st.get("pitchesThrown", 0))
        h = st.get("hits", 0)
        r = st.get("runs", 0)
        er = st.get("earnedRuns", 0)
        k = st.get("strikeOuts", 0)
        bb = st.get("baseOnBalls", 0)
        note = st.get("note", "")
        total_bp_pitches += pitches
        bp_lines.append(
            f"  RELIEF   {person.get('fullName', '?'):<22} "
            f"{ip} IP, {h} H, {r} R, {er} ER, {k} K, {bb} BB, {pitches} P {note}".rstrip()
        )
        # Flag high-leverage relief: largest |WPA| play they were in.
        max_abs_wpa = max(
            (
                abs((e["wpa"] or {}).get("wpa_batter", 0.0))
                for e in enriched
                if (e["play"].get("matchup", {}).get("pitcher") or {}).get("id") == rid
            ),
            default=0.0,
        )
        # Sum WPA from this reliever's perspective (pitcher = -batter WPA, sign-flipped Jays-perspective).
        sum_pitcher_wpa = pitcher_tally.get(rid, {}).get("wpa", 0.0)
        if max_abs_wpa >= 0.10:
            high_lev_relief.append(
                f"    high-leverage: {person.get('fullName', '?')} "
                f"(top |WPA|={max_abs_wpa:.3f}, sum WPA={sum_pitcher_wpa:+.3f})"
            )

    for line in bp_lines:
        print(line)
    print(
        f"  Bullpen workload: {len(relievers)} relievers, {total_bp_pitches} total pitches"
    )
    for hl in high_lev_relief:
        print(hl)

    # opponent starter for context
    opp_box = box["teams"][opp_side]
    opp_pitcher_ids = opp_box.get("pitchers", [])
    if opp_pitcher_ids:
        op = opp_box.get("players", {}).get(f"ID{opp_pitcher_ids[0]}", {})
        ost = op.get("stats", {}).get("pitching", {})
        oname = op.get("person", {}).get("fullName", "?")
        print()
        print(
            f"  (Opp starter {oname}: "
            f"{ost.get('inningsPitched', '0')} IP, "
            f"{ost.get('hits', 0)} H, {ost.get('earnedRuns', 0)} ER, "
            f"{ost.get('strikeOuts', 0)} K)"
        )

    print()
    print("=" * 78)


if __name__ == "__main__":
    main()
