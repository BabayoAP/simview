"""Path-tracking controllers (TB-VEH): pure pursuit and Stanley, plus a speed P-controller.

Each returns a steering angle in rad (positive turns left) for a rear-axle pose
(x, y, yaw) and speed v, like `KinematicBicycle`'s state."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from simview.toolboxes.vehicles.path import Path


def wrap(angle: float) -> float:
    """Angle wrapped to [-pi, pi)."""
    return float((angle + np.pi) % (2 * np.pi) - np.pi)


@dataclass
class PurePursuit:
    """Pure pursuit: steer along the circle through the rear axle and a goal point one
    lookahead distance ahead on the path, `steer = atan(2 L sin(alpha) / ld)`.

    The lookahead is `gain * v + min_lookahead` (D-096). The goal is searched forward from the
    vehicle's nearest point; `goal` keeps the last one (for drawing)."""

    path: Path
    wheelbase: float = 2.7
    min_lookahead: float = 3.0
    gain: float = 0.5
    max_steer: float = np.radians(35.0)
    goal: np.ndarray = field(default_factory=lambda: np.zeros(2), init=False)

    def lookahead(self, v: float) -> float:
        return self.gain * abs(v) + self.min_lookahead

    def __call__(self, x: float, y: float, yaw: float, v: float) -> float:
        ld = self.lookahead(v)
        near = self.path.nearest((x, y))
        self.goal = self.path.point_at(near.s + ld)
        dx, dy = self.goal[0] - x, self.goal[1] - y
        alpha = wrap(np.arctan2(dy, dx) - yaw)
        dist = max(float(np.hypot(dx, dy)), 1e-6)  # == ld except near the path's end
        steer = np.arctan2(2.0 * self.wheelbase * np.sin(alpha), dist)
        return float(np.clip(steer, -self.max_steer, self.max_steer))


@dataclass
class Stanley:
    """Stanley: `steer = heading_error + atan(k * e / (v + softening))`, with the cross-track
    error `e` measured at the front axle (positive when the axle is right of the path)."""

    path: Path
    wheelbase: float = 2.7
    k: float = 1.0
    softening: float = 1.0
    max_steer: float = np.radians(35.0)

    def __call__(self, x: float, y: float, yaw: float, v: float) -> float:
        front = (x + self.wheelbase * np.cos(yaw), y + self.wheelbase * np.sin(yaw))
        near = self.path.nearest(front)
        heading_error = wrap(near.heading - yaw)
        steer = heading_error + np.arctan2(-self.k * near.cross_track, abs(v) + self.softening)
        return float(np.clip(steer, -self.max_steer, self.max_steer))


def speed_control(v: float, target: float, *, kp: float = 1.0, max_accel: float = 4.0) -> float:
    """Proportional speed controller: an acceleration toward `target` (m/s)."""
    return float(np.clip(kp * (target - v), -max_accel, max_accel))


def cross_track_error(path: Path, point: Sequence[float]) -> float:
    """Signed distance from `point` to `path` (m), positive left of it (UC-1's plot)."""
    return path.nearest(point).cross_track
