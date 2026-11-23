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
        n = len(u)
        if n == 0:
            return 0.0, np.zeros(3)
        vals = u.tolist() if isinstance(u, np.ndarray) else [float(v) for v in u]
        thrust = min(max(vals[0], 0.0), self.max_thrust)
        if n < 4:
            return thrust, np.zeros(3)
        m = self.max_torque
        return thrust, np.array([min(max(v, -m), m) for v in vals[1:4]])

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

    def _rates(
        self,
        s: list[float],
        a: float,
        tau: tuple[float, float, float],
        air: tuple[float, float, float],
    ) -> list[float]:
        """`derivative` on plain floats, for the RK4 fast path (same equations)."""
        vx, vy, vz, qw, qx, qy, qz, wx, wy, wz = s[3:13]
        n = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
        nw, nx, ny, nz = qw / n, qx / n, qy / n, qz / n
        k = self.drag / self.mass
        jx, jy, jz = self._j
        tx, ty, tz = tau
        return [
            vx,
            vy,
            vz,
            2 * (nx * nz + nw * ny) * a - k * (vx - air[0]),
            2 * (ny * nz - nw * nx) * a - k * (vy - air[1]),
            (1 - 2 * (nx * nx + ny * ny)) * a - G - k * (vz - air[2]),
            0.5 * (-nx * wx - ny * wy - nz * wz),
            0.5 * (nw * wx + ny * wz - nz * wy),
            0.5 * (nw * wy - nx * wz + nz * wx),
            0.5 * (nw * wz + nx * wy - ny * wx),
            (tx - (wy * jz * wz - wz * jy * wy)) / jx,
            (ty - (wz * jx * wx - wx * jz * wz)) / jy,
            (tz - (wx * jy * wy - wy * jx * wx)) / jz,
        ]

    def advance(self, t: float, dt: float) -> None:
        if self.integrator == "rk4" and type(self).derivative is Quadrotor.derivative:
            # RK4 on Python floats (NF-03): the input and the wind are constant over a tick,
            # so they're read once instead of at each of the four stages.
            thrust, tau = self.inputs(self.u)
            a = thrust / self.mass
            tq = tuple(tau.tolist())
            air = tuple(self.air().tolist()) if self.wind is not None else (0.0, 0.0, 0.0)
            self._j = tuple(self.inertia.tolist())
            x = self.x.tolist()
            h = dt / 2
            k1 = self._rates(x, a, tq, air)
            k2 = self._rates([xi + h * ki for xi, ki in zip(x, k1, strict=True)], a, tq, air)
            k3 = self._rates([xi + h * ki for xi, ki in zip(x, k2, strict=True)], a, tq, air)
            k4 = self._rates([xi + dt * ki for xi, ki in zip(x, k3, strict=True)], a, tq, air)
            c = dt / 6
            self.x = np.array(
                [
                    xi + c * (a1 + 2 * a2 + 2 * a3 + a4)
                    for xi, a1, a2, a3, a4 in zip(x, k1, k2, k3, k4, strict=True)
                ]
            )
        else:
            super().advance(t, dt)
        x = self.x
        qw, qx, qy, qz = x[6:10].tolist()
        x[6:10] /= math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)


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
        # Scalar 3-vector math (NF-03): NumPy's cross / column_stack on 3-vectors cost more
        # than the arithmetic. Same law as before: e_r = vee(Rd' R - R' Rd) / 2.
        quad = self.quad
        rot = quat_matrix(quad.x[6:10]).T.tolist()  # rows of rot.T = columns of rot
        wx, wy, wz = quad.x[10:13].tolist()
        ax, ay, az = (float(v) for v in accel)
        mass = quad.mass
        fx, fy = mass * ax, mass * ay
        fz = max(mass * (az + G), 0.1 * quad.hover_thrust)  # never point the rotors down
        horizontal = math.hypot(fx, fy)
        limit = fz * math.tan(self.max_tilt)
        if horizontal > limit:
            fx, fy = fx * limit / horizontal, fy * limit / horizontal
        n = math.sqrt(fx * fx + fy * fy + fz * fz)
        b3 = (fx / n, fy / n, fz / n)
        cx, cy = math.cos(yaw), math.sin(yaw)
        b2 = (-b3[2] * cy, b3[2] * cx, b3[0] * cy - b3[1] * cx)  # b3 x (cos, sin, 0)
        n = math.sqrt(b2[0] ** 2 + b2[1] ** 2 + b2[2] ** 2)
        b2 = (b2[0] / n, b2[1] / n, b2[2] / n)
        b1 = (
            b2[1] * b3[2] - b2[2] * b3[1],
            b2[2] * b3[0] - b2[0] * b3[2],
            b2[0] * b3[1] - b2[1] * b3[0],
        )
        rd = (b1, b2, b3)

        def a(i: int, j: int) -> float:  # (Rd' R)[i, j]
            ri, cj = rd[i], rot[j]
            return ri[0] * cj[0] + ri[1] * cj[1] + ri[2] * cj[2]

        ex = 0.5 * (a(2, 1) - a(1, 2))
        ey = 0.5 * (a(0, 2) - a(2, 0))
        ez = 0.5 * (a(1, 0) - a(0, 1))
        jx, jy, jz = quad.inertia.tolist()
        (krx, kry, krz), (kwx, kwy, kwz) = self.kr.tolist(), self.kw.tolist()
        hx, hy, hz = jx * wx, jy * wy, jz * wz
        r3 = rot[2]
        return np.array(
            [
                fx * r3[0] + fy * r3[1] + fz * r3[2],
                -krx * ex - kwx * wx + (wy * hz - wz * hy),
                -kry * ey - kwy * wy + (wz * hx - wx * hz),
                -krz * ez - kwz * wz + (wx * hy - wy * hx),
            ]
        )


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
