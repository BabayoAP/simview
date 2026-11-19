"""Fixed-step ODE integrators for custom models (SE-04)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import numpy as np
from scipy.integrate import solve_ivp

Derivative = Callable[[float, np.ndarray, np.ndarray], np.ndarray]
IntegratorName = Literal["euler", "rk4", "rk45"]
INTEGRATORS: tuple[IntegratorName, ...] = ("euler", "rk4", "rk45")

# RK45 adapts its internal steps inside each tick; these tolerances bound the per-tick error.
RK45_RTOL = 1e-8
RK45_ATOL = 1e-10


def euler(f: Derivative, t: float, x: np.ndarray, u: np.ndarray, dt: float) -> np.ndarray:
    return x + dt * f(t, x, u)


def rk4(f: Derivative, t: float, x: np.ndarray, u: np.ndarray, dt: float) -> np.ndarray:
    k1 = f(t, x, u)
    k2 = f(t + dt / 2, x + dt / 2 * k1, u)
    k3 = f(t + dt / 2, x + dt / 2 * k2, u)
    k4 = f(t + dt, x + dt * k3, u)
    return x + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)


def rk45(f: Derivative, t: float, x: np.ndarray, u: np.ndarray, dt: float) -> np.ndarray:
    """Adaptive Dormand-Prince (SciPy) over one tick; the input is held constant."""
    sol = solve_ivp(
        lambda tt, xx: f(tt, xx, u), (t, t + dt), x, method="RK45", rtol=RK45_RTOL, atol=RK45_ATOL
    )
    if not sol.success:
        raise RuntimeError(f"RK45 failed at t={t}: {sol.message}")
    return sol.y[:, -1]


STEP: dict[IntegratorName, Callable[..., np.ndarray]] = {"euler": euler, "rk4": rk4, "rk45": rk45}


def step(
    name: IntegratorName, f: Derivative, t: float, x: np.ndarray, u: np.ndarray, dt: float
) -> np.ndarray:
    """Advance state `x` by one tick of `dt` with the named integrator."""
    return STEP[name](f, t, x, u, dt)
