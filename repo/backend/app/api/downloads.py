import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..db import get_conn
from ..models import ChooseRequest
from ..storage import copy_file, run_dir

router = APIRouter(prefix="/api/runs", tags=["downloads"])


@router.post("/{run_id}/choose")
def choose_candidate(run_id: str, body: ChooseRequest) -> dict:
    with get_conn() as conn:
        cand = conn.execute(
            "SELECT * FROM candidates WHERE run_id=? AND id=?", (run_id, body.cand_id)
        ).fetchone()
        if not cand:
            raise HTTPException(status_code=404, detail="Candidate not found")

    base = run_dir(run_id)
    chosen_dir = base / "results" / "chosen"
    chosen_dir.mkdir(parents=True, exist_ok=True)
    src_rot = Path(cand["rotated_stl_path"])
    src_gc = Path(cand["gcode_path"])
    if not src_rot.exists() or not src_gc.exists():
        raise HTTPException(status_code=400, detail="Candidate artifacts missing")
    dst_rot = chosen_dir / "chosen_rotated.stl"
    dst_gc = chosen_dir / "chosen.gcode"
    copy_file(src_rot, dst_rot)
    copy_file(src_gc, dst_gc)

    report_path = chosen_dir / "report.md"
    with get_conn() as conn:
        run_row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    report_path.write_text(
        "\n".join(
            [
                f"# Run {run_id}",
                "",
                f"Chosen candidate: {body.cand_id}",
                f"Best candidate from ranking: {run_row['best_candidate_id']}",
                "",
                "## Stage2 metrics",
                json.dumps(json.loads(cand["stage2_json"] or "{}"), indent=2),
            ]
        ),
        encoding="utf-8",
    )

    zip_path = base / "downloads" / "chosen_bundle.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(dst_rot, arcname="chosen_rotated.stl")
        zf.write(dst_gc, arcname="chosen.gcode")
        zf.write(report_path, arcname="report.md")
    return {"download_url": f"/api/runs/{run_id}/download"}


@router.get("/{run_id}/download")
def download_bundle(run_id: str):
    zip_path = run_dir(run_id) / "downloads" / "chosen_bundle.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Bundle not found")
    return FileResponse(zip_path, media_type="application/zip", filename="chosen_bundle.zip")
