"""Delivery routes and a route follower for quadrotors (TB-AERO, UC-2)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from simview.toolboxes.aero.quadrotor import PositionController


@dataclass
class Route:
    """Waypoints flown in order at `speed` (m/s). `dwell` is how long to hover at each
    waypoint once inside `arrive_radius` (one value, or one per waypoint): a drop-off."""

    waypoints: np.ndarray
    speed: float = 5.0
    dwell: float | Sequence[float] = 0.0
    arrive_radius: float = 0.5
    dwells: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.waypoints = np.asarray(self.waypoints, dtype=np.float64)
        if self.waypoints.ndim != 2 or self.waypoints.shape[1] != 3 or len(self.waypoints) < 2:
            raise ValueError("a route needs at least two (x, y, z) waypoints")
        if self.speed <= 0 or self.arrive_radius <= 0:
            raise ValueError("speed and arrive_radius must be positive")
        self.dwells = np.broadcast_to(
            np.asarray(self.dwell, dtype=np.float64), (len(self.waypoints),)
        ).copy()

    @property
    def length(self) -> float:
        return float(np.linalg.norm(np.diff(self.waypoints, axis=0), axis=1).sum())

    def distance(self, points: np.ndarray) -> np.ndarray:
        """Distance from each point (N, 3) to the route's polyline: the route deviation."""
        p = np.atleast_2d(np.asarray(points, dtype=np.float64))[:, None, :]  # (N, 1, 3)
        a = self.waypoints[:-1]
        ab = self.waypoints[1:] - a  # (S, 3)
        s = np.clip(np.einsum("nsk,sk->ns", p - a, ab) / np.maximum((ab * ab).sum(1), 1e-12), 0, 1)
        d = p - (a + s[..., None] * ab)
        return np.sqrt(np.einsum("nsk,nsk->ns", d, d).min(axis=1))


class RouteFollower:
    """Flies a `Route` with a `PositionController` (D-103).

    A reference point (the carrot) moves along the current leg at the route speed. Its speed
    ramps up and down at `accel` (m/s^2), so it stops at each waypoint instead of overshooting
    the corner, and it slows linearly to a stop as the drone falls `max_lag` metres behind it,
    so gusts don't run it away. At each waypoint it waits until the drone is within
    `arrive_radius`, records the arrival time in `arrivals`, hovers for that waypoint's dwell,
    then starts the next leg.
    Call it once per controller tick with the time and the state to steer by (true or
    estimated); it returns the quadrotor input."""

    def __init__(
        self,
        route: Route,
        controller: PositionController,
        *,
        max_lag: float = 3.0,
        accel: float = 2.0,
    ) -> None:
        if max_lag <= 0 or accel <= 0:
            raise ValueError("max_lag and accel must be positive")
        self.route = route
        self.controller = controller
        self.max_lag = float(max_lag)
        self.accel = float(accel)
        self.reset()

    def reset(self) -> None:
        self.leg = 0  # flying from waypoint leg to leg + 1
        self.s = 0.0  # carrot distance along the leg
        self.rate = 0.0  # carrot speed (m/s)
        self.dwell_until: float | None = None
        self.arrivals: list[tuple[int, float]] = [(0, 0.0)]
        self.done = False
        self._t: float | None = None

    @property
    def target(self) -> int:
        """The index of the waypoint being flown to (the last one once done)."""
        return min(self.leg + 1, len(self.route.waypoints) - 1)

    def reference(
        self, t: float, pos: Sequence[float]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The reference position, velocity, and acceleration (a feed-forward) at time `t`."""
        dt = 0.0 if self._t is None else max(t - self._t, 0.0)
        self._t = t
        wp = self.route.waypoints
        zero = np.zeros(3)
        if self.done:
            return wp[-1].copy(), zero, zero
        a, b = wp[self.leg], wp[self.leg + 1]
        length = float(np.linalg.norm(b - a))
        if self.dwell_until is not None:
            if t < self.dwell_until:
                return b.copy(), zero, zero
            self.dwell_until = None
            self.leg += 1
            self.s = 0.0
            self.rate = 0.0
            if self.leg >= len(wp) - 1:
                self.done = True
                return wp[-1].copy(), zero, zero
            a, b = wp[self.leg], wp[self.leg + 1]
            length = float(np.linalg.norm(b - a))
        direction = (b - a) / max(length, 1e-12)
        carrot = a + self.s * direction
        lag = float(np.linalg.norm(np.asarray(pos, dtype=np.float64) - carrot))
        rate = min(
            self.route.speed * float(np.clip(1.0 - lag / self.max_lag, 0.0, 1.0)),
            self.rate + self.accel * dt,
            float(np.sqrt(2.0 * self.accel * max(length - self.s, 0.0))),
        )
        accel = (rate - self.rate) / dt if dt > 0 else 0.0
        self.rate = rate
        self.s = min(self.s + rate * dt, length)
        if self.s >= length:
            if np.linalg.norm(np.asarray(pos) - b) <= self.route.arrive_radius:
                self.arrivals.append((self.leg + 1, t))
                self.dwell_until = t + float(self.route.dwells[self.leg + 1])
            return b.copy(), zero, zero
        return a + self.s * direction, rate * direction, accel * direction

    def __call__(
        self, t: float, pos: Sequence[float], vel: Sequence[float], yaw: float = 0.0
    ) -> np.ndarray:
        ref_pos, ref_vel, ref_acc = self.reference(t, pos)
        a = self.controller.accel(ref_pos, pos, vel, ref_vel, ref_acc)
        return self.controller.attitude(a, yaw)

    def arrival(self, index: int) -> float | None:
        """When the drone first reached waypoint `index` (s), or None if it hasn't yet."""
        return next((t for i, t in self.arrivals if i == index), None)
