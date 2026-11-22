"""Frame streams (VW-02, D-123): timestamped items with one producer and any number of readers.

A `Stream` keeps its newest `maxlen` items. `stream.latest()` is the newest item; a consumer that
needs every item takes a `Reader` (`stream.reader()`) and calls `since_last()`; a reader that
fell behind the buffer (or used `latest()` and skipped items) counts what it missed in
`dropped`. During a run every producer and consumer runs inside the scheduler tick, so nothing
is dropped and the result is deterministic.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

# OpenCV optical frame (x right, y down, z forward) expressed in a SimView sensor frame
# (x forward, y left, z up): sensor_from_optical.
SENSOR_FROM_OPTICAL = np.array(
    [[0.0, 0.0, 1.0, 0.0], [-1.0, 0.0, 0.0, 0.0], [0.0, -1.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
)


@dataclass(eq=False)
class Frame:
    """One camera image.

    `K` is the 3x3 pinhole matrix in the OpenCV convention (pixel (u, v)'s centre is at (u, v)),
    `pose` the 4x4 world-from-camera transform of the optical frame (x right, y down, z
    forward), `rgb` an (H, W, 3) uint8 image, `depth` an (H, W) float32 z-depth in metres along
    the optical axis (inf, nan, or 0 = no measurement), `ego` the 4x4 world pose of the vehicle
    carrying the camera when known."""

    t: float
    seq: int
    source: str
    K: np.ndarray  # noqa: N815 - the standard name for intrinsics
    pose: np.ndarray
    rgb: np.ndarray
    depth: np.ndarray | None = None
    ego: np.ndarray | None = None

    @property
    def width(self) -> int:
        return int(self.rgb.shape[1])

    @property
    def height(self) -> int:
        return int(self.rgb.shape[0])


@dataclass
class _Item:
    seq: int
    t: float
    value: Any


class Stream:
    """A named sequence of timestamped items (frames, point clouds, grids, BEV maps)."""

    def __init__(self, name: str, maxlen: int = 64) -> None:
        if maxlen < 1:
            raise ValueError("a stream keeps at least one item")
        self.name = name
        self.maxlen = int(maxlen)
        self._items: deque[_Item] = deque(maxlen=self.maxlen)
        self.seq = -1  # sequence number of the newest item (-1 = none yet)

    def reset(self) -> None:
        self._items.clear()
        self.seq = -1

    def push(self, value: Any, t: float) -> int:  # noqa: ANN401 - streams carry any item
        """Append an item; returns its sequence number (0, 1, 2, ...)."""
        self.seq += 1
        self._items.append(_Item(self.seq, float(t), value))
        return self.seq

    def latest(self) -> Any:  # noqa: ANN401
        """The newest item, or None before the first."""
        return self._items[-1].value if self._items else None

    @property
    def t(self) -> float:
        """Time of the newest item (nan before the first)."""
        return self._items[-1].t if self._items else float("nan")

    def items(self, after: int = -1) -> list[tuple[int, float, Any]]:
        """Buffered (seq, t, item) with seq > `after`, oldest first."""
        return [(i.seq, i.t, i.value) for i in self._items if i.seq > after]

    def reader(self) -> Reader:
        """A consumer with its own read position (starts before the first item)."""
        return Reader(self)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"Stream({self.name!r}, seq={self.seq})"


@dataclass
class Reader:
    """One consumer's position in a stream. `dropped` counts items it never got."""

    stream: Stream
    cursor: int = -1  # last seq read
    dropped: int = 0

    def since_last(self) -> list[Any]:
        """Every item since this reader's last read, oldest first."""
        items = self.stream.items(self.cursor)
        if items:
            self.dropped += items[0][0] - self.cursor - 1
            self.cursor = items[-1][0]
        return [v for _, _, v in items]

    def latest(self) -> Any:  # noqa: ANN401
        """The newest item (None before the first); items skipped count as dropped."""
        seq = self.stream.seq
        if seq > self.cursor:
            self.dropped += seq - self.cursor - 1
            self.cursor = seq
        return self.stream.latest()

    @property
    def pending(self) -> int:
        """Items published since the last read."""
        return max(0, self.stream.seq - self.cursor)
