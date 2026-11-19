"""Continuous: Integrator, Derivative, Transfer Function, State-Space (BD-02).

Continuous states are integrated by the diagram's solver over each sample period.
"""

from __future__ import annotations

import numpy as np

from simview.blocks.library.base import Block, BlockError, Inputs, Signal, as_signal


class Integrator(Block):
    type = "Integrator"
    category = "Continuous"
    doc = "y = ∫u dt from `initial`. Its shape is the initial value's (a vector needs a vector)."
    defaults = {"initial": 0.0}
    feedthrough = False

    def configure(self) -> None:
        self.ic = as_signal(self.params["initial"], "initial")

    def x0(self) -> np.ndarray:
        return self.ic.ravel().copy()

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        return [x.reshape(self.ic.shape).copy()]

    def derivative(self, t: float, x: np.ndarray, u: Inputs) -> np.ndarray:
        if np.shape(u[0]) != self.ic.shape and np.ndim(u[0]) != 0:
            raise BlockError(f"input is {np.shape(u[0])} but the state is {self.ic.shape}")
        return np.broadcast_to(np.asarray(u[0], dtype=np.float64), self.ic.shape).ravel()


class Derivative(Block):
    type = "Derivative"
    category = "Continuous"
    doc = "du/dt, estimated at each sample as (u - u_previous) / sample period (0 at the first)."
    defaults: dict = {}
    discrete = True

    def reset(self) -> None:
        self.prev: np.ndarray | None = None

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        assert u is not None
        v = np.asarray(u[0], dtype=np.float64)
        if self.prev is None or self.ts <= 0:
            return [np.zeros_like(v)]
        return [(v - self.prev) / self.ts]

    def update(self, t: float, x: np.ndarray, u: Inputs, ts: float) -> None:
        self.prev = np.asarray(u[0], dtype=np.float64).copy()


class StateSpace(Block):
    type = "StateSpace"
    category = "Continuous"
    doc = "x' = A x + B u, y = C x + D u, from `x0`."
    defaults = {"A": [[-1.0]], "B": [[1.0]], "C": [[1.0]], "D": [[0.0]], "x0": None}

    def configure(self) -> None:
        a, b, c, d = (np.atleast_2d(as_signal(self.params[k], k)) for k in "ABCD")
        n = a.shape[0]
        if (
            a.shape != (n, n)
            or b.shape[0] != n
            or c.shape[1] != n
            or d.shape != (c.shape[0], b.shape[1])
        ):
            raise BlockError(
                f"inconsistent sizes: A {a.shape}, B {b.shape}, C {c.shape}, D {d.shape}"
            )
        self.A, self.B, self.C, self.D = a, b, c, d
        x0 = self.params["x0"]
        self._x0 = np.zeros(n) if x0 is None else as_signal(x0, "x0").ravel()
        if self._x0.shape != (n,):
            raise BlockError(f"x0 must have {n} values")
        self.feedthrough_ = bool(np.any(d))
        self.m, self.p = b.shape[1], c.shape[0]

    @property
    def feedthrough(self) -> bool:  # type: ignore[override]
        return self.feedthrough_

    def x0(self) -> np.ndarray:
        return self._x0.copy()

    def _u(self, u: Inputs | None) -> np.ndarray:
        if u is None:
            return np.zeros(self.m)
        v = np.atleast_1d(np.asarray(u[0], dtype=np.float64)).ravel()
        if v.shape != (self.m,):
            raise BlockError(f"input has {v.size} values; B has {self.m} columns")
        return v

    def _shape_out(self, y: np.ndarray) -> np.ndarray:
        return y[0] if self.p == 1 else y

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        y = self.C @ x
        if self.feedthrough_:
            y = y + self.D @ self._u(u)
        return [self._shape_out(y)]

    def derivative(self, t: float, x: np.ndarray, u: Inputs) -> np.ndarray:
        return self.A @ x + self.B @ self._u(u)


class TransferFunction(StateSpace):
    type = "TransferFunction"
    category = "Continuous"
    doc = "num(s) / den(s), coefficients highest power first, e.g. num [1], den [1, 2, 1]."
    defaults = {"num": [1.0], "den": [1.0, 1.0]}

    def configure(self) -> None:
        from scipy.signal import tf2ss

        num = np.atleast_1d(as_signal(self.params["num"], "num")).ravel()
        den = np.atleast_1d(as_signal(self.params["den"], "den")).ravel()
        den = np.trim_zeros(den, "f")
        if den.size == 0:
            raise BlockError("den must not be all zeros")
        if np.trim_zeros(num, "f").size > den.size:
            raise BlockError("the transfer function must be proper (num degree <= den degree)")
        a, b, c, d = tf2ss(num, den)
        self.params = {**self.params}
        n = a.shape[0]
        self.A = np.atleast_2d(a) if n else np.zeros((0, 0))
        self.B = np.atleast_2d(b).reshape(n, 1) if n else np.zeros((0, 1))
        self.C = np.atleast_2d(c).reshape(1, n) if n else np.zeros((1, 0))
        self.D = np.atleast_2d(d).reshape(1, 1)
        self._x0 = np.zeros(n)
        self.feedthrough_ = bool(np.any(self.D))
        self.m, self.p = 1, 1
