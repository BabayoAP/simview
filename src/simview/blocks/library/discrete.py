"""Discrete: Delay (BD-02)."""

from __future__ import annotations

from collections import deque

import numpy as np

from simview.blocks.library.base import Block, BlockError, Inputs, Signal, as_signal


class Delay(Block):
    type = "Delay"
    category = "Discrete"
    doc = "The input from `samples` samples ago (z^-n); `initial` until then."
    defaults = {"samples": 1, "initial": 0.0}
    feedthrough = False
    discrete = True

    def configure(self) -> None:
        self.n = int(self.params["samples"])
        if self.n < 1:
            raise BlockError("samples must be at least 1")
        self.ic = as_signal(self.params["initial"], "initial")

    def reset(self) -> None:
        self.buf: deque[np.ndarray] = deque([self.ic.copy() for _ in range(self.n)])

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        return [self.buf[0]]

    def update(self, t: float, x: np.ndarray, u: Inputs, ts: float) -> None:
        v = np.asarray(u[0], dtype=np.float64)
        if v.shape != self.ic.shape and self.ic.ndim:
            raise BlockError(f"input is {v.shape} but the initial value is {self.ic.shape}")
        self.buf.popleft()
        self.buf.append(np.broadcast_to(v, self.ic.shape if self.ic.ndim else v.shape).copy())
