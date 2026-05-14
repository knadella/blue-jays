"""Win Probability Added (WPA) for MLB StatsAPI play-by-play.

Loads an empirical Win Expectancy (WE) table at import time and exposes
``compute_wpa_for_game`` which walks the StatsAPI ``allPlays`` list and
returns per-play WPA values for the batting and pitching sides.

The WE table is built by ``scripts/build_we_table.py`` from cached Statcast
seasons; see ``data/win_expectancy/we_table.json``.

State key (matches the WE table schema)::

    f"{inning_key}|{half}|{outs}|{bases}|{score_diff}"

- ``inning_key``: "1".."9" or "X" for extras
- ``half``: "T" (top) or "B" (bottom)
- ``outs``: 0..2
- ``bases``: 3-char "1B|2B|3B" string, e.g. "101"
- ``score_diff``: BATTING team score minus FIELDING team score, clipped to [-10, 10]

WPA is signed for the batting team; pitcher WPA is its negation.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WE_TABLE_PATH = _REPO_ROOT / "data" / "win_expectancy" / "we_table.json"

SCORE_CLIP = 10
_INNING_KEYS = {i: str(i) for i in range(1, 10)}


# ----- WE table loader ---------------------------------------------------


@lru_cache(maxsize=1)
def _load_we_table(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else _WE_TABLE_PATH
    if not p.is_file():
        logger.warning("WE table not found at %s; WPA will be zeros", p)
        return {"_meta": {}, "table": {}}
    with p.open() as f:
        data = json.load(f)
    tbl = data.get("table", {})
    logger.info("loaded WE table: %d states", len(tbl))
    return data


def we_table_meta() -> dict[str, Any]:
    return _load_we_table().get("_meta", {})


def reload_we_table() -> None:
    """Clear cached WE table + lookup cache so a fresh load picks up changes."""
    _load_we_table.cache_clear()
    _smoothed_lookup.cache_clear()
    _table_index.cache_clear()


# ----- state helpers -----------------------------------------------------


def _inning_key(inning: int) -> str:
    return _INNING_KEYS.get(inning, "X")


def _bases_str(on1: bool, on2: bool, on3: bool) -> str:
    return ("1" if on1 else "0") + ("1" if on2 else "0") + ("1" if on3 else "0")


def _state_key(
    inning: int,
    half: str,  # "top" or "bot"/"bottom" or "T"/"B"
    outs: int,
    bases: str,
    score_diff: int,
) -> str:
    h = half[0].upper()
    if h not in ("T", "B"):
        h = "B"  # safe default
    sd = max(-SCORE_CLIP, min(SCORE_CLIP, int(score_diff)))
    return f"{_inning_key(inning)}|{h}|{int(outs)}|{bases}|{sd}"


_MIN_N = 15  # below this, smooth with neighbouring cells
_TRUST_N = 60  # at or above this, use the exact cell verbatim (no shrinkage)


def _index_table(table: dict[str, dict[str, Any]]) -> dict[tuple, list[tuple[str, dict]]]:
    """Pre-index by (inn, h, outs) for fast slab lookup."""
    idx: dict[tuple, list[tuple[str, dict]]] = {}
    for k, v in table.items():
        try:
            inn, h, outs, bases, sd = k.split("|")
        except ValueError:
            continue
        idx.setdefault((inn, h, int(outs)), []).append((bases, int(sd), v))
    return idx


@lru_cache(maxsize=1)
def _table_index() -> dict:
    table = _load_we_table()["table"]
    return _index_table(table)


@lru_cache(maxsize=32768)
def _smoothed_lookup(
    inn: str, h: str, outs: int, bases: str, sd: int
) -> tuple[float, int]:
    """Lookup with empirical-Bayes shrinkage that preserves score_diff monotonicity.

    Algorithm:
    1. Exact cell ``(inn, h, outs, bases, sd)``: if n >= 4*MIN_N, use directly.
    2. Compute a bases-aggregated value at the SAME outs but at the score_diff
       neighbourhood ``[sd-2, sd+2]``. This gives a smooth prior that's
       monotonic in sd because it pools across bases (which all share the same
       run-environment baseline).
    3. Use the prior at the requested sd (interpolated from neighbours weighted
       by 1/(1+|d|)) and shrink the exact cell toward that with K=MIN_N.
    4. If even the prior is empty, fall back to inning+half across all outs and
       bases at the score_diff window. Last resort: ~0.5 + 0.05*sd.
    """
    table = _load_we_table()["table"]
    idx = _table_index()
    primary_key = f"{inn}|{h}|{outs}|{bases}|{sd}"
    cell = table.get(primary_key)
    exact_wp = float(cell["win_prob_bat"]) if cell else None
    exact_n = int(cell["n"]) if cell else 0
    if exact_n >= _TRUST_N and exact_wp is not None:
        return exact_wp, exact_n

    slab = idx.get((inn, h, outs), [])

    # Pool by score_diff (across all bases) at the same outs, weighted by |sd-d|
    # closeness. This produces a smooth, monotonic-in-sd prior.
    by_sd: dict[int, tuple[float, int]] = {}
    for _bases, sd_cell, v in slab:
        cur_wp_n, cur_n = by_sd.get(sd_cell, (0.0, 0))
        n = int(v["n"])
        by_sd[sd_cell] = (cur_wp_n + float(v["win_prob_bat"]) * n, cur_n + n)

    def prior_for_sd(target_sd: int, window: int = 2) -> tuple[float | None, int]:
        wp_num = 0.0
        nn = 0
        for d in range(-window, window + 1):
            sd2 = max(-SCORE_CLIP, min(SCORE_CLIP, target_sd + d))
            if sd2 in by_sd:
                w = 1.0 / (1.0 + abs(d))
                wpn, n = by_sd[sd2]
                wp_num += wpn * w
                nn += int(n * w)
        if nn <= 0:
            return None, 0
        return wp_num / nn, nn

    prior, prior_n = prior_for_sd(sd, window=2)
    if prior is None:
        # broaden across all outs at same inn+h
        broad_idx_keys = [(inn, h, o) for o in range(0, 3)]
        all_by_sd: dict[int, tuple[float, int]] = {}
        for k2 in broad_idx_keys:
            for _b, sd_cell, v in idx.get(k2, []):
                cur_wp_n, cur_n = all_by_sd.get(sd_cell, (0.0, 0))
                n = int(v["n"])
                all_by_sd[sd_cell] = (cur_wp_n + float(v["win_prob_bat"]) * n, cur_n + n)
        wp_num = 0.0
        nn = 0
        for d in range(-2, 3):
            sd2 = max(-SCORE_CLIP, min(SCORE_CLIP, sd + d))
            if sd2 in all_by_sd:
                w = 1.0 / (1.0 + abs(d))
                wpn, n = all_by_sd[sd2]
                wp_num += wpn * w
                nn += int(n * w)
        if nn > 0:
            prior = wp_num / nn
            prior_n = nn

    if prior is None:
        # Last resort: lean on score_diff sign.
        if sd > 0:
            return min(0.5 + 0.05 * sd, 0.99), 0
        if sd < 0:
            return max(0.5 + 0.05 * sd, 0.01), 0
        return 0.5, 0

    K = float(_MIN_N)
    if exact_wp is not None:
        smoothed = (exact_wp * exact_n + prior * K) / (exact_n + K)
        return smoothed, exact_n
    return prior, prior_n


def _lookup_we_bat(
    table: dict[str, Any],
    inning: int,
    half: str,
    outs: int,
    bases: str,
    score_diff: int,
) -> tuple[float, int]:
    """Return (WE for the batting team, n_observations) with smoothing."""
    sd = max(-SCORE_CLIP, min(SCORE_CLIP, int(score_diff)))
    h = half[0].upper() if half else "B"
    inn = _inning_key(inning)
    return _smoothed_lookup(inn, h, int(outs), bases, sd)


def we_for_state(
    inning: int,
    half: str,
    outs: int,
    bases: str,
    score_diff_bat_minus_fld: int,
) -> float:
    """Public helper: WE from the BATTING team's perspective."""
    table = _load_we_table()["table"]
    we, _ = _lookup_we_bat(
        table, inning, half, outs, bases, score_diff_bat_minus_fld
    )
    return we




# ----- core computation --------------------------------------------------


def _bases_from_post(matchup: dict[str, Any]) -> str:
    """Read post-play base occupancy from a play's matchup."""
    return _bases_str(
        bool(matchup.get("postOnFirst")),
        bool(matchup.get("postOnSecond")),
        bool(matchup.get("postOnThird")),
    )


def _final_winner(plays: list[dict[str, Any]]) -> str | None:
    """Return 'home', 'away', or None if no decision detected."""
    if not plays:
        return None
    last = plays[-1].get("result", {}) or {}
    h = last.get("homeScore")
    a = last.get("awayScore")
    if h is None or a is None:
        return None
    if h > a:
        return "home"
    if a > h:
        return "away"
    return None


def compute_wpa_for_game(
    plays: Iterable[dict[str, Any]],
    home_team_id: int,  # noqa: ARG001 -- kept for API stability; not strictly needed
) -> list[dict[str, Any]]:
    """Compute WPA per play.

    Args:
        plays: ``liveData.plays.allPlays`` from MLB StatsAPI ``game`` endpoint.
        home_team_id: home team ID (unused at present; kept for forward-compat).

    Returns:
        list of dicts, one per play, with:
            ``play_index``, ``wpa_batter``, ``wpa_pitcher``, ``we_before``, ``we_after``,
            ``outs_before``, ``bases_before`` (3-char "010" mask), ``diff_before_bat``
            (batting-team minus fielding-team, going in).

        ``we_before`` / ``we_after`` are from the BATTING side's perspective for
        that play (so ``wpa_batter == we_after - we_before``). Pitcher WPA is the
        negation.
    """
    plays = list(plays)
    table = _load_we_table()["table"]
    out: list[dict[str, Any]] = []

    final_winner = _final_winner(plays)

    # Track running state going INTO each play. Reset at half-inning boundaries.
    prev_half = None
    prev_inning = None
    bases_before = "000"
    outs_before = 0

    for idx, play in enumerate(plays):
        about = play.get("about") or {}
        result = play.get("result") or {}
        matchup = play.get("matchup") or {}
        count = play.get("count") or {}

        inning = int(about.get("inning") or 1)
        half_raw = about.get("halfInning") or ("top" if about.get("isTopInning") else "bottom")
        half_letter = "T" if half_raw.lower().startswith("t") else "B"

        # Half-inning boundary -> bases reset, outs reset
        if (prev_half is None) or (prev_half != half_letter) or (prev_inning != inning):
            bases_before = "000"
            outs_before = 0

        # Score going INTO this play = score after previous play (carried in result of prev),
        # but easier: the result of THIS play already encodes post-play score, and we read
        # pre-play score by tracking running totals from prior play.
        # Use prior play to find score_before.
        if idx == 0:
            home_before = 0
            away_before = 0
        else:
            prev_result = (plays[idx - 1].get("result") or {})
            home_before = int(prev_result.get("homeScore") or 0)
            away_before = int(prev_result.get("awayScore") or 0)
        # If we just crossed a half-inning, score_before is still the running score.
        # (Score doesn't reset between innings.)

        # batting team score - fielding team score
        if half_letter == "T":
            bat_before = away_before
            fld_before = home_before
        else:
            bat_before = home_before
            fld_before = away_before
        diff_before = bat_before - fld_before

        we_before, _n_before = _lookup_we_bat(
            table, inning, half_letter, outs_before, bases_before, diff_before
        )

        # AFTER this play
        outs_after = int(count.get("outs") or 0)
        home_after = int(result.get("homeScore") or home_before)
        away_after = int(result.get("awayScore") or away_before)
        # post-play bases (StatsAPI populates these on the play itself)
        bases_after_same_half = _bases_from_post(matchup)

        is_last_play = idx == len(plays) - 1
        ends_half_inning = outs_after >= 3

        if is_last_play and final_winner is not None:
            # Game-ending play: anchor WE to the actual outcome from BATTING side.
            # Determine batting side for THIS play.
            bat_side_is_home = half_letter == "B"
            we_after_bat = (
                1.0
                if (bat_side_is_home and final_winner == "home")
                or (not bat_side_is_home and final_winner == "away")
                else 0.0
            )
        elif ends_half_inning:
            # Look up the start state of the NEXT half-inning (bases empty, outs=0,
            # half flipped, inning advances if we just finished bottom).
            next_half = "B" if half_letter == "T" else "T"
            next_inning = inning + 1 if half_letter == "B" else inning
            # Score-diff perspective flips because batting team flips.
            next_bat = home_after if next_half == "B" else away_after
            next_fld = away_after if next_half == "B" else home_after
            next_diff = next_bat - next_fld
            we_next_bat, _ = _lookup_we_bat(
                table, next_inning, next_half, 0, "000", next_diff
            )
            # That WE is from the NEXT batting team's perspective. Convert back to
            # THIS play's batting team's perspective by flipping (1 - x).
            we_after_bat = 1.0 - we_next_bat
        else:
            # Same half-inning continues.
            bat_after = away_after if half_letter == "T" else home_after
            fld_after = home_after if half_letter == "T" else away_after
            diff_after = bat_after - fld_after
            we_after_bat, _ = _lookup_we_bat(
                table, inning, half_letter, outs_after, bases_after_same_half, diff_after
            )

        wpa_bat = we_after_bat - we_before
        out.append(
            {
                "play_index": idx,
                "wpa_batter": round(wpa_bat, 5),
                "wpa_pitcher": round(-wpa_bat, 5),
                "we_before": round(we_before, 5),
                "we_after": round(we_after_bat, 5),
                "outs_before": int(outs_before),
                "bases_before": bases_before,
                # batting team's score - fielding team's score, going in
                "diff_before_bat": int(diff_before),
            }
        )

        # Roll state forward
        if ends_half_inning:
            bases_before = "000"
            outs_before = 0
        else:
            bases_before = bases_after_same_half
            outs_before = outs_after
        prev_half = half_letter
        prev_inning = inning

    return out


__all__ = [
    "compute_wpa_for_game",
    "we_for_state",
    "we_table_meta",
]
