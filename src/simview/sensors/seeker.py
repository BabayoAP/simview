"""Range/bearing seeker (SN-01): range, bearing (azimuth), and elevation to a target entity.

Angles are in the world frame at the sensor (D-092): bearing is atan2(dy, dx) and elevation
atan2(dz, horizontal distance), as a stabilized seeker reports them. Noise is white, with
standard deviations (range m, bearing rad, elevation rad).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from simview.sensors.base import Sensor, noise_vector

if TYPE_CHECKING:
    from simview.core.entity import Entity
    from simview.core.scheduler import Sim


def rbe(d: np.ndarray) -> np.ndarray:
    """(range, bearing, elevation) of a relative position."""
    horizontal = float(np.hypot(d[0], d[1]))
    return np.array(
        [
            float(np.linalg.norm(d)),
            float(np.arctan2(d[1], d[0])),
            float(np.arctan2(d[2], horizontal)),
        ]
    )


def rbe_to_position(z: Sequence[float]) -> np.ndarray:
    """The relative position of a (range, bearing, elevation) measurement."""
    r, b, e = (float(v) for v in z)
    return r * np.array([np.cos(e) * np.cos(b), np.cos(e) * np.sin(b), np.sin(e)])


class Seeker(Sensor):
    fields = ("range", "bearing", "elevation")
    units = {"range": "m", "bearing": "rad", "elevation": "rad"}

    def __init__(
        self,
        rate: float = 20.0,
        *,
        target: str | Entity | None = None,
        noise_std: Sequence[float] = (0.0, 0.0, 0.0),
        name: str | None = None,
        pos: Sequence[float] = (0.0, 0.0, 0.0),
    ) -> None:
        """`target` is the tracked entity (or its name); it can also be set later."""
        super().__init__(rate, name=name, pos=pos)
        self.target = target
        self.noise_std = noise_vector(noise_std, 3, "noise_std")
        self.origin = np.full(3, np.nan)  # the seeker's world position at the last sample

    def _target(self) -> Entity:
        if self.target is None:
            raise ValueError(f"seeker {self.name!r} has no target")
        if isinstance(self.target, str):
            assert self.entity is not None and self.entity.scene is not None
            return self.entity.scene[self.target]
        return self.target

    def reset(self, sim: Sim) -> None:
        super().reset(sim)
        if self._target().position() is None:
            raise ValueError(f"seeker target {self._target().name!r} has no position()")

    def measure(self, sim: Sim) -> None:
        p = self._target().position()
        assert p is not None
        self.origin = self.pose()[:3, 3]
        z = rbe(p - self.origin) + self.noise_std * self.rng.standard_normal(3)
        z[1] = (z[1] + np.pi) % (2 * np.pi) - np.pi
        self.value = z
