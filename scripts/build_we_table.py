#!/usr/bin/env python3
"""Build empirical Win Expectancy table from cached Statcast season files.

Reads ``.cache/statcast_seasons/<year>.parquet`` for each requested season,
derives a per-PA state row (one observation per plate appearance), joins
each state to the eventual home-team win indicator, and computes the empirical
P(home team wins | state) per state cell.

State key: (inning, half_inning, outs, base_state, score_diff)
- inning: 1..9, with 10+ collapsed to "X"
- half_inning: "T" / "B"
- outs: 0,1,2
- base_state: 3-bit string for (1B, 2B, 3B), e.g. "101" = runners on 1B+3B
- score_diff: BATTING team minus FIELDING team, clipped to [-10, 10]

Writes ``data/win_expectancy/we_table.json`` keyed by ``"{inning}|{half}|{outs}|{bases}|{diff}"``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache" / "statcast_seasons"
OUT_DIR = ROOT / "data" / "win_expectancy"
OUT_FILE = OUT_DIR / "we_table.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("build_we_table")

SCORE_CLIP = 10
OUTS_RANGE = (0, 1, 2)


def _bases_str(row) -> str:
    return (
        ("1" if pd.notna(row["on_1b"]) else "0")
        + ("1" if pd.notna(row["on_2b"]) else "0")
        + ("1" if pd.notna(row["on_3b"]) else "0")
    )


def state_key(
    inning: int | str,
    half: str,
    outs: int,
    bases: str,
    score_diff: int,
) -> str:
    return f"{inning}|{half}|{int(outs)}|{bases}|{int(score_diff)}"


def load_season(year: int) -> pd.DataFrame | None:
    p = CACHE_DIR / f"{year}.parquet"
    if not p.is_file():
        log.warning("no cache for %d at %s", year, p)
        return None
    df = pd.read_parquet(p)
    log.info("loaded %d (%d rows)", year, len(df))
    return df


def derive_states(df: pd.DataFrame) -> pd.DataFrame:
    """Return one row per plate appearance with state-before-PA + eventual home win."""
    # Restrict to regular-season games
    if "game_type" in df.columns:
        df = df[df["game_type"] == "R"].copy()
    # Sort so we can pick the first pitch per PA
    df = df.sort_values(["game_pk", "at_bat_number", "pitch_number"], kind="mergesort")
    # First pitch of each PA carries the state-before
    first = df.groupby(["game_pk", "at_bat_number"], as_index=False).head(1).copy()

    # Compute final score per game. ``home_score``/``away_score`` are PRE-pitch;
    # ``post_home_score``/``post_away_score`` are POST-pitch and reflect the
    # actual final after the last pitch of the game.
    score_h_col = "post_home_score" if "post_home_score" in df.columns else "home_score"
    score_a_col = "post_away_score" if "post_away_score" in df.columns else "away_score"
    finals = df.groupby("game_pk", as_index=False).agg(
        final_home=(score_h_col, "max"),
        final_away=(score_a_col, "max"),
    )
    finals["home_won"] = (finals["final_home"] > finals["final_away"]).astype(int)
    # Drop ties (extras shouldn't tie in regular season post-2020 ghost runner era,
    # but defensively drop)
    tied = (finals["final_home"] == finals["final_away"]).sum()
    if tied:
        log.info("dropping %d tied games", tied)
    finals = finals[finals["final_home"] != finals["final_away"]]

    first = first.merge(finals[["game_pk", "home_won"]], on="game_pk", how="inner")

    # Build state columns
    first["base_state"] = (
        first["on_1b"].notna().astype(int).astype(str)
        + first["on_2b"].notna().astype(int).astype(str)
        + first["on_3b"].notna().astype(int).astype(str)
    )
    first["outs"] = first["outs_when_up"].astype(int).clip(0, 2)
    first["half"] = first["inning_topbot"].map({"Top": "T", "Bot": "B"})

    inning = first["inning"].astype(int)
    first["inning_key"] = inning.where(inning <= 9, 10).astype(int).astype(str)
    first.loc[inning > 9, "inning_key"] = "X"  # extras lumped

    # batting/fielding scores
    bat = pd.to_numeric(first["bat_score"], errors="coerce")
    fld = pd.to_numeric(first["fld_score"], errors="coerce")
    diff = (bat - fld).clip(-SCORE_CLIP, SCORE_CLIP).astype("Int64")

    # we want score_diff from the batting team's perspective
    first["score_diff"] = diff

    # win indicator from the BATTING team's perspective for easier inspection,
    # but we'll store P(home wins) so use home_won directly along with half.
    keep = first[
        [
            "game_pk",
            "inning_key",
            "half",
            "outs",
            "base_state",
            "score_diff",
            "home_won",
        ]
    ].dropna(subset=["half", "score_diff"])
    return keep


def aggregate(states: pd.DataFrame) -> pd.DataFrame:
    g = (
        states.groupby(
            ["inning_key", "half", "outs", "base_state", "score_diff"],
            as_index=False,
        )
        .agg(home_wins=("home_won", "sum"), n=("home_won", "count"))
    )
    g["win_prob_home"] = g["home_wins"] / g["n"]
    return g


def to_we_dict(agg: pd.DataFrame) -> dict[str, dict]:
    """Convert to dict keyed by state string. Stores BATTING-team WE.

    For ``half == 'T'``: batting team is away => bat_we = 1 - p(home wins)
    For ``half == 'B'``: batting team is home => bat_we = p(home wins)

    We store both, plus ``n``, so callers can pick.
    """
    out: dict[str, dict] = {}
    for r in agg.itertuples(index=False):
        key = state_key(r.inning_key, r.half, r.outs, r.base_state, int(r.score_diff))
        p_home = float(r.win_prob_home)
        p_bat = (1.0 - p_home) if r.half == "T" else p_home
        out[key] = {
            "win_prob_home": round(p_home, 5),
            "win_prob_bat": round(p_bat, 5),
            "n": int(r.n),
        }
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--years", nargs="+", type=int, required=True)
    p.add_argument("--out", default=str(OUT_FILE))
    args = p.parse_args()

    frames: list[pd.DataFrame] = []
    used_years: list[int] = []
    t0 = time.time()
    for y in args.years:
        df = load_season(y)
        if df is None or len(df) == 0:
            continue
        s = derive_states(df)
        log.info("  %d -> %d state rows", y, len(s))
        frames.append(s)
        used_years.append(y)

    if not frames:
        log.error("no data")
        return 1

    states = pd.concat(frames, ignore_index=True)
    log.info("total state rows: %d (across %s)", len(states), used_years)

    agg = aggregate(states)
    log.info("unique states: %d", len(agg))

    out = to_we_dict(agg)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_meta": {
            "seasons": used_years,
            "n_states": len(out),
            "n_observations": int(states.shape[0]),
            "score_clip": SCORE_CLIP,
            "schema": "key='inning|half|outs|bases|score_diff' (score_diff = bat - fld, clipped)",
        },
        "table": out,
    }
    with out_path.open("w") as f:
        json.dump(payload, f, separators=(",", ":"))
    log.info("wrote %s (%.2f MB) in %.1fs", out_path, out_path.stat().st_size / 1e6, time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
