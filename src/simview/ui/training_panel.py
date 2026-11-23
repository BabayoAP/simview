"""Training panel (ML-03, ML-04): live curves of a training run, and click-to-replay of the
episodes it recorded.

It follows the newest `train-*` folder in the run folder (see `simview.rl.metrics`), rereading
it a few times a second while training appends. Each metric is a checkable row; the checked ones
are plotted against the training step. On the episode-return curve, recorded episodes are
drawn as larger points: clicking one replays that episode in the viewport.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pyqtgraph as pg
from qtpy.QtCore import Qt, QTimer, Signal
from qtpy.QtGui import QColor, QFont
from qtpy.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from simview.rl.metrics import EPISODE_RETURN, EPISODE_SUCCESS, TrainingRun, latest_training_dir
from simview.ui import theme
from simview.ui.panels import EmptyState
from simview.ui.runs_panel import _button
from simview.ui.theme import tokens
from simview.ui.theme.tokens import ThemeName

POLL_MS = 1000  # how often the training folder is reread
DEFAULT_CHECKED = (EPISODE_RETURN, "rollout/ep_rew_mean")  # plotted when a run first appears
SUCCESS_WINDOW = 100  # episodes the header's success rate averages over


class TrainingPanel(QWidget):
    replay_requested = Signal(str)  # a recorded episode's log file

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runs_folder: Path | None = None
        self.run: TrainingRun | None = None
        self.pinned = False  # a folder opened by hand isn't replaced by a newer one
        self.items: dict[str, pg.PlotDataItem] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget(self)
        lay.addWidget(self.stack)
        self.empty = EmptyState(
            "brain",
            "Train with sv.make_vec_env(..., record_every=N) to see curves here.",
            "Open Training Folder…",
            self.open_folder_dialog,
        )
        self.stack.addWidget(self.empty)

        body = QWidget(self)
        v = QVBoxLayout(body)
        s = tokens.SPACING
        v.setContentsMargins(s[1], s[0], s[1], s[0])
        v.setSpacing(s[0])
        bar = QHBoxLayout()
        self.summary = QLabel(body)
        self.summary.setObjectName("Secondary")
        bar.addWidget(self.summary, 1)
        self.open_button = _button(body, "folder-open", "Show another training folder")
        self.open_button.clicked.connect(lambda _c=False: self.open_folder_dialog())
        bar.addWidget(self.open_button)
        v.addLayout(bar)
        split = QSplitter(Qt.Orientation.Horizontal, body)
        self.metrics = QListWidget(split)
        self.metrics.itemChanged.connect(lambda _i: self.redraw())
        self.plot = pg.PlotWidget(split)
        self.plot.setMinimumHeight(tokens.PLOT_MIN_HEIGHT)
        self.plot.setLabel("bottom", "step")
        # §7.6, as in the Plots panel: top right, shown only for 2+ curves (one curve is named
        # by its axis label), so it doesn't sit on the curve.
        self.legend = self.plot.addLegend(offset=(-s[1], s[1]))
        self.recorded = pg.ScatterPlotItem()  # recorded episodes: click to replay
        self.recorded.sigClicked.connect(self._point_clicked)
        self.recorded.setZValue(10)
        self.plot.addItem(self.recorded)
        split.setStretchFactor(1, 1)
        split.setSizes(list(tokens.TRAINING_SPLIT))
        v.addWidget(split, 1)
        self.stack.addWidget(body)

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.style(theme.current_theme())

    # -- folders ---------------------------------------------------------------------------------
    def set_runs_folder(self, folder: Path) -> None:
        """Follow the newest training run in this run folder."""
        self.runs_folder = Path(folder)
        self.poll()

    def open_folder_dialog(self) -> None:
        start = str(self.runs_folder or Path.cwd())
        path = QFileDialog.getExistingDirectory(self, "Open Training Folder", start)
        if path:
            self.show_folder(Path(path), pinned=True)

    def show_folder(self, folder: Path, *, pinned: bool = False) -> None:
        self.pinned = pinned
        self.run = TrainingRun(folder)
        self.metrics.clear()
        for item in self.items.values():
            self.plot.removeItem(item)
        self.items.clear()
        self.stack.setCurrentIndex(1)
        self.poll()

    def poll(self) -> None:
        if not self.pinned and self.runs_folder is not None:
            latest = latest_training_dir(self.runs_folder)
            if latest is not None and (self.run is None or self.run.folder != latest):
                self.show_folder(latest)
                return
        if self.run is not None and self.run.refresh():
            self._sync_metrics()
            self.redraw()

    # -- drawing ---------------------------------------------------------------------------------
    def _sync_metrics(self) -> None:
        assert self.run is not None
        have = {self.metrics.item(i).text() for i in range(self.metrics.count())}
        self.metrics.blockSignals(True)
        for name in self.run.names():
            if name in have:
                continue
            item = QListWidgetItem(name, self.metrics)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = name in DEFAULT_CHECKED
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.metrics.sortItems()
        self.metrics.blockSignals(False)

    def checked(self) -> list[str]:
        out = []
        for i in range(self.metrics.count()):
            item = self.metrics.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.text())
        return out

    def redraw(self) -> None:
        if self.run is None:
            return
        run, names = self.run, self.checked()
        for name in list(self.items):
            if name not in names:
                self.plot.removeItem(self.items.pop(name))
        for k, name in enumerate(names):
            steps, values = run.series[name].arrays()
            item = self.items.get(name)
            if item is None:
                color = tokens.OKABE_ITO[k % len(tokens.OKABE_ITO)]
                item = self.plot.plot([], [], name=name)
                item.setPen(pg.mkPen(color, width=tokens.PLOT_LINE_WIDTH))
                self.items[name] = item
            item.setData(steps, values)
        self.legend.setVisible(len(names) > 1)
        # The short name ("return" for "episode/return"): a short dock clips the long one, and
        # the full name stays checked in the list beside the plot.
        self.plot.setLabel("left", names[0].rsplit("/", 1)[-1] if len(names) == 1 else "")
        rec = run.recorded() if EPISODE_RETURN in names else []
        self.recorded.setData(
            x=[e["step"] for e in rec],
            y=[e["return"] for e in rec],
            data=[e["log"] for e in rec],
        )
        self.recorded.setVisible(bool(rec))
        self._update_summary()

    def _update_summary(self) -> None:
        assert self.run is not None
        run = self.run
        parts = [run.folder.name, f"{len(run.episodes)} episodes"]
        if EPISODE_SUCCESS in run.series:
            last = run.series[EPISODE_SUCCESS].values[-SUCCESS_WINDOW:]
            parts.append(f"success {100 * float(np.mean(last)):.0f}% (last {len(last)})")
        n_rec = len(run.recorded())
        if n_rec:
            parts.append(f"{n_rec} recorded, click a large point to replay")
        self.summary.setText(" · ".join(parts))

    def _point_clicked(self, _item: Any, points: Any, *_args: Any) -> None:  # noqa: ANN401
        if len(points):
            self.replay_requested.emit(str(points[0].data()))

    def style(self, theme_name: ThemeName) -> None:
        c = lambda token: tokens.color(theme_name, token)  # noqa: E731
        self.plot.setBackground(c("bg.panel"))
        self.plot.showGrid(x=True, y=True, alpha=tokens.PLOT_GRID_ALPHA)
        mono = QFont(tokens.FONT_MONO)
        mono.setPixelSize(tokens.FONT_SIZE["caption"])
        for side in ("left", "bottom"):
            axis = self.plot.getAxis(side)
            axis.setPen(pg.mkPen(c("border.subtle"), width=tokens.HAIRLINE))
            axis.setTextPen(pg.mkPen(c("text.secondary")))
            axis.setTickFont(mono)
            axis.label.setFont(QFont(tokens.FONT_UI, tokens.FONT_SIZE["secondary"]))
        self.legend.setLabelTextColor(c("text.primary"))
        for _sample, text in self.legend.items:
            text.setText(text.text, color=c("text.primary"))
        fill = QColor(c("bg.panel"))
        fill.setAlpha(tokens.LEGEND_ALPHA)
        self.legend.setBrush(pg.mkBrush(fill))
        self.legend.setPen(pg.mkPen(c("border.subtle")))
        self.recorded.setPen(pg.mkPen(c("text.primary"), width=tokens.PLOT_REF_WIDTH))
        self.recorded.setBrush(pg.mkBrush(c("state.warning")))
        self.recorded.setSize(tokens.PLOT_SYMBOL_SIZE * 2.5)
