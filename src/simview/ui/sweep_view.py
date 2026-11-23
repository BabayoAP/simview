"""Monte Carlo results view (DA-06): the trials table, a histogram of any metric, and a scatter
of that metric against any parameter. Selecting a row marks its trial in both plots; clicking a
scatter point selects its row. Failed trials stay in the table (with their error) and are left
out of the plots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pyqtgraph as pg
from qtpy.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from qtpy.QtGui import QBrush, QColor, QFont
from qtpy.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from simview.runner.montecarlo import SweepResults
from simview.ui import theme
from simview.ui.plots.panel import HISTOGRAM_BINS
from simview.ui.theme import tokens
from simview.ui.theme.tokens import ThemeName

SORT_ROLE = Qt.ItemDataRole.UserRole + 1


def _fmt(value: Any) -> str:
    if isinstance(value, float | np.floating):
        return "—" if not np.isfinite(value) else f"{value:.4g}"
    return str(value)


class SweepModel(QAbstractTableModel):
    """The results table: trial, seed, parameters, metrics, status, error."""

    def __init__(self, res: SweepResults, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.res = res
        self.headers = ["trial", "seed", *res.params, *res.metrics, "status", "error"]
        self.data_ = {name: res[name] for name in self.headers}
        self.ok = res.ok
        self.error_color = QColor(tokens.color(theme.current_theme(), "state.error"))

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.res)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        name = self.headers[index.column()]
        value = self.data_[name][index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return _fmt(value)
        if role == SORT_ROLE:  # numbers sort as numbers, NaN last
            if isinstance(value, float | np.floating):
                return float(value) if np.isfinite(value) else float("inf")
            return value.item() if isinstance(value, np.generic) else value
        if role == Qt.ItemDataRole.TextAlignmentRole and name not in ("status", "error"):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and not self.ok[index.row()]:
            return QBrush(self.error_color)
        if role == Qt.ItemDataRole.ToolTipRole and name == "error" and value:
            return str(value)
        return None

    def headerData(  # noqa: N802 (Qt API)
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None


class SweepView(QDialog):
    """A sweep's results in their own window (non-modal)."""

    def __init__(self, res: SweepResults, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.res = res
        self.selected_trial: int | None = None
        scene = "sweep"
        if res.scene:  # templates are all `scene.py`: name the folder too
            sp = Path(res.scene)
            scene = f"{sp.parent.name}/{sp.name}" if sp.name == "scene.py" else sp.name
        self.setWindowTitle(f"Sweep results — {scene} ({res.path.parent.name})")
        self.resize(*tokens.SWEEP_VIEW_SIZE)
        s = tokens.SPACING
        lay = QVBoxLayout(self)
        lay.setContentsMargins(s[2], s[2], s[2], s[2])
        lay.setSpacing(s[2])

        failed = int((~res.ok).sum())
        mins, secs = divmod(int(round(res.wall_s)), 60)
        took = f"{mins} min {secs} s" if mins else f"{secs} s"
        self.summary = QLabel(
            f"{scene}  ·  {len(res)} trials  ·  {failed} failed  ·  "
            f"{res.duration:g} s each  ·  took {took}",
            self,
        )
        self.summary.setProperty("role", "secondary")
        lay.addWidget(self.summary)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        lay.addWidget(split, 1)

        self.model = SweepModel(res, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(SORT_ROLE)
        self.table = QTableView(split)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        mono = QFont(tokens.FONT_MONO)
        mono.setPixelSize(tokens.FONT_SIZE["secondary"])
        self.table.setFont(mono)
        self.table.resizeColumnsToContents()
        self.table.selectionModel().selectionChanged.connect(self._row_selected)

        right = QWidget(split)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(s[1])
        pick = QHBoxLayout()
        pick.setSpacing(s[1])
        self.metric_box = QComboBox(right)
        self.metric_box.addItems(res.metrics)
        self.param_box = QComboBox(right)
        self.param_box.addItems([*res.params, "trial"])
        for text, box in (("Metric", self.metric_box), ("vs", self.param_box)):
            lbl = QLabel(text, right)
            lbl.setProperty("role", "secondary")
            pick.addWidget(lbl)
            pick.addWidget(box, 1)
        rl.addLayout(pick)
        self.hist = pg.PlotWidget(right)
        self.scatter = pg.PlotWidget(right)
        for w in (self.hist, self.scatter):
            w.setMinimumHeight(tokens.PLOT_MIN_HEIGHT)
            w.setMenuEnabled(False)
            rl.addWidget(w, 1)
        self.bars = pg.PlotDataItem()
        self.hist.addItem(self.bars)
        self.marker = pg.InfiniteLine(angle=90, movable=False)
        self.marker.setVisible(False)
        self.hist.addItem(self.marker)
        self.points = pg.ScatterPlotItem()
        self.points.sigClicked.connect(self._point_clicked)
        self.scatter.addItem(self.points)
        self.chosen = pg.ScatterPlotItem()
        self.scatter.addItem(self.chosen)
        self.note = QLabel("", right)
        self.note.setProperty("role", "secondary")
        rl.addWidget(self.note)
        split.addWidget(self.table)
        split.addWidget(right)
        split.setSizes(list(tokens.SWEEP_VIEW_SPLIT))

        self.metric_box.currentTextChanged.connect(lambda _t: self.redraw())
        self.param_box.currentTextChanged.connect(lambda _t: self.redraw())
        self.style(theme.current_theme())
        self.redraw()

    # -- drawing -------------------------------------------------------------------------------
    @property
    def metric(self) -> str:
        return self.metric_box.currentText()

    @property
    def param(self) -> str:
        return self.param_box.currentText()

    def _values(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(trial, x, y) of the trials that finished with a finite metric."""
        if not self.metric:
            return np.zeros(0, int), np.zeros(0), np.zeros(0)
        y = self.res[self.metric].astype(np.float64)
        x = self.res[self.param].astype(np.float64)
        keep = self.res.ok & np.isfinite(y) & np.isfinite(x)
        return self.res["trial"][keep], x[keep], y[keep]

    def redraw(self) -> None:
        trials, x, y = self._values()
        self.plotted_trials = trials
        if len(y):
            edges = np.histogram_bin_edges(y, bins="auto")
            if len(edges) - 1 > HISTOGRAM_BINS:
                edges = np.histogram_bin_edges(y, bins=HISTOGRAM_BINS)
            counts, edges = np.histogram(y, bins=edges)
            self.bars.setData(edges, counts, stepMode="center")
        else:
            self.bars.setData(np.zeros(0), np.zeros(0))
        self.points.setData(x=x, y=y, data=trials)
        self.hist.setLabel("bottom", self.metric)
        self.hist.setLabel("left", "trials")
        self.scatter.setLabel("bottom", self.param)
        self.scatter.setLabel("left", self.metric)
        left_out = len(self.res) - len(y)
        if len(y):
            self.note.setText(
                f"{self.metric}: mean {np.mean(y):.4g}, std {np.std(y):.4g}, "
                f"min {np.min(y):.4g}, max {np.max(y):.4g}"
                + (f"  ·  {left_out} trials not plotted (failed or no value)" if left_out else "")
            )
        else:
            self.note.setText("No trial has a value for this metric.")
        self._mark()

    def _mark(self) -> None:
        trial = self.selected_trial
        idx = np.nonzero(self.plotted_trials == trial)[0] if trial is not None else []
        if len(idx):
            _, x, y = self._values()
            i = int(idx[0])
            self.chosen.setData(x=[x[i]], y=[y[i]])
            self.marker.setValue(y[i])
            self.marker.setVisible(True)
        else:
            self.chosen.setData(x=[], y=[])
            self.marker.setVisible(False)

    # -- selection -----------------------------------------------------------------------------
    def select_trial(self, trial: int) -> None:
        """Select a trial's row (and mark it in the plots)."""
        rows = np.nonzero(self.res["trial"] == trial)[0]
        if not len(rows):
            return
        src = self.model.index(int(rows[0]), 0)
        self.table.selectRow(self.proxy.mapFromSource(src).row())
        self.table.scrollTo(self.proxy.mapFromSource(src))

    def _row_selected(self, *_args: Any) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.selected_trial = None
        else:
            src = self.proxy.mapToSource(rows[0])
            self.selected_trial = int(self.res["trial"][src.row()])
        self._mark()

    def _point_clicked(self, _item: Any, points: Any, *_args: Any) -> None:
        if len(points):
            self.select_trial(int(points[0].data()))

    # -- style (§7.6) --------------------------------------------------------------------------
    def style(self, theme_name: ThemeName) -> None:
        c = lambda token: tokens.color(theme_name, token)  # noqa: E731
        mono = QFont(tokens.FONT_MONO)
        mono.setPixelSize(tokens.FONT_SIZE["caption"])
        for w in (self.hist, self.scatter):
            w.setBackground(c("bg.panel"))
            plot = w.getPlotItem()
            plot.showGrid(x=True, y=True, alpha=tokens.PLOT_GRID_ALPHA)
            for side in ("left", "bottom"):
                axis = plot.getAxis(side)
                axis.setPen(pg.mkPen(c("border.subtle"), width=tokens.HAIRLINE))
                axis.setTextPen(pg.mkPen(c("text.secondary")))
                axis.setTickFont(mono)
                axis.enableAutoSIPrefix(False)
                axis.label.setFont(QFont(tokens.FONT_UI, tokens.FONT_SIZE["secondary"]))
                axis.labelStyle = {"color": c("text.secondary")}
                axis._updateLabel()
        accent = QColor(c("accent"))
        fill = QColor(accent)
        fill.setAlpha(tokens.PLOT_FILL_ALPHA)
        self.bars.setPen(pg.mkPen(accent, width=tokens.PLOT_LINE_WIDTH))
        self.bars.setFillLevel(0)
        self.bars.setBrush(pg.mkBrush(fill))
        self.points.setPen(None)
        self.points.setBrush(pg.mkBrush(accent))
        self.points.setSize(tokens.PLOT_SYMBOL_SIZE * 1.5)
        self.chosen.setPen(pg.mkPen(c("text.primary"), width=tokens.PLOT_REF_WIDTH))
        self.chosen.setBrush(pg.mkBrush(c("state.warning")))
        self.chosen.setSize(tokens.PLOT_SYMBOL_SIZE * 3)
        self.marker.setPen(pg.mkPen(c("state.warning"), width=tokens.PLOT_REF_WIDTH))
        self.model.error_color = QColor(c("state.error"))
