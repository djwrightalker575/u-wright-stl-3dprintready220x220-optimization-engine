import numpy as np
import trimesh


def compute_stage1_metrics(mesh: trimesh.Trimesh, overhang_threshold_deg: float = 45.0) -> dict:
    bounds = mesh.bounds
    z_height = float(bounds[1][2] - bounds[0][2])

    z_min = bounds[0][2]
    face_centers = mesh.triangles_center
    face_areas = mesh.area_faces
    normals = mesh.face_normals

    contact_mask = np.abs(face_centers[:, 2] - z_min) < max(0.05, z_height * 0.002)
    bed_contact_area_proxy = float(face_areas[contact_mask].sum())

    down = np.array([0.0, 0.0, -1.0])
    cos_th = np.cos(np.deg2rad(overhang_threshold_deg))
    overhang_mask = (normals @ down) > cos_th
    overhang_area_proxy = float(face_areas[overhang_mask].sum())

    extents = mesh.extents
    footprint = max(extents[0] * extents[1], 1e-6)
    stability_proxy = float((bed_contact_area_proxy + 1e-6) / max(z_height, 1e-3))
    quality_proxy = float((z_height / max((footprint ** 0.5), 1e-3)) + (overhang_area_proxy / max(mesh.area, 1e-6)))

    stage1_score = float(0.5 * overhang_area_proxy + 0.3 * z_height + 0.2 * (1.0 / max(stability_proxy, 1e-6)))

    return {
        "z_height_mm": z_height,
        "bed_contact_area_proxy": bed_contact_area_proxy,
        "overhang_area_proxy": overhang_area_proxy,
        "stability_proxy": stability_proxy,
        "quality_proxy": quality_proxy,
        "stage1_score": stage1_score,
    }
