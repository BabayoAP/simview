"""Sinks: Scope, To Workspace (BD-02, BD-08). Their inputs are logged like every block
output (SE-06); a Scope also docks a plot of them into the plot panel, and To Workspace
names a console variable that gets them after a run."""

from __future__ import annotations

import numpy as np

from simview.blocks.library.base import Block, BlockError, Inputs, Signal


class Scope(Block):
    type = "Scope"
    category = "Sinks"
    doc = "Plots its inputs in the plot panel, synced with the timeline."
    defaults = {"inputs": 1}

    def configure(self) -> None:
        self.n_in = int(self.params["inputs"])
        if self.n_in < 1:
            raise BlockError("inputs must be at least 1")
        self.n_out = 0

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        return []


class ToWorkspace(Block):
    type = "ToWorkspace"
    category = "Sinks"
    doc = "Saves its input as a console variable (`variable`) with its time, after a run."
    defaults = {"variable": "simout"}

    def configure(self) -> None:
        name = str(self.params["variable"])
        if not name.isidentifier():
            raise BlockError(f"variable {name!r} is not a valid Python name")
        self.variable = name
        self.n_out = 0

    def output(self, t: float, x: np.ndarray, u: Inputs | None) -> list[Signal]:
        return []
