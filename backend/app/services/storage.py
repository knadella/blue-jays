"""Persistence helpers for posterior sample snapshots."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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

    @property
    def draw_count(self) -> int:
        return len(self.mu)

    def mu_array(self) -> np.ndarray:
        return np.asarray(self.mu, dtype=float)

    def hfa_array(self) -> np.ndarray:
        return np.asarray(self.hfa, dtype=float)

    def offense_array(self) -> np.ndarray:
        return np.asarray(self.offense, dtype=float)

    def defense_array(self) -> np.ndarray:
        return np.asarray(self.defense, dtype=float)


def snapshot_directory(season: int) -> Path:
    path = POSTERIOR_CACHE_DIR / str(season)
    path.mkdir(parents=True, exist_ok=True)
    return path


def latest_snapshot_path(season: int) -> Optional[Path]:
    candidates = sorted(snapshot_directory(season).glob("*.json"))
    return candidates[-1] if candidates else None


def load_latest_snapshot(season: int) -> Optional[PosteriorSnapshot]:
    path = latest_snapshot_path(season)
    if path is None:
        return None
    payload = json.loads(path.read_text())
    return PosteriorSnapshot(**payload)


def save_snapshot(snapshot: PosteriorSnapshot) -> Path:
    filename = f"{snapshot.generated_at.replace(':', '-').replace('T', '_')}.json"
    target = snapshot_directory(snapshot.season) / filename
    target.write_text(json.dumps(asdict(snapshot)))
    return target
