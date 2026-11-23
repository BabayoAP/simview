"""One delivery drone's flight loop, split into the blocks of `d0_loop.svd` (the hero demo's
diagram, PRD §10): IMU + GPS -> EKF -> Route follower -> the quadrotor (an Entity Input block).

Each function is a Python Function block (BD-03); its ports come from the type hints. They do
exactly what `Drone.step` in `scene.py` does, so drone d0 flies the same whether the diagram or
the script runs it (`tests/templates/test_drone_delivery_diagram.py`).

Each block loads its own copy of this file (`"delivery_loop.py:ekf"`). `scene.py` imports it
as the module `delivery_loop`, sets `DRONE` there, then calls `add_diagram`, which loads the
blocks; each copy takes the drone at that moment. So every scene keeps its own drone, even with
several scenes in one process (a sweep without workers). In the app's Diagram tab there is
no drone (the UI never runs the scene), so the editor's check gets zeros of the right shapes.
"""

from __future__ import annotations

import sys
from typing import Any, NamedTuple

import numpy as np

# The `Drone` this copy flies: scene.py sets it on the imported module just before the blocks
# load (None in the UI's Diagram tab).
DRONE: Any = getattr(sys.modules.get("delivery_loop"), "DRONE", None)


def _drone() -> Any:  # noqa: ANN401 - the template's own Drone class
    return DRONE


class Sensed(NamedTuple):
    accel: np.ndarray  # specific force, body frame (m/s^2)
    attitude: np.ndarray  # body-to-world rotation, row-major (9)
    gps: np.ndarray  # GPS position (m)
    fresh: float  # 1 when the GPS sampled this tick


class Estimate(NamedTuple):
    position: np.ndarray
    velocity: np.ndarray


def sense(t: float) -> Sensed:
    """IMU + GPS: the latest readings of the drone's sensors."""
    d = _drone()
    if d is None:
        return Sensed(np.zeros(3), np.eye(3).reshape(9), np.zeros(3), 0.0)
    tick = round(t / d.dt)
    fresh = 1.0 if d.gps.tick == tick else 0.0
    return Sensed(d.imu.accel, d.quad.rotation().reshape(9), d.gps.position, fresh)


def ekf(
    t: float, accel: np.ndarray, attitude: np.ndarray, gps: np.ndarray, fresh: float
) -> Estimate:
    """GPS + IMU navigation filter (EKF): predict with the IMU, correct with fresh GPS."""
    d = _drone()
    if d is None:
        return Estimate(np.zeros(3), np.zeros(3))
    if round(t / d.dt) == 0:
        d.reset()  # every run starts from the same filter and follower
    else:
        d.nav.predict(1.0 / d.imu_rate, accel, attitude.reshape(3, 3))
    if fresh:
        d.nav.update_gps(gps)
    truth = d.quad.position()
    d.err = d.nav.position - truth
    d.bound = 3.0 * np.sqrt(np.diag(d.nav.position_cov))
    d.dev = float(d.route.distance(truth)[0])
    return Estimate(d.nav.position, d.nav.velocity)


def follow(t: float, position: np.ndarray, velocity: np.ndarray) -> np.ndarray:
    """Route follower: the quadrotor's command from the estimated position and velocity."""
    d = _drone()
    if d is None:
        return np.zeros(4)  # thrust and three body torques
    return d.follower(t, position, velocity)
