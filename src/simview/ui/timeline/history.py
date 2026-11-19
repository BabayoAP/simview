"""The recorded run the timeline scrubs and the plots draw (VP-05, DA-01, DA-02).

Holds every history row the sim process streamed (`ipc/record.py`) in one growable float64
array, plus the debug draws as they changed. Qt-free, so it is tested on every OS.
"""

from __future__ import annotations

import bisect
import json

import numpy as np
import pyarrow as pa

from simview.ipc.record import RowLayout
from simview.ipc.shm import Frame

# Memory the history may use before its oldest quarter is dropped (D-049).
MAX_BYTES = 512 * 1024**2
TRAIL_POINTS = 2000  # most points a replayed trail is drawn with
NO_DRAWS: list[tuple] = []  # one shared object: the UI redraws only when draws change identity


class History:
    def __init__(self, layout: RowLayout, dt: float, max_bytes: int = MAX_BYTES) -> None:
        self.layout = layout
        self.dt = dt
        self.max_rows = max(16, max_bytes // (8 * layout.width))
        self._data = np.zeros((1024, layout.width))
        self.n = 0
        self.version = 0  # bumps on every change, so plots redraw only when needed
        self.edits = 0  # bumps when held rows are replaced or dropped (not on plain appends)
        self._draws: list[tuple[int, list[tuple]]] = []  # (tick, draws) when they changed
        self._columns = {name: 1 + i for i, name in enumerate(layout.signals)}
        self.units = dict(zip(layout.signals, layout.units, strict=True))

    # -- filling --------------------------------------------------------------------------
    def append(self, rows: np.ndarray) -> None:
        """Add rows; any held rows from the first new tick on are replaced (re-record, reset)."""
        if not len(rows):
            return
        first = rows[0, 0]
        keep = int(np.searchsorted(self.ticks, first, side="left"))
        if keep < self.n:
            self.edits += 1
        self.n = keep
        need = self.n + len(rows)
        if need > len(self._data):
            grown = np.zeros((max(need, 2 * len(self._data)), self.layout.width))
            grown[: self.n] = self._data[: self.n]
            self._data = grown
        self._data[self.n : need] = rows
        self.n = need
        if self.n > self.max_rows:
            drop = self.n - (3 * self.max_rows) // 4
            self._data[: self.n - drop] = self._data[drop : self.n]
            self.n -= drop
            self.edits += 1
            # Keep the last draw set from before the new start, so it still shows there.
            k = bisect.bisect_right(self._draws, self.ticks[0], key=lambda d: d[0])
            self._draws = self._draws[max(0, k - 1) :]
        self.version += 1

    def add_draws(self, tick: int, draws: list[tuple]) -> None:
        """Debug draws as of `tick` (the sim sends them only when they change)."""
        k = bisect.bisect_left(self._draws, tick, key=lambda d: d[0])
        del self._draws[k:]  # a re-recorded tick or a reset replaces later ones
        self._draws.append((tick, draws))

    # -- reading ----------------------------------------------------------------------------
    @property
    def ticks(self) -> np.ndarray:
        return self._data[: self.n, 0]

    @property
    def t(self) -> np.ndarray:
        return self.ticks * self.dt

    @property
    def signals(self) -> tuple[str, ...]:
        return self.layout.signals

    def signal(self, name: str) -> np.ndarray:
        """One logged signal over the whole history (a view; don't modify it)."""
        return self._data[: self.n, self._columns[name]]

    def block(self, names: list[str], i0: int, i1: int) -> np.ndarray:
        """Rows i0..i1 of several signals as one (n, len(names)) array."""
        return self._data[i0:i1, [self._columns[n] for n in names]]

    def time_of(self, i: int) -> float:
        return float(self._data[i, 0]) * self.dt

    def index_at(self, t: float) -> int:
        """The row nearest to sim time `t` (clamped to the history)."""
        if self.n == 0:
            return 0
        i = round(t / self.dt - self._data[0, 0])
        i = min(max(i, 0), self.n - 1)
        if self._data[i, 0] * self.dt != t:  # rows aren't contiguous: search
            ts = self.t
            j = int(np.searchsorted(ts, t))
            i = min(max(j, 0), self.n - 1)
            if j > 0 and (j == self.n or abs(ts[j - 1] - t) <= abs(ts[j] - t)):
                i = j - 1
        return i

    def frame(self, i: int, live: Frame | None = None) -> Frame:
        """Row `i` as a state frame for the viewport; RTF and speed come from `live`."""
        row = self._data[i]
        lay = self.layout
        states: dict[str, np.ndarray] = {}
        at = 1
        for name, size in zip(lay.state.entity_names, lay.state.entity_sizes, strict=True):
            states[name] = row[at : at + size].copy()
            at += size
        m = lay.markers_at
        markers = {
            name: row[m + 3 * k : m + 3 * k + 3].copy()
            for k, name in enumerate(lay.state.marker_entities)
        }
        bodies = row[lay.bodies_at : lay.width].reshape(-1, 7).copy()
        return Frame(
            tick=int(row[0]),
            t=float(row[0]) * self.dt,
            rtf=live.rtf if live else 0.0,
            running=live.running if live else False,
            wall=live.wall if live else 0.0,
            speed=live.speed if live else 1.0,
            states=states,
            markers=markers,
            bodies=bodies,
        )

    def draws_at(self, tick: int) -> list[tuple]:
        """The debug draws shown at `tick` (the newest set sent at or before it)."""
        k = bisect.bisect_right(self._draws, tick, key=lambda d: d[0])
        return self._draws[k - 1][1] if k else NO_DRAWS

    def trails(self, i: int, seconds: dict[str, float]) -> dict[str, np.ndarray]:
        """Each marker's path over the `seconds` before row `i`, as (n, 3) points (VP-04)."""
        out: dict[str, np.ndarray] = {}
        lay = self.layout
        ts = self.t
        for k, name in enumerate(lay.state.marker_entities):
            if name not in seconds:
                continue
            start = int(np.searchsorted(ts[: i + 1], ts[i] - seconds[name]))
            step = max(1, (i + 1 - start) // TRAIL_POINTS)
            col = lay.markers_at + 3 * k
            pts = self._data[start : i + 1 : step, col : col + 3]
            if len(pts) and (i - start) % step:
                pts = np.vstack([pts, self._data[i, col : col + 3]])  # end at the marker
            out[name] = pts
        return out

    def table(self, metadata: dict[str, object] | None = None) -> pa.Table:
        """All logged signals with the Parquet log's columns: t, tick, then signals (DA-07)."""
        ticks = self.ticks.astype(np.int64)
        columns: dict[str, pa.Array] = {"t": pa.array(ticks * self.dt), "tick": pa.array(ticks)}
        for name in self.signals:
            columns[name] = pa.array(self.signal(name).copy())
        meta = {"dt": self.dt, **(metadata or {})}
        return pa.table(columns).replace_schema_metadata(
            {b"simview": json.dumps(meta, sort_keys=True).encode()}
        )
