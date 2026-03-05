from pathlib import Path

from app.gcode.metrics_stage2 import compute_stage2_metrics
from app.gcode.parse_gcode import parse_gcode_moves
from app.gcode.preview_cache import build_preview_cache


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "sample.gcode"
    p.write_text(text, encoding="utf-8")
    return p


def test_preview_cache_layers(tmp_path: Path):
    gcode = """
;TYPE:SKIRT
G1 X0 Y0 Z0.2 E0.0
G1 X10 Y0 E1.0
;TYPE:WALL-OUTER
G1 X10 Y10 E2.0
G0 X0 Y0
;TYPE:SUPPORT
G1 X5 Y5 E3.5
""".strip()
    p = _write(tmp_path, gcode)
    moves, total = parse_gcode_moves(p)
    preview = build_preview_cache(moves)
    assert preview["meta"]["layer_count"] == 1
    assert total is None
    types = {seg["type"] for seg in preview["layers"][0]["paths"]}
    assert {"BRIM", "MODEL", "SUPPORT", "TRAVEL"}.issuperset(types)


def test_support_extrusion_mm(tmp_path: Path):
    gcode = """
; estimated printing time (normal mode) = 1m 5s
;TYPE:WALL-INNER
G1 X0 Y0 Z0.2 E0.0
G1 X10 Y0 E2.0
;TYPE:SUPPORT
G1 X10 Y10 E3.0
G1 X0 Y10 E5.5
G1 E4.8
""".strip()
    p = _write(tmp_path, gcode)
    moves, total = parse_gcode_moves(p)
    metrics = compute_stage2_metrics(moves, total)
    assert metrics["total_time_sec"] == 65
    assert abs(metrics["support_extrusion_mm"] - 3.5) < 1e-6
    assert metrics["retractions_count"] >= 1
