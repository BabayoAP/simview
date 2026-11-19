"""The plot panel (DA-01..DA-04, DA-07, DS-09): pyqtgraph plots of the recorded run.

Plot kinds: time (signals against sim time, with the synced time cursor), XY (the first signal is
X, the rest are plotted against it, e.g. a top-view trajectory), scatter (XY without lines), and
histogram. Styling follows §7.6 from theme tokens; image exports use the light theme (DS-09).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pyqtgraph as pg
from qtpy.QtCore import QPointF, QSize, Qt, Signal
from qtpy.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont
from qtpy.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from simview.ui import theme
from simview.ui.panels import EmptyState
from simview.ui.plots.decimate import PeakCache, peak_decimate
from simview.ui.plots.signals import decode
from simview.ui.theme import icon, tokens
from simview.ui.theme.tokens import ThemeName
from simview.ui.timeline.history import History

KINDS = {
    "time": ("chart-line", "Time plot"),
    "xy": ("spline", "XY plot"),
    "scatter": ("chart-scatter", "Scatter plot"),
    "histogram": ("chart-column", "Histogram"),
}
HINTS = {
    "time": "Drag signals here to plot them against time.",
    "xy": "Drag the X signal here first, then one or more Y signals.",
    "scatter": "Drag the X signal here first, then one or more Y signals.",
    "histogram": "Drag signals here to see their distribution.",
}
XY_POINTS = 20_000  # most points an XY line is drawn with (strided; DA-04)
SCATTER_POINTS = 5_000  # most points a scatter series is drawn with
HISTOGRAM_BINS = 100  # at most
LEGEND_COLUMNS = 3  # legend entries side by side, so short plots keep their data visible
PEAKS_PER_PX = 0.75  # time plots: at most 0.75 min/max pairs per px of width (DA-01, D-050)
VECTOR_STATES = {"x", "y", "z", "vx", "vy", "vz", "wx", "wy", "wz"}  # X/Y/Z = red/green/blue

# Segmented lines: Qt draws wide antialiased polylines several times slower (DA-01, D-050).
pg.setConfigOptions(antialias=True, useNumba=False, segmentedLineMode="on")


def label(name: str, unit: str) -> str:
    """Axis label with units, MATLAB style: `ur5.shoulder.q [rad]`."""
    return f"{name} [{unit}]" if unit else name


class _PlotWidget(pg.PlotWidget):
    """pyqtgraph's widget, plus signal drops and a leave event (for the hover cursor)."""

    dropped = Signal(list)
    left = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, ev: QDragEnterEvent) -> None:  # noqa: N802 (Qt API)
        if decode(ev.mimeData()):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev: Any) -> None:  # noqa: N802 (Qt API)
        ev.acceptProposedAction()

    def dropEvent(self, ev: QDropEvent) -> None:  # noqa: N802 (Qt API)
        names = decode(ev.mimeData())
        if names:
            ev.acceptProposedAction()
            self.dropped.emit(names)

    def leaveEvent(self, ev: Any) -> None:  # noqa: N802 (Qt API)
        self.left.emit()
        super().leaveEvent(ev)


class PlotView(QFrame):
    """One plot with a small header (kind, hint, export, close)."""

    hover_time = Signal(object)  # sim time under the mouse, or None (DA-02)
    seek_time = Signal(float)  # clicked time
    selected = Signal(object)  # entity of a clicked trace (DS-06)
    closed = Signal()

    def __init__(
        self,
        kind: str,
        entity_of: Callable[[str], str | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PlotView")
        self.kind = kind
        self.entity_of = entity_of
        self.names: list[str] = []
        self.history: History | None = None
        self.curves: dict[str, pg.PlotDataItem] = {}
        self.selection: str | None = None
        self.theme: ThemeName = theme.current_theme()
        self._drawn_version = -1
        self._peaks = PeakCache()
        self.cursor_index: int | None = None
        self.hover_index: int | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        s = tokens.SPACING
        head.setContentsMargins(s[1], s[0], s[0], 0)
        head.setSpacing(s[0])
        kind_icon, title = KINDS[kind]
        glyph = QLabel(self)
        glyph.setPixmap(icon(kind_icon).pixmap(tokens.ICON_SIZE_TOOLBAR))
        self.title = QLabel(title, self)
        self.title.setProperty("role", "secondary")
        self.hint = QLabel(HINTS[kind], self)
        self.hint.setProperty("role", "secondary")
        head.addWidget(glyph)
        head.addWidget(self.title)
        head.addWidget(self.hint)
        head.addStretch(1)
        for ic, tip, slot in (
            ("image-down", "Export plot as PNG or SVG (light theme)", self._export_dialog),
            ("x", "Close plot", self._close),
        ):
            b = QToolButton(self)
            b.setIcon(icon(ic))
            b.setIconSize(QSize(tokens.ICON_SIZE_TOOLBAR, tokens.ICON_SIZE_TOOLBAR))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _c=False, f=slot: f())
            head.addWidget(b)
        lay.addLayout(head)

        existing = QApplication.topLevelWidgets()
        self.widget = _PlotWidget(self)
        self.widget.setMinimumHeight(tokens.PLOT_MIN_HEIGHT)
        self.plot: pg.PlotItem = self.widget.getPlotItem()
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        if kind == "time":  # DA-01: re-thin the data when the user zooms or pans
            self.plot.vb.sigXRangeChanged.connect(self._x_range_changed)
        self.legend = self.plot.addLegend(offset=(-s[1], s[1]))  # top right (§7.6)
        self.cursor = pg.InfiniteLine(angle=90, movable=False)
        self.hover_line = pg.InfiniteLine(angle=90, movable=False)
        self.cursor_dot = pg.ScatterPlotItem(size=tokens.PLOT_CURSOR_SYMBOL)
        self.readout = pg.TextItem(anchor=(0, 0))
        for item in (self.cursor, self.hover_line, self.cursor_dot, self.readout):
            item.setZValue(10)
            self.plot.addItem(item, ignoreBounds=True)
            item.hide()
        self.widget.dropped.connect(self.add_signals)
        self.widget.left.connect(self._hover_left)
        self.widget.scene().sigMouseMoved.connect(self._mouse_moved)
        self.widget.scene().sigMouseClicked.connect(self._mouse_clicked)
        lay.addWidget(self.widget, 1)
        self.style(self.theme)
        # pyqtgraph builds its context menus and option panels as parentless windows. Hand them
        # to this plot, so Qt deletes them with it (deleting one first crashes the plot later).
        for w in QApplication.topLevelWidgets():
            if w.parent() is None and w is not self and not any(w is e for e in existing):
                w.setParent(self, w.windowFlags())

    # -- signals in --------------------------------------------------------------------------
    def add_signals(self, names: list[str]) -> None:
        if self.history is None:
            return
        for n in names:
            if n in self.history.units and n not in self.names:
                self.names.append(n)
        self._rebuild()

    def remove_signal(self, name: str) -> None:
        if name in self.names:
            self.names.remove(name)
            self._rebuild()

    def set_history(self, history: History | None) -> None:
        """A new run: keep the plotted signals that still exist."""
        self.history = history
        self.names = [n for n in self.names if history is not None and n in history.units]
        self._rebuild()

    def _series(self) -> list[tuple[str, str]]:
        """(curve key, legend name): time and histogram plot every signal; XY plots Y vs X."""
        if self.kind in ("xy", "scatter"):
            return [(n, n) for n in self.names[1:]]
        return [(n, n) for n in self.names]

    def _rebuild(self) -> None:
        for c in self.curves.values():
            self.plot.removeItem(c)
        self.legend.clear()
        self.curves = {}
        self.hint.setVisible(not self._complete())
        used: set[str] = set()
        for k, (key, name) in enumerate(self._series()):
            color = self._color(name, k, used)
            used.add(color)
            curve = pg.PlotDataItem(name=name)
            curve.setData(np.zeros(0), np.zeros(0))
            curve.color = color  # type: ignore[attr-defined]
            curve.setCurveClickable(True, width=tokens.SPACING[1])
            curve.sigClicked.connect(lambda _c, _ev=None, n=name: self._trace_clicked(n))
            self.plot.addItem(curve)
            self.curves[key] = curve
        # A one-trace plot is named by its axis label; more get a compact legend, top right.
        self.legend.setVisible(len(self.curves) > 1)
        self.legend.setColumnCount(max(1, min(len(self.curves), LEGEND_COLUMNS)))
        self._style_curves()
        self._labels()
        self._drawn_version = -1
        self.refresh()

    def _complete(self) -> bool:
        return len(self.names) >= (2 if self.kind in ("xy", "scatter") else 1)

    @staticmethod
    def _color(name: str, k: int, used: set[str]) -> str:
        state = name.rpartition(".")[2]
        if state in VECTOR_STATES and tokens.AXIS_COLORS[state[-1]] not in used:
            return tokens.AXIS_COLORS[state[-1]]  # §7.3: vector components X/Y/Z
        palette = [c for c in tokens.OKABE_ITO if c not in used] or list(tokens.OKABE_ITO)
        return palette[k % len(palette)]

    def _unit(self, name: str) -> str:
        return self.history.units.get(name, "") if self.history is not None else ""

    def _labels(self) -> None:
        p = self.plot
        names = self.names
        if self.kind == "time":
            p.setLabel("bottom", "Time [s]")
            units = {self._unit(n) for n in names}
            if len(names) == 1:
                p.setLabel("left", label(names[0], self._unit(names[0])))
            else:
                p.setLabel("left", label("Value", units.pop() if len(units) == 1 else ""))
        elif self.kind in ("xy", "scatter"):
            p.setLabel("bottom", label(names[0], self._unit(names[0])) if names else "X")
            ys = names[1:]
            units = {self._unit(n) for n in ys}
            if len(ys) == 1:
                p.setLabel("left", label(ys[0], self._unit(ys[0])))
            else:
                p.setLabel("left", label("Y", units.pop() if len(units) == 1 else ""))
        else:
            units = {self._unit(n) for n in names}
            only = names[0] if len(names) == 1 else "Value"
            p.setLabel("bottom", label(only, units.pop() if len(units) == 1 else ""))
            p.setLabel("left", "Count")
        self.plot.setAspectLocked(self.kind in ("xy", "scatter") and self._same_units())

    def _same_units(self) -> bool:
        """XY plots of positions in one unit keep a true aspect ratio (a top view isn't skewed)."""
        units = {self._unit(n) for n in self.names}
        return len(units) == 1 and units != {""}

    # -- data --------------------------------------------------------------------------------
    def refresh(self) -> None:
        """Redraw from the history if it changed (called at PLOT_FPS while data streams in)."""
        h = self.history
        if h is None or h.version == self._drawn_version:
            return
        self._drawn_version = h.version
        if h.n == 0 or not self._complete():
            for c in self.curves.values():
                c.setData(np.zeros(0), np.zeros(0))
            return
        if self.kind == "time":
            self._draw_time()
        elif self.kind in ("xy", "scatter"):
            cap = XY_POINTS if self.kind == "xy" else SCATTER_POINTS
            step = max(1, h.n // cap)
            x = h.signal(self.names[0])[::step]
            for key, c in self.curves.items():
                c.setData(x, h.signal(key)[::step])
        else:
            for key, c in self.curves.items():
                v = h.signal(key)
                v = v[np.isfinite(v)]
                if not len(v):
                    c.setData(np.zeros(0), np.zeros(0))
                    continue
                edges = np.histogram_bin_edges(v, bins="auto")
                if len(edges) - 1 > HISTOGRAM_BINS:
                    edges = np.histogram_bin_edges(v, bins=HISTOGRAM_BINS)
                counts, edges = np.histogram(v, bins=edges)
                c.setData(edges, counts, stepMode="center")
        self._place_cursor()

    def _draw_time(self) -> None:
        """DA-01: every trace thinned to a min and a max per pixel column (or two) of the
        visible span, so 10 x 100k samples redraw inside a 30 FPS frame."""
        h = self.history
        if h is None or not h.n or not self.curves:
            return
        vb = self.plot.vb
        t = h.t
        i0, i1 = 0, h.n
        if not vb.state["autoRange"][0]:  # zoomed or panned by hand: only what's in view
            x0, x1 = vb.viewRange()[0]
            i0 = max(0, int(np.searchsorted(t, x0)) - 1)
            i1 = min(h.n, int(np.searchsorted(t, x1)) + 1)
        bins = int(vb.width() * PEAKS_PER_PX)
        series = [h.signal(name)[i0:i1] for name in self.curves]
        if i0 == 0:  # following the whole run: reduce only the rows that arrived
            key = (id(h), h.edits, tuple(self.curves))
            x, ys = self._peaks.update(key, t[i0:i1], series, bins)
        else:
            x, ys = peak_decimate(t[i0:i1], series, bins)
        for c, y in zip(self.curves.values(), ys, strict=True):
            c.setData(x, y)

    def _x_range_changed(self) -> None:
        if not self.plot.vb.state["autoRange"][0]:
            self._draw_time()

    def set_cursor(self, index: int | None, hover: int | None = None) -> None:
        """The synced time cursor (DA-02) at history row `index` (None hides it)."""
        if index == self.cursor_index and hover == self.hover_index:
            return
        self.cursor_index, self.hover_index = index, hover
        self._place_cursor()

    def _place_cursor(self) -> None:
        h, i = self.history, self.cursor_index
        ok = h is not None and i is not None and 0 <= i < h.n and self._complete()
        self.cursor.setVisible(ok and self.kind in ("time", "histogram"))
        self.cursor_dot.setVisible(ok and self.kind in ("xy", "scatter"))
        if not ok:
            return
        assert h is not None and i is not None
        if self.kind == "time":
            self.cursor.setValue(h.time_of(i))
        elif self.kind == "histogram":
            self.cursor.setValue(float(h.signal(self.names[0])[i]))
        else:
            x = float(h.signal(self.names[0])[i])
            ys = [float(h.signal(n)[i]) for n in self.names[1:]]
            self.cursor_dot.setData([x] * len(ys), ys)

    # -- mouse: hover readout, click to seek or select ---------------------------------------
    def _view_x(self, scene_pos: QPointF) -> float | None:
        if not self.plot.sceneBoundingRect().contains(scene_pos):
            return None
        return float(self.plot.vb.mapSceneToView(scene_pos).x())

    def _mouse_moved(self, scene_pos: QPointF) -> None:
        h = self.history
        x = self._view_x(scene_pos)
        if self.kind != "time" or h is None or h.n == 0 or x is None or not self.names:
            self._hover_left()
            return
        i = h.index_at(x)
        t = h.time_of(i)
        self.hover_line.setValue(t)
        self.hover_line.show()
        lines = [f"t = {t:.3f} s"]
        for n in self.names:
            unit = self._unit(n)
            lines.append(f"{n}: {h.signal(n)[i]:+.4g}{' ' + unit if unit else ''}")
        self.readout.setText("\n".join(lines))
        (x0, x1), (y0, y1) = self.plot.vb.viewRange()
        right_half = t > (x0 + x1) / 2
        self.readout.setAnchor((1, 0) if right_half else (0, 0))
        self.readout.setPos(t, y1)
        self.readout.show()
        self.legend.hide()  # the readout names every trace; the legend would sit on top of it
        self.hover_time.emit(t)

    def _hover_left(self) -> None:
        if self.hover_line.isVisible() or self.readout.isVisible():
            self.hover_line.hide()
            self.readout.hide()
            self.legend.setVisible(len(self.curves) > 1)
            self.hover_time.emit(None)

    def _mouse_clicked(self, ev: Any) -> None:
        if ev.button() != Qt.MouseButton.LeftButton or self.kind != "time":
            return
        x = self._view_x(ev.scenePos())
        if x is not None and self.history is not None and self.history.n:
            self.seek_time.emit(x)

    def _trace_clicked(self, name: str) -> None:
        entity = self.entity_of(name)
        if entity is not None:
            self.selected.emit(entity)

    def set_selection(self, entity: str | None) -> None:
        """DS-06: the selected entity's traces are drawn bolder."""
        if entity != self.selection:
            self.selection = entity
            self._style_curves()

    # -- style (§7.6, DS-09) -------------------------------------------------------------------
    def style(self, theme_name: ThemeName) -> None:
        self.theme = theme_name
        c = lambda token: tokens.color(theme_name, token)  # noqa: E731
        self.widget.setBackground(c("bg.panel"))
        mono = QFont(tokens.FONT_MONO)
        mono.setPixelSize(tokens.FONT_SIZE["caption"])
        for side in ("left", "bottom"):
            axis = self.plot.getAxis(side)
            axis.setPen(pg.mkPen(c("border.subtle"), width=tokens.HAIRLINE))
            axis.setTextPen(pg.mkPen(c("text.secondary")))
            axis.setTickFont(mono)  # tabular figures for tick labels
            axis.enableAutoSIPrefix(False)  # values as logged, in the labelled unit
            axis.label.setFont(QFont(tokens.FONT_UI, tokens.FONT_SIZE["secondary"]))
            axis.labelStyle = {"color": c("text.secondary")}
            axis._updateLabel()
        self.plot.showGrid(x=True, y=True, alpha=tokens.PLOT_GRID_ALPHA)
        self.legend.setLabelTextColor(c("text.primary"))  # new entries
        for _sample, text in self.legend.items:  # and the ones already there
            text.setText(text.text, color=c("text.primary"))
        self.legend.setBrush(pg.mkBrush(_alpha(c("bg.panel"), 200)))
        self.legend.setPen(pg.mkPen(c("border.subtle")))
        self.cursor.setPen(pg.mkPen(c("accent"), width=tokens.PLOT_REF_WIDTH))
        self.hover_line.setPen(
            pg.mkPen(c("text.secondary"), width=tokens.PLOT_REF_WIDTH, style=Qt.PenStyle.DotLine)
        )
        self.cursor_dot.setBrush(pg.mkBrush(c("accent")))
        self.cursor_dot.setPen(pg.mkPen(c("bg.panel")))
        self.readout.setColor(c("text.primary"))
        self.readout.fill = pg.mkBrush(c("bg.elevated"))
        self.readout.border = pg.mkPen(c("border.subtle"))
        self.readout.setFont(mono)
        self._style_curves()
        self.plot.update()

    def _style_curves(self) -> None:
        for key, curve in self.curves.items():
            color = curve.color  # type: ignore[attr-defined]
            name = key
            bold = self.selection is not None and self.entity_of(name) == self.selection
            width = tokens.PLOT_SELECTED_WIDTH if bold else tokens.PLOT_LINE_WIDTH
            if self.kind == "scatter":
                curve.setPen(None)
                curve.setSymbol("o")
                curve.setSymbolSize(tokens.PLOT_SYMBOL_SIZE * (1.5 if bold else 1))
                curve.setSymbolBrush(pg.mkBrush(color))
                curve.setSymbolPen(None)
            elif self.kind == "histogram":
                curve.setPen(pg.mkPen(color, width=width))
                curve.setFillLevel(0)
                curve.setBrush(pg.mkBrush(_alpha(color, tokens.PLOT_FILL_ALPHA)))
            else:
                curve.setPen(pg.mkPen(color, width=width))

    # -- export (DA-07, DS-09) -------------------------------------------------------------
    def export_image(self, path: str | Path, theme_name: ThemeName = "light") -> Path:
        """PNG or SVG of this plot, in the light theme by default (ready for reports)."""
        import pyqtgraph.exporters as exporters

        path = Path(path)
        current = self.theme
        self.style(theme_name)
        self.readout.hide()
        self.hover_line.hide()
        self.legend.setVisible(len(self.curves) > 1)
        try:
            if path.suffix.lower() == ".svg":
                # Qt's own SVG writer: pyqtgraph's SVGExporter can't parse the paths Qt 6 emits.
                from qtpy.QtCore import QRectF
                from qtpy.QtGui import QPainter
                from qtpy.QtSvg import QSvgGenerator

                src = self.plot.sceneBoundingRect()
                gen = QSvgGenerator()
                gen.setFileName(str(path))
                gen.setSize(src.size().toSize())
                gen.setViewBox(QRectF(0, 0, src.width(), src.height()))
                gen.setTitle(self.title.text())
                painter = QPainter(gen)
                painter.fillRect(gen.viewBoxF(), self.widget.backgroundBrush())
                self.widget.scene().render(painter, gen.viewBoxF(), src)
                painter.end()
            else:
                exp = exporters.ImageExporter(self.plot)
                exp.parameters()["width"] = int(self.plot.width() * tokens.PLOT_EXPORT_SCALE)
                exp.export(str(path))
        finally:
            self.style(current)
        return path

    def _export_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Plot", f"{self.kind}-plot.png", "PNG image (*.png);;SVG image (*.svg)"
        )
        if path:
            self.export_image(path)

    def _close(self) -> None:
        self.closed.emit()


def _alpha(hex_color: str, alpha: int) -> QColor:
    q = QColor(hex_color)
    q.setAlpha(alpha)
    return q


class PlotPanel(QWidget):
    """The Plots dock: a toolbar to add plots and export data, and a stack of plots."""

    hover_time = Signal(object)
    seek_time = Signal(float)
    selected = Signal(object)
    export_data = Signal()

    def __init__(
        self, on_show_signals: Callable[[], object], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.history: History | None = None
        self.entities: set[str] = set()
        self.plots: list[PlotView] = []
        self.selection: str | None = None
        self._cursor: tuple[int | None, int | None] = (None, None)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QHBoxLayout()
        s = tokens.SPACING
        bar.setContentsMargins(s[1], s[0], s[1], s[0])
        bar.setSpacing(s[0])
        self.add_buttons: dict[str, QToolButton] = {}
        for kind, (ic, title) in KINDS.items():
            b = QToolButton(self)
            b.setIcon(icon(ic))
            b.setIconSize(QSize(tokens.ICON_SIZE_TOOLBAR, tokens.ICON_SIZE_TOOLBAR))
            b.setToolTip(f"Add a {title.lower()}")
            b.setAutoRaise(True)
            b.clicked.connect(lambda _c=False, k=kind: self.add_plot(k))
            bar.addWidget(b)
            self.add_buttons[kind] = b
        bar.addStretch(1)
        data = QToolButton(self)
        data.setIcon(icon("download"))
        data.setIconSize(QSize(tokens.ICON_SIZE_TOOLBAR, tokens.ICON_SIZE_TOOLBAR))
        data.setText("Export data…")
        data.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        data.setToolTip("Export every logged signal to CSV, Parquet, or MATLAB .mat")
        data.setAutoRaise(True)
        data.clicked.connect(lambda _c=False: self.export_data.emit())
        bar.addWidget(data)
        lay.addLayout(bar)

        self.stack = QStackedWidget(self)
        self.empty = EmptyState(
            "chart-line", "Drag a signal here to plot it.", "Show Signals", on_show_signals
        )
        self.splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.splitter.setChildrenCollapsible(False)
        self.stack.addWidget(self.empty)
        # Plots scroll rather than grow the dock: the 3D view keeps its share (§7.2).
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.splitter)
        self.stack.addWidget(self.scroll)
        lay.addWidget(self.stack, 1)

    # -- plots ---------------------------------------------------------------------------------
    def entity_of(self, signal: str) -> str | None:
        head, dot, _ = signal.partition(".")
        return head if dot and head in self.entities else None

    def add_plot(self, kind: str, names: list[str] | None = None) -> PlotView:
        view = PlotView(kind, self.entity_of, self.splitter)
        view.set_history(self.history)
        view.set_selection(self.selection)
        view.hover_time.connect(self.hover_time)
        view.seek_time.connect(self.seek_time)
        view.selected.connect(self.selected)
        view.closed.connect(lambda v=view: self.remove_plot(v))
        self.splitter.addWidget(view)
        self.plots.append(view)
        self.stack.setCurrentWidget(self.scroll)
        if names:
            view.add_signals(names)
        view.set_cursor(*self._cursor)
        return view

    def remove_plot(self, view: PlotView) -> None:
        self.plots.remove(view)
        view.setParent(None)  # type: ignore[call-overload]
        view.deleteLater()
        if not self.plots:
            self.stack.setCurrentWidget(self.empty)
        self.hover_time.emit(None)

    def plot_signals(self, names: list[str]) -> None:
        """Double-clicked signals go on the last time plot (a new one if there is none)."""
        target = next((p for p in reversed(self.plots) if p.kind == "time"), None)
        if target is None:
            self.add_plot("time", names)
        else:
            target.add_signals(names)

    # -- drops on the empty panel make a time plot (DA-03) ---------------------------------
    def dragEnterEvent(self, ev: QDragEnterEvent) -> None:  # noqa: N802 (Qt API)
        if decode(ev.mimeData()) and self.history is not None:
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dropEvent(self, ev: QDropEvent) -> None:  # noqa: N802 (Qt API)
        names = decode(ev.mimeData())
        if names:
            ev.acceptProposedAction()
            self.plot_signals(names)

    # -- run, cursor, selection, theme ---------------------------------------------------------
    def set_history(self, history: History | None) -> None:
        self.history = history
        self.entities = set(history.layout.state.entity_names) if history is not None else set()
        for p in self.plots:
            p.set_history(history)

    def refresh(self) -> None:
        for p in self.plots:
            p.refresh()

    def set_cursor(self, index: int | None, hover: int | None = None) -> None:
        self._cursor = (index, hover)
        for p in self.plots:
            p.set_cursor(index, hover)

    def set_selection(self, entity: str | None) -> None:
        self.selection = entity
        for p in self.plots:
            p.set_selection(entity)

    def set_theme(self, theme_name: ThemeName) -> None:
        for p in self.plots:
            p.style(theme_name)
