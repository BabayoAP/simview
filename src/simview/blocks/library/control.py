"""Control: PID with anti-windup (BD-02, PRD §9 Controls)."""

from __future__ import annotations

import numpy as np

from simview.blocks.library.base import Block, BlockError, Inputs, Signal


class PID(Block):
    """Discrete PID at the diagram's sample period Ts, on the error input e:

    I_k = I_{k-1} + e_k Ts           (skipped while the output is saturated and e pushes
                                      further into the limit: anti-windup)
    D_k = (e_k - e_{k-1}) / Ts       (0 at the first sample)
    u_k = kp e_k + ki I_k + kd D_k   (clipped to [lower, upper] when given)
    """

    type = "PID"
    category = "Control"
    doc = "u = kp·e + ki·∫e + kd·de/dt at the diagram's rate, optional output limits."
    defaults = {"kp": 1.0, "ki": 0.0, "kd": 0.0, "lower": None, "upper": None}
    discrete = True

    def configure(self) -> None:
        self.kp, self.ki, self.kd = (float(self.params[k]) for k in ("kp", "ki", "kd"))
        lo, hi = self.params["lower"], self.params["upper"]
        self.lo = -np.inf if lo is None else float(lo)
        self.hi = np.inf if hi is None else float(hi)
        if self.lo > self.hi:
            raise BlockError("lower must not exceed upper")

    def reset(self) -> None:
        self.integral = 0.0
        self.prev: float | None = None
        self._pending: tuple[float, float] | None = None

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        assert u is not None
        if np.ndim(u[0]) != 0:
            raise BlockError(f"the error input must be a scalar, got shape {np.shape(u[0])}")
        e = float(u[0])
        ts = self.ts
        integral = self.integral + e * ts
        deriv = (e - self.prev) / ts if self.prev is not None and ts > 0 else 0.0
        raw = self.kp * e + self.ki * integral + self.kd * deriv
        out = min(max(raw, self.lo), self.hi)
        if out != raw and np.sign(e * self.ki) == np.sign(raw - out):
            integral = self.integral  # anti-windup: don't integrate further into the limit
        self._pending = (integral, e)
        return [np.asarray(out, dtype=np.float64)]

    def update(self, t: float, x: np.ndarray, u: Inputs, ts: float) -> None:
        if self._pending is not None:
            self.integral, self.prev = self._pending
