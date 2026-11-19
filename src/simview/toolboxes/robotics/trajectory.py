"""Joint trajectories (RB-09): cubic, quintic, and trapezoidal-velocity profiles.

Each works on one joint or many (arrays of the same shape). `traj.at(t)` returns
`(q, qd, qdd)`; before the start it holds the first point and after `duration` the last one.
Multi-joint trapezoidal profiles are synchronized: every joint starts and stops together.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

State = tuple[np.ndarray, np.ndarray, np.ndarray]


@dataclass(frozen=True)
class Polynomial:
    """q(s) = sum c_k s^k, with s = t in [0, duration]; one coefficient row per joint."""

    coeffs: np.ndarray  # (order + 1, n_joints)
    duration: float

    def at(self, t: float) -> State:
        s = float(np.clip(t, 0.0, self.duration))
        k = np.arange(len(self.coeffs))
        q = (self.coeffs.T * s**k).sum(axis=-1)
        qd = (self.coeffs[1:].T * k[1:] * s ** (k[1:] - 1)).sum(axis=-1)
        qdd = (self.coeffs[2:].T * k[2:] * (k[2:] - 1) * s ** (k[2:] - 2)).sum(axis=-1)
        if t < 0.0 or t > self.duration:
            qd, qdd = np.zeros_like(q), np.zeros_like(q)
        return q, qd, qdd


def _vec(x: float | np.ndarray) -> np.ndarray:
    return np.atleast_1d(np.asarray(x, dtype=np.float64))


def _check_duration(duration: float) -> float:
    if duration <= 0:
        raise ValueError(f"duration must be positive, got {duration}")
    return float(duration)


def cubic(
    q0: float | np.ndarray,
    q1: float | np.ndarray,
    duration: float,
    v0: float | np.ndarray = 0.0,
    v1: float | np.ndarray = 0.0,
) -> Polynomial:
    """Cubic from (q0, v0) to (q1, v1) in `duration` seconds."""
    T = _check_duration(duration)
    q0, q1 = _vec(q0), _vec(q1)
    v0, v1 = np.broadcast_to(_vec(v0), q0.shape), np.broadcast_to(_vec(v1), q0.shape)
    dq = q1 - q0
    c2 = (3 * dq - (2 * v0 + v1) * T) / T**2
    c3 = (-2 * dq + (v0 + v1) * T) / T**3
    return Polynomial(np.stack([q0, v0, c2, c3]), T)


def quintic(
    q0: float | np.ndarray,
    q1: float | np.ndarray,
    duration: float,
    v0: float | np.ndarray = 0.0,
    v1: float | np.ndarray = 0.0,
    a0: float | np.ndarray = 0.0,
    a1: float | np.ndarray = 0.0,
) -> Polynomial:
    """Quintic from (q0, v0, a0) to (q1, v1, a1): continuous acceleration at both ends."""
    T = _check_duration(duration)
    q0, q1 = _vec(q0), _vec(q1)
    v0, v1, a0, a1 = (np.broadcast_to(_vec(x), q0.shape) for x in (v0, v1, a0, a1))
    dq = q1 - q0
    c3 = (20 * dq - (8 * v1 + 12 * v0) * T - (3 * a0 - a1) * T**2) / (2 * T**3)
    c4 = (-30 * dq + (14 * v1 + 16 * v0) * T + (3 * a0 - 2 * a1) * T**2) / (2 * T**4)
    c5 = (12 * dq - 6 * (v1 + v0) * T - (a0 - a1) * T**2) / (2 * T**5)
    return Polynomial(np.stack([q0, v0, a0 / 2, c3, c4, c5]), T)


@dataclass(frozen=True)
class Trapezoidal:
    """Accelerate at `a`, cruise at `v`, decelerate: per joint, scaled to a shared duration."""

    q0: np.ndarray
    q1: np.ndarray
    v: np.ndarray  # cruise speed per joint (>= 0)
    a: np.ndarray  # acceleration per joint (>= 0)
    t_acc: float
    duration: float

    def at(self, t: float) -> State:
        sign = np.sign(self.q1 - self.q0)
        T, ta = self.duration, self.t_acc
        t = float(np.clip(t, 0.0, T)) if T > 0 else 0.0
        if t <= ta:
            s, sd, sdd = 0.5 * self.a * t**2, self.a * t, self.a
        elif t <= T - ta:
            s, sd, sdd = 0.5 * self.a * ta**2 + self.v * (t - ta), self.v, np.zeros_like(self.v)
        else:
            r = T - t
            dist = np.abs(self.q1 - self.q0)
            s, sd, sdd = dist - 0.5 * self.a * r**2, self.a * r, -self.a
        q = self.q0 + sign * s
        if t >= T:
            return self.q1.copy(), np.zeros_like(q), np.zeros_like(q)
        return q, sign * sd, sign * sdd


def trapezoidal(
    q0: float | np.ndarray,
    q1: float | np.ndarray,
    v_max: float | np.ndarray,
    a_max: float | np.ndarray,
) -> Trapezoidal:
    """Fastest synchronized trapezoidal-velocity move within per-joint `v_max` and `a_max`.

    The slowest joint sets the duration; the others are slowed to finish with it, keeping the
    same acceleration-phase time (a triangular profile when there is no room to cruise).
    """
    q0, q1 = _vec(q0), _vec(q1)
    v_max = np.broadcast_to(_vec(v_max), q0.shape).astype(np.float64)
    a_max = np.broadcast_to(_vec(a_max), q0.shape).astype(np.float64)
    if np.any(v_max <= 0) or np.any(a_max <= 0):
        raise ValueError("v_max and a_max must be positive")
    dist = np.abs(q1 - q0)
    # Per joint: time to cover dist at its own limits.
    tri = dist <= v_max**2 / a_max
    t_alone = np.where(tri, 2 * np.sqrt(dist / a_max), dist / v_max + v_max / a_max)
    k = int(np.argmax(t_alone))
    T = float(t_alone[k])
    if T == 0.0:
        z = np.zeros_like(q0)
        return Trapezoidal(q0, q1, z, z, 0.0, 0.0)
    ta = float(np.sqrt(dist[k] / a_max[k]) if tri[k] else v_max[k] / a_max[k])
    # Every joint uses the same ta and T: dist = v * (T - ta), a = v / ta.
    v = dist / (T - ta)
    a = v / ta
    return Trapezoidal(q0, q1, v, a, ta, T)
