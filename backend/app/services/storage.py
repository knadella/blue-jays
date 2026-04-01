"""Persistence helpers for posterior sample snapshots."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np

from config import POSTERIOR_CACHE_DIR


@dataclass
class PosteriorSnapshot:
    season: int
    generated_at: str
    source: str
    teams: list[str]
    mu: list[float]
    hfa: list[float]
    offense: list[list[float]]
    defense: list[list[float]]
    park: Optional[list[list[float]]] = None
    alpha: Optional[list[float]] = None
    beta_pitcher: Optional[list[float]] = None
    beta_rest: Optional[list[float]] = None
    beta_momentum: Optional[list[float]] = None
    beta_division: Optional[list[float]] = None
    diagnostics: Optional[dict] = None

    @property
    def draw_count(self) -> int:
        return len(self.mu)

    def mu_array(self) -> np.ndarray:
        cached = getattr(self, "_mu_array_cache", None)
        if cached is None:
            cached = np.asarray(self.mu, dtype=float)
            self._mu_array_cache = cached
        return cached

    def hfa_array(self) -> np.ndarray:
        cached = getattr(self, "_hfa_array_cache", None)
        if cached is None:
            cached = np.asarray(self.hfa, dtype=float)
            self._hfa_array_cache = cached
        return cached

    def offense_array(self) -> np.ndarray:
        cached = getattr(self, "_offense_array_cache", None)
        if cached is None:
            cached = np.asarray(self.offense, dtype=float)
            self._offense_array_cache = cached
        return cached

    def defense_array(self) -> np.ndarray:
        cached = getattr(self, "_defense_array_cache", None)
        if cached is None:
            cached = np.asarray(self.defense, dtype=float)
            self._defense_array_cache = cached
        return cached

    def park_array(self) -> np.ndarray:
        cached = getattr(self, "_park_array_cache", None)
        if cached is None:
            if self.park is not None:
                cached = np.asarray(self.park, dtype=float)
            else:
                cached = np.zeros((self.draw_count, len(self.teams)))
            self._park_array_cache = cached
        return cached

    def alpha_array(self) -> np.ndarray:
        cached = getattr(self, "_alpha_array_cache", None)
        if cached is None:
            if self.alpha is not None:
                cached = np.asarray(self.alpha, dtype=float)
            else:
                cached = np.full(self.draw_count, 1e6)
            self._alpha_array_cache = cached
        return cached

    def beta_pitcher_array(self) -> np.ndarray:
        cached = getattr(self, "_beta_pitcher_array_cache", None)
        if cached is None:
            if self.beta_pitcher is not None:
                cached = np.asarray(self.beta_pitcher, dtype=float)
            else:
                cached = np.zeros(self.draw_count)
            self._beta_pitcher_array_cache = cached
        return cached

    def beta_rest_array(self) -> np.ndarray:
        cached = getattr(self, "_beta_rest_array_cache", None)
        if cached is None:
            if self.beta_rest is not None:
                cached = np.asarray(self.beta_rest, dtype=float)
            else:
                cached = np.zeros(self.draw_count)
            self._beta_rest_array_cache = cached
        return cached

    def beta_momentum_array(self) -> np.ndarray:
        cached = getattr(self, "_beta_momentum_array_cache", None)
        if cached is None:
            if self.beta_momentum is not None:
                cached = np.asarray(self.beta_momentum, dtype=float)
            else:
                cached = np.zeros(self.draw_count)
            self._beta_momentum_array_cache = cached
        return cached

    def beta_division_array(self) -> np.ndarray:
        cached = getattr(self, "_beta_division_array_cache", None)
        if cached is None:
            if self.beta_division is not None:
                cached = np.asarray(self.beta_division, dtype=float)
            else:
                cached = np.zeros(self.draw_count)
            self._beta_division_array_cache = cached
        return cached


_SNAPSHOT_FIELD_NAMES = frozenset(f.name for f in fields(PosteriorSnapshot))


def snapshot_directory(season: int) -> Path:
    path = POSTERIOR_CACHE_DIR / str(season)
    path.mkdir(parents=True, exist_ok=True)
    return path


def latest_snapshot_path(season: int) -> Optional[Path]:
    candidates = sorted(snapshot_directory(season).glob("*.json"))
    return candidates[-1] if candidates else None


def monthly_projection_path(season: int, month: int, n_games: int) -> Path:
    """Disk cache for a league-wide fit using games strictly before month start."""
    path = snapshot_directory(season) / "monthly"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"m{month:02d}_n{n_games}.json"


@lru_cache(maxsize=8)
def _load_snapshot_from_path(path_str: str) -> PosteriorSnapshot:
    raw = json.loads(Path(path_str).read_text())
    payload = {k: v for k, v in raw.items() if k in _SNAPSHOT_FIELD_NAMES}
    return PosteriorSnapshot(**payload)


def load_latest_snapshot(season: int) -> Optional[PosteriorSnapshot]:
    path = latest_snapshot_path(season)
    if path is None:
        return None
    return _load_snapshot_from_path(str(path.resolve()))


def save_snapshot(snapshot: PosteriorSnapshot) -> Path:
    filename = f"{snapshot.generated_at.replace(':', '-').replace('T', '_')}.json"
    target = snapshot_directory(snapshot.season) / filename
    target.write_text(json.dumps(asdict(snapshot)))
    _load_snapshot_from_path.cache_clear()
    return target
