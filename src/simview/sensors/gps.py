"""GPS (SN-01): the sensor's world position with white noise, at its update rate."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from simview.sensors.base import Sensor, noise_vector

if TYPE_CHECKING:
    from simview.core.scheduler import Sim


class GPS(Sensor):
    fields = ("x", "y", "z")
    units = dict.fromkeys(fields, "m")

    def __init__(
        self,
        rate: float = 10.0,
        *,
        noise_std: float | Sequence[float] = 0.0,
        name: str | None = None,
        pos: Sequence[float] = (0.0, 0.0, 0.0),
    ) -> None:
        """`noise_std` is in metres: one value, or (x, y, z)."""
        super().__init__(rate, name=name, pos=pos)
        self.noise_std = noise_vector(noise_std, 3, "noise_std")

    def measure(self, sim: Sim) -> None:
        p = self.pose()[:3, 3]
        self.value = p + self.noise_std * self.rng.standard_normal(3)

    @property
    def position(self) -> np.ndarray:
        return self.value.copy()
