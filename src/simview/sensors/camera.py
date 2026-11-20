"""Pinhole camera (SN-02): an offscreen RGB image (and depth) at a set resolution and rate.

The image is ray cast on the CPU through MuJoCo (`mj_multiRay`, one ray per pixel) rather than
rendered with OpenGL, so it works headless on any machine and is the same everywhere (D-093).
Each hit pixel is its geom's color, shaded by the angle to the camera; misses are the sky color.
The camera looks along its sensor x axis, with image rows going down its z axis.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from simview.sensors.base import Sensor
from simview.sensors.raycast import cast

if TYPE_CHECKING:
    from simview.core.scheduler import Sim

SKY = np.array([0.62, 0.74, 0.86])
VISIBLE = np.array([1, 1, 1, 0, 0, 0], dtype=np.uint8)  # MuJoCo's visible geom groups 0-2


class Camera(Sensor):
    uses_world = True

    def __init__(
        self,
        rate: float = 10.0,
        *,
        width: int = 160,
        height: int = 120,
        fov: float = np.radians(60.0),
        max_range: float = 200.0,
        name: str | None = None,
        pos: Sequence[float] = (0.0, 0.0, 0.0),
        rpy: Sequence[float] = (0.0, 0.0, 0.0),
    ) -> None:
        """`fov` is the horizontal field of view in radians; `width`/`height` in pixels."""
        super().__init__(rate, name=name, pos=pos, rpy=rpy)
        if width < 1 or height < 1 or not 0 < fov < np.pi:
            raise ValueError("camera needs a positive size and 0 < fov < 180°")
        self.width, self.height = int(width), int(height)
        self.max_range = float(max_range)
        self.focal = (self.width / 2) / np.tan(fov / 2)  # pixels
        u = np.arange(self.width) + 0.5 - self.width / 2
        v = np.arange(self.height) + 0.5 - self.height / 2
        vv, uu = np.meshgrid(v, u, indexing="ij")
        rays = np.stack([np.full_like(uu, self.focal), -uu, -vv], axis=-1).reshape(-1, 3)
        self.directions = rays / np.linalg.norm(rays, axis=1, keepdims=True)
        self.image = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        self.depth = np.full((self.height, self.width), np.inf)

    @property
    def intrinsics(self) -> np.ndarray:
        """The 3x3 pinhole matrix K (pixels), for a camera frame with z forward."""
        return np.array(
            [[self.focal, 0, self.width / 2], [0, self.focal, self.height / 2], [0, 0, 1.0]]
        )

    def reset(self, sim: Sim) -> None:
        super().reset(sim)
        self.image = np.zeros_like(self.image)
        self.depth = np.full_like(self.depth, np.inf)

    def measure(self, sim: Sim) -> None:
        pose = self.pose()
        dirs = self.directions @ pose[:3, :3].T
        dist, geom, normals = cast(
            sim, pose[:3, 3], dirs, self.max_range, self.entity, VISIBLE, normals=True
        )
        rgb = np.tile(SKY, (len(dist), 1))
        hit = geom >= 0
        if hit.any():
            m = sim.scene.world.model  # type: ignore[union-attr]
            gid = geom[hit]
            colors = m.geom_rgba[gid, :3].copy()
            mat = m.geom_matid[gid]
            has_mat = mat >= 0
            colors[has_mat] = m.mat_rgba[mat[has_mat], :3]
            assert normals is not None
            shade = np.abs(np.einsum("ij,ij->i", normals[hit], dirs[hit]))
            rgb[hit] = colors * (0.35 + 0.65 * shade[:, None])
        self.image = (np.clip(rgb, 0, 1) * 255).astype(np.uint8).reshape(self.height, self.width, 3)
        self.depth = dist.reshape(self.height, self.width)
