from .parse_gcode import Move


def _map_type(type_tag: str) -> str:
    t = type_tag.upper()
    if t in {"SUPPORT", "SUPPORT-INTERFACE"}:
        return "SUPPORT"
    if t in {"SKIRT", "BRIM", "RAFT"}:
        return "BRIM"
    return "MODEL"


def compute_stage2_metrics(moves: list[Move], total_time_sec: float | None) -> dict:
    support_e = 0.0
    model_e = 0.0
    retractions = 0
    zmax = 0.0
    prev_e = 0.0
    for m in moves:
        zmax = max(zmax, m.z)
        e = m.e or prev_e
        delta = e - prev_e
        if delta < -0.5:
            retractions += 1
        if delta > 0 and m.extruding:
            if _map_type(m.type_tag) == "SUPPORT":
                support_e += delta
            else:
                model_e += delta
        prev_e = e
    return {
        "total_time_sec": total_time_sec,
        "z_height_mm_exact": zmax,
        "support_extrusion_mm": support_e,
        "model_extrusion_mm": model_e,
        "retractions_count": retractions,
    }
