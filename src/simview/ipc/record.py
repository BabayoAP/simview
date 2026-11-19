"""Per-tick rows the sim process streams to the UI for the timeline and plots (VP-05, DA-01).

Every tick becomes one float64 row: the tick number, every logged signal (the same columns as
the Parquet log, SE-06), every entity's marker position, and every MuJoCo body pose. The UI keeps
them in a `History`, so it can scrub, step back, and plot without asking the sim again.
Nothing here imports Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from simview.ipc.shm import Layout

if TYPE_CHECKING:
    from simview.core.scene import Scene
    from simview.core.scheduler import Sim


@dataclass(frozen=True)
class RowLayout:
    """Column order of a history row. Sent to the UI with the scene description."""

    signals: tuple[str, ...]  # `<entity>.<state>` for every entity, then the scene's channels
    units: tuple[str, ...]  # one per signal; "" when unknown
    state: Layout  # entity sizes, marker entities, and body count (the shared-memory layout)

    @property
    def n_signals(self) -> int:
        return len(self.signals)

    @property
    def markers_at(self) -> int:
        return 1 + self.n_signals

    @property
    def bodies_at(self) -> int:
        return self.markers_at + 3 * len(self.state.marker_entities)

    @property
    def width(self) -> int:
        return self.bodies_at + 7 * self.state.n_bodies


def row_layout(scene: Scene, state: Layout) -> RowLayout:
    signals: list[str] = []
    units: list[str] = []
    for name in state.entity_names:
        e = scene[name]
        for s in e.state_names:
            signals.append(f"{name}.{s}")
            units.append(e.state_units.get(s, ""))
    for ch in scene.channels:
        signals.append(ch)
        units.append(scene.channel_units.get(ch, ""))
    return RowLayout(tuple(signals), tuple(units), state)


def record_row(scene: Scene, sim: Sim, layout: RowLayout) -> np.ndarray:
    """The row for the sim's current tick (call after a step, and once after loading)."""
    parts: list[np.ndarray | list[float]] = [[float(sim.tick)]]
    parts += [scene[n].x for n in layout.state.entity_names]
    parts.append([float(fn(sim)) for fn in scene.channels.values()])
    parts += [scene[n].position() for n in layout.state.marker_entities]  # type: ignore[misc]
    if layout.state.n_bodies:
        import mujoco

        m, d = scene.world.model, scene.world.data  # type: ignore[union-attr]
        mujoco.mj_kinematics(m, d)  # poses of the state just stepped to
        parts.append(np.hstack([d.xpos, d.xquat]).ravel())
    return np.concatenate(parts).astype(np.float64)
