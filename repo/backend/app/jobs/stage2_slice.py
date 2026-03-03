import json
from pathlib import Path

import numpy as np
from trimesh.transformations import quaternion_matrix

from ..db import get_conn
from ..gcode.metrics_stage2 import compute_stage2_metrics
from ..gcode.parse_gcode import parse_gcode_moves
from ..gcode.preview_cache import build_preview_cache
from ..geometry.mesh_load import load_mesh
from ..slicer.prusa_cli import slice_stl_to_gcode
from ..storage import run_dir, write_json


def export_rotated_stl(input_path: str, quat: list[float], output_path: Path) -> None:
    mesh = load_mesh(input_path)
    mat = quaternion_matrix(np.array(quat))
    mesh.apply_transform(mat)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(output_path)


def slice_candidate(run_id: str, candidate_id: str, config: dict) -> None:
    with get_conn() as conn:
        run_row = conn.execute("SELECT input_path FROM runs WHERE id=?", (run_id,)).fetchone()
        cand = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        conn.execute("UPDATE candidates SET status='slicing' WHERE id=?", (candidate_id,))

    stage2_dir = run_dir(run_id) / "stage2" / f"cand_{cand['idx']}"
    rotated_path = stage2_dir / "rotated.stl"
    gcode_path = stage2_dir / "slice.gcode"
    metrics_path = stage2_dir / "stage2_metrics.json"
    preview_path = stage2_dir / "preview_cache.json"

    quat = [cand["rot_w"], cand["rot_x"], cand["rot_y"], cand["rot_z"]]
    export_rotated_stl(run_row["input_path"], quat, rotated_path)
    result = slice_stl_to_gcode(rotated_path, gcode_path, config["bed_size_mm"])

    with get_conn() as conn:
        if result.returncode != 0:
            conn.execute(
                "UPDATE candidates SET status='error', error=? WHERE id=?",
                (result.stderr[-1000:], candidate_id),
            )
            return

    moves, total_time = parse_gcode_moves(gcode_path)
    stage2_metrics = compute_stage2_metrics(moves, total_time)
    preview = build_preview_cache(moves)
    write_json(metrics_path, stage2_metrics)
    write_json(preview_path, preview)

    with get_conn() as conn:
        conn.execute(
            "UPDATE candidates SET status='done', rotated_stl_path=?, gcode_path=?, preview_json_path=?, stage2_json=? WHERE id=?",
            (str(rotated_path), str(gcode_path), str(preview_path), json.dumps(stage2_metrics), candidate_id),
        )
        conn.execute(
            "UPDATE runs SET sliced_candidates=(SELECT COUNT(*) FROM candidates WHERE run_id=? AND status='done') WHERE id=?",
            (run_id, run_id),
        )
