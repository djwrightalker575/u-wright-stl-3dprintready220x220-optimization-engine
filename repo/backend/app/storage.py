import json
import shutil
from pathlib import Path
from typing import Any

from .settings import RUNS_DIR


def run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def ensure_run_dirs(run_id: str) -> dict[str, Path]:
    base = run_dir(run_id)
    paths = {
        "base": base,
        "input": base / "input",
        "config": base / "config",
        "stage1": base / "stage1",
        "stage2": base / "stage2",
        "results": base / "results",
        "downloads": base / "downloads",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
