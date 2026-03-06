from dataclasses import dataclass
from pathlib import Path


@dataclass
class Move:
    x: float
    y: float
    z: float
    e: float | None
    extruding: bool
    type_tag: str


def parse_gcode_moves(path: Path) -> tuple[list[Move], float | None]:
    moves: list[Move] = []
    curr = {"x": 0.0, "y": 0.0, "z": 0.0, "e": 0.0}
    current_type = "MODEL"
    total_time_sec = None

    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if line.startswith("; estimated printing time"):
            total_time_sec = _parse_time(line)
        if line.startswith(";TYPE:"):
            current_type = line.split(":", 1)[1].strip().upper()
            continue
        if not line.startswith("G0") and not line.startswith("G1"):
            continue
        params = _parse_params(line)
        prev_e = curr["e"]
        for axis in ("x", "y", "z", "e"):
            if axis in params:
                curr[axis] = params[axis]
        extruding = "e" in params and curr["e"] > prev_e
        moves.append(Move(curr["x"], curr["y"], curr["z"], curr["e"], extruding, current_type))
    return moves, total_time_sec


def _parse_params(line: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for token in line.split()[1:]:
        axis = token[0].lower()
        if axis in {"x", "y", "z", "e", "f"}:
            try:
                out[axis] = float(token[1:])
            except ValueError:
                pass
    return out


def _parse_time(line: str) -> float | None:
    _, rhs = line.split("=", 1) if "=" in line else ("", line)
    rhs = rhs.strip().lower()
    total = 0
    for part in rhs.split():
        if part.endswith("d"):
            total += int(part[:-1]) * 86400
        elif part.endswith("h"):
            total += int(part[:-1]) * 3600
        elif part.endswith("m"):
            total += int(part[:-1]) * 60
        elif part.endswith("s"):
            total += int(part[:-1])
    return float(total) if total > 0 else None
