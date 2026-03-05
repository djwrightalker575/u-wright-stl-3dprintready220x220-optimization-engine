import subprocess
from pathlib import Path


def slice_stl_to_gcode(stl_path: Path, gcode_path: Path, bed_size_mm: list[float]) -> subprocess.CompletedProcess:
    gcode_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "prusa-slicer",
        "--export-gcode",
        str(stl_path),
        "--output",
        str(gcode_path),
        "--bed-shape",
        f"0x0,{bed_size_mm[0]}x0,{bed_size_mm[0]}x{bed_size_mm[1]},0x{bed_size_mm[1]}",
    ]
    return subprocess.run(cmd, check=False, capture_output=True, text=True)
