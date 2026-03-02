from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    base_dir: Path
    db_path: Path
    state_dir: Path
    config_path: Path
    presets_path: Path


def resolve_paths() -> AppPaths:
    base = Path.home() / ".orienter"
    state = base / "state"
    base.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    return AppPaths(
        base_dir=base,
        db_path=base / "orienter_ui.db",
        state_dir=state,
        config_path=base / "config.json",
        presets_path=base / "weight_presets.json",
    )


DEFAULT_CONFIG = {
    "brand": "U-Wright Open Innovations",
    "title": "Creality 220 Orientation Optimizer",
    "profile": "Creality_220_Generic",
    "bed": {"x": 220, "y": 220, "locked": True},
    "weights": {
        "support": 0.4,
        "time": 0.35,
        "height": 0.25,
    },
    "worker_count": 2,
    "cache_enabled": True,
}

DEFAULT_PRESETS = {
    "Hybrid": {"support": 0.4, "time": 0.35, "height": 0.25},
    "Speed": {"support": 0.2, "time": 0.6, "height": 0.2},
    "SupportSaver": {"support": 0.65, "time": 0.2, "height": 0.15},
}
