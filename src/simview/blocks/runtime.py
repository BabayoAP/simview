"""Running a diagram in a scene (BD-04, BD-05, BD-08, SE-06).

A diagram is a sampled system: at every sample (every tick, or `rate` Hz) it
  1. computes every block's outputs at t, in topological order,
  2. writes Entity Input blocks to their entities (before the entities move this tick),
  3. updates discrete blocks (Delay, PID, Derivative),
  4. integrates its continuous states (Integrator, Transfer Function, State-Space) over the
     sample period with the chosen integrator, holding discrete outputs and entity readings.
It runs as one of the scene's controllers, so a diagram and a script controller with the same
math give the same numbers. Every block output is logged as `<diagram>.<block>.<port>`
(`[i]` per element for vectors); outputs hold between samples.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from simview.blocks.compiler import compile_diagram
from simview.blocks.graph import Diagram
from simview.blocks.library.entities import EntityInput
from simview.blocks.library.sinks import Scope, ToWorkspace
from simview.core.integrators import INTEGRATORS, IntegratorName, step

if TYPE_CHECKING:
    from simview.core.scene import Context, Scene


def element_names(base: str, shape: tuple[int, ...]) -> list[str]:
    if not shape:
        return [base]
    return [f"{base}[{k}]" for k in range(int(np.prod(shape)))]


class DiagramRun:
    def __init__(
        self,
        scene: Scene,
        diagram: Diagram,
        name: str,
        rate: float | None = None,
        integrator: IntegratorName = "rk4",
        base: Path | None = None,
    ) -> None:
        if integrator not in INTEGRATORS:
            raise ValueError(f"integrator must be one of {INTEGRATORS}")
        self.scene, self.diagram, self.name = scene, diagram, name
        self.integrator: IntegratorName = integrator
        self.period = 1 if rate is None else round(1.0 / (rate * scene.dt))
        self.ts = self.period * scene.dt
        self.compiled = compile_diagram(diagram, scene=scene, base=base, ts=self.ts)
        nodes = self.compiled.nodes
        self.discrete = [i for i, n in enumerate(nodes) if n.block.discrete]
        self.writers = [i for i, n in enumerate(nodes) if isinstance(n.block, EntityInput)]
        # Signal names of every output port, element by element.
        self.signals: dict[tuple[int, int], list[str]] = {}
        for i, n in enumerate(nodes):
            for k, port in enumerate(n.block.output_names()):
                shape = self.compiled.shapes[(n.path, k)]
                self.signals[(i, k)] = element_names(f"{name}.{n.path}.{port}", shape)
        self.scopes: dict[str, list[str]] = {}  # "<diagram>.<scope>" -> its input signals
        self.to_workspace: dict[str, list[str]] = {}  # variable -> its input signals
        for n in nodes:
            ins = [s for j, p in n.inputs for s in self.signals[(j, p)]]
            if isinstance(n.block, Scope):
                self.scopes[f"{name}.{n.path}"] = ins
            elif isinstance(n.block, ToWorkspace):
                self.to_workspace[n.block.variable] = ins
        for (i, k), names in self.signals.items():
            for e, sig in enumerate(names):
                scene.channels[sig] = lambda sim, i=i, k=k, e=e: self._value(sim, i, k, e)
                scene.channel_units[sig] = ""
        scene.controller(rate)(self.sample)
        self.reset()

    def reset(self) -> None:
        self.compiled.reset(self.ts)
        self.x = self.compiled.x0.copy()
        self._outs: list[list[np.ndarray]] | None = None
        self._tick = -1

    # -- evaluation -------------------------------------------------------------------------
    def evaluate(self, tick: int) -> list[list[np.ndarray]]:
        """The outputs at a sample tick (computed once per sample, so the logger and the
        controller see the same values), or the last sample's between samples (held)."""
        if self._outs is None or (tick % self.period == 0 and tick != self._tick):
            self._outs = self.compiled.outputs(tick * self.scene.dt, self.x)
            self._tick = tick
        return self._outs

    def _value(self, sim: Any, i: int, k: int, e: int) -> float:
        return float(np.ravel(self.evaluate(sim.tick)[i][k])[e])

    def sample(self, t: float, state: Scene, ctx: Context) -> None:
        outs = self.evaluate(ctx.tick)
        comp = self.compiled
        for i in self.writers:
            comp.nodes[i].block.write(comp.inputs(i, outs))  # type: ignore[attr-defined]
        held = {i: outs[i] for i in self.discrete}
        for i in self.discrete:
            comp.nodes[i].block.update(t, self.x[comp.nodes[i].xs], comp.inputs(i, outs), self.ts)
        if len(self.x):
            self.x = step(
                self.integrator,
                lambda tt, xx, _u: comp.derivative(tt, xx, held),
                t,
                self.x,
                np.zeros(0),
                self.ts,
            )
