"""Monte Carlo and parameter sweeps (SE-08): run a scene file N times in parallel processes
with sampled or gridded parameters, and collect each trial's metrics into one table.

    import simview as sv

    if __name__ == "__main__":  # trials run in spawned processes
        res = sv.sweep(
            "scene.py",
            duration=60,
            params={"gust": sv.Uniform(0.5, 3.0), "gps_noise": sv.Normal(0.8, 0.2)},
            trials=50,
        )
        print(res["delivery_time"].mean())

Metrics come from the scene file (`scene.metric(name, fn)`) or are column names, whose last
logged value is taken. Each trial gets its own seed (`seed + trial`), and the parameter
samples are drawn up front from `seed`, so a sweep repeats exactly whatever the worker count.
"""

from __future__ import annotations

import itertools
import json
import os
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

META_KEY = b"simview.sweep"
RESULTS_NAME = "results.parquet"


# -- parameter distributions -----------------------------------------------------------------
@dataclass(frozen=True)
class Uniform:
    """Uniform on [lo, hi)."""

    lo: float
    hi: float

    def __post_init__(self) -> None:
        if not self.hi > self.lo:
            raise ValueError(f"Uniform needs hi > lo, got {self.lo}, {self.hi}")

    def sample(self, rng: np.random.Generator) -> float:
        return float(rng.uniform(self.lo, self.hi))


@dataclass(frozen=True)
class Normal:
    """Gaussian with this mean and standard deviation, optionally clipped to [lo, hi] (for
    quantities that can't go negative, like a noise level)."""

    mean: float
    std: float
    lo: float | None = None
    hi: float | None = None

    def __post_init__(self) -> None:
        if self.std < 0:
            raise ValueError(f"Normal needs std >= 0, got {self.std}")

    def sample(self, rng: np.random.Generator) -> float:
        v = float(rng.normal(self.mean, self.std))
        lo = -np.inf if self.lo is None else self.lo
        hi = np.inf if self.hi is None else self.hi
        return float(np.clip(v, lo, hi))


@dataclass(frozen=True)
class Choice:
    """One of these values, equally likely."""

    values: tuple[float, ...]

    def __init__(self, values: Sequence[float]) -> None:
        if not len(values):
            raise ValueError("Choice needs at least one value")
        object.__setattr__(self, "values", tuple(float(v) for v in values))

    def sample(self, rng: np.random.Generator) -> float:
        return self.values[int(rng.integers(len(self.values)))]


Distribution = Uniform | Normal | Choice


# -- trial plan ------------------------------------------------------------------------------
def plan_trials(
    params: Mapping[str, Any] | None,
    grid: Mapping[str, Sequence[float]] | None,
    trials: int,
    seed: int,
) -> list[dict[str, float]]:
    """Every trial's parameter values: each grid point (the product of `grid`'s lists) is run
    `trials` times; `params` values are constants or distributions sampled per trial."""
    if trials < 1:
        raise ValueError(f"trials must be >= 1, got {trials}")
    params, grid = dict(params or {}), dict(grid or {})
    both = sorted(set(params) & set(grid))
    if both:
        raise ValueError(f"{', '.join(both)} given in both params and grid")
    for name, values in grid.items():
        if isinstance(values, str) or not len(values):
            raise ValueError(f"grid {name!r} needs a non-empty list of values")
    rng = np.random.Generator(np.random.PCG64(seed))
    points = list(itertools.product(*grid.values())) or [()]
    plan = []
    for point in points:
        for _ in range(trials):
            row = {k: float(v) for k, v in zip(grid, point, strict=True)}
            for name, spec in params.items():
                row[name] = spec.sample(rng) if hasattr(spec, "sample") else float(spec)
            plan.append(row)
    return plan


# -- one trial (runs in a worker process) ----------------------------------------------------
@dataclass
class TrialSpec:
    index: int
    scene: str
    duration: float
    params: dict[str, float]
    seed: int
    log: str
    keep_log: bool
    metrics: list[str] | None  # None: all the scene declares
    extra: dict[str, Callable[[Any], float]]  # picklable callables from the caller


def _remove(path: Path) -> None:
    """Delete a trial file, best effort: on Windows a scanner or indexer can hold a new file
    for a moment, and a leftover log must not fail the trial."""
    for attempt in range(5):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))


def run_trial(spec: TrialSpec) -> dict[str, Any]:
    """Load, run, and measure one trial. Errors are reported in the row, not raised."""
    from simview.runner.headless import load_scene
    from simview.runner.run import context_path, run

    row: dict[str, Any] = {"trial": spec.index, "seed": spec.seed, **spec.params}
    start = time.perf_counter()
    log = Path(spec.log)
    try:
        scene = load_scene(spec.scene, params=spec.params, seed=spec.seed)
        result = run(scene, spec.duration, out=log)
        names = list(scene.metrics) if spec.metrics is None else spec.metrics
        values: dict[str, float] = {}
        for name in names:
            if name in scene.metrics:
                values[name] = float(scene.metrics[name](result))
            elif name in result.columns:
                values[name] = float(result[name][-1])
            else:
                raise KeyError(f"no metric or logged column {name!r}")
        for name, fn in spec.extra.items():
            values[name] = float(fn(result))
        row.update(values, status="ok", error="")
    except Exception as exc:  # noqa: BLE001 - one bad trial must not stop the sweep
        tb = traceback.format_exception_only(type(exc), exc)[-1].strip()
        row.update(status="error", error=tb)
    finally:
        if not spec.keep_log:
            _remove(log)
            _remove(context_path(log))
    row["wall_s"] = time.perf_counter() - start
    row["log"] = spec.log if spec.keep_log and row["status"] == "ok" else ""
    return row


# -- results ---------------------------------------------------------------------------------
class SweepResults:
    """A sweep's table: one row per trial with `trial`, `seed`, the parameters, the metrics,
    `status` ("ok" / "error"), `error`, `wall_s`, and `log` (the trial's Parquet log if kept)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.table = pq.read_table(self.path)
        meta = json.loads((self.table.schema.metadata or {}).get(META_KEY, b"{}"))
        self.params: list[str] = meta.get("params", [])
        self.metrics: list[str] = meta.get("metrics", [])
        self.scene: str = meta.get("scene", "")
        self.duration: float = meta.get("duration", 0.0)
        self.wall_s: float = meta.get("wall_s", 0.0)

    @classmethod
    def load(cls, path: str | Path) -> SweepResults:
        """Open a sweep's `results.parquet` (or the folder that holds it)."""
        p = Path(path)
        return cls(p / RESULTS_NAME if p.is_dir() else p)

    def __len__(self) -> int:
        return self.table.num_rows

    def __getitem__(self, column: str) -> np.ndarray:
        return self.table.column(column).to_numpy(zero_copy_only=False)

    @property
    def columns(self) -> list[str]:
        return list(self.table.column_names)

    @property
    def ok(self) -> np.ndarray:
        """Mask of the trials that finished without an error."""
        return self["status"] == "ok"

    def to_pandas(self) -> Any:  # noqa: ANN401 - pandas is optional, not a dependency
        return self.table.to_pandas()

    def __repr__(self) -> str:
        failed = int((~self.ok).sum())
        return (
            f"SweepResults({len(self)} trials, {failed} failed, params={self.params}, "
            f"metrics={self.metrics}, path={str(self.path)!r})"
        )


def _default_out() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path("runs") / f"sweep-{stamp}"
    i = 1
    while path.exists():
        path = Path("runs") / f"sweep-{stamp}-{i}"
        i += 1
    return path


def _write(
    rows: list[dict[str, Any]], path: Path, params: list[str], metrics: list[str], meta: dict
) -> None:
    cols: dict[str, Any] = {
        "trial": pa.array([r["trial"] for r in rows], pa.int64()),
        "seed": pa.array([r["seed"] for r in rows], pa.int64()),
    }
    for name in [*params, *metrics]:
        cols[name] = pa.array([r.get(name, np.nan) for r in rows], pa.float64())
    for name in ("status", "error", "log"):
        cols[name] = pa.array([r[name] for r in rows], pa.string())
    cols["wall_s"] = pa.array([r["wall_s"] for r in rows], pa.float64())
    table = pa.table(cols)
    meta = {**meta, "params": params, "metrics": metrics}
    table = table.replace_schema_metadata({META_KEY: json.dumps(meta).encode()})
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def sweep(
    scene: str | Path,
    duration: float,
    *,
    params: Mapping[str, Any] | None = None,
    grid: Mapping[str, Sequence[float]] | None = None,
    trials: int = 1,
    seed: int = 0,
    metrics: Sequence[str] | Mapping[str, Callable[[Any], float]] | None = None,
    workers: int | None = None,
    keep_logs: bool = False,
    out: str | Path | None = None,
    on_trial: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> SweepResults:
    """Run `scene` (a scene file) once per trial and return the results table (SE-08).

    `params`: name -> constant or distribution (`Uniform`, `Normal`, `Choice`), sampled per
    trial. `grid`: name -> list of values; every combination is run `trials` times. `metrics`:
    names of the scene's `scene.metric(...)`s or logged columns (last value), or a dict of
    name -> picklable `fn(run)`; by default every metric the scene declares. `workers`:
    processes (default: CPU count, at most the number of trials); 0 runs in this process.
    `keep_logs` keeps each trial's full Parquet log next to the results. `on_trial(done,
    total, row)` is called as each trial finishes. Results go to `out` (default
    `runs/sweep-<time>/`) as `results.parquet`."""
    path = Path(scene).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"no scene file {path}")
    if duration <= 0:
        raise ValueError(f"duration must be positive, got {duration}")
    plan = plan_trials(params, grid, trials, seed)
    names: list[str] | None
    extra: dict[str, Callable[[Any], float]] = {}
    if metrics is None:
        names = None
    elif isinstance(metrics, Mapping):
        names, extra = [], dict(metrics)
    else:
        names = list(metrics)
    out_dir = Path(out) if out is not None else _default_out()
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        TrialSpec(
            index=i,
            scene=str(path),
            duration=float(duration),
            params=values,
            seed=seed + i,
            log=str((out_dir / f"trial-{i:04d}.parquet").resolve()),
            keep_log=keep_logs,
            metrics=names,
            extra=extra,
        )
        for i, values in enumerate(plan)
    ]
    n_workers = min(os.cpu_count() or 1, len(specs)) if workers is None else int(workers)
    start = time.perf_counter()
    rows: list[dict[str, Any]] = []

    def done(row: dict[str, Any]) -> None:
        rows.append(row)
        if on_trial is not None:
            on_trial(len(rows), len(specs), row)

    if n_workers <= 0:
        for spec in specs:
            done(run_trial(spec))
    else:
        with ProcessPoolExecutor(n_workers, mp_context=get_context("spawn")) as pool:
            futures = [pool.submit(run_trial, spec) for spec in specs]
            for fut in as_completed(futures):
                done(fut.result())
    rows.sort(key=lambda r: r["trial"])
    param_names = list(dict.fromkeys(k for r in plan for k in r))
    skip = {"trial", "seed", "status", "error", "wall_s", "log", *param_names}
    metric_names = list(dict.fromkeys(k for r in rows for k in r if k not in skip))
    if names:  # keep the caller's order, even for metrics every trial failed to produce
        metric_names = list(dict.fromkeys([*names, *metric_names]))
    meta = {
        "scene": str(path),
        "duration": float(duration),
        "seed": seed,
        "trials": len(specs),
        "workers": n_workers,
        "wall_s": time.perf_counter() - start,
    }
    results_path = out_dir / RESULTS_NAME
    _write(rows, results_path, param_names, metric_names, meta)
    return SweepResults(results_path)
