"""Extended and unscented Kalman filters, and a GPS + IMU navigation filter (TB-AERO).

Both filters share one interface: `predict(dt, u)` then `update(z)`. The models are plain
functions: `f(x, u, dt) -> x` and `h(x) -> z`; Jacobians are optional for the EKF (central
differences otherwise). `Q` and `R` can be matrices or functions (`Q(dt)`, `R()`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

Fn = Callable[..., np.ndarray]


def numerical_jacobian(fn: Callable[[np.ndarray], np.ndarray], x: np.ndarray) -> np.ndarray:
    """Central-difference Jacobian of `fn` at `x`."""
    x = np.asarray(x, dtype=np.float64)
    f0 = np.asarray(fn(x))
    jac = np.empty((f0.size, x.size))
    for i in range(x.size):
        h = 1e-6 * max(1.0, abs(x[i]))
        d = np.zeros_like(x)
        d[i] = h
        jac[:, i] = (np.asarray(fn(x + d)) - np.asarray(fn(x - d))).ravel() / (2 * h)
    return jac


def _mat(m: Any, *args: Any) -> np.ndarray:
    return np.asarray(m(*args) if callable(m) else m, dtype=np.float64)


class _Filter:
    def __init__(
        self,
        x0: Sequence[float],
        P0: np.ndarray,
        f: Fn,
        h: Fn,
        Q: Any,
        R: Any,
        residual: Fn | None = None,
    ) -> None:
        self.x = np.asarray(x0, dtype=np.float64).copy()
        self.P = np.asarray(P0, dtype=np.float64).copy()
        if self.P.shape != (self.x.size, self.x.size):
            raise ValueError(f"P0 must be {self.x.size}x{self.x.size}, got {self.P.shape}")
        self.f, self.h, self.Q, self.R = f, h, Q, R
        self.residual = residual or np.subtract
        self.y = np.zeros(0)  # last innovation
        self.S = np.zeros((0, 0))  # its covariance
        self.nis = float("nan")  # normalized innovation squared, y' S^-1 y

    def _correct(self, z: np.ndarray, zhat: np.ndarray, S: np.ndarray, K: np.ndarray) -> None:
        self.y = np.asarray(self.residual(z, zhat), dtype=np.float64)
        self.S = S
        self.nis = float(self.y @ np.linalg.solve(S, self.y))
        self.x = self.x + K @ self.y

    def std(self) -> np.ndarray:
        return np.sqrt(np.clip(np.diag(self.P), 0.0, None))


class EKF(_Filter):
    """Extended Kalman filter (D-104). `F(x, u, dt)` and `H(x)` give the Jacobians of `f` and
    `h`; without them they are taken by central differences. The covariance update uses the
    Joseph form, so P stays symmetric positive definite."""

    def __init__(
        self,
        x0: Sequence[float],
        P0: np.ndarray,
        f: Fn,
        h: Fn,
        Q: Any,
        R: Any,
        *,
        F: Fn | None = None,
        H: Fn | None = None,
        residual: Fn | None = None,
    ) -> None:
        super().__init__(x0, P0, f, h, Q, R, residual)
        self.F, self.H = F, H

    def predict(self, dt: float, u: Any = None) -> None:
        F = (
            self.F(self.x, u, dt)
            if self.F is not None
            else numerical_jacobian(lambda x: self.f(x, u, dt), self.x)
        )
        self.x = np.asarray(self.f(self.x, u, dt), dtype=np.float64)
        self.P = F @ self.P @ F.T + _mat(self.Q, dt)

    def update(self, z: Sequence[float], R: Any = None) -> None:
        z = np.asarray(z, dtype=np.float64)
        H = self.H(self.x) if self.H is not None else numerical_jacobian(self.h, self.x)
        Rm = _mat(self.R if R is None else R)
        S = H @ self.P @ H.T + Rm
        K = np.linalg.solve(S, H @ self.P).T
        self._correct(z, np.asarray(self.h(self.x)), S, K)
        ikh = np.eye(self.x.size) - K @ H
        self.P = ikh @ self.P @ ikh.T + K @ Rm @ K.T


class UKF(_Filter):
    """Unscented Kalman filter with scaled sigma points (D-104): 2n + 1 points, spread `alpha`,
    prior knowledge `beta` (2 is optimal for Gaussians), and secondary scaling `kappa`."""

    def __init__(
        self,
        x0: Sequence[float],
        P0: np.ndarray,
        f: Fn,
        h: Fn,
        Q: Any,
        R: Any,
        *,
        alpha: float = 0.5,
        beta: float = 2.0,
        kappa: float = 0.0,
        residual: Fn | None = None,
    ) -> None:
        super().__init__(x0, P0, f, h, Q, R, residual)
        n = self.x.size
        self.lam = alpha**2 * (n + kappa) - n
        self.wm = np.full(2 * n + 1, 0.5 / (n + self.lam))
        self.wc = self.wm.copy()
        self.wm[0] = self.lam / (n + self.lam)
        self.wc[0] = self.wm[0] + 1 - alpha**2 + beta

    def sigma_points(self) -> np.ndarray:
        n = self.x.size
        root = np.linalg.cholesky((n + self.lam) * 0.5 * (self.P + self.P.T))
        return np.vstack([self.x, self.x + root.T, self.x - root.T])

    def predict(self, dt: float, u: Any = None) -> None:
        pts = np.array([self.f(p, u, dt) for p in self.sigma_points()])
        self.x = self.wm @ pts
        d = pts - self.x
        self.P = (self.wc[:, None] * d).T @ d + _mat(self.Q, dt)

    def update(self, z: Sequence[float], R: Any = None) -> None:
        z = np.asarray(z, dtype=np.float64)
        pts = self.sigma_points()
        zs = np.array([np.asarray(self.h(p), dtype=np.float64) for p in pts])
        zhat = self.wm @ zs
        dz = np.array([self.residual(zi, zhat) for zi in zs])
        dx = pts - self.x
        S = (self.wc[:, None] * dz).T @ dz + _mat(self.R if R is None else R)
        cross = (self.wc[:, None] * dx).T @ dz
        K = np.linalg.solve(S.T, cross.T).T
        self._correct(z, zhat, S, K)
        self.P = self.P - K @ S @ K.T


GRAVITY = np.array([0.0, 0.0, -9.81])


class NavFilter:
    """GPS + IMU navigation filter for one drone (D-105): state [position, velocity] (world).

    The IMU's specific force, rotated to the world by the drone's attitude (taken as known,
    from an attitude reference), plus gravity drives the prediction; GPS positions correct it.
    `accel_std` is the IMU accelerometer noise per sample (m/s^2), `gps_std` the GPS noise (m).
    `kind` picks the EKF or the UKF; both give the same answer here, as the models are linear.
    """

    def __init__(
        self,
        pos: Sequence[float],
        vel: Sequence[float] = (0.0, 0.0, 0.0),
        *,
        pos_std: float = 1.0,
        vel_std: float = 0.5,
        accel_std: float = 0.1,
        gps_std: float | Sequence[float] = 1.0,
        kind: str = "ekf",
    ) -> None:
        x0 = np.concatenate([pos, vel]).astype(np.float64)
        P0 = np.diag([pos_std**2] * 3 + [vel_std**2] * 3)
        r = np.broadcast_to(np.asarray(gps_std, dtype=np.float64), (3,))
        self.accel_var = float(accel_std) ** 2
        self._cache: dict[tuple[str, float], np.ndarray] = {}
        cls = {"ekf": EKF, "ukf": UKF}.get(kind)
        if cls is None:
            raise ValueError("kind must be 'ekf' or 'ukf'")
        kw: dict[str, Any] = {}
        if cls is EKF:
            kw = {"F": lambda x, u, dt: self._F(dt), "H": lambda x: self._H}
        self._H = np.hstack([np.eye(3), np.zeros((3, 3))])
        self.filter: EKF | UKF = cls(x0, P0, self._f, self._h, self._Q, np.diag(r**2), **kw)

    def _F(self, dt: float) -> np.ndarray:
        cached = self._cache.get(("F", dt))
        if cached is None:
            cached = np.eye(6)
            cached[:3, 3:] = dt * np.eye(3)
            cached.flags.writeable = False
            self._cache[("F", dt)] = cached
        return cached

    @staticmethod
    def _f(x: np.ndarray, a: np.ndarray | None, dt: float) -> np.ndarray:
        a = np.zeros(3) if a is None else a
        return np.concatenate([x[:3] + x[3:] * dt + 0.5 * a * dt**2, x[3:] + a * dt])

    def _h(self, x: np.ndarray) -> np.ndarray:
        return x[:3]

    def _Q(self, dt: float) -> np.ndarray:
        # Cached per dt: the IMU rate is fixed, and rebuilding it was ~10% of UC-2's tick.
        cached = self._cache.get(("Q", dt))
        if cached is None:
            g = np.concatenate([np.full(3, 0.5 * dt**2), np.full(3, dt)])
            Q = np.outer(g, g) * self.accel_var
            mask = np.kron(np.ones((2, 2)), np.eye(3))  # axes are independent
            cached = Q * mask
            cached.flags.writeable = False
            self._cache[("Q", dt)] = cached
        return cached

    def predict(self, dt: float, specific_force: Sequence[float], rotation: np.ndarray) -> None:
        """Propagate by `dt` with an IMU specific force (body frame) and the body rotation."""
        a = np.asarray(rotation) @ np.asarray(specific_force, dtype=np.float64) + GRAVITY
        self.filter.predict(dt, a)

    def update_gps(self, position: Sequence[float]) -> None:
        self.filter.update(position)

    @property
    def position(self) -> np.ndarray:
        return self.filter.x[:3].copy()

    @property
    def velocity(self) -> np.ndarray:
        return self.filter.x[3:].copy()

    @property
    def position_cov(self) -> np.ndarray:
        return self.filter.P[:3, :3].copy()

    @property
    def nis(self) -> float:
        return self.filter.nis


def nees(error: np.ndarray, P: np.ndarray) -> np.ndarray:
    """Normalized estimation error squared e' P^-1 e, for one error or a batch of them
    (errors (N, n), covariances (N, n, n))."""
    e = np.asarray(error, dtype=np.float64)
    P = np.asarray(P, dtype=np.float64)
    if e.ndim == 1:
        return np.asarray(e @ np.linalg.solve(P, e))
    return np.einsum("ni,ni->n", e, np.linalg.solve(P, e[..., None])[..., 0])
