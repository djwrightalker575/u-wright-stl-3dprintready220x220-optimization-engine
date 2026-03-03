import json
import uuid

import numpy as np

from ..db import get_conn
from ..geometry.candidates import apply_quaternion, generate_candidate_quaternions, quat_distance
from ..geometry.mesh_load import load_mesh
from ..geometry.metrics_stage1 import compute_stage1_metrics
from ..storage import run_dir, write_json


def run_stage1(run_id: str, config: dict) -> list[dict]:
    with get_conn() as conn:
        run_row = conn.execute("SELECT input_path FROM runs WHERE id=?", (run_id,)).fetchone()
    mesh = load_mesh(run_row["input_path"])
    quats = generate_candidate_quaternions(int(config["max_candidates_stage1"]))

    candidates: list[dict] = []
    for idx, q in enumerate(quats):
        rotated = apply_quaternion(mesh, q)
        metrics = compute_stage1_metrics(rotated, float(config["overhang_threshold_deg"]))
        candidates.append(
            {
                "idx": idx,
                "quat": [float(q[0]), float(q[1]), float(q[2]), float(q[3])],
                "stage1": metrics,
            }
        )

    candidates.sort(key=lambda c: c["stage1"]["stage1_score"])
    shortlist_pool = candidates[: int(config["shortlist_k"]) * 2]

    deduped: list[dict] = []
    for cand in shortlist_pool:
        q = np.array(cand["quat"])
        if any(quat_distance(q, np.array(existing["quat"])) < 0.01 for existing in deduped):
            continue
        deduped.append(cand)
        if len(deduped) >= int(config["shortlist_k"]):
            break

    write_json(run_dir(run_id) / "stage1" / "shortlist.json", deduped)

    with get_conn() as conn:
        conn.execute("DELETE FROM candidates WHERE run_id=?", (run_id,))
        for pos, cand in enumerate(deduped):
            cid = str(uuid.uuid4())
            q = cand["quat"]
            conn.execute(
                """
                INSERT INTO candidates(id, run_id, idx, rot_w, rot_x, rot_y, rot_z,
                                       stage1_json, stage2_json, score, rank, status,
                                       rotated_stl_path, gcode_path, preview_json_path, error)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    cid,
                    run_id,
                    pos,
                    q[0],
                    q[1],
                    q[2],
                    q[3],
                    json.dumps(cand["stage1"]),
                    None,
                    None,
                    None,
                    "pending",
                    "",
                    "",
                    "",
                    None,
                ),
            )
        conn.execute(
            "UPDATE runs SET total_candidates=?, stage='slicing' WHERE id=?",
            (len(deduped), run_id),
        )
    return deduped
