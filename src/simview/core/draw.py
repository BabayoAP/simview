"""Debug draw API (VP-07): `ctx.draw.line / arrow / point / text / frame` from user code, plus
point clouds (VP-08) and covariance ellipsoids (VP-09).

Draws are recorded in the sim process and shown by the viewport. A controller's draws last
until that controller runs again (D-089), unless `persist=True`; `clear()` removes persistent
draws. Headless runs record into the same list, so scene code behaves the same with or without
a viewport (and costs a list append per call).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

Kind = Literal["line", "arrow", "point", "text", "frame", "cloud", "ellipsoid"]
DEFAULT_COLOR = "accent"  # a theme token; any color name or "#rrggbb" also works


@dataclass(frozen=True)
class Draw:
    kind: Kind
    # line/arrow: 2 points, point/text: 1, frame: 4 (origin, then x, y, z axis ends)
    points: tuple[tuple[float, float, float], ...]
    color: str
    size: float  # line width (px), point size (px), text size (pt), or frame axis length (m)
    text: str = ""
    # cloud: the (N, 3) float32 points; ellipsoid: the 3x3 matrix whose columns are the
    # semi-axes (sigma-scaled), centered on points[0]
    data: np.ndarray | None = field(default=None, compare=False)


def _p(v: Sequence[float] | np.ndarray) -> tuple[float, float, float]:
    a = np.asarray(v, dtype=np.float64).reshape(-1)
    if a.shape not in ((2,), (3,)):
        raise ValueError(f"a point needs 2 or 3 coordinates, got {a.shape}")
    return (float(a[0]), float(a[1]), float(a[2]) if len(a) == 3 else 0.0)


def ellipsoid_axes(cov: Sequence[Sequence[float]] | np.ndarray, sigma: float) -> np.ndarray:
    """Semi-axes (as columns) of the `sigma` level set of a 3x3 covariance (VP-09):
    the eigenvectors scaled by sigma * sqrt(eigenvalue). Negative eigenvalues (round-off in a
    filter's P) count as 0."""
    c = np.asarray(cov, dtype=np.float64)
    if c.shape != (3, 3):
        raise ValueError(f"a covariance must be 3x3, got shape {c.shape}")
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    vals, vecs = np.linalg.eigh(0.5 * (c + c.T))
    return vecs * (sigma * np.sqrt(np.clip(vals, 0.0, None)))


@dataclass
class DrawList:
    """Live draws: each owner's latest ones plus persistent ones. `snapshot()` is what the
    viewport shows. An owner is a controller (its draws are replaced when it runs again,
    D-089); draws made outside a controller last one tick."""

    persistent: list[Draw] = field(default_factory=list)
    _owned: dict[object, list[Draw]] = field(default_factory=dict)
    _owner: object = None

    @property
    def transient(self) -> list[Draw]:
        return [d for items in self._owned.values() for d in items]

    def begin(self, owner: object) -> None:
        """Start `owner`'s draws for this call: its previous ones are dropped."""
        self._owner = owner
        self._owned[owner] = []

    def end(self) -> None:
        self._owner = None

    def _add(self, d: Draw, persist: bool) -> None:
        if persist:
            self.persistent.append(d)
        else:
            self._owned.setdefault(self._owner, []).append(d)

    def line(
        self,
        a: Sequence[float],
        b: Sequence[float],
        *,
        color: str = DEFAULT_COLOR,
        width: float = 2.0,
        persist: bool = False,
    ) -> None:
        self._add(Draw("line", (_p(a), _p(b)), color, width), persist)

    def arrow(
        self,
        a: Sequence[float],
        b: Sequence[float],
        *,
        color: str = DEFAULT_COLOR,
        width: float = 2.0,
        persist: bool = False,
    ) -> None:
        self._add(Draw("arrow", (_p(a), _p(b)), color, width), persist)

    def point(
        self,
        p: Sequence[float],
        *,
        color: str = DEFAULT_COLOR,
        size: float = 8.0,
        persist: bool = False,
    ) -> None:
        self._add(Draw("point", (_p(p),), color, size), persist)

    def text(
        self,
        p: Sequence[float],
        text: str,
        *,
        color: str = "text.primary",
        size: float = 11.0,
        persist: bool = False,
    ) -> None:
        self._add(Draw("text", (_p(p),), color, size, str(text)), persist)

    def frame(self, pose: np.ndarray, *, scale: float = 0.1, persist: bool = False) -> None:
        """RGB axes (x red, y green, z blue) of a 4x4 pose."""
        pose = np.asarray(pose, dtype=np.float64)
        o = pose[:3, 3]
        pts = (_p(o), *(_p(o + scale * pose[:3, i]) for i in range(3)))
        self._add(Draw("frame", pts, "frame", scale), persist)

    def points(
        self,
        cloud: Sequence[Sequence[float]] | np.ndarray,
        *,
        color: str = DEFAULT_COLOR,
        size: float = 2.0,
        persist: bool = False,
    ) -> None:
        """A point cloud (VP-08): an (N, 3) array, e.g. a lidar scan's `points`."""
        a = np.asarray(cloud, dtype=np.float32)
        if a.size == 0:
            a = a.reshape(0, 3)
        if a.ndim != 2 or a.shape[1] != 3:
            raise ValueError(f"a point cloud is an (N, 3) array, got shape {a.shape}")
        self._add(Draw("cloud", (), color, size, data=a), persist)

    def ellipsoid(
        self,
        center: Sequence[float],
        cov: Sequence[Sequence[float]] | np.ndarray,
        *,
        sigma: float = 3.0,
        color: str = DEFAULT_COLOR,
        persist: bool = False,
    ) -> None:
        """The `sigma` covariance ellipsoid of a 3x3 covariance around `center` (VP-09)."""
        self._add(
            Draw("ellipsoid", (_p(center),), color, sigma, data=ellipsoid_axes(cov, sigma)),
            persist,
        )

    def clear(self) -> None:
        """Remove persistent draws too."""
        self._owned.clear()
        self.persistent.clear()

    def new_tick(self) -> None:
        """Drop draws made outside controllers (they last one tick)."""
        self._owned.pop(None, None)

    def snapshot(self) -> list[Draw]:
        return [*self.persistent, *self.transient]
