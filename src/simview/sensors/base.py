"""Sensor base (SN-01..SN-03): mounted on an entity, sampled at a fixed rate, seeded noise.

A sensor samples once when a run starts and then at the end of every tick that is a multiple
of its period, so a controller running at tick k reads a measurement of the state at tick k.
Between samples it holds its last reading. Each sensor draws its noise from its own generator,
seeded from the scene seed and the sensor's full name, so adding a sensor doesn't change the
noise of the others (D-091).
"""

from __future__ import annotations

import zlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, ClassVar

import numpy as np

if TYPE_CHECKING:
    from simview.core.entity import Entity
    from simview.core.scheduler import Sim


def rpy_matrix(rpy: Sequence[float]) -> np.ndarray:
    """Rotation from roll, pitch, yaw (radians, applied about x, then y, then z)."""
    r, p, y = (float(v) for v in rpy)
    cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(y), np.sin(y)
    return np.array(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ]
    )


class Sensor:
    """Subclasses set `fields` (logged scalars, in `value`) and implement `measure`.

    `pos` and `rpy` mount the sensor in its entity's frame (metres, radians). The sensor's
    own frame is x forward, y left, z up.
    """

    fields: ClassVar[tuple[str, ...]] = ()
    units: ClassVar[Mapping[str, str]] = {}
    uses_world: ClassVar[bool] = False  # needs MuJoCo geometry (ray casts)

    def __init__(
        self,
        rate: float,
        *,
        name: str | None = None,
        pos: Sequence[float] = (0.0, 0.0, 0.0),
        rpy: Sequence[float] = (0.0, 0.0, 0.0),
    ) -> None:
        if rate <= 0:
            raise ValueError(f"sensor rate must be positive, got {rate}")
        self.rate = float(rate)
        self.name = name or type(self).__name__.lower()
        if not self.name.isidentifier():
            raise ValueError(f"sensor name {self.name!r} must be a Python identifier")
        self.mount = np.eye(4)
        self.mount[:3, :3] = rpy_matrix(rpy)
        self.mount[:3, 3] = np.asarray(pos, dtype=np.float64)
        self.entity: Entity | None = None
        self.value = np.full(len(self.fields), np.nan)
        self.t = float("nan")  # time of the last sample
        self.tick = -1  # tick of the last sample
        self.rng = np.random.default_rng()

    def __getattr__(self, name: str) -> float:
        fields = type(self).fields
        if name in fields:
            return float(self.__dict__["value"][fields.index(name)])
        raise AttributeError(f"{type(self).__name__} has no attribute {name!r}")

    def pose(self) -> np.ndarray:
        """The sensor's 4x4 world pose: its entity's pose times the mount."""
        assert self.entity is not None, f"sensor {self.name!r} isn't attached to an entity"
        return self.entity.pose() @ self.mount

    def updated(self, sim_or_ctx: object) -> bool:
        """True if the sensor sampled at the current tick (a fresh measurement)."""
        return self.tick == sim_or_ctx.tick  # type: ignore[attr-defined]

    def reset(self, sim: Sim) -> None:
        assert self.entity is not None
        key = zlib.crc32(f"{self.entity.name}.{self.name}".encode())
        self.rng = np.random.Generator(np.random.PCG64([sim.scene.seed, key]))
        self.value = np.full(len(self.fields), np.nan)
        self.t, self.tick = float("nan"), -1

    def sample(self, sim: Sim) -> None:
        self.t, self.tick = sim.t, sim.tick
        self.measure(sim)

    def measure(self, sim: Sim) -> None:
        raise NotImplementedError


def noise_vector(std: float | Sequence[float], n: int, what: str) -> np.ndarray:
    a = np.broadcast_to(np.asarray(std, dtype=np.float64), (n,)).copy()
    if np.any(a < 0):
        raise ValueError(f"{what} must be >= 0")
    return a
