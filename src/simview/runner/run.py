"""`sv.run(scene, duration)` and the `Run` handle (SE-05 Python API)."""

from __future__ import annotations

import time
from datetime import datetime
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

    def workspace(self) -> dict[str, np.ndarray]:
        """To Workspace blocks' variables (BD-02): a record array per variable with `t` and
        `value` (or `value[0]`, `value[1]`, ... for vectors)."""
        import json

        meta = json.loads((pq.read_schema(self.path).metadata or {}).get(b"simview", b"{}"))
        out: dict[str, np.ndarray] = {}
        for var, signals in (meta.get("to_workspace") or {}).items():
            names = ["value"] if len(signals) == 1 else [f"value[{k}]" for k in range(len(signals))]
            rec = np.empty(len(self["t"]), dtype=[("t", float)] + [(n, float) for n in names])
            rec["t"] = self["t"]
            for n, sig in zip(names, signals, strict=True):
                rec[n] = self[sig]
            out[var] = rec
        return out

    def to_pandas(self) -> Any:  # noqa: ANN401 - pandas is optional, not a dependency
        """All logged signals as a DataFrame (requires pandas to be installed)."""
        return self.table().to_pandas()


def signal_units(scene: Scene) -> dict[str, str]:
    """Units of every logged signal that has one (plot and report labels, DS-09)."""
    units = {
        f"{e.name}.{s}": u for e in scene.entities.values() for s, u in e.state_units.items() if u
    }
    units.update({k: u for k, u in scene.channel_units.items() if u})
    return units


def run_metadata(
    scene: Scene, duration: float, source: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The run's metadata stored in its Parquet log. Only what the run itself determines, so
    the same seed gives a byte-identical file (NF-06); context goes in `write_context`."""
    return {
        "dt": scene.dt,
        "seed": scene.seed,
        "duration": duration,
        "version": simview.__version__,
        "source": source,
        "params": scene.params.to_json() if params is None else params,  # values at the start
        "units": signal_units(scene),
        "to_workspace": {k: v for d in scene.diagrams.values() for k, v in d.to_workspace.items()},
    }


def write_context(
    path: Path, scene: Scene | None = None, *, scene_file: str | None = None, **extra: Any
) -> Path:
    """The run's context for the catalog (RI-01): when it ran and which scene file it came
    from, in `<run>.run.json` next to the log (D-056)."""
    import json

    ctx: dict[str, Any] = {"date": datetime.now().isoformat(timespec="seconds")}
    if scene is not None and scene.file is not None:
        ctx["scene"] = str(scene.file)
    if scene_file is not None:
        ctx["scene"] = scene_file
    ctx.update(extra)
    side = context_path(path)
    side.write_text(json.dumps(ctx, indent=2) + "\n", encoding="utf-8")
    return side


def context_path(path: Path) -> Path:
    return path.with_suffix(".run.json")


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
    start_params = scene.params.to_json()  # changes during the run are `params.*` columns
    start = time.perf_counter()
    log.record()
    for _ in range(n):
        sim.step()
        log.record()
    wall = time.perf_counter() - start
    path = Path(out) if out is not None else default_log_path(scene.seed)
    log.write(path, run_metadata(scene, duration, source="sim", params=start_params))
    write_context(path, scene)
    return Run(path, n, wall, duration)
