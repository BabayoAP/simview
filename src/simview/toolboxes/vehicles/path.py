"""Planar paths and roads (TB-VEH): polylines with arc length, nearest-point queries, signed
cross-track error, and a road made of parallel lanes (D-094)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from simview.core.draw import DrawList


@dataclass(frozen=True)
class Nearest:
    """The closest point on a path to a query point."""

    s: float  # arc length of the closest point (m)
    point: np.ndarray  # (2,) the closest point
    heading: float  # path heading there (rad)
    cross_track: float  # signed distance (m), positive when the query is left of the path
    segment: int  # index of the segment holding the closest point


class Path:
    """A 2-D polyline through `points` (N >= 2, consecutive duplicates removed)."""

    def __init__(self, points: Sequence[Sequence[float]] | np.ndarray) -> None:
        p = np.asarray(points, dtype=np.float64)
        if p.ndim != 2 or p.shape[1] < 2:
            raise ValueError(f"a path needs (N, 2) points, got shape {p.shape}")
        p = p[:, :2]
        keep = np.r_[True, np.linalg.norm(np.diff(p, axis=0), axis=1) > 1e-12]
        p = p[keep]
        if len(p) < 2:
            raise ValueError("a path needs at least 2 distinct points")
        self.points = p
        seg = np.diff(p, axis=0)
        self._len = np.linalg.norm(seg, axis=1)
        self._dir = seg / self._len[:, None]
        self.s = np.r_[0.0, np.cumsum(self._len)]  # arc length at each point

    @property
    def length(self) -> float:
        return float(self.s[-1])

    def _segment(self, s: float) -> int:
        return int(np.clip(np.searchsorted(self.s, s, side="right") - 1, 0, len(self._len) - 1))

    def point_at(self, s: float) -> np.ndarray:
        """The point at arc length `s`, clamped to the path's ends."""
        s = float(np.clip(s, 0.0, self.length))
        i = self._segment(s)
        return self.points[i] + (s - self.s[i]) * self._dir[i]

    def heading_at(self, s: float) -> float:
        d = self._dir[self._segment(float(np.clip(s, 0.0, self.length)))]
        return float(np.arctan2(d[1], d[0]))

    def nearest(self, point: Sequence[float] | np.ndarray) -> Nearest:
        q = np.asarray(point, dtype=np.float64)[:2]
        rel = q - self.points[:-1]
        t = np.clip(np.einsum("ij,ij->i", rel, self._dir), 0.0, self._len)
        foot = self.points[:-1] + t[:, None] * self._dir
        i = int(np.argmin(np.linalg.norm(q - foot, axis=1)))
        d = self._dir[i]
        off = q - foot[i]
        cte = float(d[0] * off[1] - d[1] * off[0])  # z of dir x offset: + on the left
        return Nearest(
            s=float(self.s[i] + t[i]),
            point=foot[i],
            heading=float(np.arctan2(d[1], d[0])),
            cross_track=cte,
            segment=i,
        )

    def offset(self, d: float) -> Path:
        """A parallel path `d` metres to the left (negative: right). Corners use the mitred
        normal, so offsets of gentle polylines (lanes) stay parallel."""
        n_seg = np.c_[-self._dir[:, 1], self._dir[:, 0]]
        n = np.empty_like(self.points)
        n[0], n[-1] = n_seg[0], n_seg[-1]
        mid = n_seg[:-1] + n_seg[1:]
        mid /= np.linalg.norm(mid, axis=1)[:, None]
        cos_half = np.einsum("ij,ij->i", mid, n_seg[1:])
        n[1:-1] = mid / np.maximum(cos_half, 0.2)[:, None]
        return Path(self.points + d * n)

    def draw(
        self,
        draw: DrawList,
        *,
        color: str = "accent",
        width: float = 2.0,
        z: float = 0.0,
        persist: bool = False,
    ) -> None:
        """Draw the path as line segments (e.g. the planned path, VP-07)."""
        for a, b in zip(self.points[:-1], self.points[1:], strict=True):
            draw.line((a[0], a[1], z), (b[0], b[1], z), color=color, width=width, persist=persist)


def straight(start: Sequence[float], heading: float, length: float, *, step: float = 1.0) -> Path:
    """A straight path from `start` along `heading` (rad)."""
    if length <= 0:
        raise ValueError("length must be positive")
    n = max(1, int(np.ceil(length / step)))
    s = np.linspace(0.0, length, n + 1)
    x0, y0 = float(start[0]), float(start[1])
    return Path(np.c_[x0 + s * np.cos(heading), y0 + s * np.sin(heading)])


def arc(
    center: Sequence[float],
    radius: float,
    start_angle: float,
    sweep: float,
    *,
    step: float = 1.0,
) -> Path:
    """A circular arc; `sweep` > 0 turns left (counter-clockwise)."""
    if radius <= 0:
        raise ValueError("radius must be positive")
    n = max(2, int(np.ceil(abs(sweep) * radius / step)))
    a = start_angle + np.linspace(0.0, sweep, n + 1)
    return Path(np.c_[center[0] + radius * np.cos(a), center[1] + radius * np.sin(a)])


def join(*paths: Path) -> Path:
    """Paths end to end (each one's first point is dropped if it repeats the last one's end)."""
    if not paths:
        raise ValueError("join needs at least one path")
    return Path(np.vstack([p.points for p in paths]))


class Road:
    """A road along `centerline` with `lanes` lanes of `lane_width` (scene primitive, TB-VEH).

    Lanes are numbered from the right edge: lane 0 is the rightmost (drive on the right)."""

    def __init__(self, centerline: Path, *, lanes: int = 2, lane_width: float = 3.5) -> None:
        if lanes < 1:
            raise ValueError("a road needs at least one lane")
        if lane_width <= 0:
            raise ValueError("lane_width must be positive")
        self.centerline = centerline
        self.lanes = int(lanes)
        self.lane_width = float(lane_width)

    @property
    def width(self) -> float:
        return self.lanes * self.lane_width

    def lane(self, i: int) -> Path:
        """The center path of lane `i`."""
        if not 0 <= i < self.lanes:
            raise IndexError(f"lane {i} out of range (road has {self.lanes})")
        return self.centerline.offset((i + 0.5) * self.lane_width - self.width / 2)

    def edges(self) -> tuple[Path, Path]:
        """Right and left road edges."""
        return self.centerline.offset(-self.width / 2), self.centerline.offset(self.width / 2)

    def lane_of(self, point: Sequence[float]) -> int | None:
        """The lane a point is in, or None when it is off the road."""
        cte = self.centerline.nearest(point).cross_track + self.width / 2
        if not 0.0 <= cte <= self.width:
            return None
        return min(int(cte // self.lane_width), self.lanes - 1)

    def draw(self, draw: DrawList, *, z: float = 0.01, persist: bool = True) -> None:
        """Edges as solid lines and lane dividers as dashes (persistent by default, so a
        controller can draw the road once at t = 0)."""
        for edge in self.edges():
            edge.draw(draw, color="text.secondary", width=2.0, z=z, persist=persist)
        for k in range(1, self.lanes):
            divider = self.centerline.offset(k * self.lane_width - self.width / 2)
            dash = 3.0
            for s0 in np.arange(0.0, divider.length, 2 * dash):
                a, b = divider.point_at(s0), divider.point_at(min(s0 + dash, divider.length))
                draw.line(
                    (a[0], a[1], z),
                    (b[0], b[1], z),
                    color="text.secondary",
                    width=1.0,
                    persist=persist,
                )
