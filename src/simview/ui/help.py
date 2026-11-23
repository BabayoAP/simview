"""Help menu content: the keyboard-shortcuts window and the user guide link (D-147).

The shortcuts list is built from the live actions, so it can't drift from the real bindings.
Keys handled outside QActions (viewport navigation, fly mode) are listed in `EXTRA_KEYS`.
"""

from __future__ import annotations

from collections.abc import Iterable

from qtpy.QtCore import Qt, QUrl
from qtpy.QtGui import QAction, QDesktopServices, QFont, QKeySequence
from qtpy.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from simview.ui.actions import tooltip_text
from simview.ui.theme import tokens

USER_GUIDE_URL = "https://github.com/BabayoAP/simview/blob/main/docs/USER_GUIDE.md"

# Keys and gestures that are not QActions: the 3D view reads them itself (§7.8, view.key).
EXTRA_KEYS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "3D View",
        (
            ("Orbit around the point under the cursor", "Right-drag"),
            ("Pan", "Ctrl+Right-drag"),
            ("Zoom toward the cursor", "Wheel"),
            ("Select", "Click"),
            ("Frame selected / frame all", "F / A"),
            ("Front, right, top, iso view", "1 / 3 / 7 / 0"),
            ("Toggle 2D mode", "Tab"),
            ("Fly (with fly mode on)", "W A S D Q E"),
        ),
    ),
)


HIDDEN_KEYS = frozenset({"Undo", "Redo"})


def open_user_guide() -> bool:
    """Open the user guide in the browser; False if the system has no handler."""
    return QDesktopServices.openUrl(QUrl(USER_GUIDE_URL))


def _native(seq: QKeySequence) -> str:
    return seq.toString(QKeySequence.SequenceFormat.NativeText)


def shortcut_rows(actions: Iterable[QAction]) -> list[tuple[str, str]]:
    """(name, shortcut) for each action that has a shortcut, all bindings joined by " or "."""
    rows = []
    for a in actions:
        keys = [_native(s) for s in a.shortcuts() if not s.isEmpty()]
        # Windows' legacy Alt+Backspace and the dedicated Undo/Redo keyboard keys still work;
        # listing them crowds out the bindings people use.
        keys = [k for k in keys if k not in HIDDEN_KEYS and not ("Alt" in k and "Backspace" in k)]
        if keys:
            rows.append((tooltip_text(a.text()), " or ".join(dict.fromkeys(keys))))
    return rows


class ShortcutsDialog(QDialog):
    """Every keyboard shortcut, grouped, with a filter box. Non-modal (§7.2: no modal dialogs)."""

    def __init__(
        self, groups: list[tuple[str, list[tuple[str, str]]]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ShortcutsDialog")
        self.setWindowTitle("Keyboard Shortcuts")
        self.setModal(False)
        self.resize(*tokens.SHORTCUTS_WINDOW)

        self.filter = QLineEdit(self)
        self.filter.setPlaceholderText("Filter shortcuts…")
        self.filter.setClearButtonEnabled(True)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["Action", "Shortcut"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, tokens.SHORTCUTS_WINDOW[0] * 3 // 5)
        hint = QLabel("Every command, with or without a shortcut, is in the command palette.")
        hint.setProperty("role", "caption")
        hint.setWordWrap(True)

        lay = QVBoxLayout(self)
        pad = tokens.SPACING[2]
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(tokens.SPACING[1])
        lay.addWidget(self.filter)
        lay.addWidget(self.tree, 1)
        lay.addWidget(hint)

        for title, rows in groups:
            if not rows:
                continue
            head = QTreeWidgetItem(self.tree, [title])
            head.setFirstColumnSpanned(True)
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = head.font(0)
            font.setWeight(QFont.Weight(tokens.WEIGHT_SEMIBOLD))
            head.setFont(0, font)
            for name, keys in rows:
                item = QTreeWidgetItem(self.tree, [name, keys])
                item.setData(0, Qt.ItemDataRole.UserRole, title)
        self.filter.textChanged.connect(self.apply_filter)

    def rows(self) -> list[tuple[str, str]]:
        """Visible (name, shortcut) rows, headings excluded."""
        out = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) and not item.isHidden():
                out.append((item.text(0), item.text(1)))
        return out

    def apply_filter(self, text: str) -> None:
        q = text.lower().strip()
        visible_groups: set[str] = set()
        heads: list[QTreeWidgetItem] = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            group = item.data(0, Qt.ItemDataRole.UserRole)
            if not group:
                heads.append(item)
                continue
            hit = not q or q in item.text(0).lower() or q in item.text(1).lower()
            item.setHidden(not hit)
            if hit:
                visible_groups.add(group)
        for head in heads:
            head.setHidden(head.text(0) not in visible_groups)
