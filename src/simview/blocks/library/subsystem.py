"""Subsystems (BD-07): Inport and Outport blocks inside a Subsystem's own diagram.

The compiler flattens subsystems before running, so these never run themselves; they only
number the subsystem's ports.
"""

from __future__ import annotations

import numpy as np

from simview.blocks.library.base import Block, BlockError, Inputs, Signal


class Inport(Block):
    type = "Inport"
    category = "Sources"
    doc = "Input `index` (1, 2, ...) of the subsystem it's in."
    defaults = {"index": 1}
    feedthrough = False

    def configure(self) -> None:
        self.index = int(self.params["index"])
        if self.index < 1:
            raise BlockError("index starts at 1")
        self.n_in = 0

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        raise BlockError("an Inport only works inside a subsystem")


class Outport(Block):
    type = "Outport"
    category = "Sinks"
    doc = "Output `index` (1, 2, ...) of the subsystem it's in."
    defaults = {"index": 1}

    def configure(self) -> None:
        self.index = int(self.params["index"])
        if self.index < 1:
            raise BlockError("index starts at 1")
        self.n_out = 0

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        return []
