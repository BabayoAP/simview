"""`sv.run(scene, duration)` and the `Run` handle (SE-05 Python API)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import simview
from simview.core.logger import Logger
from simview.core.scene import Scene
from simview.core.scheduler import Sim, tick_count


class Run:
    """A finished run: its Parquet log plus timing."""

    def __init__(self, path: Path, ticks: int, wall_s: float, duration: float) -> None:
        self.path = path
        self.ticks = ticks
        self.wall_s = wall_s
        self.duration = duration

    @property
    def rtf(self) -> float:
        """Real-time factor: simulated seconds per wall-clock second."""
        return self.duration / self.wall_s if self.wall_s > 0 else float("inf")

    def table(self) -> pa.Table:
        return pq.read_table(self.path)

    def __getitem__(self, column: str) -> np.ndarray:
        return self.table().column(column).to_numpy()

    @property
    def columns(self) -> list[str]:
        return pq.read_schema(self.path).names

    def to_pandas(self) -> Any:  # noqa: ANN401 - pandas is optional, not a dependency
        """All logged signals as a DataFrame (requires pandas to be installed)."""
        return self.table().to_pandas()


def default_log_path(seed: int) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path("runs") / f"{stamp}-seed{seed}.parquet"
    i = 1
    while path.exists():
        path = Path("runs") / f"{stamp}-seed{seed}-{i}.parquet"
        i += 1
    return path


def run(
    scene: Scene,
    duration: float,
    *,
    headless: bool = True,
    out: str | Path | None = None,
) -> Run:
    """Simulate `scene` for `duration` seconds and log every tick to Parquet."""
    if not headless:
        raise NotImplementedError("live runs need the viewport (M4); use headless=True")
    n = tick_count(duration, scene.dt)
    sim = Sim(scene)
    log = Logger(sim, n + 1)
    start = time.perf_counter()
    log.record()
    for _ in range(n):
        sim.step()
        log.record()
    wall = time.perf_counter() - start
    path = Path(out) if out is not None else default_log_path(scene.seed)
    log.write(
        path,
        {"dt": scene.dt, "seed": scene.seed, "duration": duration, "version": simview.__version__},
    )
    return Run(path, n, wall, duration)
