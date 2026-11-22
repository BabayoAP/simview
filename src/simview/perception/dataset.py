"""Recorded camera datasets (VW-03, D-128): read, replay, and write one folder format.

    <dataset>/
      cameras.json
      <camera>/rgb/000000.png            8-bit RGB
      <camera>/depth/000000.npy          z-depth in metres (float), or
      <camera>/depth/000000.png          16-bit gray, z-depth in millimetres (0 = no depth)

`cameras.json`:

    {"format": "simview-dataset", "version": 1,
     "cameras": [{"name": "ego.front_main", "width": 160, "height": 120,
                  "K": [[fx, 0, cx], [0, fy, cy], [0, 0, 1]],
                  "frames": [{"t": 0.0, "seq": 0, "pose": [[...4x4...]],
                              "rgb": "ego.front_main/rgb/000000.png",
                              "depth": "ego.front_main/depth/000000.npy",
                              "ego": [[...4x4...]]}]}]}

K uses the OpenCV convention (pixel centres at integer coordinates); `pose` is world-from-camera
of the optical frame (x right, y down, z forward), metres; `t` is seconds. Required: name, width,
height, K, and per frame t, pose, rgb. Optional: seq (defaults to the frame's index), depth, ego.
Paths are relative to the folder.
"""

from __future__ import annotations

import json
import struct
import time
import weakref
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from simview.perception.png import read_png, write_png
from simview.perception.stream import Frame, Stream

FORMAT = "simview-dataset"
VERSION = 1
DepthFormat = Literal["npy", "png16"]


class DatasetError(ValueError):
    """A dataset folder or its cameras.json is missing something or malformed."""


@dataclass
class FrameInfo:
    t: float
    seq: int
    pose: np.ndarray
    rgb: str
    depth: str | None
    ego: np.ndarray | None


@dataclass
class CameraInfo:
    name: str
    width: int
    height: int
    K: np.ndarray  # noqa: N815
    frames: list[FrameInfo] = field(default_factory=list)


def _matrix(value: Any, shape: tuple[int, int], where: str) -> np.ndarray:  # noqa: ANN401
    try:
        m = np.array(value, dtype=np.float64)
    except (TypeError, ValueError):
        raise DatasetError(f"{where} must be a {shape[0]}x{shape[1]} matrix of numbers") from None
    if m.shape != shape or not np.all(np.isfinite(m)):
        raise DatasetError(f"{where} must be a finite {shape[0]}x{shape[1]} matrix, got {m.shape}")
    return m


def _is_int(value: Any) -> bool:  # noqa: ANN401
    return isinstance(value, int) and not isinstance(value, bool)


def _read_image(path: Path, rel: str) -> np.ndarray:
    """read_png, with a damaged or unsupported file reported as a DatasetError."""
    try:
        return read_png(path)
    except (OSError, ValueError, zlib.error, struct.error) as exc:
        raise DatasetError(f"{rel}: can't read the PNG ({exc})") from None


def _pose(value: Any, where: str) -> np.ndarray:  # noqa: ANN401
    m = _matrix(value, (4, 4), where)
    r = m[:3, :3]
    if not np.allclose(r.T @ r, np.eye(3), atol=1e-4) or not np.allclose(m[3], [0, 0, 0, 1]):
        raise DatasetError(
            f"{where} must be a rigid transform (orthonormal rotation, last row 0 0 0 1)"
        )
    return m


class Dataset:
    """A recorded dataset folder, validated on open. `cameras` lists `CameraInfo`;
    `frames()` yields every `Frame` in time order (ties in camera order)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        meta_path = self.path / "cameras.json"
        if not meta_path.is_file():
            raise DatasetError(f"{self.path}: no cameras.json (not a dataset folder)")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DatasetError(f"{meta_path}: invalid JSON ({exc})") from None
        if not isinstance(meta, dict) or not isinstance(meta.get("cameras"), list):
            raise DatasetError(f"{meta_path}: needs a 'cameras' list")
        if meta.get("format", FORMAT) != FORMAT or meta.get("version", VERSION) != VERSION:
            raise DatasetError(
                f"{meta_path}: format {meta.get('format')!r} version {meta.get('version')!r} "
                f"is not supported (this reads {FORMAT!r} version {VERSION})"
            )
        if not meta["cameras"]:
            raise DatasetError(f"{meta_path}: 'cameras' is empty")
        self.cameras = [self._camera(c, i) for i, c in enumerate(meta["cameras"])]
        names = [c.name for c in self.cameras]
        if len(set(names)) != len(names):
            raise DatasetError(f"{meta_path}: camera names must be unique, got {names}")
        self.streams = {c.name: Stream(c.name) for c in self.cameras}

    def _camera(self, c: Any, i: int) -> CameraInfo:  # noqa: ANN401
        where = f"cameras.json: cameras[{i}]"
        if not isinstance(c, dict):
            raise DatasetError(f"{where} must be an object")
        for key in ("name", "width", "height", "K", "frames"):
            if key not in c:
                raise DatasetError(f"{where} is missing required field {key!r}")
        name = c["name"]
        if not isinstance(name, str) or not name:
            raise DatasetError(f"{where}.name must be a non-empty string")
        where = f"cameras.json: camera {name!r}"
        w, h = c["width"], c["height"]
        if not (_is_int(w) and _is_int(h) and w > 0 and h > 0):
            raise DatasetError(f"{where}: width and height must be positive integers")
        k = _matrix(c["K"], (3, 3), f"{where}.K")
        if k[0, 0] <= 0 or k[1, 1] <= 0 or not np.allclose(k[2], [0, 0, 1]):
            raise DatasetError(f"{where}.K must have positive fx, fy and last row 0 0 1")
        if not isinstance(c["frames"], list):
            raise DatasetError(f"{where}.frames must be a list")
        cam = CameraInfo(name, w, h, k)
        last = -np.inf
        for j, f in enumerate(c["frames"]):
            fw = f"{where}.frames[{j}]"
            if not isinstance(f, dict):
                raise DatasetError(f"{fw} must be an object")
            for key in ("t", "pose", "rgb"):
                if key not in f:
                    raise DatasetError(f"{fw} is missing required field {key!r}")
            t = f["t"]
            if isinstance(t, bool) or not isinstance(t, (int, float)) or not np.isfinite(t):
                raise DatasetError(f"{fw}.t must be a number (seconds)")
            seq = f.get("seq", j)
            if not _is_int(seq):
                raise DatasetError(f"{fw}.seq must be an integer")
            if t < last:
                raise DatasetError(f"{fw}.t goes back in time ({t} < {last})")
            last = float(t)
            for key in ("rgb", "depth"):
                rel = f.get(key)
                if rel is None and key == "depth":
                    continue
                if not isinstance(rel, str) or not (self.path / rel).is_file():
                    raise DatasetError(f"{fw}.{key}: file {rel!r} not found in {self.path}")
                if key == "depth" and Path(rel).suffix.lower() not in (".png", ".npy"):
                    raise DatasetError(f"{fw}.depth must be a .png (mm) or .npy (m) file")
            ego = f.get("ego")
            cam.frames.append(
                FrameInfo(
                    t=float(t),
                    seq=int(seq),
                    pose=_pose(f["pose"], f"{fw}.pose"),
                    rgb=f["rgb"],
                    depth=f.get("depth"),
                    ego=None if ego is None else _pose(ego, f"{fw}.ego"),
                )
            )
        return cam

    def __len__(self) -> int:
        return sum(len(c.frames) for c in self.cameras)

    @property
    def duration(self) -> float:
        ts = [f.t for c in self.cameras for f in c.frames]
        return (max(ts) - min(ts)) if ts else 0.0

    def load(self, cam: CameraInfo, info: FrameInfo) -> Frame:
        """Read one frame's images (checks their size against the camera's)."""
        rgb = _read_image(self.path / info.rgb, info.rgb)
        if rgb.ndim != 3 or rgb.dtype != np.uint8:
            raise DatasetError(f"{info.rgb}: RGB images must be 8-bit color")
        if rgb.shape[:2] != (cam.height, cam.width):
            raise DatasetError(
                f"{info.rgb}: image is {rgb.shape[1]}x{rgb.shape[0]}, camera {cam.name!r} "
                f"says {cam.width}x{cam.height}"
            )
        depth = None
        if info.depth is not None:
            p = self.path / info.depth
            if p.suffix.lower() == ".npy":
                try:
                    raw = np.load(p, allow_pickle=False)
                except (OSError, ValueError) as exc:
                    msg = f"{info.depth}: can't read the depth array ({exc})"
                    raise DatasetError(msg) from None
                if raw.dtype.kind not in "fiu":
                    raise DatasetError(f"{info.depth}: depth must be real numbers, got {raw.dtype}")
                depth = raw.astype(np.float32)
            else:
                mm = _read_image(p, info.depth)
                if mm.ndim != 2 or mm.dtype != np.uint16:
                    raise DatasetError(f"{info.depth}: depth PNGs must be 16-bit grayscale (mm)")
                depth = np.where(mm == 0, np.inf, mm.astype(np.float32) / 1000.0).astype(np.float32)
            if depth.shape != (cam.height, cam.width):
                raise DatasetError(
                    f"{info.depth}: depth is {depth.shape}, expected {(cam.height, cam.width)}"
                )
        return Frame(
            info.t,
            info.seq,
            cam.name,
            cam.K.copy(),
            info.pose.copy(),
            rgb,
            depth,
            None if info.ego is None else info.ego.copy(),
        )

    def frames(self) -> Iterator[Frame]:
        """Every frame in time order; frames with equal times in camera order."""
        order = sorted(
            ((f.t, ci, fi) for ci, c in enumerate(self.cameras) for fi, f in enumerate(c.frames))
        )
        for _, ci, fi in order:
            cam = self.cameras[ci]
            yield self.load(cam, cam.frames[fi])

    def replay(self, speed: float | None = None) -> Iterator[Frame]:
        """Yield frames in time order and push each to `streams[camera]`. `speed` 1.0 replays
        at the recorded rate, 2.0 twice as fast; None as fast as possible."""
        if speed is not None and speed <= 0:
            raise ValueError("replay speed must be positive (or None for as fast as possible)")
        for s in self.streams.values():
            s.reset()
        start_wall = time.perf_counter()
        t0: float | None = None
        for f in self.frames():
            if speed is not None:
                t0 = f.t if t0 is None else t0
                wait = (f.t - t0) / speed - (time.perf_counter() - start_wall)
                if wait > 0:
                    time.sleep(wait)
            self.streams[f.source].push(f, f.t)
            yield f


class DatasetWriter:
    """Writes frames to a dataset folder. Images are written as frames arrive; cameras.json is
    rewritten by `flush()` (and `close()`), so the folder is a valid dataset after each flush.
    `depth="npy"` keeps the float32 depth exactly; `"png16"` stores millimetres (lossy, compact)."""

    def __init__(self, path: str | Path, depth: DepthFormat = "npy") -> None:
        if depth not in ("npy", "png16"):
            raise ValueError("depth is 'npy' (metres) or 'png16' (millimetres)")
        self.path = Path(path)
        self.depth = depth
        self.path.mkdir(parents=True, exist_ok=True)
        self._cams: dict[str, dict[str, Any]] = {}
        self._frames: dict[str, list[str]] = {}  # pre-serialized frame entries per camera
        self._last_t: dict[str, float] = {}

    def add(self, frame: Frame) -> None:
        name = frame.source
        if name not in self._cams:
            if not name or "/" in name or "\\" in name or name in (".", ".."):
                raise ValueError(f"camera name {name!r} can't be a folder name")
            self._cams[name] = {
                "name": name,
                "width": frame.width,
                "height": frame.height,
                "K": np.asarray(frame.K, dtype=np.float64).tolist(),
            }
            self._frames[name] = []
            self._last_t[name] = -np.inf
            (self.path / name / "rgb").mkdir(parents=True, exist_ok=True)
            (self.path / name / "depth").mkdir(parents=True, exist_ok=True)
        # What Dataset() checks on open, refused here so the writer never makes an invalid folder
        head = self._cams[name]
        size = (head["width"], head["height"])
        if (frame.width, frame.height) != size:
            raise ValueError(
                f"{name}: frame is {frame.width}x{frame.height}, earlier frames were "
                f"{size[0]}x{size[1]}"
            )
        if frame.depth is not None and np.shape(frame.depth) != (size[1], size[0]):
            shape = np.shape(frame.depth)
            raise ValueError(f"{name}: depth is {shape}, rgb is {size[1]}x{size[0]}")
        if not (np.isfinite(frame.t) and frame.t >= self._last_t[name]):
            raise ValueError(
                f"{name}: frame time {frame.t} isn't finite or goes back from {self._last_t[name]}"
            )
        self._last_t[name] = float(frame.t)
        i = len(self._frames[name])
        rgb = f"{name}/rgb/{i:06d}.png"
        write_png(self.path / rgb, np.asarray(frame.rgb, dtype=np.uint8))
        entry: dict[str, Any] = {
            "t": float(frame.t),
            "seq": int(frame.seq),
            "pose": np.asarray(frame.pose, dtype=np.float64).tolist(),
            "rgb": rgb,
        }
        if frame.depth is not None:
            d = np.asarray(frame.depth, dtype=np.float32)
            if self.depth == "npy":
                rel = f"{name}/depth/{i:06d}.npy"
                np.save(self.path / rel, d, allow_pickle=False)
            else:
                rel = f"{name}/depth/{i:06d}.png"
                ok = np.isfinite(d) & (d > 0)
                mm = np.where(ok, np.clip(np.round(d * 1000.0), 1, 65535), 0).astype(np.uint16)
                write_png(self.path / rel, mm)
            entry["depth"] = rel
        if frame.ego is not None:
            entry["ego"] = np.asarray(frame.ego, dtype=np.float64).tolist()
        self._frames[name].append(json.dumps(entry))

    def flush(self) -> None:
        cams = []
        for name, head in self._cams.items():
            text = json.dumps(head)[:-1] + ', "frames": [' + ", ".join(self._frames[name]) + "]}"
            cams.append(text)
        body = (
            f'{{"format": "{FORMAT}", "version": {VERSION}, "cameras": [\n'
            + ",\n".join(cams)
            + "\n]}\n"
        )
        tmp = self.path / "cameras.json.tmp"
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(self.path / "cameras.json")

    def close(self) -> None:
        self.flush()

    def __enter__(self) -> DatasetWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def write_dataset(path: str | Path, frames: Iterable[Frame], depth: DepthFormat = "npy") -> Dataset:
    """Write frames (e.g. a list collected from streams) as a dataset; returns it opened."""
    with DatasetWriter(path, depth) as w:
        for f in frames:
            w.add(f)
    return Dataset(path)


class Record:
    """Pipeline stage that exports a run's camera streams as a dataset: it writes each step's
    frames' images to `path` as they arrive and passes the frames on unchanged. The index
    (cameras.json) is written when the run ends (`close()`), every `flush_every` steps (None =
    only at the end), and when the stage is reset or garbage-collected, so a long run doesn't
    rewrite a growing file every step (D-132)."""

    output = "record"

    def __init__(
        self, path: str | Path, depth: DepthFormat = "npy", *, flush_every: int | None = 100
    ) -> None:
        if flush_every is not None and flush_every < 1:
            raise ValueError("flush_every must be a positive number of steps (or None)")
        self.path = Path(path)
        self.depth: DepthFormat = depth
        self.flush_every = flush_every
        self.writer: DatasetWriter | None = None
        self._steps = 0
        self._finalizer: weakref.finalize | None = None

    def reset(self) -> None:
        self.close()
        self.writer = DatasetWriter(self.path, self.depth)
        self._steps = 0
        # an unclosed run (e.g. a live session that is dropped) still leaves a valid folder
        self._finalizer = weakref.finalize(self, _flush_writer, self.writer)

    def close(self) -> None:
        """Write the dataset index (cameras.json); called when the run ends."""
        if self._finalizer is not None:
            self._finalizer()  # flushes once and detaches
            self._finalizer = None

    def __call__(self, frames: list[Frame]) -> list[Frame]:
        if self.writer is None:
            self.reset()
        assert self.writer is not None
        for f in frames:
            self.writer.add(f)
        self._steps += 1
        if self.flush_every is not None and self._steps % self.flush_every == 0:
            self.writer.flush()
        return frames


def _flush_writer(writer: DatasetWriter) -> None:
    writer.flush()
