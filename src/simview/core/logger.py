"""Per-tick columnar log written to Parquet (SE-06), byte-identical per seed (SE-07)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from simview.core.scheduler import Sim


class Logger:
    """Records `t`, `tick`, every entity state as `<entity>.<state>`, and tagged channels."""

    def __init__(self, sim: Sim, rows: int) -> None:
        self.sim = sim
        scene = sim.scene
        self.state_columns = [
            f"{e.name}.{s}" for e in scene.entities.values() for s in e.state_names
        ]
        self.channel_names = list(scene.channels)
        self.ticks = np.zeros(rows, dtype=np.int64)
        self.data = np.zeros((rows, len(self.state_columns) + len(self.channel_names)))
        self.row = 0

    def record(self) -> None:
        sim, r = self.sim, self.row
        self.ticks[r] = sim.tick
        col = 0
        for e in sim.scene.entities.values():
            self.data[r, col : col + len(e.x)] = e.x
            col += len(e.x)
        for fn in sim.scene.channels.values():
            self.data[r, col] = float(fn(sim))
            col += 1
        self.row += 1

    def write(self, path: Path, metadata: dict[str, object]) -> None:
        n = self.row
        columns: dict[str, pa.Array] = {
            "t": pa.array(self.ticks[:n] * self.sim.dt),
            "tick": pa.array(self.ticks[:n]),
        }
        for i, name in enumerate([*self.state_columns, *self.channel_names]):
            columns[name] = pa.array(self.data[:n, i])
        meta = {b"simview": json.dumps(metadata, sort_keys=True).encode()}
        table = pa.table(columns).replace_schema_metadata(meta)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path)
