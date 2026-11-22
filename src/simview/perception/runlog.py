"""Logging and replay of perceived worlds (VW-09, D-131).

A pipeline with an `OccupancyGrid` stage logs, with the run:

- scalar signals in the run's Parquet log (so plots and RI scenarios can use them):
  `<entity>.perception.min_obstacle_dist` (m, horizontal, from the ego position to the nearest
  occupied voxel centre; NaN while nothing is seen), `<entity>.perception.occupied_voxels`, and
  optionally `<entity>.perception.iou` against ground truth;
- snapshots every `snapshot_every` s: the occupied voxels (sparse indices) and the BEV image,
  in `<run>.perception/<pipeline>.parquet` beside the log;
- camera frames every `camera_every` s (off by default) in
  `<run>.perception/<pipeline>.cameras.parquet`.

Both side files are plain Parquet tables (readable with pyarrow alone) written once at the end
of the run, deterministically, so repeated runs give byte-identical files (NF-06). Read them back
with `load_snapshots(run)`, which gives time-indexed access for timeline scrubbing:

    snaps = sv.perception.load_snapshots("runs/x.parquet")
    s = snaps.at(3.2)          # the newest snapshot at or before t = 3.2 s (or None)
    s.centers, s.bev           # (N, 3) occupied voxel centres, (ny, nx, 3) uint8 BEV image
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from simview.perception.bev import Bev
from simview.perception.occupancy import OccupancyGrid
from simview.perception.stream import Frame

if TYPE_CHECKING:
    from os import PathLike

    from simview.core.scheduler import Sim
    from simview.perception.pipeline import Pipeline

SUFFIX = ".perception"
IOU_BAND = (0.2, 2.5)  # z range (m) scored by the iou signal (the default BEV band)
IOU_EVERY = 0.5  # s: the iou signal is recomputed at most this often (it reads every geom)

SNAPSHOT_SCHEMA = pa.schema(
    [
        ("t", pa.float64()),
        ("version", pa.int64()),
        ("res", pa.float64()),
        ("origin", pa.list_(pa.float64(), 3)),
        ("shape", pa.list_(pa.int32(), 3)),
        ("voxels", pa.list_(pa.uint16())),  # occupied (i, j, k), flattened
        ("bev_origin", pa.list_(pa.float64(), 2)),
        ("bev_res", pa.float64()),
        ("bev_shape", pa.list_(pa.int32(), 2)),  # (ny, nx) of the gray image
        ("bev", pa.binary()),  # gray uint8 image, row 0 = largest y (D-127)
        ("ego", pa.list_(pa.float64(), 3)),  # x, y, yaw of the grid's ego pose (D-134)
    ]
)
CAMERA_SCHEMA = pa.schema(
    [
        ("t", pa.float64()),
        ("camera", pa.string()),
        ("width", pa.int32()),
        ("height", pa.int32()),
        ("rgb", pa.binary()),  # uint8 (height, width, 3), row-major
    ]
)


def perception_dir(run: str | PathLike[str] | Any) -> Path:  # noqa: ANN401 - a path or a Run
    """The folder of a run's perception side files: `<run>.perception/` beside the log."""
    path = Path(getattr(run, "path", run))
    return path.with_suffix(SUFFIX)


# -- recording, in the sim process ------------------------------------------------------------
class PerceptionLog:
    """What one pipeline logs. Created by `Pipeline`; `attach(scene)` (from
    `scene.add_pipeline`) adds the scalar signals, `capture()` runs after each pipeline step."""

    def __init__(
        self,
        pipeline: Pipeline,
        *,
        entity: str | None,
        signals: bool,
        iou_radius: float | None,
        snapshot_every: float | None,
        camera_every: float | None,
    ) -> None:
        for name, v in (("snapshot_every", snapshot_every), ("camera_every", camera_every)):
            if v is not None and v <= 0:
                raise ValueError(f"{name} must be positive (or None for off)")
        self.pipeline = pipeline
        self.entity = entity
        self.signals = signals
        self.iou_radius = None if iou_radius is None else float(iou_radius)
        self.snapshot_every = snapshot_every
        self.camera_every = camera_every
        self.reset()

    def reset(self) -> None:
        self.snapshots: list[dict[str, Any]] = []
        self.frames: list[dict[str, Any]] = []
        self._next_snap = 0.0
        self._next_cam = 0.0
        self._cache: dict[str, tuple[Any, float]] = {}
        self._iou_t = -math.inf

    # -- streams this pipeline produces ------------------------------------------------------
    def _output(self, kind: type) -> str | None:
        for stage, name in zip(self.pipeline.stages, self.pipeline.outputs, strict=True):
            if isinstance(stage, kind):
                return name
        return None

    def grid(self) -> OccupancyGrid | None:
        name = self._output(OccupancyGrid)
        item = None if name is None else self.pipeline.outputs[name].latest()
        return item if isinstance(item, OccupancyGrid) else None

    def bev(self) -> Bev | None:
        from simview.perception.bev import BevMap

        name = self._output(BevMap)
        item = None if name is None else self.pipeline.outputs[name].latest()
        return item if isinstance(item, Bev) else None

    # -- scalar signals ----------------------------------------------------------------------
    def owner(self) -> str:
        """The entity the signals are named after: `entity`, else the input rig's entity,
        else the pipeline's name."""
        if self.entity is not None:
            return self.entity
        from simview.perception.rig import CameraRig

        inputs = self.pipeline.inputs
        for it in inputs if isinstance(inputs, (list, tuple)) else [inputs]:
            if isinstance(it, CameraRig) and it.entity is not None:
                return it.entity.name
        return self.pipeline.name

    def attach(self, scene: Any) -> None:  # noqa: ANN401 - a core Scene
        if not self.signals or self._output(OccupancyGrid) is None:
            return
        prefix = f"{self.owner()}.perception"
        chans = {
            f"{prefix}.min_obstacle_dist": (self._min_dist, "m"),
            f"{prefix}.occupied_voxels": (self._count, ""),
        }
        if self.iou_radius is not None:
            chans[f"{prefix}.iou"] = (self._iou, "")
        for name, (fn, unit) in chans.items():
            if name in scene.channels:
                raise ValueError(f"a signal named {name!r} is already logged")
            scene.channels[name] = fn
            if unit:
                scene.channel_units[name] = unit

    def _cached(self, key: str, grid: OccupancyGrid, compute: Any) -> float:  # noqa: ANN401
        stamp = (grid.version, grid.t)
        hit = self._cache.get(key)
        if hit is None or hit[0] != stamp:
            hit = (stamp, float(compute(grid)))
            self._cache[key] = hit
        return hit[1]

    def _min_dist(self, sim: Sim) -> float:
        grid = self.grid()
        if grid is None or grid.ego is None:
            return float("nan")

        def compute(g: OccupancyGrid) -> float:
            d = g.nearest_obstacle(g.ego[:2, 3])  # type: ignore[index]
            return d if math.isfinite(d) else float("nan")

        return self._cached("dist", grid, compute)

    def _count(self, sim: Sim) -> float:
        grid = self.grid()
        if grid is None:
            return 0.0
        return self._cached("count", grid, lambda g: len(g.occupied_centers()))

    def _iou(self, sim: Sim) -> float:
        grid = self.grid()
        if grid is None or grid.ego is None:
            return float("nan")
        hit = self._cache.get("iou")
        if hit is not None and sim.t < self._iou_t + IOU_EVERY - 1e-9:
            return hit[1]
        from simview.perception.evaluate import evaluate

        self._iou_t = sim.t
        acc = evaluate(
            grid, sim.scene, z_band=IOU_BAND, radius=self.iou_radius, exclude=[self.owner()]
        )
        self._cache["iou"] = ((grid.version, grid.t), float(acc.iou))
        return float(acc.iou)

    # -- snapshots ---------------------------------------------------------------------------
    def capture(self, items: list[Any], t: float) -> None:
        """After a pipeline step at sim time `t` with input `items`."""
        if self.camera_every is not None and t >= self._next_cam - 1e-9:
            frames = [f for f in items if isinstance(f, Frame)]
            for f in frames:
                rgb = np.ascontiguousarray(f.rgb, dtype=np.uint8)
                self.frames.append(
                    {
                        "t": float(f.t),
                        "camera": f.source,
                        "width": int(rgb.shape[1]),
                        "height": int(rgb.shape[0]),
                        "rgb": rgb.tobytes(),
                    }
                )
            if frames:
                self._next_cam = _advance(self._next_cam, t, self.camera_every)
        if self.snapshot_every is None or t < self._next_snap - 1e-9:
            return
        grid = self.grid()
        if grid is None:
            return
        self._next_snap = _advance(self._next_snap, t, self.snapshot_every)
        ijk = np.argwhere(grid.logodds > 0).astype(np.uint16)
        row: dict[str, Any] = {
            "t": float(t),
            "version": int(grid.version),
            "res": grid.res,
            "origin": [float(v) for v in grid.origin],
            "shape": [int(v) for v in grid.shape],
            "voxels": ijk.reshape(-1),
            "bev_origin": None,
            "bev_res": None,
            "bev_shape": None,
            "bev": None,
            "ego": None if grid.ego is None else ego_xyyaw(grid.ego),
        }
        bev = self.bev()
        if bev is not None:
            gray = np.ascontiguousarray(bev.image[:, :, 0])
            row.update(
                bev_origin=[float(v) for v in bev.origin],
                bev_res=float(bev.res),
                bev_shape=[int(v) for v in gray.shape],
                bev=gray.tobytes(),
            )
        self.snapshots.append(row)

    def write(self, run_path: str | PathLike[str]) -> list[Path]:
        """Write the side files for the run logged at `run_path`; returns the files written."""
        return write_rows(run_path, self.pipeline.name, self.snapshots, self.frames)


def ego_xyyaw(ego: np.ndarray) -> list[float]:
    """(x, y, yaw) of a 4x4 world pose."""
    e = np.asarray(ego, dtype=np.float64)
    return [float(e[0, 3]), float(e[1, 3]), float(math.atan2(e[1, 0], e[0, 0]))]


def snapshot_table(rows: list[dict[str, Any]]) -> pa.Table:
    """Snapshot rows (as `PerceptionLog.snapshots` holds them) as a table."""
    return pa.table(
        {f.name: pa.array([r.get(f.name) for r in rows], type=f.type) for f in SNAPSHOT_SCHEMA},
        schema=SNAPSHOT_SCHEMA,
    )


def camera_table(frames: list[dict[str, Any]]) -> pa.Table:
    """Camera frame rows (as `PerceptionLog.frames` holds them) as a table."""
    return pa.Table.from_pylist(frames, schema=CAMERA_SCHEMA)


def write_rows(
    run_path: str | PathLike[str],
    pipeline: str,
    snapshots: list[dict[str, Any]],
    frames: list[dict[str, Any]],
) -> list[Path]:
    """Write one pipeline's snapshot and camera rows beside the run log at `run_path` (also
    used by the app to save a live session's perception history, D-134)."""
    written: list[Path] = []
    if not snapshots and not frames:
        return written
    folder = perception_dir(run_path)
    folder.mkdir(parents=True, exist_ok=True)
    if snapshots:
        path = folder / f"{pipeline}.parquet"
        pq.write_table(snapshot_table(snapshots), path)
        written.append(path)
    if frames:
        path = folder / f"{pipeline}.cameras.parquet"
        pq.write_table(camera_table(frames), path)
        written.append(path)
    return written


def _advance(due: float, t: float, every: float) -> float:
    """The next due time after `t` on the grid due + k * every."""
    k = math.floor((t - due) / every + 1e-9) + 1
    return due + k * every


def write_snapshots(run_path: str | PathLike[str], pipelines: list[Any]) -> list[Path]:
    """Write every pipeline's perception side files beside the run log at `run_path`."""
    out: list[Path] = []
    for p in pipelines:
        log = getattr(p, "log", None)
        if isinstance(log, PerceptionLog):
            out += log.write(run_path)
    return out


# -- reading, for playback --------------------------------------------------------------------
@dataclass(frozen=True)
class Snapshot:
    """One logged perceived world. `indices` are the occupied voxels' (i, j, k); the voxel with
    index (i, j, k) has its lower corner at `origin + (i, j, k) * res` (D-126)."""

    t: float
    version: int
    res: float
    origin: np.ndarray
    shape: tuple[int, int, int]
    indices: np.ndarray  # (N, 3) int64
    bev: np.ndarray | None  # (ny, nx, 3) uint8, or None if the pipeline has no BEV stage
    bev_origin: np.ndarray | None
    bev_res: float | None
    ego: np.ndarray | None = None  # (x, y, yaw) of the ego pose; None in older logs (D-134)

    @property
    def centers(self) -> np.ndarray:
        """World centres (N, 3) of the occupied voxels."""
        return self.origin + (self.indices + 0.5) * self.res

    def occupancy(self) -> np.ndarray:
        """Boolean (nx, ny, nz) occupancy, rebuilt from the sparse indices."""
        out = np.zeros(self.shape, dtype=bool)
        i = self.indices
        out[i[:, 0], i[:, 1], i[:, 2]] = True
        return out


@dataclass(frozen=True)
class CameraFrame:
    t: float
    camera: str
    rgb: np.ndarray  # (height, width, 3) uint8


@dataclass
class Snapshots:
    """A run's logged snapshots for one pipeline, time-indexed (`at(t)`)."""

    pipeline: str
    table: pa.Table
    cameras_table: pa.Table | None = None
    times: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.times = self.table.column("t").to_numpy()
        self._cam: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        if self.cameras_table is not None:
            names = self.cameras_table.column("camera").to_pylist()
            ts = self.cameras_table.column("t").to_numpy()
            for name in dict.fromkeys(names):
                rows = np.array([i for i, n in enumerate(names) if n == name], dtype=np.int64)
                self._cam[name] = (ts[rows], rows)

    def __len__(self) -> int:
        return len(self.times)

    def index_at(self, t: float) -> int | None:
        """Index of the newest snapshot at or before `t` (None if `t` is before the first)."""
        i = int(np.searchsorted(self.times, t + 1e-9, side="right")) - 1
        return None if i < 0 else i

    def at(self, t: float) -> Snapshot | None:
        """The newest snapshot at or before `t` (None if `t` is before the first)."""
        i = self.index_at(t)
        return None if i is None else self[i]

    def __getitem__(self, i: int) -> Snapshot:
        row = self.table.slice(i, 1).to_pylist()[0]
        shape = tuple(int(v) for v in row["shape"])
        idx = np.asarray(row["voxels"], dtype=np.int64).reshape(-1, 3)
        bev = bev_origin = None
        if row["bev"] is not None:
            ny, nx = row["bev_shape"]
            gray = np.frombuffer(row["bev"], dtype=np.uint8).reshape(ny, nx)
            bev = np.repeat(gray[:, :, None], 3, axis=2)
            bev_origin = np.asarray(row["bev_origin"], dtype=np.float64)
        ego = row.get("ego")
        return Snapshot(
            t=float(row["t"]),
            version=int(row["version"]),
            res=float(row["res"]),
            origin=np.asarray(row["origin"], dtype=np.float64),
            shape=shape,  # type: ignore[arg-type]
            indices=idx,
            bev=bev,
            bev_origin=bev_origin,
            bev_res=row["bev_res"],
            ego=None if ego is None else np.asarray(ego, dtype=np.float64),
        )

    @property
    def cameras(self) -> list[str]:
        """Names of the cameras with logged frames (empty when camera logging was off)."""
        return list(self._cam)

    def camera_at(self, camera: str, t: float) -> CameraFrame | None:
        """A camera's newest logged frame at or before `t` (None if there is none)."""
        if camera not in self._cam or self.cameras_table is None:
            return None
        ts, rows = self._cam[camera]
        i = int(np.searchsorted(ts, t + 1e-9, side="right")) - 1
        if i < 0:
            return None
        row = self.cameras_table.slice(int(rows[i]), 1).to_pylist()[0]
        rgb = np.frombuffer(row["rgb"], dtype=np.uint8).reshape(row["height"], row["width"], 3)
        return CameraFrame(float(row["t"]), camera, rgb)


def snapshot_pipelines(run: str | PathLike[str] | Any) -> list[str]:  # noqa: ANN401
    """Names of the pipelines with logged snapshots for a run (sorted)."""
    folder = perception_dir(run)
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.parquet") if not p.stem.endswith(".cameras"))


def load_snapshots(
    run: str | PathLike[str] | Any,  # noqa: ANN401 - a log path or a Run
    pipeline: str | None = None,
) -> Snapshots:
    """A run's perception snapshots (`run` is its Parquet log path or a `Run`). `pipeline`
    picks one by name; None takes the only one (or the first by name)."""
    folder = perception_dir(run)
    names = snapshot_pipelines(run)
    if not names:
        raise FileNotFoundError(f"no perception snapshots in {folder}")
    name = pipeline if pipeline is not None else names[0]
    if name not in names:
        raise KeyError(f"no snapshots for pipeline {name!r}; have {names}")
    cams = folder / f"{name}.cameras.parquet"
    return Snapshots(
        name,
        pq.read_table(folder / f"{name}.parquet"),
        pq.read_table(cams) if cams.is_file() else None,
    )
