"""The scene: what gets simulated (SC-04). Built the same way from a script or the GUI."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from simview.core.entity import Entity

if TYPE_CHECKING:
    from simview.core.scheduler import Sim
    from simview.physics.mujoco_world import Robot

DT_MIN = 1e-4  # 0.1 ms (SE-01)
DT_MAX = 1e-1  # 100 ms
DT_DEFAULT = 1e-3

E = TypeVar("E", bound=Entity)
LogFn = Callable[["Sim"], float]


class Scene:
    def __init__(self, dt: float = DT_DEFAULT, seed: int = 0) -> None:
        if not DT_MIN <= dt <= DT_MAX:
            raise ValueError(f"dt must be between {DT_MIN} and {DT_MAX} s, got {dt}")
        self.dt = float(dt)
        self.seed = int(seed)
        self.entities: dict[str, Entity] = {}
        self.channels: dict[str, LogFn] = {}

    def add_entity(self, entity: E) -> E:
        if entity.name in self.entities:
            raise ValueError(f"an entity named {entity.name!r} already exists; pass name=")
        self.entities[entity.name] = entity
        return entity

    def add_robot(self, path: str | Path, *, name: str | None = None) -> Robot:
        """Add a MuJoCo-backed robot from a URDF/MJCF file or a bundled name like "ur5.urdf"."""
        from simview.physics.mujoco_world import Robot  # MuJoCo loads only when a robot is used

        return self.add_entity(Robot(path, name=name))

    def log(self, name: str, fn: LogFn) -> None:
        """Log a user-tagged channel each tick. `fn(sim)` returns a float (SE-06)."""
        if name in self.channels or "." in name:
            raise ValueError(f"channel name {name!r} is taken or contains '.'")
        self.channels[name] = fn

    def __getitem__(self, name: str) -> Entity:
        return self.entities[name]
