import math
from typing import Iterable

import numpy as np
import trimesh
from trimesh.transformations import quaternion_about_axis, quaternion_matrix, quaternion_multiply


def fibonacci_normals(n: int) -> Iterable[np.ndarray]:
    phi = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(n):
        y = 1 - (i / float(max(n - 1, 1))) * 2
        radius = math.sqrt(max(0.0, 1 - y * y))
        theta = phi * i
        x = math.cos(theta) * radius
        z = math.sin(theta) * radius
        yield np.array([x, y, z], dtype=float)


def quat_from_to(v1: np.ndarray, v2: np.ndarray) -> np.ndarray:
    v1 = v1 / np.linalg.norm(v1)
    v2 = v2 / np.linalg.norm(v2)
    dot = np.clip(np.dot(v1, v2), -1.0, 1.0)
    if dot > 0.999999:
        return np.array([1.0, 0.0, 0.0, 0.0])
    if dot < -0.999999:
        axis = np.cross(v1, np.array([1.0, 0.0, 0.0]))
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(v1, np.array([0.0, 1.0, 0.0]))
        axis = axis / np.linalg.norm(axis)
        return quaternion_about_axis(math.pi, axis)
    axis = np.cross(v1, v2)
    s = math.sqrt((1 + dot) * 2)
    invs = 1 / s
    q = np.array([s * 0.5, axis[0] * invs, axis[1] * invs, axis[2] * invs])
    return q / np.linalg.norm(q)


def generate_candidate_quaternions(max_candidates: int) -> list[np.ndarray]:
    yaw_angles = [0, 120, 240]
    base_count = max(1, max_candidates // len(yaw_angles))
    down = np.array([0.0, 0.0, -1.0])
    quats: list[np.ndarray] = []
    for normal in fibonacci_normals(base_count):
        q_align = quat_from_to(normal, down)
        for yaw in yaw_angles:
            q_yaw = quaternion_about_axis(math.radians(yaw), [0, 0, 1])
            q = quaternion_multiply(q_yaw, q_align)
            quats.append(q / np.linalg.norm(q))
            if len(quats) >= max_candidates:
                return quats
    return quats


def apply_quaternion(mesh: trimesh.Trimesh, quat: np.ndarray) -> trimesh.Trimesh:
    m = mesh.copy()
    mat = quaternion_matrix(quat)
    m.apply_transform(mat)
    return m


def quat_distance(a: np.ndarray, b: np.ndarray) -> float:
    d = abs(float(np.dot(a, b)))
    return 1.0 - d
