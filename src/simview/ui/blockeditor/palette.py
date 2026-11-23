"""Quick-add (§7.7): double-click the canvas, type to search the block library, Enter adds."""

from __future__ import annotations

from qtpy.QtCore import QEvent, QObject, QPoint, QSize, Qt, Signal
from qtpy.QtGui import QColor, QIcon, QKeyEvent, QPainter, QPixmap
from qtpy.QtWidgets import QFrame, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from simview.blocks.library import BLOCKS, CATEGORIES, SUBSYSTEM
from simview.ui.theme import current_theme, tokens

SUBSYSTEM_DOC = (
    "An empty subsystem: double-click it to add blocks inside "
    "(or select blocks and group them, Ctrl+G)."
)


def entries() -> list[tuple[str, str, str]]:
    """(type, category, doc) for every block, in §7.7 category order, then by name."""
    from simview.toolboxes.registry import discover

    discover()  # toolbox blocks (TB-02)
    order = {c: i for i, c in enumerate(CATEGORIES)}
    out = [(name, cls.category, cls.doc) for name, cls in BLOCKS.items()]
    out.sort(key=lambda e: (order[e[1]], e[0]))
    out.append((SUBSYSTEM, SUBSYSTEM, SUBSYSTEM_DOC))
    return out


def matches(query: str, entry: tuple[str, str, str]) -> bool:
    q = query.strip().lower()
    return not q or all(w in " ".join(entry).lower() for w in q.split())


def _dot(color: str) -> QIcon:
    size = tokens.ICON_SIZE_TOOLBAR
    pm = QPixmap(QSize(size, size))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    r = size // 4
    p.drawRoundedRect(r, r, size - 2 * r, size - 2 * r, r / 2, r / 2)
    p.end()
    return QIcon(pm)


class QuickAdd(QFrame):
    chosen = Signal(str)  # block type

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("QuickAdd")
        self.setFixedSize(*tokens.QUICK_ADD_SIZE)
        lay = QVBoxLayout(self)
        s = tokens.SPACING[1]
        lay.setContentsMargins(s, s, s, s)
        lay.setSpacing(tokens.SPACING[0])
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search blocks…")
        self.search.textChanged.connect(self._filter)
        self.search.installEventFilter(self)
        self.list = QListWidget(self)
        self.list.itemActivated.connect(lambda _i: self._choose())
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)

    def open_at(self, pos: QPoint) -> None:
        colors = tokens.BLOCK_CATEGORY_COLORS[current_theme()]
        self.list.clear()
        for name, cat, doc in entries():
            item = QListWidgetItem(_dot(colors[cat]), f"{name}    {cat}")
            item.setData(Qt.ItemDataRole.UserRole, (name, cat, doc))
            item.setToolTip(doc)
            self.list.addItem(item)
        self.search.clear()
        self._filter("")
        self.move(pos)
        self.show()
        self.search.setFocus()

    def visible_types(self) -> list[str]:
        return [
            self.list.item(i).data(Qt.ItemDataRole.UserRole)[0]
            for i in range(self.list.count())
            if not self.list.item(i).isHidden()
        ]

    def _filter(self, text: str) -> None:
        first = None
        for i in range(self.list.count()):
            item = self.list.item(i)
            hide = not matches(text, item.data(Qt.ItemDataRole.UserRole))
            item.setHidden(hide)
            if not hide and first is None:
                first = item
        self.list.setCurrentItem(first)

    def _move(self, step: int) -> None:
        rows = [i for i in range(self.list.count()) if not self.list.item(i).isHidden()]
        if not rows:
            return
        cur = self.list.currentRow()
        at = rows.index(cur) if cur in rows else -1
        self.list.setCurrentRow(rows[max(0, min(len(rows) - 1, at + step))])

    def _choose(self) -> None:
        item = self.list.currentItem()
        if item is not None and not item.isHidden():
            self.hide()
            self.chosen.emit(item.data(Qt.ItemDataRole.UserRole)[0])

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._move(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._choose()
                return True
            if key == Qt.Key.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, event)
