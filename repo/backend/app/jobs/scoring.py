import csv
import json
from pathlib import Path

from ..db import get_conn
from ..storage import run_dir, write_json


def _norm(values: list[float | None], invert_missing: bool = False) -> list[float]:
    clean = [v for v in values if v is not None]
    if not clean:
        return [0.5 for _ in values]
    lo, hi = min(clean), max(clean)
    if hi - lo < 1e-9:
        return [0.0 for _ in values]
    out = []
    for v in values:
        if v is None:
            out.append(1.0 if invert_missing else 0.5)
        else:
            out.append((v - lo) / (hi - lo))
    return out


def rank_run(run_id: str, weights: dict) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM candidates WHERE run_id=? AND status='done' ORDER BY idx", (run_id,)
        ).fetchall()

    cands = []
    for row in rows:
        stage1 = json.loads(row["stage1_json"]) if row["stage1_json"] else {}
        stage2 = json.loads(row["stage2_json"]) if row["stage2_json"] else {}
        cands.append({"row": row, "stage1": stage1, "stage2": stage2})

    support = _norm([c["stage2"].get("support_extrusion_mm") for c in cands])
    time_vals = [c["stage2"].get("total_time_sec") for c in cands]
    if all(v is None for v in time_vals):
        time_vals = [c["stage2"].get("z_height_mm_exact") for c in cands]
    time_cost = _norm(time_vals)
    quality_vals = [
        (c["stage1"].get("quality_proxy", 0.0) + 0.0001 * c["stage2"].get("support_extrusion_mm", 0.0))
        for c in cands
    ]
    quality_cost = _norm(quality_vals)
    stability_vals = [1.0 / max(c["stage1"].get("stability_proxy", 1e-6), 1e-6) for c in cands]
    stability_cost = _norm(stability_vals)

    ranked = []
    for i, c in enumerate(cands):
        score = 1.0 - (
            weights["support"] * support[i]
            + weights["time"] * time_cost[i]
            + weights["quality"] * quality_cost[i]
            + weights["stability"] * stability_cost[i]
        )
        ranked.append(
            {
                "id": c["row"]["id"],
                "idx": c["row"]["idx"],
                "score": score,
                "stage1": c["stage1"],
                "stage2": c["stage2"],
                "rotated_stl_path": c["row"]["rotated_stl_path"],
                "gcode_path": c["row"]["gcode_path"],
                "preview_json_path": c["row"]["preview_json_path"],
            }
        )
    ranked.sort(key=lambda x: x["score"], reverse=True)

    for i, item in enumerate(ranked, start=1):
        item["rank"] = i

    results_dir = run_dir(run_id) / "results"
    write_json(results_dir / "ranked.json", ranked)
    with (results_dir / "ranked.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "id", "idx", "score"])
        writer.writeheader()
        for item in ranked:
            writer.writerow({k: item[k] for k in ["rank", "id", "idx", "score"]})

    with get_conn() as conn:
        for item in ranked:
            conn.execute(
                "UPDATE candidates SET score=?, rank=? WHERE id=?",
                (item["score"], item["rank"], item["id"]),
            )
        best = ranked[0]["id"] if ranked else None
        conn.execute(
            "UPDATE runs SET stage='ranking', status='done', best_candidate_id=? WHERE id=?",
            (best, run_id),
        )
    return ranked
