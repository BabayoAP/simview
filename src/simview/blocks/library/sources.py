"""Sources: Constant, Step, Sine (BD-02)."""

from __future__ import annotations

import numpy as np

from simview.blocks.library.base import Block, BlockError, Inputs, Signal, as_signal


class Constant(Block):
    type = "Constant"
    category = "Sources"
    doc = "A fixed value: a number, a vector, or a matrix."
    defaults = {"value": 1.0}
    feedthrough = False

    def configure(self) -> None:
        self.n_in = 0
        self.value = as_signal(self.params["value"], "value")

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        return [self.value]


class Step(Block):
    type = "Step"
    category = "Sources"
    doc = "`before` until `time` (s), then `after`."
    defaults = {"time": 1.0, "before": 0.0, "after": 1.0}
    feedthrough = False

    def configure(self) -> None:
        self.n_in = 0
        self.time = float(self.params["time"])
        self.before = as_signal(self.params["before"], "before")
        self.after = as_signal(self.params["after"], "after")
        if self.before.shape != self.after.shape:
            raise BlockError("before and after must have the same shape")

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        # A small tolerance so a step at a sample time is taken at that sample.
        return [self.after if t >= self.time - 1e-12 else self.before]


class Sine(Block):
    type = "Sine"
    category = "Sources"
    doc = "amplitude · sin(frequency · t + phase) + bias, frequency in rad/s."
    defaults = {"amplitude": 1.0, "frequency": 1.0, "phase": 0.0, "bias": 0.0}
    feedthrough = False

    def configure(self) -> None:
        self.n_in = 0
        self.a, self.w, self.phi, self.b = (
            as_signal(self.params[k], k) for k in ("amplitude", "frequency", "phase", "bias")
        )

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        return [np.asarray(self.a * np.sin(self.w * t + self.phi) + self.b, dtype=np.float64)]
