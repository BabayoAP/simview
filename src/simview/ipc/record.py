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


def record_row(
    scene: Scene, sim: Sim, layout: RowLayout, channels: np.ndarray | None = None
) -> np.ndarray:
    """The row for the sim's current tick (call after a step, and once after loading).
    `channels` gives the channel values instead of computing them (replaying a log)."""
    parts: list[np.ndarray | list[float]] = [[float(sim.tick)]]
    parts += [scene[n].x for n in layout.state.entity_names]
    if channels is None:
        parts.append([float(fn(sim)) for fn in scene.channels.values()])
    else:
        parts.append(channels)
    parts += [scene[n].position() for n in layout.state.marker_entities]  # type: ignore[misc]
    if layout.state.n_bodies:
        import mujoco

        m, d = scene.world.model, scene.world.data  # type: ignore[union-attr]
        mujoco.mj_kinematics(m, d)  # poses of the state just stepped to
        parts.append(np.hstack([d.xpos, d.xquat]).ravel())
    return np.concatenate(parts).astype(np.float64)


def replay_rows(scene: Scene, sim: Sim, layout: RowLayout, path: str) -> tuple[np.ndarray, float]:
    """History rows for a saved or imported run (RI-01, RI-06): each logged row's states are
    set on the scene's entities (states the log lacks keep their start values), and markers
    and body poses are computed from them, so the run replays in the viewport. Channels come
    from the log (NaN if it lacks them). Returns (rows, the run's sample period)."""
    import json

    import pyarrow.parquet as pq

    table = pq.read_table(path)
    names = set(table.column_names)
    meta = json.loads((table.schema.metadata or {}).get(b"simview", b"{}"))
    t = table.column("t").to_numpy().astype(np.float64)
    dt = float(meta.get("dt") or (np.median(np.diff(t)) if len(t) > 1 else scene.dt))
    if "tick" in names:
        ticks = table.column("tick").to_numpy().astype(np.float64)
    else:
        ticks = np.round(t / dt)
    n = len(t)
    setters = []
    for name in layout.state.entity_names:
        e = scene[name]
        idx = [i for i, s in enumerate(e.state_names) if f"{name}.{s}" in names]
        if idx:
            cols = np.column_stack(
                [table.column(f"{name}.{e.state_names[i]}").to_numpy() for i in idx]
            ).astype(np.float64)
            setters.append((e, np.array(idx), cols))
    channels = (
        np.column_stack(
            [
                table.column(c).to_numpy().astype(np.float64) if c in names else np.full(n, np.nan)
                for c in scene.channels
            ]
        )
        if scene.channels
        else np.zeros((n, 0))
    )
    rows = np.empty((n, layout.width))
    for k in range(n):
        for e, idx, cols in setters:
            e.x[idx] = cols[k]
        if scene.world is not None:
            scene.world.load_state()
        sim.tick = int(ticks[k])
        rows[k] = record_row(scene, sim, layout, channels[k])
    return rows, dt
