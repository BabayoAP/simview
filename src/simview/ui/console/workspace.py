"""The workspace browser (SC-03): console variables with name, type, shape, and a value
preview. Double-click a NumPy array to open it in a table viewer."""

from __future__ import annotations

import types
from collections.abc import Mapping
from typing import Any

import numpy as np
from qtpy.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt, Signal
from qtpy.QtGui import QFont
from qtpy.QtWidgets import (
    QDialog,
    QHeaderView,
    QLabel,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from simview.ui.theme import tokens

COLUMNS = ("Name", "Value", "Shape", "Type")  # Value first: the side panel is narrow
VALUE = 1
NAME_ROLE = Qt.ItemDataRole.UserRole

_Index = QModelIndex | QPersistentModelIndex


def shape_of(value: Any) -> str:
    shape = getattr(value, "shape", None)
    if isinstance(shape, tuple):
        return "×".join(str(n) for n in shape) if shape else "scalar"
    if isinstance(value, str | bytes):
        return ""
    try:
        return str(len(value))
    except TypeError:
        return ""


def type_of(value: Any) -> str:
    if isinstance(value, np.ndarray):
        if value.dtype.names:
            return "ndarray (record)"
        return f"ndarray {value.dtype}"
    return type(value).__name__


def preview(value: Any, limit: int = tokens.WORKSPACE_PREVIEW_CHARS) -> str:
    if isinstance(value, np.ndarray):
        if value.dtype.names:
            text = "[" + ", ".join(value.dtype.names) + "]"
        else:
            with np.printoptions(precision=4, threshold=8, edgeitems=2, linewidth=10_000):
                text = np.array2string(value, separator=", ")
    else:
        try:
            text = repr(value)
        except Exception:  # noqa: BLE001 - a broken __repr__ must not break the browser
            text = f"<{type(value).__name__}>"
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def visible(namespace: Mapping[str, Any], hidden: Mapping[str, Any]) -> list[str]:
    """User variables: not hidden, not private, not modules, functions, or classes."""
    out = []
    for name, value in namespace.items():
        if name.startswith("_") or (name in hidden and hidden[name] is value):
            continue
        if isinstance(value, types.ModuleType | types.FunctionType | type):
            continue
        out.append(name)
    return sorted(out, key=str.lower)


class WorkspaceBrowser(QTreeWidget):
    open_array = Signal(str)  # the variable's name

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(len(COLUMNS))
        self.setHeaderLabels(list(COLUMNS))
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)
        header = self.header()
        header.setStretchLastSection(True)  # Type takes what's left
        for i in range(len(COLUMNS) - 1):
            mode = QHeaderView.ResizeMode.ResizeToContents
            if i == VALUE:
                mode = QHeaderView.ResizeMode.Interactive
            header.setSectionResizeMode(i, mode)
        header.resizeSection(VALUE, tokens.WORKSPACE_VALUE_WIDTH)
        mono = QFont(tokens.FONT_MONO)
        mono.setPixelSize(tokens.FONT_SIZE["secondary"])
        self.mono = mono
        self.values: dict[str, Any] = {}
        self.itemDoubleClicked.connect(self._double_clicked)

    def refresh(self, namespace: Mapping[str, Any], hidden: Mapping[str, Any]) -> None:
        names = visible(namespace, hidden)
        self.values = {n: namespace[n] for n in names}
        selected = {i.data(0, NAME_ROLE) for i in self.selectedItems()}
        self.clear()
        for name in names:
            value = namespace[name]
            item = QTreeWidgetItem(self, [name, preview(value), shape_of(value), type_of(value)])
            item.setData(0, NAME_ROLE, name)
            item.setFont(VALUE, self.mono)
            item.setToolTip(VALUE, preview(value, limit=10 * tokens.WORKSPACE_PREVIEW_CHARS))
            if isinstance(value, np.ndarray):
                item.setToolTip(0, "Double-click to open in a table")
            item.setSelected(name in selected)

    def names(self) -> list[str]:
        return [self.topLevelItem(i).text(0) for i in range(self.topLevelItemCount())]

    def row(self, name: str) -> dict[str, str]:
        """The row shown for a variable, by column title."""
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.text(0) == name:
                return {title: item.text(c) for c, title in enumerate(COLUMNS)}
        raise KeyError(name)

    def _double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        name = item.data(0, NAME_ROLE)
        if isinstance(self.values.get(name), np.ndarray):
            self.open_array.emit(name)


class ArrayModel(QAbstractTableModel):
    """A NumPy array as a table: 0-D and 1-D as one column, 2-D as is, higher dimensions
    flattened to (first axis, rest); record arrays get one column per field."""

    def __init__(self, array: np.ndarray, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fields: tuple[str, ...] = array.dtype.names or ()
        if self.fields:
            self.array = np.atleast_1d(array).ravel()
        elif array.ndim < 2:
            self.array = np.atleast_1d(array).reshape(-1, 1)
        else:
            self.array = array.reshape(array.shape[0], -1)
        cols = len(self.fields) or self.array.shape[1]
        rows = max(1, tokens.ARRAY_VIEWER_MAX_CELLS // max(1, cols))
        self.truncated = len(self.array) > rows
        self.array = self.array[:rows]

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: N802, B008 (Qt API)
        return 0 if parent.isValid() else len(self.array)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: N802, B008 (Qt API)
        if parent.isValid():
            return 0
        return len(self.fields) or int(self.array.shape[1])

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role != Qt.ItemDataRole.DisplayRole or not index.isValid():
            return None
        r, c = index.row(), index.column()
        v = self.array[r][self.fields[c]] if self.fields else self.array[r, c]
        if isinstance(v, float | np.floating):
            return f"{v:.6g}"
        return str(v)

    def headerData(  # noqa: N802 (Qt API)
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and self.fields:
            return self.fields[section]
        return str(section)  # zero-based, like NumPy


class ArrayViewer(QDialog):
    def __init__(self, name: str, array: np.ndarray, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{name}  ({type_of(array)}, {shape_of(array)})")
        self.resize(*tokens.ARRAY_VIEWER_SIZE)
        self.model = ArrayModel(array, self)
        self.table = QTableView(self)
        self.table.setModel(self.model)
        mono = QFont(tokens.FONT_MONO)
        mono.setPixelSize(tokens.FONT_SIZE["secondary"])
        self.table.setFont(mono)
        layout = QVBoxLayout(self)
        pad = tokens.SPACING[1]
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.addWidget(self.table, 1)
        if self.model.truncated:
            note = QLabel(f"Showing the first {self.model.rowCount()} rows.", self)
            note.setProperty("role", "secondary")
            layout.addWidget(note)
