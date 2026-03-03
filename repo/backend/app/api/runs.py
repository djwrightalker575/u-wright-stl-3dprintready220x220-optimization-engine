import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..db import get_conn
from ..jobs.runner import enqueue_run
from ..models import RunStatusResponse
from ..storage import ensure_run_dirs

router = APIRouter(prefix="/api/runs", tags=["runs"])

DEFAULT_CONFIG = {
    "bed_size_mm": [220, 220],
    "overhang_threshold_deg": 45,
    "max_candidates_stage1": 250,
    "shortlist_k": 20,
    "weights": {"support": 0.45, "time": 0.25, "quality": 0.20, "stability": 0.10},
}


@router.post("")
async def create_run(file: UploadFile = File(...)) -> dict:
    run_id = str(uuid.uuid4())
    dirs = ensure_run_dirs(run_id)
    input_path = dirs["input"] / "original.stl"
    config_path = dirs["config"] / "config.json"

    content = await file.read()
    input_path.write_bytes(content)
    config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO runs(id, created_at, status, stage, input_path, config_json, shortlist_k,
                             total_candidates, sliced_candidates, best_candidate_id, error)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                now,
                "queued",
                "geometry",
                str(Path(input_path)),
                json.dumps(DEFAULT_CONFIG),
                DEFAULT_CONFIG["shortlist_k"],
                0,
                0,
                None,
                None,
            ),
        )
    await enqueue_run(run_id)
    return {"run_id": run_id}


@router.get("/{run_id}", response_model=RunStatusResponse)
def get_run(run_id: str) -> RunStatusResponse:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunStatusResponse(**dict(row))
