"""Debug draw API (VP-07): `ctx.draw.line / arrow / point / text / frame` from user code.

Draws are recorded in the sim process and shown by the viewport. A draw lasts one tick unless
`persist=True`; `clear()` removes persistent draws. Headless runs record into the same list, so
scene code behaves the same with or without a viewport (and costs a list append per call).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

Kind = Literal["line", "arrow", "point", "text", "frame"]
DEFAULT_COLOR = "accent"  # a theme token; any color name or "#rrggbb" also works


@dataclass(frozen=True)
class Draw:
    kind: Kind
    # line/arrow: 2 points, point/text: 1, frame: 4 (origin, then x, y, z axis ends)
    points: tuple[tuple[float, float, float], ...]
    color: str
    size: float  # line width (px), point size (px), text size (pt), or frame axis length (m)
    text: str = ""


def _p(v: Sequence[float] | np.ndarray) -> tuple[float, float, float]:
    a = np.asarray(v, dtype=np.float64).reshape(-1)
    if a.shape not in ((2,), (3,)):
        raise ValueError(f"a point needs 2 or 3 coordinates, got {a.shape}")
    return (float(a[0]), float(a[1]), float(a[2]) if len(a) == 3 else 0.0)


@dataclass
class DrawList:
    """This tick's draws plus persistent ones. `snapshot()` is what the viewport shows."""

    transient: list[Draw] = field(default_factory=list)
    persistent: list[Draw] = field(default_factory=list)

    def _add(self, d: Draw, persist: bool) -> None:
        (self.persistent if persist else self.transient).append(d)

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

    def clear(self) -> None:
        """Remove persistent draws too."""
        self.transient.clear()
        self.persistent.clear()

    def new_tick(self) -> None:
        self.transient.clear()

    def snapshot(self) -> list[Draw]:
        return [*self.persistent, *self.transient]
