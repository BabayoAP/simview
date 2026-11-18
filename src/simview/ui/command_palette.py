"""Command palette (DS-07): Ctrl/Cmd+K, fuzzy search over every registered action."""

from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtGui import QAction, QKeyEvent
from qtpy.QtWidgets import (
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from simview.ui.actions import ActionRegistry, fuzzy_filter
from simview.ui.theme import tokens

PALETTE_MAX_ROWS = 10


class CommandPalette(QFrame):
    def __init__(self, registry: ActionRegistry, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("CommandPalette")
        self._registry = registry
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Type a command…")
        self.results = QListWidget(self)
        self.results.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QVBoxLayout(self)
        pad = tokens.SPACING[1]
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(pad)
        layout.addWidget(self.search)
        layout.addWidget(self.results)

        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self.run_current)
        self.results.itemActivated.connect(lambda _item: self.run_current())
        self.search.installEventFilter(self)

    def _labels(self) -> dict[str, QAction]:
        out: dict[str, QAction] = {}
        for a in self._registry.all():
            if a.isEnabled():
                out[f"{a.data()}: {a.text().replace('&', '')}"] = a
        return out

    def refresh(self) -> None:
        labels = self._labels()
        self.results.clear()
        for label in fuzzy_filter(self.search.text(), list(labels)):
            action = labels[label]
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, action.objectName())
            shortcut = action.shortcut().toString(action.shortcut().SequenceFormat.NativeText)
            if shortcut:
                item.setToolTip(shortcut)
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)

    def visible_action_ids(self) -> list[str]:
        return [
            self.results.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.results.count())
        ]

    def open(self) -> None:
        self.search.clear()
        self.refresh()
        host = self.parentWidget()
        rows = min(PALETTE_MAX_ROWS, max(self.results.count(), 1))
        height = tokens.CONTROL_HEIGHT * (rows + 1) + tokens.SPACING[4]
        self.resize(tokens.PALETTE_WIDTH, height)
        if host is not None:
            top_left = host.mapToGlobal(host.rect().topLeft())
            x = top_left.x() + (host.width() - tokens.PALETTE_WIDTH) // 2
            self.move(x, top_left.y() + tokens.SPACING[5] * 3)
        self.show()
        self.search.setFocus()

    def run_current(self) -> None:
        item = self.results.currentItem()
        if item is None:
            return
        action_id = item.data(Qt.ItemDataRole.UserRole)
        self.hide()
        self._registry.get(action_id).trigger()

    def eventFilter(self, obj: object, event: object) -> bool:  # noqa: N802 (Qt API)
        if isinstance(event, QKeyEvent) and event.type() == QKeyEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                step = 1 if key == Qt.Key.Key_Down else -1
                row = (self.results.currentRow() + step) % max(self.results.count(), 1)
                self.results.setCurrentRow(row)
                return True
            if key == Qt.Key.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, event)
