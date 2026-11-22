"""Panels that show a loaded scene: scene tree and inspector (VP-06, DS-06).

Selection and hover are synced through `select` / `set_hover` and the `selected` / `hovered`
signals, so the viewport, tree, inspector, signal tree, and plots always agree (DS-06).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QColor, QFont
from qtpy.QtWidgets import (
    QFormLayout,
    QLabel,
    QScrollArea,
    QSlider,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from simview.ipc.protocol import Description
from simview.ipc.shm import Frame
from simview.ui import theme
from simview.ui.panels import EmptyState
from simview.ui.theme import tokens

GROUPS = (("robot", "Robots"), ("body", "Objects"), ("entity", "Models"))
SLIDER_RESOLUTION = 1000  # slider steps per radian or metre


class SceneTree(QTreeWidget):
    selected = Signal(object)
    hovered = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setMouseTracking(True)
        self.items: dict[str, QTreeWidgetItem] = {}
        self._syncing = False
        self._hover: str | None = None
        self.itemSelectionChanged.connect(self._on_selection)
        self.itemEntered.connect(
            lambda item, _col: self._emit_hover(item.data(0, Qt.ItemDataRole.UserRole))
        )

    def load(self, desc: Description) -> None:
        self.clear()
        self.items = {}
        for kind, title in GROUPS:
            members = [e for e in desc.entities if e.kind == kind]
            if not members:
                continue
            group = QTreeWidgetItem(self, [title])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for e in members:
                item = QTreeWidgetItem(group, [e.name])
                item.setData(0, Qt.ItemDataRole.UserRole, e.name)
                self.items[e.name] = item
        if desc.targets:
            group = QTreeWidgetItem(self, ["Targets"])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for name in desc.targets:
                QTreeWidgetItem(group, [name]).setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.expandAll()

    def _on_selection(self) -> None:
        if self._syncing:
            return
        items = self.selectedItems()
        name = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
        self.selected.emit(name)

    def _emit_hover(self, name: str | None) -> None:
        if name != self._hover:
            self.set_hover(name)
            self.hovered.emit(name)

    def leaveEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        self._emit_hover(None)
        super().leaveEvent(event)  # type: ignore[arg-type]

    def select(self, name: str | None) -> None:
        self._syncing = True
        try:
            self.clearSelection()
            if name in self.items:
                self.items[name].setSelected(True)
                self.scrollToItem(self.items[name])
        finally:
            self._syncing = False

    def set_hover(self, name: str | None) -> None:
        """Hover from the viewport shows as an accent tint on the row (§7.5)."""
        self._hover = name
        tint = QColor(tokens.color(theme.current_theme(), "accent"))
        tint.setAlphaF(tokens.HOVER_OPACITY / 2)
        for n, item in self.items.items():
            item.setBackground(0, tint if n == name else QColor(0, 0, 0, 0))


EMPTY_HINT = "Select an entity to see its properties."


class Inspector(QScrollArea):
    """VP-06: the selected entity's pose, velocity, and every state, live. Robots get one
    slider per joint, which follows the simulation (UC-3)."""

    def __init__(
        self, parent: QWidget | None = None, on_empty: Callable[[], object] | None = None
    ) -> None:
        """`on_empty` is the empty state's button action (§7.8), e.g. show the scene tree."""
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.name: str | None = None
        self.desc: Description | None = None
        self.values: dict[str, QLabel] = {}
        self.sliders: dict[str, QSlider] = {}
        self._body = QWidget()
        self.setWidget(self._body)
        self.empty = EmptyState(
            "sliders-horizontal",
            EMPTY_HINT,
            "Show Scene Tree",
            on_empty or (lambda: None),
        )
        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.hide()
        self.form = QFormLayout()
        outer = QVBoxLayout(self._body)
        outer.addWidget(self.empty, 1)
        outer.addWidget(self.title)
        outer.addLayout(self.form)
        outer.addStretch(1)

    def show_entity(self, desc: Description | None, name: str | None) -> None:
        self.desc, self.name = desc, name
        while self.form.rowCount():
            self.form.removeRow(0)
        self.values, self.sliders = {}, {}
        info = None if desc is None else next((e for e in desc.entities if e.name == name), None)
        self.empty.setVisible(info is None)
        self.title.setVisible(info is not None)
        if info is None:
            return
        self.title.setText(f"{info.name}  ·  {info.kind}")
        mono = QFont(tokens.FONT_MONO)
        mono.setPixelSize(tokens.FONT_SIZE["secondary"])
        if info.has_marker:
            self._row("position [m]", mono)
        for state in info.state_names:
            joint = info.kind == "robot" and state.endswith(".q")
            if joint:
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(-int(np.pi * SLIDER_RESOLUTION), int(np.pi * SLIDER_RESOLUTION))
                slider.setEnabled(False)  # follows the sim; dragging joints is the gizmo's job
                self.sliders[state] = slider
                self.form.addRow(state.removesuffix(".q"), slider)
            self._row(state, mono)

    def _row(self, label: str, font: QFont) -> None:
        value = QLabel("—")
        value.setFont(font)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.values[label] = value
        self.form.addRow(label, value)

    def update_frame(self, frame: Frame) -> None:
        if self.name is None or self.name not in frame.states:
            return
        x = frame.states[self.name]
        info = next(e for e in self.desc.entities if e.name == self.name)  # type: ignore[union-attr]
        if "position [m]" in self.values and self.name in frame.markers:
            p = frame.markers[self.name]
            self.values["position [m]"].setText(f"{p[0]:+.3f} {p[1]:+.3f} {p[2]:+.3f}")
        for state, v in zip(info.state_names, x, strict=True):
            self.values[state].setText(f"{v:+.4f}")
            if state in self.sliders:
                wrapped = (v + np.pi) % (2 * np.pi) - np.pi
                self.sliders[state].setValue(int(wrapped * SLIDER_RESOLUTION))


class NoViewport(QWidget):
    """Stand-in when OpenGL isn't available (e.g. a headless test run). The simulation, panels,
    and console still work; only the 3D view is missing."""

    selected = Signal(object)
    hovered = Signal(object)
    target_moved = Signal(str, object)
    body_moved = Signal(str, object, object)

    def __init__(self, reason: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        label = QLabel(f"3D view unavailable: {reason}")
        label.setProperty("role", "secondary")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        QVBoxLayout(self).addWidget(label)
        self.desc: Description | None = None
        self.frame: Frame | None = None
        self.selection: str | None = None
        self.draws: list[tuple] = []
        self.trails: dict[str, np.ndarray] | None = None
        self.voxels: np.ndarray | None = None  # VW-08: the voxel centres it would draw
        self.voxel_res = 0.0
        self.geometry_mode = "both"

    def load(self, desc: Description) -> None:
        self.desc = desc

    def set_voxels(self, centers: np.ndarray | None, res: float = 0.0) -> None:
        self.voxels = None if centers is None or len(centers) == 0 else centers
        self.voxel_res = res

    @property
    def voxel_count(self) -> int:
        return 0 if self.voxels is None else len(self.voxels)

    def set_geometry_mode(self, mode: str) -> None:
        if mode not in ("both", "perceived", "true"):
            raise ValueError(f"unknown geometry mode {mode!r}")
        self.geometry_mode = mode

    def update_frame(self, frame: Frame, trails: dict[str, np.ndarray] | None = None) -> None:
        self.frame = frame
        self.trails = trails

    def set_draws(self, draws: list[tuple]) -> None:
        self.draws = draws

    def select(self, name: str | None, emit: bool = False) -> None:
        self.selection = name
        if emit:
            self.selected.emit(name)

    def set_hover(self, name: str | None, emit: bool = False) -> None:
        pass

    def render(self) -> None:
        pass

    def set_theme(self, theme_name: str) -> None:
        pass

    def key(self, text: str, code: int = 0) -> bool:
        return False

    def close_viewport(self) -> None:
        pass
