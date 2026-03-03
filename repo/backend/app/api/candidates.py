import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..db import get_conn

router = APIRouter(prefix="/api/runs", tags=["candidates"])


@router.get("/{run_id}/candidates")
def list_candidates(run_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, idx, rank, score, stage2_json FROM candidates WHERE run_id=? ORDER BY rank ASC, idx ASC",
            (run_id,),
        ).fetchall()
    out = []
    for row in rows:
        stage2 = json.loads(row["stage2_json"]) if row["stage2_json"] else {}
        out.append(
            {
                "id": row["id"],
                "idx": row["idx"],
                "rank": row["rank"],
                "score": row["score"],
                "stage2": stage2,
            }
        )
    return out


@router.get("/{run_id}/candidates/{cand_id}/preview")
def get_candidate_preview(run_id: str, cand_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT preview_json_path FROM candidates WHERE run_id=? AND id=?",
            (run_id, cand_id),
        ).fetchone()
    if not row or not row["preview_json_path"]:
        raise HTTPException(status_code=404, detail="Preview not found")
    p = Path(row["preview_json_path"])
    if not p.exists():
        raise HTTPException(status_code=404, detail="Preview file missing")
    return json.loads(p.read_text(encoding="utf-8"))
