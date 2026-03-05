from .parse_gcode import Move


def _map_type(type_tag: str, extruding: bool) -> str:
    if not extruding:
        return "TRAVEL"
    t = type_tag.upper()
    if t in {"SUPPORT", "SUPPORT-INTERFACE"}:
        return "SUPPORT"
    if t in {"SKIRT", "BRIM", "RAFT"}:
        return "BRIM"
    return "MODEL"


def build_preview_cache(moves: list[Move]) -> dict:
    layers: dict[float, list[dict]] = {}
    bounds_min = [float("inf"), float("inf"), float("inf")]
    bounds_max = [float("-inf"), float("-inf"), float("-inf")]
    prev = None
    for m in moves:
        for i, v in enumerate([m.x, m.y, m.z]):
            bounds_min[i] = min(bounds_min[i], v)
            bounds_max[i] = max(bounds_max[i], v)
        if prev is None:
            prev = m
            continue
        z = round(m.z, 4)
        ptype = _map_type(m.type_tag, m.extruding)
        seg = {"type": ptype, "pts": [[prev.x, prev.y], [m.x, m.y]], "e": bool(m.extruding)}
        layers.setdefault(z, []).append(seg)
        prev = m
    out_layers = [{"z": z, "paths": paths} for z, paths in sorted(layers.items(), key=lambda x: x[0])]
    if bounds_min[0] == float("inf"):
        bounds_min = [0, 0, 0]
        bounds_max = [0, 0, 0]
    return {
        "layers": out_layers,
        "bounds": {"min": bounds_min, "max": bounds_max},
        "meta": {"layer_count": len(out_layers)},
    }
