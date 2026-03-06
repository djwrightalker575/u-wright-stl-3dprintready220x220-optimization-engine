import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..db import get_conn

router = APIRouter(prefix="/api/runs", tags=["events"])


@router.get("/{run_id}/events")
async def stream_events(run_id: str):
    async def gen():
        last_id = 0
        while True:
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT id, ts, level, message FROM events WHERE run_id=? AND id>? ORDER BY id ASC",
                    (run_id, last_id),
                ).fetchall()
            for row in rows:
                last_id = row["id"]
                payload = {
                    "id": row["id"],
                    "ts": row["ts"],
                    "level": row["level"],
                    "message": row["message"],
                }
                yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")
