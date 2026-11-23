"""Perception pipeline (VW-04, D-124): stages chained stream-in / stream-out.

The first stage gets the list of new input items of one step (all rig cameras' frames, ordered
by input stream then sequence number); each later stage gets the previous stage's output. A
stage returning None ends that step's chain. Each stage's output is pushed to the stream
`<pipeline name>.<stage output>` (built-ins: `cloud`, `occupancy`, `bev`; a plain callable uses
its `output` attribute or its `__name__`).

In a run, `scene.add_pipeline(p)` steps it inside the scheduler tick right after sensors sample,
every `1/rate` s (every tick if rate is None), and only when new input arrived. Offline,
`p.run(dataset)` groups the frames into the same steps by time (step k holds frames with
k-1 < t*rate <= k), so identical inputs give identical outputs.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING, Any

from simview.perception.runlog import PerceptionLog
from simview.perception.stream import Frame, Reader, Stream

if TYPE_CHECKING:
    from simview.core.scheduler import Sim
    from simview.perception.dataset import Dataset

Stage = Callable[[Any], Any]


def stage_output(stage: Stage) -> str:
    name = getattr(stage, "output", None) or getattr(stage, "__name__", None)
    return str(name or type(stage).__name__.lower())


class Pipeline:
    """`stages` run in order at `rate` Hz on new items of `inputs`: a `CameraRig`, a stream
    name, or a list of them (None: every camera stream in the run). `name` prefixes the output
    streams (e.g. "ego" -> "ego.occupancy").

    Logging with the run (VW-09, D-131), when a stage is an `OccupancyGrid`: `signals` adds
    `<entity>.perception.min_obstacle_dist` and `.occupied_voxels` to the run log (`entity`
    defaults to the input rig's entity, else `name`), plus `.iou` against ground truth within
    `iou_radius` m when given; `snapshot_every` (s, None = off) stores the occupied voxels and BEV
    image beside the log; `camera_every` (s, default off) stores the input camera frames."""

    def __init__(
        self,
        stages: Sequence[Stage],
        *,
        rate: float | None = None,
        inputs: Any = None,  # noqa: ANN401 - a rig, a stream name, or a list of them
        name: str = "perception",
        maxlen: int = 64,
        entity: str | None = None,
        signals: bool = True,
        iou_radius: float | None = None,
        snapshot_every: float | None = 0.5,
        camera_every: float | None = None,
    ) -> None:
        if not stages:
            raise ValueError("a pipeline needs at least one stage")
        if rate is not None and rate <= 0:
            raise ValueError("pipeline rate must be positive")
        if not name or "." in name:
            raise ValueError(f"pipeline name {name!r} must be non-empty without '.'")
        self.stages = list(stages)
        self.rate = None if rate is None else float(rate)
        self.inputs = inputs
        self.name = name
        outs = [stage_output(s) for s in self.stages]
        if len(set(outs)) != len(outs):
            raise ValueError(f"stage outputs must be unique, got {outs}; set `output` on them")
        self.outputs: dict[str, Stream] = {
            f"{name}.{o}": Stream(f"{name}.{o}", maxlen) for o in outs
        }
        self._readers: list[Reader] = []
        self.log = PerceptionLog(
            self,
            entity=entity,
            signals=signals,
            iou_radius=iou_radius,
            snapshot_every=snapshot_every,
            camera_every=camera_every,
        )

    def __getitem__(self, output: str) -> Stream:
        """An output stream by short ("occupancy") or full ("ego.occupancy") name."""
        return self.outputs[output if output in self.outputs else f"{self.name}.{output}"]

    def reset(self) -> None:
        for s in self.stages:
            reset = getattr(s, "reset", None)
            if callable(reset):
                reset()
        for st in self.outputs.values():
            st.reset()
        self.log.reset()

    def close(self) -> None:
        """Called when a run ends: stages with a `close()` (e.g. `Record`) finish their files."""
        for s in self.stages:
            close = getattr(s, "close", None)
            if callable(close):
                close()

    # -- one step ----------------------------------------------------------------------------
    def process(self, items: list[Any], t: float) -> None:
        """Run the chain once on one step's input items (no-op if there are none)."""
        if not items:
            return
        value: Any = items
        for stage, stream in zip(self.stages, self.outputs.values(), strict=True):
            value = stage(value)
            if value is None:
                return
            stream.push(value, getattr(value, "t", t))

    def latest(self) -> dict[str, Any]:
        """Each output stream's newest item."""
        return {n: s.latest() for n, s in self.outputs.items()}

    # -- in a run ----------------------------------------------------------------------------
    def input_names(self, available: Iterable[str]) -> list[str]:
        from simview.perception.rig import CameraRig

        avail = list(available)
        if self.inputs is None:
            return [n for n in avail if n not in self.outputs]
        items = self.inputs if isinstance(self.inputs, (list, tuple)) else [self.inputs]
        names: list[str] = []
        for it in items:
            if isinstance(it, CameraRig):
                names += list(it.streams)
            elif isinstance(it, Stream):
                names.append(it.name)
            else:
                names.append(str(it))
        missing = [n for n in names if n not in avail]
        if missing:
            raise ValueError(f"pipeline {self.name!r}: no stream named {missing}; have {avail}")
        return names

    def bind(self, sim: Sim, streams: dict[str, Stream]) -> None:
        """Called when a run starts: reset, subscribe to the inputs, publish the outputs.
        With `inputs=None` only the sensors' (camera) streams are inputs, not other
        pipelines' outputs (D-135)."""
        self.reset()
        available: Iterable[str] = streams
        if self.inputs is None:
            sensor_streams = {n for s, _ in sim.sensors for n in getattr(s, "streams", {})}
            available = [n for n in streams if n in sensor_streams]
        names = self.input_names(available)
        self._readers = [streams[n].reader() for n in names]
        for n, s in self.outputs.items():
            if n in streams:
                raise ValueError(f"stream name {n!r} is already used")
            streams[n] = s

    def tick(self, t: float) -> None:
        items: list[Any] = []
        for r in self._readers:
            items += r.since_last()
        if items:
            self.process(items, t)
            self.log.capture(items, t)

    # -- offline -----------------------------------------------------------------------------
    def run(self, source: Dataset | Iterable[Frame], speed: float | None = None) -> dict[str, Any]:
        """Run over a recorded dataset (or any frames) from a fresh state; returns each output
        stream's last item by full name. `speed` paces a dataset's replay (None: as fast as
        possible)."""
        from simview.perception.dataset import Dataset

        self.reset()
        if isinstance(source, Dataset):
            frames: Iterable[Frame] = source.replay(speed)
            order = {c.name: i for i, c in enumerate(source.cameras)}
        else:
            frames = source
            order = {}
        batch: list[Frame] = []
        key: float | None = None
        for f in frames:
            k = self._step_of(f.t)
            if key is not None and k != key:
                self._flush(batch, order)
                batch = []
            key = k
            batch.append(f)
        self._flush(batch, order)
        self.close()  # the run ended: e.g. a `Record` stage writes its index (D-132)
        return self.latest()

    def _step_of(self, t: float) -> float:
        if self.rate is None:
            return round(t, 9)
        return float(math.ceil(t * self.rate - 1e-6))

    def _flush(self, batch: list[Frame], order: dict[str, int]) -> None:
        if not batch:
            return
        names = order or {n: i for i, n in enumerate(dict.fromkeys(f.source for f in batch))}
        batch = sorted(batch, key=lambda f: (names.get(f.source, len(names)), f.seq))
        self.process(batch, max(f.t for f in batch))
