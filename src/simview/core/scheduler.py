"""Fixed-timestep scheduler (SE-01) and the per-run `sim` object (SE-07)."""

from __future__ import annotations

import numpy as np

from simview.core.integrators import step
from simview.core.rng import make_rng
from simview.core.scene import Scene


def tick_count(duration: float, dt: float) -> int:
    """Number of ticks to cover `duration`; must be a whole number of `dt`."""
    n = round(duration / dt)
    if n < 1 or abs(n * dt - duration) > 1e-9 * max(1.0, duration):
        raise ValueError(f"duration {duration} s is not a positive multiple of dt {dt} s")
    return n


class Sim:
    """Runtime state of one run: the scene, the clock, and the seeded RNG."""

    def __init__(self, scene: Scene) -> None:
        self.scene = scene
        self.dt = scene.dt
        self.rng: np.random.Generator = make_rng(scene.seed)
        self.tick = 0
        for e in scene.entities.values():
            e.reset()
            dx = np.asarray(e.derivative(0.0, e.x, e.u))
            if dx.shape != e.x.shape:
                raise ValueError(f"{e.name}.derivative returned shape {dx.shape}, not {e.x.shape}")

    @property
    def t(self) -> float:
        # Integer tick count times dt: no drift from summing dt.
        return self.tick * self.dt

    def step(self) -> None:
        t = self.t
        for e in self.scene.entities.values():
            e.x = step(e.integrator, e.derivative, t, e.x, e.u, self.dt)
        self.tick += 1
