"""Back-projection stage (VW-05, D-125): depth + K + pose -> one world-frame point cloud per tick.

Pixel (u, v) with z-depth z (OpenCV convention) is the optical-frame point
((u - cx) z / fx, (v - cy) z / fy, z), moved to the world by the frame's pose. Every frame of a
pipeline step (all rig cameras) is merged into one `PointCloud` that keeps each point's camera
origin, so the occupancy grid can trace the free space along each ray.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from simview.perception.stream import Frame


@dataclass(eq=False)
class PointCloud:
    """World-frame points (N, 3) with RGB (N, 3) uint8; `origins` (C, 3) are the camera
    centres and `origin_index` (N,) says which one saw each point. `ego` is the vehicle's world
    pose (4x4) at the newest frame when the frames carried it."""

    t: float
    points: np.ndarray
    colors: np.ndarray
    origins: np.ndarray
    origin_index: np.ndarray
    ego: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.points)


class BackProject:
    """Pipeline stage: list[Frame] -> PointCloud.

    `max_range` drops points farther than that from their camera (metres, Euclidean),
    `min_range` closer ones; `stride` keeps every stride-th pixel in both directions;
    `ego_box=((xmin, ymin, zmin), (xmax, ymax, zmax))` (in the vehicle's frame, needs frames with
    an `ego` pose) masks out the rig's own vehicle. Frames without depth are skipped."""

    output = "cloud"

    def __init__(
        self,
        max_range: float = 40.0,
        *,
        min_range: float = 0.0,
        stride: int = 2,
        ego_box: tuple[Sequence[float], Sequence[float]] | None = None,
    ) -> None:
        if max_range <= 0 or min_range < 0 or min_range >= max_range:
            raise ValueError("need 0 <= min_range < max_range")
        if stride < 1:
            raise ValueError("stride must be >= 1")
        self.max_range = float(max_range)
        self.min_range = float(min_range)
        self.stride = int(stride)
        self.ego_box = (
            None
            if ego_box is None
            else (np.asarray(ego_box[0], dtype=np.float64), np.asarray(ego_box[1], np.float64))
        )
        self._rays: dict[tuple[bytes, int, int], np.ndarray] = {}

    def reset(self) -> None:
        pass

    def _unit_rays(self, k: np.ndarray, h: int, w: int) -> np.ndarray:
        """Optical-frame rays (h', w', 3) with z = 1 for the strided pixels (cached per K)."""
        key = (np.asarray(k, dtype=np.float64).tobytes(), h, w)
        rays = self._rays.get(key)
        if rays is None:
            s = self.stride
            u = np.arange(0, w, s, dtype=np.float64)
            v = np.arange(0, h, s, dtype=np.float64)
            vv, uu = np.meshgrid(v, u, indexing="ij")
            fx, fy, cx, cy = k[0, 0], k[1, 1], k[0, 2], k[1, 2]
            skew = k[0, 1]
            y = (vv - cy) / fy
            x = (uu - cx - skew * y) / fx
            rays = np.stack([x, y, np.ones_like(x)], axis=-1)
            self._rays[key] = rays
        return rays

    def project(self, frame: Frame) -> tuple[np.ndarray, np.ndarray]:
        """One frame's world points (N, 3) and colors (N, 3)."""
        assert frame.depth is not None
        s = self.stride
        z = np.asarray(frame.depth, dtype=np.float64)[::s, ::s]
        rays = self._unit_rays(np.asarray(frame.K, dtype=np.float64), *frame.depth.shape)
        rng = z * np.linalg.norm(rays, axis=-1)
        valid = np.isfinite(z) & (z > 0) & (rng <= self.max_range) & (rng >= self.min_range)
        cam = rays[valid] * z[valid][:, None]
        pose = np.asarray(frame.pose, dtype=np.float64)
        pts = cam @ pose[:3, :3].T + pose[:3, 3]
        colors = np.asarray(frame.rgb)[::s, ::s][valid]
        if self.ego_box is not None and frame.ego is not None:
            ego = np.asarray(frame.ego, dtype=np.float64)
            local = (pts - ego[:3, 3]) @ ego[:3, :3]
            lo, hi = self.ego_box
            inside = np.all((local >= lo) & (local <= hi), axis=1)
            pts, colors = pts[~inside], colors[~inside]
        return pts, colors

    def __call__(self, frames: Sequence[Frame]) -> PointCloud | None:
        frames = [f for f in frames if f.depth is not None]
        if not frames:
            return None
        pts, cols, idx = [], [], []
        origins = np.array([np.asarray(f.pose, dtype=np.float64)[:3, 3] for f in frames])
        for i, f in enumerate(frames):
            p, c = self.project(f)
            pts.append(p)
            cols.append(c)
            idx.append(np.full(len(p), i, dtype=np.int32))
        newest = max(range(len(frames)), key=lambda i: frames[i].t)
        return PointCloud(
            t=max(f.t for f in frames),
            points=np.concatenate(pts),
            colors=np.concatenate(cols).astype(np.uint8),
            origins=origins,
            origin_index=np.concatenate(idx),
            ego=None if frames[newest].ego is None else np.asarray(frames[newest].ego),
        )
