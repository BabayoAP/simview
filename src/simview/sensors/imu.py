"""IMU (SN-01): accelerometer (specific force) and gyroscope, in the sensor frame, with a
constant bias and white noise per axis.

Acceleration and angular rate are finite differences over the sample period of the entity's
velocity and orientation, so any entity works, and the result is what an IMU integrating
between samples would report (D-091). The first sample has no previous one: it reads zero
acceleration (specific force -g) and zero rate.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from simview.sensors.base import Sensor, noise_vector

if TYPE_CHECKING:
    from simview.core.scheduler import Sim

GRAVITY = np.array([0.0, 0.0, -9.81])


def rotation_log(r: np.ndarray) -> np.ndarray:
    """Rotation vector (axis * angle) of a rotation matrix."""
    cos = np.clip((np.trace(r) - 1.0) / 2.0, -1.0, 1.0)
    angle = float(np.arccos(cos))
    w = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]])
    if angle < 1e-9:
        return w / 2.0
    return w * angle / (2.0 * np.sin(angle))


class IMU(Sensor):
    fields = ("ax", "ay", "az", "gx", "gy", "gz")
    units = {
        **dict.fromkeys(("ax", "ay", "az"), "m/s²"),
        **dict.fromkeys(("gx", "gy", "gz"), "rad/s"),
    }

    def __init__(
        self,
        rate: float = 100.0,
        *,
        accel_noise: float | Sequence[float] = 0.0,
        gyro_noise: float | Sequence[float] = 0.0,
        accel_bias: Sequence[float] = (0.0, 0.0, 0.0),
        gyro_bias: Sequence[float] = (0.0, 0.0, 0.0),
        name: str | None = None,
        pos: Sequence[float] = (0.0, 0.0, 0.0),
        rpy: Sequence[float] = (0.0, 0.0, 0.0),
    ) -> None:
        """Noise values are standard deviations per sample (m/s², rad/s), one or per axis."""
        super().__init__(rate, name=name, pos=pos, rpy=rpy)
        self.accel_noise = noise_vector(accel_noise, 3, "accel_noise")
        self.gyro_noise = noise_vector(gyro_noise, 3, "gyro_noise")
        self.accel_bias = np.asarray(accel_bias, dtype=np.float64)
        self.gyro_bias = np.asarray(gyro_bias, dtype=np.float64)
        self._prev: tuple[np.ndarray, np.ndarray] | None = None

    def reset(self, sim: Sim) -> None:
        super().reset(sim)
        self._prev = None

    def measure(self, sim: Sim) -> None:
        assert self.entity is not None
        rot = self.pose()[:3, :3]
        vel = self.entity.velocity()  # the entity origin's; a lever arm isn't modelled
        period = 1.0 / self.rate
        if self._prev is None:
            accel, rate = np.zeros(3), np.zeros(3)
        else:
            v0, r0 = self._prev
            accel = (vel - v0) / period
            rate = rotation_log(r0.T @ rot) / period  # in the sensor frame
        self._prev = (vel.copy(), rot.copy())
        f = (
            rot.T @ (accel - GRAVITY)
            + self.accel_bias
            + self.accel_noise * self.rng.standard_normal(3)
        )
        g = rate + self.gyro_bias + self.gyro_noise * self.rng.standard_normal(3)
        self.value = np.concatenate([f, g])

    @property
    def accel(self) -> np.ndarray:
        return self.value[:3].copy()

    @property
    def gyro(self) -> np.ndarray:
        return self.value[3:].copy()
