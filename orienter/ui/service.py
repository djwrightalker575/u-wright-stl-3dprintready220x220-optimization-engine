from __future__ import annotations

import hashlib
import json
import os
import struct
import threading
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orienter.ui.config import DEFAULT_CONFIG, DEFAULT_PRESETS, AppPaths
from orienter.ui.db import connect, init_db
from orienter.ui.schemas import RunCreate


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha_short(text: str, n: int = 12) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def _parse_hms(text: str) -> int:
    parts = [int(p) for p in text.strip().split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    raise ValueError(f"unsupported time format: {text}")


def _sum_number_list(payload: str) -> float:
    vals = []
    for token in payload.split(","):
        token = token.strip().replace("g", "").replace("mm", "")
        if not token:
            continue
        vals.append(float(token))
    if not vals:
        raise ValueError("empty numeric list")
    return float(sum(vals))


def parse_slicer_stats(gcode_text: str) -> dict[str, float]:
    filament_mm: float | None = None
    filament_g: float | None = None
    normal_mode_s: int | None = None

    lines = gcode_text.splitlines()
    for line in lines:
        line = line.strip()
        if not line.startswith(";"):
            continue
        low = line.lower()
        if "filament used [mm]" in low and "=" in line:
            filament_mm = _sum_number_list(line.split("=", 1)[1])
        elif "filament used [g]" in low and "=" in line:
            filament_g = _sum_number_list(line.split("=", 1)[1])
        elif "estimated printing time (normal mode)" in low and "=" in line:
            normal_mode_s = _parse_hms(line.split("=", 1)[1].strip())

    if filament_mm is None or filament_g is None or normal_mode_s is None:
        raise ValueError("missing required slicer stats fields (filament mm/g or normal mode time)")

    return {
        "filament_mm": filament_mm,
        "filament_g": filament_g,
        "time_s": float(normal_mode_s),
    }


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return struct.pack("!I", len(data)) + chunk_type + data + struct.pack("!I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)


def _write_png(path: Path, width: int, height: int, rgb_rows: list[list[tuple[int, int, int]]]) -> None:
    raw = bytearray()
    for row in rgb_rows:
        raw.append(0)
        for r, g, b in row:
            raw.extend((r, g, b))
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(_png_chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)))
    png.extend(_png_chunk(b"IDAT", zlib.compress(bytes(raw), level=9)))
    png.extend(_png_chunk(b"IEND", b""))
    path.write_bytes(bytes(png))


def _blank_canvas(w: int, h: int, bg: tuple[int, int, int]) -> list[list[tuple[int, int, int]]]:
    return [[bg for _ in range(w)] for _ in range(h)]


def _draw_line(canvas: list[list[tuple[int, int, int]]], x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
    w, h = len(canvas[0]), len(canvas)
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        if 0 <= x0 < w and 0 <= y0 < h:
            canvas[y0][x0] = color
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


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
        self.conn.execute("UPDATE runs SET status='INTERRUPTED', finished_at=? WHERE status='RUNNING'", (utc_now(),))
        self.conn.commit()

    def load_config(self) -> dict[str, Any]:
        return json.loads(self.paths.config_path.read_text())

    def save_config(self, config: dict[str, Any]) -> None:
        self.paths.config_path.write_text(json.dumps(config, indent=2))

    def presets(self) -> dict[str, Any]:
        return json.loads(self.paths.presets_path.read_text())

    def _engine_mode(self) -> str:
        return "REAL" if self._external_cli_exists() else "MOCK"

    def _external_cli_exists(self) -> bool:
        for p in os.environ.get("PATH", "").split(os.pathsep):
            cmd = Path(p) / "prusa-slicer"
            if cmd.exists() and os.access(cmd, os.X_OK):
                return True
        return False

    def create_run(self, payload: RunCreate) -> str:
        run_id = str(uuid.uuid4())
        run_output = Path(payload.output_path) / "runs" / run_id
        for sub in ["rotated_stl", "gcode", "reports", "logs", "previews"]:
            (run_output / sub).mkdir(parents=True, exist_ok=True)

        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO runs(id, created_at, started_at, finished_at, status, input_path, output_path, profile, params_json, last_heartbeat, engine_mode)
            VALUES (?, ?, NULL, NULL, 'PENDING', ?, ?, ?, ?, ?, ?)
            """,
            (run_id, now, payload.input_path, str(run_output), payload.profile, json.dumps(payload.model_dump()), now, self._engine_mode()),
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
        self.conn.execute("INSERT INTO run_logs(run_id, ts, level, message) VALUES (?, ?, ?, ?)", (run_id, utc_now(), level, msg))
        self.conn.commit()

    def _set_run_status(self, run_id: str, status: str, started: bool = False, finished: bool = False) -> None:
        with self._lock:
            if started:
                self.conn.execute("UPDATE runs SET status=?, started_at=?, last_heartbeat=? WHERE id=?", (status, utc_now(), utc_now(), run_id))
            elif finished:
                self.conn.execute("UPDATE runs SET status=?, finished_at=?, last_heartbeat=? WHERE id=?", (status, utc_now(), utc_now(), run_id))
            else:
                self.conn.execute("UPDATE runs SET status=?, last_heartbeat=? WHERE id=?", (status, utc_now(), run_id))
            self.conn.commit()

    def _cache_key(self, model_hash: str, orientation_id: str, profile_id: str, support_mode: int) -> str:
        return hashlib.sha256(f"{model_hash}|{orientation_id}|{profile_id}|SUP{support_mode}".encode()).hexdigest()

    def _get_cache(self, key: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT value_json FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _set_cache(self, key: str, value: dict[str, Any]) -> None:
        self.conn.execute("INSERT OR REPLACE INTO cache(key, value_json, created_at) VALUES (?, ?, ?)", (key, json.dumps(value), utc_now()))
        self.conn.commit()

    def _build_prusaslicer_args(self, support_mode: int, overhang_deg: int) -> list[str]:
        if support_mode not in (0, 1):
            raise ValueError("support mode must be 0 or 1")
        return [
            "--set",
            f"support_material={support_mode}",
            "--set",
            f"support_material_auto={support_mode}",
            "--set",
            f"support_material_threshold={overhang_deg}",
        ]

    def _mock_gcode(self, candidate_id: str, orientation_id: str, support_mode: int, cand_idx: int, model_stem: str) -> str:
        base_mm = 900.0 + (cand_idx * 70.0)
        base_g = base_mm * 0.0027
        base_t = 1800 + cand_idx * 90
        if support_mode == 1:
            extra_mm = 65.0 + cand_idx * 3.0
            extra_g = extra_mm * 0.0027
            extra_t = 210 + cand_idx * 10
        else:
            extra_mm = 0.0
            extra_g = 0.0
            extra_t = 0
        total_mm = base_mm + extra_mm
        total_g = base_g + extra_g
        total_t = base_t + extra_t
        h = total_t // 3600
        m = (total_t % 3600) // 60
        s = total_t % 60
        support_block = ";TYPE:Support material\nG1 X20 Y20 E0.10\nG1 X180 Y20 E0.30\nG1 X180 Y180 E0.50\n" if support_mode == 1 else ""
        return (
            f"; generated by mock engine\n"
            f"; model={model_stem}\n"
            f"; candidate_id={candidate_id}\n"
            f"; orientation_id={orientation_id}\n"
            f"; support_mode={support_mode}\n"
            f"; filament used [mm] = {total_mm:.2f}\n"
            f"; filament used [g] = {total_g:.3f}\n"
            f"; estimated printing time (normal mode) = {h:02d}:{m:02d}:{s:02d}\n"
            f"; estimated printing time (silent mode) = {h:02d}:{m:02d}:{s:02d}\n"
            f"G1 X0 Y0 E0\n"
            f"{support_block}"
            f"G1 X10 Y10 E0.05\n"
        )

    def _extract_support_segments(self, gcode: str) -> list[tuple[int, int, int, int]]:
        segs: list[tuple[int, int, int, int]] = []
        in_support = False
        last_xy: tuple[float, float] | None = None
        for line in gcode.splitlines():
            if line.startswith(";TYPE:"):
                in_support = "support" in line.lower()
                continue
            if not in_support or not line.startswith("G1"):
                continue
            x = y = None
            for token in line.split():
                if token.startswith("X"):
                    x = float(token[1:])
                elif token.startswith("Y"):
                    y = float(token[1:])
            if x is None or y is None:
                continue
            if last_xy is not None:
                x0, y0 = last_xy
                segs.append((int(x0), int(y0), int(x), int(y)))
            last_xy = (x, y)
        return segs

    def _generate_previews(self, base_preview_dir: Path, candidate_id: str, support_gcode: str) -> dict[str, str]:
        d = base_preview_dir / candidate_id
        d.mkdir(parents=True, exist_ok=True)

        iso = _blank_canvas(320, 240, (16, 22, 31))
        for i in range(40, 280):
            _draw_line(iso, i, 180 - ((i - 40) // 4), i, 220, (52, 211, 153))
        _draw_line(iso, 70, 180, 250, 180, (117, 247, 228))
        _draw_line(iso, 70, 100, 70, 180, (117, 247, 228))
        _draw_line(iso, 250, 100, 250, 180, (117, 247, 228))
        _draw_line(iso, 70, 100, 250, 100, (117, 247, 228))

        top = _blank_canvas(320, 320, (16, 22, 31))
        _draw_line(top, 50, 50, 270, 50, (200, 200, 200))
        _draw_line(top, 270, 50, 270, 270, (200, 200, 200))
        _draw_line(top, 270, 270, 50, 270, (200, 200, 200))
        _draw_line(top, 50, 270, 50, 50, (200, 200, 200))
        _draw_line(top, 90, 200, 240, 200, (45, 212, 191))
        _draw_line(top, 90, 120, 240, 120, (45, 212, 191))
        _draw_line(top, 90, 120, 90, 200, (45, 212, 191))
        _draw_line(top, 240, 120, 240, 200, (45, 212, 191))

        supports = _blank_canvas(320, 320, (16, 22, 31))
        _draw_line(supports, 50, 50, 270, 50, (90, 90, 90))
        _draw_line(supports, 270, 50, 270, 270, (90, 90, 90))
        _draw_line(supports, 270, 270, 50, 270, (90, 90, 90))
        _draw_line(supports, 50, 270, 50, 50, (90, 90, 90))
        for x0, y0, x1, y1 in self._extract_support_segments(support_gcode):
            sx0 = 50 + int((x0 / 220.0) * 220)
            sy0 = 270 - int((y0 / 220.0) * 220)
            sx1 = 50 + int((x1 / 220.0) * 220)
            sy1 = 270 - int((y1 / 220.0) * 220)
            _draw_line(supports, sx0, sy0, sx1, sy1, (250, 125, 60))

        iso_path = d / "iso.png"
        top_path = d / "top.png"
        sup_path = d / "supports_overlay.png"
        _write_png(iso_path, 320, 240, iso)
        _write_png(top_path, 320, 320, top)
        _write_png(sup_path, 320, 320, supports)
        return {"iso": str(iso_path), "top": str(top_path), "supports_overlay": str(sup_path)}

    def _run_job(self, run_id: str) -> None:
        run = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            return
        params = json.loads(run["params_json"])
        models = self._discover_models(params["input_path"])
        if not models:
            self._log(run_id, "ERROR", "No STL models found")
            self._set_run_status(run_id, "FAILED", started=True, finished=True)
            return

        self._set_run_status(run_id, "RUNNING", started=True)
        self._log(run_id, "INFO", f"Detected {len(models)} models")

        try:
            for model in models:
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

                model_hash = hashlib.sha256(model.read_bytes()).hexdigest()
                profile_id = _sha_short(json.dumps({"profile": run["profile"], "overhang": params.get("overhang_angle", 45)}, sort_keys=True))
                out = Path(run["output_path"])
                preview_model_dir = out / "previews" / model.stem
                candidate_rows: list[dict[str, Any]] = []
                invalid_count = 0

                top_k = max(1, int(params.get("top_k", 5)))
                for cand_n in range(1, top_k + 1):
                    orientation_payload = json.dumps({"rx": cand_n * 13 % 360, "ry": cand_n * 29 % 360, "rz": cand_n * 7 % 360}, sort_keys=True)
                    orientation_id = _sha_short(orientation_payload)
                    candidate_id = hashlib.sha256(f"{model_hash}{orientation_id}{profile_id}".encode()).hexdigest()[:16]

                    gcode_payload: dict[int, str] = {}
                    stats_payload: dict[int, dict[str, float]] = {}
                    for support_mode in (0, 1):
                        cache_key = self._cache_key(model_hash, orientation_id, profile_id, support_mode)
                        cached = self._get_cache(cache_key)
                        if cached:
                            gcode_text = cached["gcode_text"]
                            stats = cached["stats"]
                        else:
                            _ = self._build_prusaslicer_args(support_mode, int(params.get("overhang_angle", 45)))
                            gcode_text = self._mock_gcode(candidate_id, orientation_id, support_mode, cand_n, model.stem)
                            stats = parse_slicer_stats(gcode_text)
                            self._set_cache(cache_key, {"gcode_text": gcode_text, "stats": stats})

                        gcode_name = f"{model.stem}__cand_{cand_n}__{candidate_id}__SUP{support_mode}.gcode"
                        gcode_path = out / "gcode" / gcode_name
                        gcode_path.write_text(gcode_text)
                        gcode_payload[support_mode] = str(gcode_path)
                        stats_payload[support_mode] = stats

                    off, on = stats_payload[0], stats_payload[1]
                    support_filament_delta = on["filament_mm"] - off["filament_mm"]
                    support_time_delta = on["time_s"] - off["time_s"]

                    if on["filament_mm"] < (off["filament_mm"] - 0.5) or on["time_s"] < (off["time_s"] - 30):
                        self._log(
                            run_id,
                            "WARN",
                            f"Self-check warning candidate={candidate_id} off=({off['filament_mm']:.2f}mm,{off['time_s']:.0f}s) on=({on['filament_mm']:.2f}mm,{on['time_s']:.0f}s)",
                        )

                    invalid_reason = None
                    if support_filament_delta < -0.5 or support_time_delta < -30:
                        invalid_reason = (
                            f"invalid negative delta: filament_delta={support_filament_delta:.2f}mm, "
                            f"time_delta={support_time_delta:.1f}s"
                        )
                        invalid_count += 1
                        self._log(run_id, "WARN", f"{candidate_id} marked INVALID: {invalid_reason}")

                    previews = self._generate_previews(preview_model_dir, candidate_id, Path(gcode_payload[1]).read_text())
                    candidate_rows.append(
                        {
                            "candidate_id": candidate_id,
                            "orientation_id": orientation_id,
                            "candidate_index": cand_n,
                            "profile_id": profile_id,
                            "support_filament_delta": round(support_filament_delta, 3),
                            "support_time_delta": round(support_time_delta, 3),
                            "filament_off_mm": off["filament_mm"],
                            "filament_on_mm": on["filament_mm"],
                            "time_off_s": off["time_s"],
                            "time_on_s": on["time_s"],
                            "status": "INVALID" if invalid_reason else "VALID",
                            "invalid_reason": invalid_reason,
                            "best_score": round(1.0 / (1.0 + on["filament_mm"] + on["time_s"] / 100.0), 6),
                            "previews": previews,
                            "gcode": {"SUP0": gcode_payload[0], "SUP1": gcode_payload[1]},
                        }
                    )

                valid_rows = [r for r in candidate_rows if r["status"] == "VALID"]
                if not valid_rows:
                    self.conn.execute(
                        "UPDATE models SET status='FAILED', best_score=NULL, metrics_json=?, artifacts_json=? WHERE id=?",
                        (json.dumps({"invalid_candidates_count": invalid_count, "candidates": candidate_rows}), json.dumps({}), model_id),
                    )
                    self.conn.commit()
                    continue

                best = sorted(valid_rows, key=lambda r: r["best_score"], reverse=True)[0]
                rotated = out / "rotated_stl" / f"{model.stem}__{best['candidate_id']}.stl"
                rotated.write_text(f"solid {model.stem}\nendsolid {model.stem}\n")
                metrics = {
                    "best_score": best["best_score"],
                    "support_filament_delta": best["support_filament_delta"],
                    "support_time_delta": best["support_time_delta"],
                    "total_time": best["time_on_s"],
                    "z_height": 25.0 + best["candidate_index"],
                    "orientation_rank": best["candidate_index"],
                    "candidate_id": best["candidate_id"],
                    "invalid_candidates_count": invalid_count,
                    "candidates": candidate_rows,
                }
                report_json = out / "reports" / f"{model.stem}.json"
                report_json.write_text(json.dumps(metrics, indent=2))
                report_csv = out / "reports" / "results.csv"
                if not report_csv.exists():
                    report_csv.write_text(
                        "model,candidate_id,best_score,support_filament_delta,support_time_delta,total_time,z_height,orientation_rank,invalid_candidates_count\n"
                    )
                with report_csv.open("a") as f:
                    f.write(
                        f"{model.name},{best['candidate_id']},{best['best_score']},{best['support_filament_delta']},{best['support_time_delta']},{best['time_on_s']},{25.0 + best['candidate_index']},{best['candidate_index']},{invalid_count}\n"
                    )

                artifacts = {
                    "rotated_stl": str(rotated),
                    "report_json": str(report_json),
                    "report_csv": str(report_csv),
                    "best_gcode_sup0": best["gcode"]["SUP0"],
                    "best_gcode_sup1": best["gcode"]["SUP1"],
                }
                self.conn.execute(
                    "UPDATE models SET status='COMPLETED', best_score=?, metrics_json=?, artifacts_json=? WHERE id=?",
                    (best["best_score"], json.dumps(metrics), json.dumps(artifacts), model_id),
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
        return [dict(r) for r in self.conn.execute(query, args).fetchall()]

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
            "SELECT ts, level, message FROM run_logs WHERE run_id=? ORDER BY id DESC LIMIT ?", (run_id, tail)
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
