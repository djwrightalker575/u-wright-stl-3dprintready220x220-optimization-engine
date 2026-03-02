from __future__ import annotations

import json
import time
from pathlib import Path

from orienter.ui.config import AppPaths
from orienter.ui.schemas import RunCreate
from orienter.ui.service import RunManager, parse_slicer_stats


def _mk_paths(tmp_path: Path) -> AppPaths:
    base = tmp_path / ".orienter"
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


def test_parse_slicer_stats_strict_normal_mode() -> None:
    gcode = """; filament used [mm] = 1000.0, 25.0
; filament used [g] = 3.2, 0.4
; estimated printing time (silent mode) = 00:10:00
; estimated printing time (normal mode) = 00:08:30
"""
    stats = parse_slicer_stats(gcode)
    assert stats["filament_mm"] == 1025.0
    assert stats["filament_g"] == 3.6
    assert stats["time_s"] == 510.0


def test_run_manager_completes_and_writes_artifacts_and_previews(tmp_path: Path) -> None:
    in_dir = tmp_path / "input"
    out_dir = tmp_path / "output"
    in_dir.mkdir()
    out_dir.mkdir()
    (in_dir / "part_a.stl").write_text("solid a\nendsolid a\n")

    manager = RunManager(_mk_paths(tmp_path))
    run_id = manager.create_run(
        RunCreate(input_path=str(in_dir), output_path=str(out_dir), profile="Creality_220_Generic", top_k=3)
    )

    deadline = time.time() + 20
    status = "PENDING"
    while time.time() < deadline:
        detail = manager.run_detail(run_id)
        assert detail is not None
        status = detail["status"]
        if status in {"COMPLETED", "FAILED", "STOPPED"}:
            break
        time.sleep(0.2)

    assert status == "COMPLETED"
    detail = manager.run_detail(run_id)
    assert detail is not None
    assert detail["models"]
    model = detail["models"][0]
    assert model["best_score"] is not None

    metrics = model["metrics_json"]
    assert metrics["support_filament_delta"] >= -0.5
    assert metrics["support_time_delta"] >= -30
    assert metrics["invalid_candidates_count"] == 0
    assert metrics["candidates"]

    first_candidate = metrics["candidates"][0]
    assert "SUP0" in Path(first_candidate["gcode"]["SUP0"]).name
    assert "SUP1" in Path(first_candidate["gcode"]["SUP1"]).name
    assert first_candidate["candidate_id"] in Path(first_candidate["gcode"]["SUP0"]).name

    preview_iso = Path(first_candidate["previews"]["iso"])
    preview_top = Path(first_candidate["previews"]["top"])
    preview_supports = Path(first_candidate["previews"]["supports_overlay"])
    assert preview_iso.exists()
    assert preview_top.exists()
    assert preview_supports.exists()

    output_path = Path(detail["output_path"])
    assert (output_path / "reports" / "results.csv").exists()
    assert any((output_path / "gcode").glob("*__SUP0.gcode"))
    assert any((output_path / "gcode").glob("*__SUP1.gcode"))


def test_recover_running_jobs_marks_interrupted(tmp_path: Path) -> None:
    paths = _mk_paths(tmp_path)
    manager = RunManager(paths)

    manager.conn.execute(
        """
        INSERT INTO runs(id, created_at, started_at, finished_at, status, input_path, output_path, profile, params_json, last_heartbeat, engine_mode)
        VALUES (?, ?, ?, NULL, 'RUNNING', ?, ?, ?, ?, ?, ?)
        """,
        (
            "run-1",
            "2020-01-01T00:00:00+00:00",
            "2020-01-01T00:00:01+00:00",
            "/tmp/in",
            "/tmp/out",
            "Creality_220_Generic",
            json.dumps({}),
            "2020-01-01T00:00:02+00:00",
            "MOCK",
        ),
    )
    manager.conn.commit()

    manager2 = RunManager(paths)
    row = manager2.conn.execute("SELECT status, finished_at FROM runs WHERE id='run-1'").fetchone()
    assert row is not None
    assert row["status"] == "INTERRUPTED"
    assert row["finished_at"] is not None
