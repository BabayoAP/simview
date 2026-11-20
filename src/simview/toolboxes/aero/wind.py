"""Wind with gusts (TB-AERO): a steady mean plus a first-order Gauss-Markov gust per axis."""

from __future__ import annotations

import zlib
from collections.abc import Sequence

import numpy as np

from simview.core.entity import Entity


class Wind(Entity):
    """A uniform wind field whose velocity is logged as states wx, wy, wz (m/s) (D-102).

    Each axis is `mean` plus a Gauss-Markov gust with standard deviation `gust_std` (m/s) and
    correlation time `tau` (s), stepped exactly each tick. The gust noise is drawn from its own
    generator seeded from the scene seed and the entity name, so it repeats run to run and
    doesn't shift other random draws."""

    state_names = ("wx", "wy", "wz")
    state_units = dict.fromkeys(state_names, "m/s")

    def __init__(
        self,
        mean: Sequence[float] = (0.0, 0.0, 0.0),
        *,
        gust_std: float | Sequence[float] = 0.0,
        tau: float = 2.0,
        name: str | None = None,
    ) -> None:
        super().__init__(np.asarray(mean, dtype=np.float64), name=name or "wind")
        if tau <= 0:
            raise ValueError("tau must be positive")
        self.mean = np.asarray(mean, dtype=np.float64)
        self.gust_std = np.broadcast_to(np.asarray(gust_std, dtype=np.float64), (3,)).copy()
        if np.any(self.gust_std < 0):
            raise ValueError("gust_std must be >= 0")
        self.tau = float(tau)
        self.rng = np.random.default_rng()

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.zeros(3)

    def reset(self) -> None:
        super().reset()
        seed = 0 if self.scene is None else self.scene.seed
        self.rng = np.random.Generator(np.random.PCG64([seed, zlib.crc32(self.name.encode())]))

    def advance(self, t: float, dt: float) -> None:
        phi = np.exp(-dt / self.tau)
        noise = self.gust_std * np.sqrt(1.0 - phi**2) * self.rng.standard_normal(3)
        self.x = self.mean + phi * (self.x - self.mean) + noise

    def velocity(self) -> np.ndarray:  # the wind, not a body velocity
        return self.x.copy()

    def position(self) -> np.ndarray | None:
        return None
