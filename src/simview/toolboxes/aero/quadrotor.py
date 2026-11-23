"""6-DOF quadrotor and its flight controllers (TB-AERO, UC-2's delivery drones)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from simview.core.entity import Entity, quat_matrix
from simview.core.integrators import IntegratorName

if TYPE_CHECKING:
    from simview.toolboxes.aero.wind import Wind

G = 9.81
E3 = np.array([0.0, 0.0, 1.0])


def quat_rate(q: np.ndarray, w: np.ndarray) -> np.ndarray:
    """dq/dt of a unit quaternion (w, x, y, z) for a body-frame angular rate w."""
    qw, qx, qy, qz = q
    wx, wy, wz = w
    return 0.5 * np.array(
        [
            -qx * wx - qy * wy - qz * wz,
            qw * wx + qy * wz - qz * wy,
            qw * wy - qx * wz + qz * wx,
            qw * wz + qx * wy - qy * wx,
        ]
    )


def vee(m: np.ndarray) -> np.ndarray:
    """The vector of a skew-symmetric matrix."""
    return np.array([m[2, 1], m[0, 2], m[1, 0]])


class Quadrotor(Entity):
    """A rigid body with collective thrust along its body z axis and body torques (D-100).

    States: position, world velocity, attitude quaternion (w, x, y, z; body to world), and
    body angular rate. Input `u = [thrust, tau_x, tau_y, tau_z]` (N, N m), clipped to
    [0, `max_thrust`] and +-`max_torque`; an empty `u` gives no thrust. Air drag is linear in
    the velocity relative to the air: `drag` (N s/m) times (v - wind)."""

    state_names = ("x", "y", "z", "vx", "vy", "vz", "qw", "qx", "qy", "qz", "p", "q", "r")
    state_units = {
        **dict.fromkeys(("x", "y", "z"), "m"),
        **dict.fromkeys(("vx", "vy", "vz"), "m/s"),
        **dict.fromkeys(("p", "q", "r"), "rad/s"),
    }

    def __init__(
        self,
        pos: Sequence[float] = (0.0, 0.0, 0.0),
        *,
        vel: Sequence[float] = (0.0, 0.0, 0.0),
        yaw: float = 0.0,
        name: str | None = None,
        mass: float = 1.0,
        inertia: Sequence[float] = (0.01, 0.01, 0.02),
        max_thrust: float | None = None,
        max_torque: float = 0.5,
        drag: float = 0.1,
        wind: Wind | None = None,
        integrator: IntegratorName = "rk4",
    ) -> None:
        if mass <= 0 or min(inertia) <= 0:
            raise ValueError("mass and inertia must be positive")
        q = [np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2)]
        x0 = np.concatenate([pos, vel, q, [0.0, 0.0, 0.0]])
        super().__init__(x0, name=name, integrator=integrator)
        self.mass = float(mass)
        self.inertia = np.asarray(inertia, dtype=np.float64)
        self.max_thrust = 2.5 * self.mass * G if max_thrust is None else float(max_thrust)
        self.max_torque = float(max_torque)
        self.drag = float(drag)
        self.wind = wind

    @property
    def hover_thrust(self) -> float:
        return self.mass * G

    def air(self) -> np.ndarray:
        """The wind velocity the drone flies in (zero without a wind model)."""
        return np.zeros(3) if self.wind is None else self.wind.velocity()

    def inputs(self, u: np.ndarray) -> tuple[float, np.ndarray]:
        """The clipped (thrust, torque) the model applies for input `u`."""
        thrust = min(max(float(u[0]), 0.0), self.max_thrust) if len(u) else 0.0
        m = self.max_torque
        tau = np.zeros(3)
        if len(u) >= 4:
            tau = np.array([min(max(float(v), -m), m) for v in u[1:4]])
        return thrust, tau

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        # Scalar math on purpose: this runs four times per tick (RK4) per drone, and NumPy's
        # cross / norm / clip cost more than the arithmetic on 3-vectors (NF-03).
        thrust, (tx, ty, tz) = self.inputs(u)
        vx, vy, vz, qw, qx, qy, qz, wx, wy, wz = x[3:13].tolist()
        n = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
        qw, qx, qy, qz = qw / n, qx / n, qy / n, qz / n
        a = thrust / self.mass
        k = self.drag / self.mass
        ax_, ay_, az_ = self.air().tolist() if self.wind is not None else (0.0, 0.0, 0.0)
        jx, jy, jz = self.inertia.tolist()
        return np.array(
            [
                vx,
                vy,
                vz,
                2 * (qx * qz + qw * qy) * a - k * (vx - ax_),
                2 * (qy * qz - qw * qx) * a - k * (vy - ay_),
                (1 - 2 * (qx * qx + qy * qy)) * a - G - k * (vz - az_),
                0.5 * (-qx * wx - qy * wy - qz * wz),
                0.5 * (qw * wx + qy * wz - qz * wy),
                0.5 * (qw * wy - qx * wz + qz * wx),
                0.5 * (qw * wz + qx * wy - qy * wx),
                (tx - (wy * jz * wz - wz * jy * wy)) / jx,
                (ty - (wz * jx * wx - wx * jz * wz)) / jy,
                (tz - (wx * jy * wy - wy * jx * wx)) / jz,
            ]
        )

    def advance(self, t: float, dt: float) -> None:
        super().advance(t, dt)
        self.x[6:10] /= np.linalg.norm(self.x[6:10])


class AttitudeController:
    """Acceleration command to quadrotor input (D-101). The thrust vector m (a + g) sets the
    desired body z axis, tilted at most `max_tilt` from vertical; a geometric PD law on SO(3)
    tracks that attitude and the commanded yaw, with natural frequency `wn` (rad/s) and
    damping `zeta` on each axis."""

    def __init__(
        self,
        quad: Quadrotor,
        *,
        wn: float = 25.0,
        zeta: float = 0.9,
        max_tilt: float = np.radians(35.0),
    ) -> None:
        self.quad = quad
        self.kr = quad.inertia * wn**2
        self.kw = quad.inertia * 2 * zeta * wn
        self.max_tilt = float(max_tilt)

    def __call__(self, accel: Sequence[float], yaw: float = 0.0) -> np.ndarray:
        quad = self.quad
        rot = quat_matrix(quad.x[6:10])
        w = quad.x[10:13]
        f = quad.mass * (np.asarray(accel, dtype=np.float64) + G * E3)
        f[2] = max(f[2], 0.1 * quad.hover_thrust)  # keep some lift: never point the rotors down
        horizontal = float(np.hypot(f[0], f[1]))
        limit = f[2] * np.tan(self.max_tilt)
        if horizontal > limit:
            f[:2] *= limit / horizontal
        b3 = f / np.linalg.norm(f)
        b2 = np.cross(b3, [np.cos(yaw), np.sin(yaw), 0.0])
        b2 /= np.linalg.norm(b2)
        rd = np.column_stack([np.cross(b2, b3), b2, b3])
        e_r = 0.5 * vee(rd.T @ rot - rot.T @ rd)
        tau = -self.kr * e_r - self.kw * w + np.cross(w, quad.inertia * w)
        return np.concatenate([[float(f @ rot[:, 2])], tau])


class PositionController:
    """PD on position and velocity errors (plus a feed-forward acceleration), limited to
    `max_accel`, flown by an `AttitudeController`. Call it with the reference and the state
    the controller should use (true or estimated); it returns the quadrotor input."""

    def __init__(
        self,
        quad: Quadrotor,
        *,
        kp: float = 2.0,
        kd: float = 2.5,
        max_accel: float = 5.0,
        **attitude: float,
    ) -> None:
        self.kp, self.kd, self.max_accel = float(kp), float(kd), float(max_accel)
        self.attitude = AttitudeController(quad, **attitude)

    def accel(
        self,
        ref_pos: Sequence[float],
        pos: Sequence[float],
        vel: Sequence[float],
        ref_vel: Sequence[float] = (0.0, 0.0, 0.0),
        ff: Sequence[float] = (0.0, 0.0, 0.0),
    ) -> np.ndarray:
        a = (
            self.kp * (np.asarray(ref_pos) - np.asarray(pos))
            + self.kd * (np.asarray(ref_vel) - np.asarray(vel))
            + np.asarray(ff, dtype=np.float64)
        )
        n = float(np.linalg.norm(a))
        return a if n <= self.max_accel else a * (self.max_accel / n)

    def __call__(
        self,
        ref_pos: Sequence[float],
        pos: Sequence[float],
        vel: Sequence[float],
        ref_vel: Sequence[float] = (0.0, 0.0, 0.0),
        yaw: float = 0.0,
    ) -> np.ndarray:
        return self.attitude(self.accel(ref_pos, pos, vel, ref_vel), yaw)
