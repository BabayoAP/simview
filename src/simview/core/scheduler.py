"""Fixed-timestep scheduler (SE-01) and the per-run `sim` object (SE-07)."""

from __future__ import annotations

from typing import Any

import numpy as np

from simview.core.draw import DrawList
from simview.core.rng import make_rng
from simview.core.scene import Context, Scene


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
        self.draw = DrawList()  # VP-07: shown by the viewport, recorded headless too
        self.params = scene.params  # SC-05: changes take effect on the next tick
        self.action: object = None  # ML-01: set by the RL env before each step
        self.params.freeze()
        for e in scene.entities.values():
            e.reset()
            e.validate()
        if scene.world is not None:
            scene.world.reset()
        for d in scene.diagrams.values():
            d.reset()
        # Controllers run every `period` ticks, starting at tick 0 (RB-06).
        self.controllers = [
            (c, 1 if c.rate is None else round(1.0 / (c.rate * self.dt))) for c in scene.controllers
        ]
        # Sensors sample at the end of every `period`-th tick, and once at the start, so a
        # controller at tick k reads the measurement of the state at tick k (SN-01).
        self.sensors = [(s, round(1.0 / (s.rate * self.dt))) for s in scene.sensors()]
        for s, _ in self.sensors:
            s.reset(self)
        # VW-02/VW-04: camera streams and perception pipelines, stepped after sensors sample.
        self.streams: dict[str, Any] = {}
        for s, _ in self.sensors:
            for name, stream in getattr(s, "streams", {}).items():
                if name in self.streams:
                    raise ValueError(f"stream name {name!r} is used twice")
                self.streams[name] = stream
        self.pipelines = [
            (p, 1 if p.rate is None else round(1.0 / (p.rate * self.dt))) for p in scene.pipelines
        ]
        for p, _ in self.pipelines:
            p.bind(self, self.streams)
        self._sample(force=True)
        self._perceive(force=True)

    @property
    def t(self) -> float:
        # Integer tick count times dt: no drift from summing dt.
        return self.tick * self.dt

    def close(self) -> None:
        """End the run: pipelines finish their files (e.g. a `Record` dataset's index).
        Safe to call more than once; only the first call closes the pipelines."""
        if getattr(self, "_closed", False):
            return
        self._closed = True
        for p, _ in self.pipelines:
            p.close()

    def _sample(self, force: bool = False) -> None:
        due = [s for s, period in self.sensors if force or self.tick % period == 0]
        if not due:
            return
        if self.scene.world is not None and any(s.uses_world for s in due):
            self.scene.world.kinematics()  # ray casts need this tick's geometry
        for s in due:
            s.sample(self)

    def _perceive(self, force: bool = False) -> None:
        for p, period in self.pipelines:
            if force or self.tick % period == 0:
                p.tick(self.t)

    def step(self) -> None:
        t = self.t
        self.draw.new_tick()
        for i, (c, period) in enumerate(self.controllers):
            if self.tick % period == 0:
                self.draw.begin(i)  # this controller's previous draws are replaced (D-089)
                try:
                    out = c.fn(t, self.scene, Context(self, period * self.dt))
                finally:
                    self.draw.end()
                for name, u in (out or {}).items():
                    self.scene[name].u = np.asarray(u, dtype=np.float64)
        for e in self.scene.entities.values():
            e.advance(t, self.dt)
        if self.scene.world is not None:
            self.scene.world.step(t, self.dt)
        self.tick += 1
        if self.sensors:
            self._sample()
        if self.pipelines:
            self._perceive()
