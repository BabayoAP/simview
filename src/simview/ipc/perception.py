"""Perception streams from the sim process to the UI (VW-08, VW-09, PRD §8.5, D-134).

Sim side, `PerceptionOut`: on each state publish, every perception output with a new frame (a
pipeline's occupied voxel centres and BEV image, each rig camera's image as a thumbnail) is
copied into that stream's shared-memory `FrameSlot`, and one FRAMES event names the streams that
changed with their sequence numbers. A UI that falls behind reads only the newest frame of each.
The rows a pipeline's `PerceptionLog` logs (snapshots every `snapshot_every` s, camera frames
every `camera_every` s) are also sent, as SNAPSHOTS events: they are the live session's
scrubbable history, and the app writes them beside the run log when it saves the session.

UI side, `PerceptionIn`: keeps the slots open by name and turns FRAMES events into the newest
`LiveFrame` per stream. Nothing here imports Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from simview.ipc import protocol as proto
from simview.ipc.shm import FrameSlot

THUMB_MAX_WIDTH = 320  # px: camera images wider than this are decimated before publishing
SLOT_HEADROOM = 1.5  # a slot is created this much bigger than the frame that needed it
MIN_SLOT = 4096  # bytes


def thumbnail(rgb: np.ndarray, max_width: int = THUMB_MAX_WIDTH) -> np.ndarray:
    """A camera image decimated by an integer stride to at most `max_width` px wide."""
    step = max(1, math.ceil(rgb.shape[1] / max_width))
    return np.ascontiguousarray(rgb[::step, ::step, :3], dtype=np.uint8)


class PerceptionOut:
    """Publishes a running `Sim`'s perception outputs (sim process)."""

    def __init__(self, sim: Any) -> None:  # noqa: ANN401 - a core Sim
        from simview.perception.rig import CameraRig

        self.pipelines = [p for p, _ in sim.pipelines if hasattr(p, "log")]
        self.cameras: dict[str, Any] = {}
        for s, _ in sim.sensors:
            if isinstance(s, CameraRig):
                self.cameras.update(s.streams)
        self.slots: dict[str, FrameSlot] = {}
        self.seq: dict[str, int] = {}
        self._stamps: dict[str, Any] = {}
        self._sent: dict[str, tuple[int, int]] = {p.name: (0, 0) for p in self.pipelines}

    @property
    def active(self) -> bool:
        return bool(self.pipelines or self.cameras)

    def _put(self, key: str, kind: str, arr: np.ndarray, meta: tuple[float, ...]) -> tuple:
        slot = self.slots.get(key)
        if slot is None or not slot.fits(arr):
            if slot is not None:
                slot.close(unlink=True)
            slot = FrameSlot(max(MIN_SLOT, int(arr.nbytes * SLOT_HEADROOM)), create=True)
            self.slots[key] = slot
        seq = self.seq.get(key, -1) + 1
        self.seq[key] = seq
        slot.write(seq, arr, meta)
        return (key, kind, slot.name, seq)

    def _changed(self, key: str, stamp: Any) -> bool:  # noqa: ANN401
        if self._stamps.get(key) == stamp:
            return False
        self._stamps[key] = stamp
        return True

    def events(self) -> list[dict[str, Any]]:
        """Write the new frames into their slots; the events to send (maybe none)."""
        from simview.perception.runlog import ego_xyyaw

        frames: list[tuple] = []
        out: list[dict[str, Any]] = []
        for p in self.pipelines:
            log = p.log
            grid = log.grid()
            key = f"{p.name}.{proto.VOXELS}"
            if grid is not None and self._changed(key, (id(grid), grid.version, grid.t)):
                centers = np.asarray(grid.occupied_centers(), dtype=np.float32).reshape(-1, 3)
                frames.append(self._put(key, proto.VOXELS, centers, (grid.t, grid.res)))
            bev = log.bev()
            key = f"{p.name}.{proto.BEV}"
            if bev is not None and self._changed(key, (id(bev), bev.t)):
                ego = (1.0, *ego_xyyaw(bev.ego)) if bev.ego is not None else (0.0, 0.0, 0.0, 0.0)
                meta = (bev.t, float(bev.origin[0]), float(bev.origin[1]), bev.res, *ego)
                gray = np.ascontiguousarray(bev.image[:, :, 0])
                frames.append(self._put(key, proto.BEV, gray, meta))
            n_snap, n_cam = self._sent[p.name]
            if len(log.snapshots) > n_snap or len(log.frames) > n_cam:
                out.append(
                    {
                        "event": proto.SNAPSHOTS,
                        "pipeline": p.name,
                        "snapshots": log.snapshots[n_snap:],
                        "frames": log.frames[n_cam:],
                    }
                )
                self._sent[p.name] = (len(log.snapshots), len(log.frames))
        for name, stream in self.cameras.items():
            if stream.seq < 0 or not self._changed(name, stream.seq):
                continue
            frame = stream.latest()
            frames.append(self._put(name, proto.CAMERA, thumbnail(frame.rgb), (float(frame.t),)))
        if frames:
            out.insert(0, {"event": proto.FRAMES, "frames": frames})
        return out

    def close(self) -> None:
        for slot in self.slots.values():
            slot.close(unlink=True)
        self.slots.clear()


@dataclass
class LiveFrame:
    """The newest frame of one perception stream, as the UI reads it."""

    stream: str
    kind: str  # proto.VOXELS, BEV or CAMERA
    seq: int
    t: float
    data: np.ndarray  # voxels: (N, 3) float32 centres; bev: (ny, nx) uint8; camera: (h, w, 3)
    res: float = 0.0  # voxel size or BEV cell size (m)
    origin: np.ndarray | None = None  # BEV lower corner (x, y)
    ego: np.ndarray | None = None  # BEV: (x, y, yaw) of the ego, if known


class PerceptionIn:
    """The UI's view of the sim's perception slots."""

    def __init__(self) -> None:
        self.slots: dict[str, FrameSlot] = {}  # shm name -> open slot
        self.pending: dict[str, tuple[str, str]] = {}  # stream -> (kind, shm name)
        self.latest: dict[str, LiveFrame] = {}
        self.names: dict[str, str] = {}  # stream -> shm name of its slot

    def on_event(self, ev: dict[str, Any]) -> None:
        """Note a FRAMES event (cheap: the slot is read once per UI frame in `read()`)."""
        for stream, kind, shm, _seq in ev["frames"]:
            self.pending[stream] = (kind, shm)

    def read(self) -> list[str]:
        """Read the newest frame of every stream announced since the last call; returns the
        streams that got a new frame."""
        got: list[str] = []
        for stream, (kind, shm) in self.pending.items():
            slot = self.slots.get(shm)
            if slot is None:
                old = self.names.get(stream)
                if old is not None and old in self.slots:  # the stream's slot grew
                    self.slots.pop(old).close()
                try:
                    slot = FrameSlot(name=shm)
                except FileNotFoundError:  # replaced by a bigger slot already
                    continue
                self.slots[shm] = slot
                self.names[stream] = shm
            f = slot.read()
            if f is None:
                continue
            m = f.meta
            frame = LiveFrame(stream, kind, f.seq, float(m[0]), f.data)
            if kind == proto.VOXELS:
                frame.res = float(m[1])
            elif kind == proto.BEV:
                frame.origin, frame.res = m[1:3].copy(), float(m[3])
                frame.ego = m[5:8].copy() if m[4] else None
            self.latest[stream] = frame
            got.append(stream)
        self.pending.clear()
        return got

    def clear(self) -> None:
        """Forget every frame and close the slots (the scene reloaded)."""
        for slot in self.slots.values():
            slot.close()
        self.slots.clear()
        self.pending.clear()
        self.latest.clear()
        self.names.clear()
