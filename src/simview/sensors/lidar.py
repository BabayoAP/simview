"""Ray-cast lidar (SN-03) through MuJoCo's ray API (`mj_multiRay`).

A scan is `beams` rows, evenly spread over the vertical field of view, by one column per
`horizontal_resolution` over the horizontal field of view (360° by default), cast from the
sensor's origin. Ranges get white noise and are clipped to [0, max_range]; misses are inf.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from simview.sensors.base import Sensor
from simview.sensors.raycast import cast

if TYPE_CHECKING:
    from simview.core.scheduler import Sim


class Lidar(Sensor):
    uses_world = True

    def __init__(
        self,
        rate: float = 10.0,
        *,
        beams: int = 32,
        vertical_fov: tuple[float, float] = (np.radians(-25.0), np.radians(15.0)),
        horizontal_fov: float = 2 * np.pi,
        horizontal_resolution: float = np.radians(1.0),
        max_range: float = 100.0,
        noise_std: float = 0.0,
        name: str | None = None,
        pos: Sequence[float] = (0.0, 0.0, 0.0),
        rpy: Sequence[float] = (0.0, 0.0, 0.0),
    ) -> None:
        """Angles in radians; `vertical_fov` is (lowest, highest) elevation; range in metres."""
        super().__init__(rate, name=name, pos=pos, rpy=rpy)
        lo, hi = (float(v) for v in vertical_fov)
        if beams < 1 or not -np.pi / 2 <= lo <= hi <= np.pi / 2:
            raise ValueError("lidar needs beams >= 1 and -90° <= vertical_fov[0] <= [1] <= 90°")
        if max_range <= 0 or horizontal_resolution <= 0 or not 0 < horizontal_fov <= 2 * np.pi:
            raise ValueError("lidar needs a positive range and resolution, and 0 < fov <= 360°")
        self.beams = int(beams)
        self.max_range = float(max_range)
        self.noise_std = float(noise_std)
        cols = max(1, round(horizontal_fov / horizontal_resolution))
        if np.isclose(horizontal_fov, 2 * np.pi):
            az = np.arange(cols) * (2 * np.pi / cols) - np.pi
        else:
            az = np.linspace(-horizontal_fov / 2, horizontal_fov / 2, cols)
        el = np.linspace(lo, hi, self.beams) if self.beams > 1 else np.array([(lo + hi) / 2])
        e, a = np.meshgrid(el, az, indexing="ij")
        self.elevations, self.azimuths = el, az
        # unit directions in the sensor frame, (beams * cols, 3), row-major by beam
        self.directions = np.stack(
            [np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)], axis=-1
        ).reshape(-1, 3)
        self.ranges = np.full((self.beams, cols), np.inf)
        self.points = np.zeros((0, 3))  # hits in the world frame
        self.points_local = np.zeros((0, 3))  # hits in the sensor frame

    def reset(self, sim: Sim) -> None:
        super().reset(sim)
        self.ranges = np.full_like(self.ranges, np.inf)
        self.points = np.zeros((0, 3))
        self.points_local = np.zeros((0, 3))

    def measure(self, sim: Sim) -> None:
        pose = self.pose()
        rot, origin = pose[:3, :3], pose[:3, 3]
        dist, _, _ = cast(sim, origin, self.directions @ rot.T, self.max_range, self.entity)
        hit = np.isfinite(dist)
        if self.noise_std > 0:
            dist[hit] += self.noise_std * self.rng.standard_normal(int(hit.sum()))
            dist[hit] = np.clip(dist[hit], 0.0, self.max_range)
        self.ranges = dist.reshape(self.ranges.shape)
        self.points_local = self.directions[hit] * dist[hit, None]
        self.points = self.points_local @ rot.T + origin
