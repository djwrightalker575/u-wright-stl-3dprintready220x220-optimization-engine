from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orienter.ui.config import DEFAULT_CONFIG, DEFAULT_PRESETS, AppPaths
from orienter.ui.db import connect, init_db
from orienter.ui.schemas import RunCreate


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunManager:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.conn = connect(paths.db_path)
        init_db(self.conn)
        self._pause_flags: dict[str, threading.Event] = {}
        self._stop_flags: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._load_or_init_config()
        self._recover_running_jobs()

    def _load_or_init_config(self) -> None:
        if not self.paths.config_path.exists():
            self.paths.config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        if not self.paths.presets_path.exists():
            self.paths.presets_path.write_text(json.dumps(DEFAULT_PRESETS, indent=2))

    def _recover_running_jobs(self) -> None:
        self.conn.execute(
            "UPDATE runs SET status='INTERRUPTED', finished_at=? WHERE status='RUNNING'",
            (utc_now(),),
        )
        self.conn.commit()

    def load_config(self) -> dict[str, Any]:
        return json.loads(self.paths.config_path.read_text())

    def save_config(self, config: dict[str, Any]) -> None:
        self.paths.config_path.write_text(json.dumps(config, indent=2))

    def presets(self) -> dict[str, Any]:
        return json.loads(self.paths.presets_path.read_text())

    def _engine_mode(self) -> str:
        return "REAL" if self._cli_exists() else "MOCK"

    def _cli_exists(self) -> bool:
        for p in os.environ.get("PATH", "").split(os.pathsep):
            cmd = Path(p) / "orienter"
            if cmd.exists() and os.access(cmd, os.X_OK):
                return True
        return False

    def create_run(self, payload: RunCreate) -> str:
        run_id = str(uuid.uuid4())
        run_output = Path(payload.output_path) / "runs" / run_id
        for sub in ["rotated_stl", "gcode", "reports", "logs"]:
            (run_output / sub).mkdir(parents=True, exist_ok=True)

        params = payload.model_dump()
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO runs(id, created_at, started_at, finished_at, status, input_path, output_path, profile, params_json, last_heartbeat, engine_mode)
            VALUES (?, ?, NULL, NULL, 'PENDING', ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                now,
                payload.input_path,
                str(run_output),
                payload.profile,
                json.dumps(params),
                now,
                self._engine_mode(),
            ),
        )
        self.conn.commit()
        self._pause_flags[run_id] = threading.Event()
        self._stop_flags[run_id] = threading.Event()
        self.executor.submit(self._run_job, run_id)
        return run_id

    def _discover_models(self, input_path: str) -> list[Path]:
        p = Path(input_path)
        if p.is_file() and p.suffix.lower() == ".stl":
            return [p]
        if p.is_dir():
            return sorted(x for x in p.iterdir() if x.suffix.lower() == ".stl")
        return []

    def _log(self, run_id: str, level: str, msg: str) -> None:
        self.conn.execute(
            "INSERT INTO run_logs(run_id, ts, level, message) VALUES (?, ?, ?, ?)",
            (run_id, utc_now(), level, msg),
        )
        self.conn.commit()

    def _set_run_status(self, run_id: str, status: str, started: bool = False, finished: bool = False) -> None:
        started_at = utc_now() if started else None
        finished_at = utc_now() if finished else None
        with self._lock:
            if started:
                self.conn.execute("UPDATE runs SET status=?, started_at=?, last_heartbeat=? WHERE id=?", (status, started_at, utc_now(), run_id))
            elif finished:
                self.conn.execute("UPDATE runs SET status=?, finished_at=?, last_heartbeat=? WHERE id=?", (status, finished_at, utc_now(), run_id))
            else:
                self.conn.execute("UPDATE runs SET status=?, last_heartbeat=? WHERE id=?", (status, utc_now(), run_id))
            self.conn.commit()

    def _cache_key(self, model: Path, profile: str) -> str:
        h = hashlib.sha256()
        h.update(model.read_bytes())
        h.update(profile.encode())
        return h.hexdigest()

    def _get_cache(self, key: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT value_json FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _set_cache(self, key: str, value: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO cache(key, value_json, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), utc_now()),
        )
        self.conn.commit()

    def _mock_compute(self, model: Path, model_idx: int) -> dict[str, Any]:
        random.seed(f"{model.name}:{model_idx}")
        score = round(random.uniform(0.65, 0.99), 4)
        return {
            "best_score": score,
            "support_filament_delta": round(random.uniform(-20, 5), 2),
            "support_time_delta": round(random.uniform(-10, 3), 2),
            "total_time": round(random.uniform(40, 160), 2),
            "z_height": round(random.uniform(18, 90), 2),
            "orientation_rank": model_idx,
        }

    def _run_job(self, run_id: str) -> None:
        row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return
        params = json.loads(row["params_json"])
        models = self._discover_models(params["input_path"])
        if not models:
            self._log(run_id, "ERROR", "No STL models found")
            self._set_run_status(run_id, "FAILED", started=True, finished=True)
            return

        self._set_run_status(run_id, "RUNNING", started=True)
        self._log(run_id, "INFO", f"Detected {len(models)} models")

        try:
            for idx, model in enumerate(models, start=1):
                if self._stop_flags[run_id].is_set():
                    self._set_run_status(run_id, "STOPPED", finished=True)
                    self._log(run_id, "WARN", "Run stopped by operator")
                    return

                while self._pause_flags[run_id].is_set():
                    self._set_run_status(run_id, "PAUSED")
                    time.sleep(0.5)
                    if self._stop_flags[run_id].is_set():
                        self._set_run_status(run_id, "STOPPED", finished=True)
                        return
                self._set_run_status(run_id, "RUNNING")

                model_id = str(uuid.uuid4())
                self.conn.execute(
                    "INSERT INTO models(id, run_id, model_path, status, best_score, metrics_json, artifacts_json) VALUES (?, ?, ?, 'RUNNING', NULL, '{}', '{}')",
                    (model_id, run_id, str(model)),
                )
                self.conn.commit()
                self._log(run_id, "INFO", f"Processing model {model.name} ({idx}/{len(models)})")

                cache_key = self._cache_key(model, row["profile"])
                cached = self._get_cache(cache_key)
                if cached:
                    metrics = cached
                    self._log(run_id, "INFO", f"Cache hit for {model.name}")
                    time.sleep(0.2)
                else:
                    for _ in range(4):
                        if self._stop_flags[run_id].is_set():
                            self._set_run_status(run_id, "STOPPED", finished=True)
                            return
                        time.sleep(0.4)
                        self.conn.execute("UPDATE runs SET last_heartbeat=? WHERE id=?", (utc_now(), run_id))
                        self.conn.commit()
                    metrics = self._mock_compute(model, idx)
                    self._set_cache(cache_key, metrics)

                out = Path(row["output_path"])
                rotated = out / "rotated_stl" / f"{model.stem}_rotated.stl"
                report_json = out / "reports" / f"{model.stem}.json"
                report_csv = out / "reports" / "results.csv"
                gcode = out / "gcode" / f"{model.stem}.gcode"
                rotated.write_text(f"solid {model.stem}\nendsolid {model.stem}\n")
                gcode.write_text("; mock gcode\nG28\n")
                report_json.write_text(json.dumps(metrics, indent=2))
                if not report_csv.exists():
                    report_csv.write_text("model,best_score,support_filament_delta,support_time_delta,total_time,z_height,orientation_rank\n")
                with report_csv.open("a") as f:
                    f.write(
                        f"{model.name},{metrics['best_score']},{metrics['support_filament_delta']},{metrics['support_time_delta']},{metrics['total_time']},{metrics['z_height']},{metrics['orientation_rank']}\n"
                    )

                artifacts = {
                    "rotated_stl": str(rotated),
                    "gcode": str(gcode),
                    "report_json": str(report_json),
                    "report_csv": str(report_csv),
                }
                self.conn.execute(
                    "UPDATE models SET status='COMPLETED', best_score=?, metrics_json=?, artifacts_json=? WHERE id=?",
                    (metrics["best_score"], json.dumps(metrics), json.dumps(artifacts), model_id),
                )
                self.conn.commit()

            self._set_run_status(run_id, "COMPLETED", finished=True)
            self._log(run_id, "INFO", "Run completed")
        except Exception as exc:  # noqa: BLE001
            self._log(run_id, "ERROR", f"Run failed: {exc}")
            self._set_run_status(run_id, "FAILED", finished=True)

    def list_runs(self, status: str | None = None, search: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM runs WHERE 1=1"
        args: list[Any] = []
        if status:
            query += " AND status=?"
            args.append(status)
        if search:
            query += " AND (id LIKE ? OR input_path LIKE ? OR output_path LIKE ?)"
            s = f"%{search}%"
            args.extend([s, s, s])
        query += " ORDER BY created_at DESC"
        rows = self.conn.execute(query, args).fetchall()
        return [dict(r) for r in rows]

    def run_detail(self, run_id: str) -> dict[str, Any] | None:
        run = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            return None
        models = self.conn.execute("SELECT * FROM models WHERE run_id=? ORDER BY best_score DESC", (run_id,)).fetchall()
        payload = dict(run)
        payload["params_json"] = json.loads(payload["params_json"])
        payload["models"] = []
        for m in models:
            item = dict(m)
            item["metrics_json"] = json.loads(item["metrics_json"] or "{}")
            item["artifacts_json"] = json.loads(item["artifacts_json"] or "{}")
            payload["models"].append(item)
        return payload

    def logs(self, run_id: str, tail: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT ts, level, message FROM run_logs WHERE run_id=? ORDER BY id DESC LIMIT ?",
            (run_id, tail),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def pause(self, run_id: str) -> None:
        self._pause_flags.setdefault(run_id, threading.Event()).set()
        self._set_run_status(run_id, "PAUSED")
        self._log(run_id, "INFO", "Paused")

    def resume(self, run_id: str) -> None:
        self._pause_flags.setdefault(run_id, threading.Event()).clear()
        self._set_run_status(run_id, "RUNNING")
        self._log(run_id, "INFO", "Resumed")

    def stop(self, run_id: str) -> None:
        self._stop_flags.setdefault(run_id, threading.Event()).set()
        self._set_run_status(run_id, "STOPPED", finished=True)
        self._log(run_id, "INFO", "Stop requested")
