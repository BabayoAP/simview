"""Kinematic bicycle model (TB-VEH, UC-1's ego vehicle)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from simview.core.entity import Entity
from simview.core.integrators import IntegratorName


class KinematicBicycle(Entity):
    """Planar car about its rear axle: x' = v cos(yaw), y' = v sin(yaw),
    yaw' = v tan(steer) / wheelbase, v' = accel.

    Inputs `u = [accel, steer]` (m/s^2, rad) are clipped to `max_accel` / `max_steer`; speed is
    kept within [`min_speed`, `max_speed`] (D-092). An empty `u` coasts straight."""

    state_names = ("x", "y", "yaw", "v")
    state_units = {"x": "m", "y": "m", "yaw": "rad", "v": "m/s"}

    def __init__(
        self,
        x0: Sequence[float] | np.ndarray = (0.0, 0.0, 0.0, 0.0),
        *,
        name: str | None = None,
        wheelbase: float = 2.7,
        max_steer: float = np.radians(35.0),
        max_accel: float = 4.0,
        min_speed: float = 0.0,
        max_speed: float = 40.0,
        integrator: IntegratorName = "rk4",
    ) -> None:
        if wheelbase <= 0:
            raise ValueError("wheelbase must be positive")
        if not 0 < max_steer < np.pi / 2:
            raise ValueError("max_steer must be in (0, pi/2) rad")
        if min_speed > max_speed:
            raise ValueError("min_speed must not exceed max_speed")
        super().__init__(x0, name=name, integrator=integrator)
        self.wheelbase = float(wheelbase)
        self.max_steer = float(max_steer)
        self.max_accel = float(max_accel)
        self.min_speed = float(min_speed)
        self.max_speed = float(max_speed)

    def inputs(self, u: np.ndarray) -> tuple[float, float]:
        """The clipped (accel, steer) the model actually applies for input `u`."""
        accel = float(u[0]) if len(u) > 0 else 0.0
        steer = float(u[1]) if len(u) > 1 else 0.0
        return (
            float(np.clip(accel, -self.max_accel, self.max_accel)),
            float(np.clip(steer, -self.max_steer, self.max_steer)),
        )

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        accel, steer = self.inputs(u)
        _, _, yaw, v = x
        if (v >= self.max_speed and accel > 0) or (v <= self.min_speed and accel < 0):
            accel = 0.0
        return np.array(
            [v * np.cos(yaw), v * np.sin(yaw), v * np.tan(steer) / self.wheelbase, accel]
        )

    def advance(self, t: float, dt: float) -> None:
        super().advance(t, dt)
        i = self.state_names.index("v")
        self.x[i] = np.clip(self.x[i], self.min_speed, self.max_speed)

    def velocity(self) -> np.ndarray:
        _, _, yaw, v = self.x
        return np.array([v * np.cos(yaw), v * np.sin(yaw), 0.0])

    @property
    def steer(self) -> float:
        """The steering angle applied this tick (rad)."""
        return self.inputs(self.u)[1]

    def front_axle(self) -> np.ndarray:
        """(x, y) of the front axle's center (Stanley's reference point)."""
        x, y, yaw, _ = self.x
        return np.array([x + self.wheelbase * np.cos(yaw), y + self.wheelbase * np.sin(yaw)])
