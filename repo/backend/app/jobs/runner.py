import asyncio
import json
from datetime import datetime, timezone

from ..db import get_conn
from .scoring import rank_run
from .stage1_geometry import run_stage1
from .stage2_slice import slice_candidate

_run_queue: asyncio.Queue[str] = asyncio.Queue()
_worker_task: asyncio.Task | None = None


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_event(run_id: str, level: str, message: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO events(run_id, ts, level, message) VALUES(?,?,?,?)",
            (run_id, _ts(), level, message),
        )


async def enqueue_run(run_id: str) -> None:
    await _run_queue.put(run_id)


async def ensure_worker() -> None:
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(worker_loop())


async def resume_incomplete_runs() -> None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM runs WHERE status IN ('queued','running')"
        ).fetchall()
    for row in rows:
        await enqueue_run(row["id"])


async def worker_loop() -> None:
    while True:
        run_id = await _run_queue.get()
        try:
            process_run(run_id)
        except Exception as exc:  # pragma: no cover
            with get_conn() as conn:
                conn.execute("UPDATE runs SET status='error', error=? WHERE id=?", (str(exc), run_id))
            add_event(run_id, "error", f"Run failed: {exc}")
        finally:
            _run_queue.task_done()


def process_run(run_id: str) -> None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return
        conn.execute("UPDATE runs SET status='running' WHERE id=?", (run_id,))
    config = json.loads(row["config_json"])

    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) c FROM candidates WHERE run_id=?", (run_id,)).fetchone()["c"]
    if count == 0:
        with get_conn() as conn:
            conn.execute("UPDATE runs SET stage='geometry' WHERE id=?", (run_id,))
        shortlist = run_stage1(run_id, config)
        add_event(run_id, "info", f"Stage1 completed with {len(shortlist)} candidates")

    with get_conn() as conn:
        pending = conn.execute(
            "SELECT id FROM candidates WHERE run_id=? AND status IN ('pending','slicing') ORDER BY idx",
            (run_id,),
        ).fetchall()
        conn.execute("UPDATE runs SET stage='slicing' WHERE id=?", (run_id,))
    for c in pending:
        slice_candidate(run_id, c["id"], config)
        add_event(run_id, "info", f"Sliced candidate {c['id']}")

    with get_conn() as conn:
        has_ranked = conn.execute(
            "SELECT COUNT(*) c FROM candidates WHERE run_id=? AND rank IS NOT NULL", (run_id,)
        ).fetchone()["c"]
    if has_ranked == 0:
        ranked = rank_run(run_id, config["weights"])
        add_event(run_id, "info", f"Ranking complete, {len(ranked)} candidates scored")
