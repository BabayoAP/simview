"""Entities with custom Python dynamics (SE-03 custom models, SE-04)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from simview.core.integrators import INTEGRATORS, IntegratorName


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

    def reset(self) -> None:
        self.x = self.x0.copy()

    def __getitem__(self, state: str) -> float:
        """Current value of one named state, e.g. `ball["h"]`."""
        return float(self.x[self.state_names.index(state)])
