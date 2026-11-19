"""Shared-memory state buffer between the sim process and the UI (SE-02, NF-04).

One float64 array: a header, then every entity's state, every entity's marker position, and the
pose of every MuJoCo body (position + quaternion). The writer bumps a sequence number to an odd
value before writing and to the next even value after (a seqlock), so a reader retries instead
of seeing a half-written frame. Nothing here imports Qt or MuJoCo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from multiprocessing import shared_memory

import numpy as np

READ_TIMEOUT = 0.02  # s a reader waits out a write in progress

# Header slots
SEQ, TICK, T, RTF, RUNNING, WALL, SPEED, N_HEADER = range(8)


@dataclass(frozen=True)
class Layout:
    """Where each part lives in the buffer. Sent from the sim process to the UI on load."""

    entity_names: tuple[str, ...]
    entity_sizes: tuple[int, ...]  # len(x) per entity
    marker_entities: tuple[str, ...]  # entities with a position() marker
    n_bodies: int  # MuJoCo bodies (0 without a world)
    offsets: dict[str, int] = field(default_factory=dict)

    @classmethod
    def build(cls, names: list[str], sizes: list[int], markers: list[str], n_bodies: int) -> Layout:
        offsets: dict[str, int] = {}
        at = N_HEADER
        for name, size in zip(names, sizes, strict=True):
            offsets[f"x:{name}"] = at
            at += size
        for name in markers:
            offsets[f"p:{name}"] = at
            at += 3
        offsets["bodies"] = at
        at += 7 * n_bodies
        offsets["end"] = at
        return cls(tuple(names), tuple(sizes), tuple(markers), n_bodies, offsets)

    @property
    def size(self) -> int:
        return self.offsets["end"]


@dataclass
class Frame:
    """One consistent read of the buffer."""

    tick: int
    t: float
    rtf: float
    running: bool
    wall: float  # time.monotonic() when the sim wrote it (NF-04 latency)
    speed: float  # requested playback speed; 0 means as fast as possible
    states: dict[str, np.ndarray]
    markers: dict[str, np.ndarray]
    bodies: np.ndarray  # (n_bodies, 7): x, y, z, qw, qx, qy, qz


class StateBuffer:
    def __init__(self, layout: Layout, name: str | None = None, create: bool = False) -> None:
        self.layout = layout
        nbytes = max(8, layout.size * 8)
        self.shm = shared_memory.SharedMemory(name=name, create=create, size=nbytes)
        self.arr = np.ndarray((layout.size,), dtype=np.float64, buffer=self.shm.buf)
        if create:
            self.arr[:] = 0.0

    @property
    def name(self) -> str:
        return self.shm.name

    # -- writer (sim process) ---------------------------------------------------------------
    def write(
        self,
        tick: int,
        t: float,
        rtf: float,
        running: bool,
        wall: float,
        speed: float,
        states: dict[str, np.ndarray],
        markers: dict[str, np.ndarray],
        bodies: np.ndarray | None,
    ) -> None:
        a, off = self.arr, self.layout.offsets
        a[SEQ] += 1  # odd: writing
        a[TICK], a[T], a[RTF], a[RUNNING], a[WALL], a[SPEED] = (
            tick,
            t,
            rtf,
            float(running),
            wall,
            speed,
        )
        for name, size in zip(self.layout.entity_names, self.layout.entity_sizes, strict=True):
            o = off[f"x:{name}"]
            a[o : o + size] = states[name]
        for name in self.layout.marker_entities:
            o = off[f"p:{name}"]
            a[o : o + 3] = markers[name]
        if self.layout.n_bodies and bodies is not None:
            o = off["bodies"]
            a[o : o + 7 * self.layout.n_bodies] = bodies.reshape(-1)
        a[SEQ] += 1  # even: done

    # -- reader (UI) ------------------------------------------------------------------------
    def read(self, timeout: float = READ_TIMEOUT) -> Frame | None:
        """A consistent frame, or None if nothing was written yet (or the writer kept racing
        for `timeout` seconds). Mid-write it yields, so a writer descheduled halfway through a
        frame (a busy CI machine) gets to finish instead of the reader giving up at once."""
        a, off = self.arr, self.layout.offsets
        deadline = time.monotonic() + timeout
        while True:
            seq = a[SEQ]
            if seq == 0:
                return None
            if int(seq) % 2:
                if time.monotonic() > deadline:
                    return None
                time.sleep(0)
                continue
            copy = a.copy()
            if a[SEQ] != seq:
                if time.monotonic() > deadline:
                    return None
                continue
            states = {
                n: copy[off[f"x:{n}"] : off[f"x:{n}"] + s]
                for n, s in zip(self.layout.entity_names, self.layout.entity_sizes, strict=True)
            }
            markers = {
                n: copy[off[f"p:{n}"] : off[f"p:{n}"] + 3] for n in self.layout.marker_entities
            }
            o = off["bodies"]
            bodies = copy[o : o + 7 * self.layout.n_bodies].reshape(-1, 7)
            return Frame(
                int(copy[TICK]),
                float(copy[T]),
                float(copy[RTF]),
                bool(copy[RUNNING]),
                float(copy[WALL]),
                float(copy[SPEED]),
                states,
                markers,
                bodies,
            )
        return None

    def close(self, unlink: bool = False) -> None:
        del self.arr
        self.shm.close()
        if unlink:
            try:
                self.shm.unlink()
            except FileNotFoundError:
                pass
