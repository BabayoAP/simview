"""Perception panels (VW-08) and the live session's perception history (VW-09, D-134).

- `CamerasPanel`: the rig's feeds as a grid of thumbnails; click one to enlarge it, click the
  enlarged view (or Back) to return to the grid.
- `BevPanel`: the top-down BEV map with the ego pose as an arrow.
- `PerceptionHistory`: the snapshot and camera rows a live session's pipelines logged, as
  `Snapshots` for timeline scrubbing, written beside the run log when the session is saved.

Both panels show a §7.8 empty state (one-line hint and an action) when the scene has no rig or
no pipeline.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from qtpy.QtCore import QPointF, QRectF, Qt, Signal
from qtpy.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent, QPen, QPolygonF
from qtpy.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from simview.ui import theme
from simview.ui.panels import EmptyState
from simview.ui.theme import tokens


def to_qimage(img: np.ndarray) -> QImage:
    """(h, w) gray or (h, w, 3) RGB uint8 -> a QImage that owns its pixels."""
    a = np.ascontiguousarray(img, dtype=np.uint8)
    if a.ndim == 2:
        a = np.ascontiguousarray(np.repeat(a[:, :, None], 3, axis=2))
    h, w = a.shape[:2]
    return QImage(a.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class ImageView(QWidget):
    """An image scaled to fit (aspect kept, nearest-neighbour so cells stay crisp), with an
    optional caption hint when there is no image and an optional ego arrow (BEV)."""

    clicked = Signal()

    def __init__(self, min_width: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.image: np.ndarray | None = None
        self._qimage: QImage | None = None
        self.hint = ""
        self.ego_px: tuple[float, float, float] | None = None  # col, row, yaw (image pixels)
        if min_width:
            self.setMinimumSize(min_width, int(min_width * 3 / 4))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_image(self, img: np.ndarray | None, hint: str = "") -> None:
        self.image = img
        self._qimage = None if img is None else to_qimage(img)
        self.hint = hint
        self.update()

    def _target(self) -> QRectF | None:
        if self._qimage is None:
            return None
        w, h = self._qimage.width(), self._qimage.height()
        scale = min(self.width() / max(w, 1), self.height() / max(h, 1))
        tw, th = w * scale, h * scale
        return QRectF((self.width() - tw) / 2, (self.height() - th) / 2, tw, th)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        name = theme.current_theme()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(tokens.color(name, "bg.app")))
        rect = self._target()
        if rect is None or self._qimage is None:
            p.setPen(QColor(tokens.color(name, "text.secondary")))
            flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
            p.drawText(self.rect(), flags, self.hint)
            p.end()
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(rect, self._qimage)
        if self.ego_px is not None:
            col, row, yaw = self.ego_px
            s = rect.width() / self._qimage.width()
            c = QPointF(rect.left() + col * s, rect.top() + row * s)
            size = float(tokens.BEV_EGO_SIZE)
            # Image rows grow downwards (y up in the world), so the heading flips its y.
            fwd = QPointF(math.cos(yaw), -math.sin(yaw))
            side = QPointF(-fwd.y(), fwd.x())
            tip = c + fwd * size
            back = c - fwd * (size / 2)
            arrow = QPolygonF([tip, back + side * (size / 2), back - side * (size / 2)])
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(QPen(QColor(tokens.color(name, "bg.app")), tokens.BEV_EGO_WIDTH))
            p.setBrush(QColor(tokens.color(name, "accent")))
            p.drawPolygon(arrow)
        p.end()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _Thumb(QWidget):
    """One camera in the grid: its image and name."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.view = ImageView(tokens.CAMERA_THUMB_WIDTH, self)
        self.view.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view.setToolTip(f"{name}: click to enlarge")
        label = QLabel(name.split(".", 1)[-1], self)
        label.setProperty("role", "secondary")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(tokens.SPACING[0])
        lay.addWidget(self.view, 1)
        lay.addWidget(label)


class CamerasPanel(QStackedWidget):
    """VW-08: the rig's camera feeds as thumbnails; click one to enlarge it."""

    EMPTY, GRID, ENLARGED = range(3)
    NO_FRAME = "No frame yet."
    NOT_LOGGED = "No camera frame logged at this time (set camera_every on the pipeline)."

    def __init__(self, on_empty: Callable[[], object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.empty = EmptyState(
            "camera", "This scene has no camera rig.", "Open Template…", on_empty
        )
        self.addWidget(self.empty)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        pad = tokens.SPACING[1]
        self.grid.setContentsMargins(pad, pad, pad, pad)
        self.grid.setSpacing(pad)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_host)
        self.addWidget(scroll)
        big = QWidget()
        top = QHBoxLayout()
        self.back = QPushButton("Back to All Cameras")
        self.back.clicked.connect(lambda _c=False: self.enlarge(None))
        self.big_label = QLabel()
        self.big_label.setProperty("role", "secondary")
        top.addWidget(self.back)
        top.addWidget(self.big_label, 1)
        self.big = ImageView(tokens.CAMERA_ENLARGED_WIDTH // 2)
        self.big.clicked.connect(lambda: self.enlarge(None))
        lay = QVBoxLayout(big)
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.addLayout(top)
        lay.addWidget(self.big, 1)
        self.addWidget(big)
        self.thumbs: dict[str, _Thumb] = {}
        self.enlarged: str | None = None
        self._columns = 0

    def set_cameras(self, names: list[str]) -> None:
        """The scene's camera streams (empty: the empty state)."""
        for t in self.thumbs.values():
            t.setParent(None)
            t.deleteLater()
        self.thumbs = {n: _Thumb(n) for n in names}
        for n, t in self.thumbs.items():
            t.view.set_image(None, self.NO_FRAME)
            t.view.clicked.connect(lambda n=n: self.enlarge(n))
        self._columns = 0
        self._relayout()
        self.enlarged = None
        self.setCurrentIndex(self.GRID if names else self.EMPTY)

    def _relayout(self) -> None:
        if not self.thumbs:
            return
        step = tokens.CAMERA_THUMB_WIDTH + tokens.SPACING[1]
        cols = max(1, min(len(self.thumbs), (self.width() - tokens.SPACING[1]) // step))
        if cols == self._columns:
            return
        self._columns = cols
        for i, t in enumerate(self.thumbs.values()):
            self.grid.addWidget(t, i // cols, i % cols)

    def resizeEvent(self, event: Any) -> None:  # noqa: ANN401, N802 (Qt API)
        super().resizeEvent(event)
        self._relayout()

    def enlarge(self, name: str | None) -> None:
        """Show one camera big (None: back to the grid)."""
        if name is not None and name not in self.thumbs:
            raise KeyError(name)
        self.enlarged = name
        if name is None:
            self.setCurrentIndex(self.GRID if self.thumbs else self.EMPTY)
            return
        view = self.thumbs[name].view
        self.big.set_image(view.image, view.hint)
        self.big_label.setText(name)
        self.setCurrentIndex(self.ENLARGED)

    def show_frame(self, name: str, rgb: np.ndarray | None, hint: str = "") -> None:
        """A camera's image (None shows `hint` instead)."""
        t = self.thumbs.get(name)
        if t is None:
            return
        t.view.set_image(rgb, hint)
        if self.enlarged == name:
            self.big.set_image(rgb, hint)

    def image(self, name: str) -> np.ndarray | None:
        t = self.thumbs.get(name)
        return None if t is None else t.view.image


class BevPanel(QStackedWidget):
    """VW-08: the BEV map seen from above with the ego pose."""

    NO_MAP = "No map yet: run the simulation."

    def __init__(self, on_empty: Callable[[], object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.empty = EmptyState(
            "map", "This scene has no perception pipeline.", "Open Template…", on_empty
        )
        self.addWidget(self.empty)
        self.view = ImageView(tokens.CAMERA_THUMB_WIDTH)
        self.view.set_image(None, self.NO_MAP)
        self.addWidget(self.view)
        self.t: float | None = None  # time of the shown map

    def set_available(self, on: bool) -> None:
        self.setCurrentIndex(1 if on else 0)
        self.show_bev(None)

    def show_bev(
        self,
        image: np.ndarray | None,
        origin: np.ndarray | None = None,
        res: float = 0.0,
        ego: np.ndarray | None = None,
        t: float | None = None,
        hint: str = NO_MAP,
    ) -> None:
        """`image` (ny, nx[, 3]) uint8 with row 0 at the largest y; `origin` the world (x, y)
        of its lower corner, `res` m per pixel, `ego` (x, y, yaw) or None."""
        self.t = t
        self.view.ego_px = None
        if image is not None and ego is not None and origin is not None and res > 0:
            col = (float(ego[0]) - float(origin[0])) / res
            row = image.shape[0] - (float(ego[1]) - float(origin[1])) / res
            self.view.ego_px = (col, row, float(ego[2]))
        self.view.set_image(image, hint)


class PerceptionHistory:
    """A live session's logged perception rows per pipeline (D-131 rows, sent by the sim)."""

    def __init__(self) -> None:
        self.snapshots: dict[str, list[dict[str, Any]]] = {}
        self.frames: dict[str, list[dict[str, Any]]] = {}
        self._cache: dict[str, tuple[tuple[int, int], Any]] = {}

    def add(self, pipeline: str, snapshots: list[dict], frames: list[dict]) -> None:
        self.snapshots.setdefault(pipeline, []).extend(snapshots)
        self.frames.setdefault(pipeline, []).extend(frames)

    def clear(self) -> None:
        self.snapshots.clear()
        self.frames.clear()
        self._cache.clear()

    def __bool__(self) -> bool:
        return any(self.snapshots.values()) or any(self.frames.values())

    def get(self, pipeline: str) -> Any:  # noqa: ANN401 - a Snapshots, or None
        """The pipeline's rows as `Snapshots` (rebuilt only when rows were added)."""
        from simview.perception.runlog import Snapshots, camera_table, snapshot_table

        snaps, frames = self.snapshots.get(pipeline, []), self.frames.get(pipeline, [])
        if not snaps:
            return None
        key = (len(snaps), len(frames))
        hit = self._cache.get(pipeline)
        if hit is None or hit[0] != key:
            cams = camera_table(frames) if frames else None
            hit = (key, Snapshots(pipeline, snapshot_table(snaps), cams))
            self._cache[pipeline] = hit
        return hit[1]

    def write(self, run_path: str | Path) -> list[Path]:
        """Write every pipeline's rows beside the run log (`<run>.perception/`)."""
        from simview.perception.runlog import write_rows

        out: list[Path] = []
        for name in self.snapshots:
            out += write_rows(run_path, name, self.snapshots[name], self.frames.get(name, []))
        return out
