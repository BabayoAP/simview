"""The signal tree: every logged channel, grouped by entity, dragged onto plots (DA-03)."""

from __future__ import annotations

from collections.abc import Sequence

from qtpy.QtCore import QMimeData, Qt, Signal
from qtpy.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from simview.ipc.record import RowLayout

SIGNAL_MIME = "application/x-simview-signals"  # newline-separated signal names
NAME = Qt.ItemDataRole.UserRole  # leaf: signal name
ENTITY = Qt.ItemDataRole.UserRole + 1  # entity group: entity name


def encode(names: Sequence[str]) -> QMimeData:
    mime = QMimeData()
    mime.setData(SIGNAL_MIME, "\n".join(names).encode())
    mime.setText("\n".join(names))
    return mime


def decode(mime: QMimeData) -> list[str]:
    if not mime.hasFormat(SIGNAL_MIME):
        return []
    return [n for n in bytes(mime.data(SIGNAL_MIME).data()).decode().split("\n") if n]


class SignalTree(QTreeWidget):
    selected = Signal(object)  # entity name or None (DS-06)
    hovered = Signal(object)
    activated = Signal(list)  # signal names (double-click: plot them)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # keep the .q / .v suffix visible
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.setMouseTracking(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.groups: dict[str, QTreeWidgetItem] = {}
        self.leaves: dict[str, QTreeWidgetItem] = {}
        self._syncing = False
        self._hover: str | None = None
        self.itemSelectionChanged.connect(self._on_selection)
        self.itemDoubleClicked.connect(lambda item, _c: self.activated.emit(self._names([item])))
        self.itemEntered.connect(lambda item, _c: self._emit_hover(self._entity(item)))

    def load(self, layout: RowLayout) -> None:
        self.clear()
        self.groups, self.leaves = {}, {}
        entities = set(layout.state.entity_names)
        for name, unit in zip(layout.signals, layout.units, strict=True):
            head, _, state = name.partition(".")
            group_name = head if state and head in entities else "Channels"
            group = self.groups.get(group_name)
            if group is None:
                group = QTreeWidgetItem(self, [group_name, ""])
                if group_name in entities:
                    group.setData(0, ENTITY, group_name)
                self.groups[group_name] = group
            leaf = QTreeWidgetItem(group, [state if group_name != "Channels" else name, unit])
            leaf.setData(0, NAME, name)
            leaf.setToolTip(0, name)
            self.leaves[name] = leaf
        self.expandAll()

    # -- dragging and plotting -----------------------------------------------------------------
    @staticmethod
    def _names(items: Sequence[QTreeWidgetItem]) -> list[str]:
        """Signal names under the items (a group means all of its signals), in order."""
        out: list[str] = []
        for item in items:
            name = item.data(0, NAME)
            if name:
                out.append(name)
            else:
                out += [item.child(i).data(0, NAME) for i in range(item.childCount())]
        return list(dict.fromkeys(out))

    def mimeTypes(self) -> list[str]:  # noqa: N802 (Qt API)
        return [SIGNAL_MIME]

    def mimeData(self, items: Sequence[QTreeWidgetItem]) -> QMimeData:  # noqa: N802 (Qt API)
        return encode(self._names(items))

    # -- selection and hover (DS-06) ---------------------------------------------------------
    @staticmethod
    def _entity(item: QTreeWidgetItem | None) -> str | None:
        while item is not None:
            entity = item.data(0, ENTITY)
            if entity:
                return entity
            item = item.parent()
        return None

    def _on_selection(self) -> None:
        if self._syncing:
            return
        items = self.selectedItems()
        self.selected.emit(self._entity(items[0]) if items else None)

    def _emit_hover(self, name: str | None) -> None:
        if name != self._hover:
            self._hover = name
            self.hovered.emit(name)

    def leaveEvent(self, event: object) -> None:  # noqa: N802 (Qt API)
        self._emit_hover(None)
        super().leaveEvent(event)  # type: ignore[arg-type]

    def select(self, entity: str | None) -> None:
        """Show the shared selection without emitting it again."""
        current = self.selectedItems()
        if current and self._entity(current[0]) == entity:
            return
        self._syncing = True
        self.clearSelection()
        if entity in self.groups:
            self.groups[entity].setSelected(True)
            self.scrollToItem(self.groups[entity])
        self._syncing = False
