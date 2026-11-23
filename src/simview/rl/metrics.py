"""Training metrics (ML-03) and recorded episodes (ML-04), kept in a training folder:

    runs/train-<time>/
        metrics.jsonl          {"name", "step", "value", "wall"} per line (`log_metric`)
        episodes-<env>.jsonl   one line per finished episode of env <env> (return, length,
                               success, and the episode's log file if it was recorded)
        episodes/              recorded episodes: normal run logs, so the app replays them
        *.tfevents.*           TensorBoard event files (read too, from any subfolder)

The Training panel follows the newest `train-*` folder in the runs folder and redraws as these
files grow. Use it from a training script:

    sv.rl.training_dir("runs/train-landing")        # or let the first log_metric pick one
    venv = sv.make_vec_env("drone_landing", 8, record_every=20)   # records into the same folder
    model = PPO("MlpPolicy", venv)
    model.set_logger(sv.rl.sb3_logger())           # PPO's own stats (loss, ep_rew_mean, ...)
    sv.log_metric("my/thing", step, value)          # anything else
"""

from __future__ import annotations

import json
import os
import struct
import time
from pathlib import Path
from typing import Any

import numpy as np

RUNS_ENV = "SIMVIEW_RUNS"  # the app's runs-folder override (as in the UI)
TRAINING_ENV = "SIMVIEW_TRAINING"  # the current training folder, inherited by env processes
METRICS_NAME = "metrics.jsonl"
EPISODE_GLOB = "episodes-*.jsonl"
EPISODE_DIR = "episodes"
EPISODE_RETURN = "episode/return"  # the per-episode series the panel can replay from
EPISODE_LENGTH = "episode/length"
EPISODE_SUCCESS = "episode/success"


def _new_dir() -> Path:
    base = Path(os.environ.get(RUNS_ENV) or "runs")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = base / f"train-{stamp}"
    i = 1
    while path.exists():
        path = base / f"train-{stamp}-{i}"
        i += 1
    return path


def training_dir(path: str | Path | None = None, *, create: bool = True) -> Path | None:
    """The current training folder. With `path`, switch to it (created if needed); without,
    the folder set before (also from the `SIMVIEW_TRAINING` environment variable, which env
    worker processes inherit), or a new `runs/train-<time>/` when `create`."""
    if path is not None:
        p = Path(path).resolve()
    elif os.environ.get(TRAINING_ENV):
        p = Path(os.environ[TRAINING_ENV])
    elif create:
        p = _new_dir().resolve()
    else:
        return None
    p.mkdir(parents=True, exist_ok=True)
    os.environ[TRAINING_ENV] = str(p)
    return p


def log_metric(name: str, step: int, value: float) -> None:
    """Append one scalar to the training folder's metrics (ML-03); the Training panel plots
    `value` against `step` for each `name`."""
    folder = training_dir()
    assert folder is not None
    line = {"name": str(name), "step": int(step), "value": float(value), "wall": time.time()}
    with open(folder / METRICS_NAME, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def log_episode(folder: Path, env_index: int, record: dict[str, Any]) -> None:
    """Append a finished episode (written by the env, one file per env process)."""
    with open(folder / f"episodes-{env_index}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# -- reading -------------------------------------------------------------------------------------
class TailReader:
    """Reads the complete lines added to a file since the last call (a training run appends
    while the panel reads)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0

    def new_lines(self) -> list[dict[str, Any]]:
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read()
        except FileNotFoundError:
            return []
        end = chunk.rfind(b"\n") + 1  # leave a half-written last line for next time
        self.offset += end
        out = []
        for raw in chunk[:end].splitlines():
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
        return out


class Series:
    """Growing (step, value) arrays."""

    def __init__(self) -> None:
        self.steps: list[float] = []
        self.values: list[float] = []

    def add(self, step: float, value: float) -> None:
        self.steps.append(step)
        self.values.append(value)

    def arrays(self) -> tuple[np.ndarray, np.ndarray]:
        s, v = np.asarray(self.steps, dtype=np.float64), np.asarray(self.values, dtype=np.float64)
        order = np.argsort(s, kind="stable")
        return s[order], v[order]


class TrainingRun:
    """A training folder's metrics, episodes, and TensorBoard scalars; `refresh()` picks up
    what was appended since the last call."""

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        self.series: dict[str, Series] = {}
        self.episodes: list[dict[str, Any]] = []
        self._metrics = TailReader(self.folder / METRICS_NAME)
        self._episode_readers: dict[Path, TailReader] = {}
        self._tb_seen: dict[Path, int] = {}  # event file -> bytes already parsed

    def _add(self, name: str, step: float, value: float) -> None:
        self.series.setdefault(name, Series()).add(step, value)

    def refresh(self) -> bool:
        """Read new data; True if anything changed."""
        changed = False
        for m in self._metrics.new_lines():
            self._add(m["name"], m["step"], m["value"])
            changed = True
        for path in sorted(self.folder.glob(EPISODE_GLOB)):
            reader = self._episode_readers.setdefault(path, TailReader(path))
            for ep in reader.new_lines():
                self.episodes.append(ep)
                self._add(EPISODE_RETURN, ep["step"], ep["return"])
                self._add(EPISODE_LENGTH, ep["step"], ep["length"])
                if ep.get("success") is not None:
                    self._add(EPISODE_SUCCESS, ep["step"], float(ep["success"]))
                changed = True
        for path in sorted(self.folder.rglob("*tfevents*")):
            done = self._tb_seen.get(path, 0)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size <= done:
                continue
            scalars, used = read_tfevents(path, start=done)
            self._tb_seen[path] = done + used
            for tag, step, value in scalars:
                self._add(tag, step, value)
            changed = changed or bool(scalars)
        return changed

    def names(self) -> list[str]:
        return sorted(self.series)

    def recorded(self) -> list[dict[str, Any]]:
        """Episodes that have a log to replay."""
        return [e for e in self.episodes if e.get("log")]


def latest_training_dir(runs: str | Path) -> Path | None:
    """The newest `train-*` folder in a runs folder (the one the panel follows)."""
    base = Path(runs)
    if not base.is_dir():
        return None
    found = [p for p in base.glob("train-*") if p.is_dir()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


# -- TensorBoard event files (no TensorFlow / tensorboard needed) ---------------------------------
def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def _fields(buf: bytes) -> list[tuple[int, int, Any]]:
    """Protobuf wire format: (field number, wire type, value) for each field of a message."""
    out, i = [], 0
    while i < len(buf):
        key, i = _varint(buf, i)
        num, wire = key >> 3, key & 7
        if wire == 0:
            val, i = _varint(buf, i)
        elif wire == 1:
            val, i = buf[i : i + 8], i + 8
        elif wire == 2:
            n, i = _varint(buf, i)
            val, i = buf[i : i + n], i + n
        elif wire == 5:
            val, i = buf[i : i + 4], i + 4
        else:  # groups (3, 4) aren't used by event files
            raise ValueError(f"unsupported protobuf wire type {wire}")
        out.append((num, wire, val))
    return out


def _tensor_scalar(buf: bytes) -> float | None:
    """A TensorProto holding one number (TF2-style scalar summaries)."""
    dtype = 0
    for num, _wire, val in _fields(buf):
        if num == 1:
            dtype = val
    for num, _wire, val in _fields(buf):
        if num == 4 and val:  # tensor_content: raw little-endian
            fmt = {1: "<f", 2: "<d", 3: "<i", 9: "<q"}.get(dtype)
            if fmt and len(val) == struct.calcsize(fmt):
                return float(struct.unpack(fmt, val)[0])
        if num == 5:  # float_val (packed or not)
            return float(struct.unpack("<f", val[:4])[0])
        if num == 6:  # double_val
            return float(struct.unpack("<d", val[:8])[0])
    return None


def read_tfevents(path: str | Path, start: int = 0) -> tuple[list[tuple[str, int, float]], int]:
    """Scalar summaries `(tag, step, value)` in a TensorBoard event file, from byte `start`,
    and how many bytes of complete records were read (a writer may be mid-record)."""
    data = Path(path).read_bytes()[start:]
    out: list[tuple[str, int, float]] = []
    i = 0
    while i + 12 <= len(data):
        (length,) = struct.unpack("<Q", data[i : i + 8])
        end = i + 12 + length + 4
        if end > len(data):
            break
        event = data[i + 12 : i + 12 + length]
        i = end
        step = 0
        summary = None
        for num, _wire, val in _fields(event):
            if num == 2:
                step = val
            elif num == 5:
                summary = val
        if summary is None:
            continue
        for num, _wire, value_msg in _fields(summary):
            if num != 1:
                continue
            tag, value = "", None
            for vn, _vw, vv in _fields(value_msg):
                if vn == 1:
                    tag = vv.decode("utf-8", "replace")
                elif vn == 2:
                    value = float(struct.unpack("<f", vv)[0])
                elif vn == 8 and value is None:
                    value = _tensor_scalar(vv)
            if tag and value is not None:
                out.append((tag, int(step), value))
    return out, i


# -- Stable-Baselines3 bridge ----------------------------------------------------------------------
def sb3_logger(folder: str | Path | None = None, *, stdout: bool = True) -> Any:  # noqa: ANN401
    """An SB3 `Logger` that also writes every scalar PPO / SAC / ... logs (rollout/ep_rew_mean,
    train/loss, ...) to the training folder: `model.set_logger(sv.rl.sb3_logger())`."""
    from stable_baselines3.common.logger import HumanOutputFormat, KVWriter, Logger

    class SimViewWriter(KVWriter):
        def write(
            self, key_values: dict[str, Any], key_excluded: dict[str, Any], step: int = 0
        ) -> None:
            for key, value in key_values.items():
                if isinstance(value, int | float | np.integer | np.floating) and not isinstance(
                    value, bool
                ):
                    log_metric(key, step, float(value))

        def close(self) -> None:
            pass

    target = training_dir(folder)
    formats: list[Any] = [SimViewWriter()]
    if stdout:
        import sys

        formats.append(HumanOutputFormat(sys.stdout))
    return Logger(str(target), formats)
