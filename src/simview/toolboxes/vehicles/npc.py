"""Scripted NPC agents (TB-VEH, UC-1's traffic): vehicles that follow a path on a speed
schedule, without dynamics or reaction to others (D-097)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from simview.core.entity import Entity
from simview.toolboxes.vehicles.path import Path

Speed = float | Sequence[tuple[float, float]] | Callable[[float], float]


class ScriptedNPC(Entity):
    """An agent that drives along `path` from arc length `start` at `speed`.

    `speed` is a constant (m/s), a schedule of (t, v) pairs (linear in between, held at the
    ends), or a function `speed(t)`. Speeds below 0 count as 0. At the path's end the agent
    stops (or, with `loop=True`, starts over). States: x, y, yaw, v, s."""

    state_names = ("x", "y", "yaw", "v", "s")
    state_units = {"x": "m", "y": "m", "yaw": "rad", "v": "m/s", "s": "m"}

    def __init__(
        self,
        path: Path,
        speed: Speed,
        *,
        start: float = 0.0,
        loop: bool = False,
        name: str | None = None,
    ) -> None:
        self.path = path
        self.loop = loop
        self._speed = _schedule(speed)
        super().__init__(self._state(0.0, float(start)), name=name)

    def speed(self, t: float) -> float:
        return max(0.0, float(self._speed(t)))

    def _state(self, t: float, s: float) -> np.ndarray:
        if self.loop:
            s %= self.path.length
        else:
            s = min(s, self.path.length)
        p = self.path.point_at(s)
        at_end = not self.loop and s >= self.path.length
        v = 0.0 if at_end else self.speed(t)
        return np.array([p[0], p[1], self.path.heading_at(s), v, s])

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        v = x[3]
        yaw = x[2]
        return np.array([v * np.cos(yaw), v * np.sin(yaw), 0.0, 0.0, v])

    def advance(self, t: float, dt: float) -> None:
        # Trapezoidal in the schedule: exact for constant and piecewise-linear speeds.
        ds = 0.5 * (self.speed(t) + self.speed(t + dt)) * dt
        s = self.x[4] + ds
        self.x = self._state(t + dt, s)

    def velocity(self) -> np.ndarray:
        _, _, yaw, v, _ = self.x
        return np.array([v * np.cos(yaw), v * np.sin(yaw), 0.0])


def _schedule(speed: Speed) -> Callable[[float], float]:
    if callable(speed):
        return speed
    if isinstance(speed, int | float):
        v = float(speed)
        return lambda t: v
    pts = np.asarray(speed, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) == 0:
        raise ValueError("a speed schedule is a list of (t, v) pairs")
    if np.any(np.diff(pts[:, 0]) <= 0):
        raise ValueError("speed schedule times must increase")
    ts, vs = pts[:, 0], pts[:, 1]
    return lambda t: float(np.interp(t, ts, vs))
