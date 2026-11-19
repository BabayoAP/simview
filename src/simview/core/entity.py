"""Entities with custom Python dynamics (SE-03 custom models, SE-04)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from simview.core.integrators import INTEGRATORS, IntegratorName, step


class Entity:
    """A custom dynamics model. Subclasses set `state_names` and implement `derivative`.

    `x` is the current state during a run; it is reset to `x0` when a run starts.
    `u` is the input vector passed to `derivative` (empty until controllers or blocks drive it).
    """

    state_names: tuple[str, ...] = ()

    def __init__(
        self,
        x0: Sequence[float] | np.ndarray,
        *,
        name: str | None = None,
        integrator: IntegratorName = "rk4",
    ) -> None:
        if integrator not in INTEGRATORS:
            raise ValueError(f"integrator must be one of {INTEGRATORS}, got {integrator!r}")
        x0 = np.array(x0, dtype=np.float64)
        if x0.ndim != 1 or len(x0) != len(self.state_names):
            raise ValueError(
                f"{type(self).__name__}: x0 has shape {x0.shape}, "
                f"expected ({len(self.state_names)},) for states {self.state_names}"
            )
        self.name = name or type(self).__name__.lower()
        self.integrator: IntegratorName = integrator
        self.x0 = x0
        self.x = x0.copy()
        self.u = np.zeros(0)

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def validate(self) -> None:
        """Called once when a run starts, after `reset`. Raises if the model is malformed."""
        dx = np.asarray(self.derivative(0.0, self.x, self.u))
        if dx.shape != self.x.shape:
            raise ValueError(
                f"{self.name}.derivative returned shape {dx.shape}, not {self.x.shape}"
            )

    def advance(self, t: float, dt: float) -> None:
        """Move `x` forward one tick. Custom models integrate `derivative`; physics-backed
        entities (MuJoCo, SE-03) override this to step their engine instead."""
        self.x = step(self.integrator, self.derivative, t, self.x, self.u, dt)

    def reset(self) -> None:
        self.x = self.x0.copy()

    def __getitem__(self, state: str) -> float:
        """Current value of one named state, e.g. `ball["h"]`."""
        return float(self.x[self.state_names.index(state)])
