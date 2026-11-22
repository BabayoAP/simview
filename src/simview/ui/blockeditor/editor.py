"""The block editor (BD-01..BD-08, DS-10): toolbar, canvas, and parameter panel.

Shortcuts (while the editor has focus): Ctrl+Z / Ctrl+Shift+Z undo / redo, Delete removes the
selection, Ctrl+G groups the selected blocks into a subsystem, Ctrl+Shift+G ungroups one,
Ctrl+A selects all, Ctrl+0 fits the diagram in view. Double-click the canvas to add a block.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from qtpy.QtCore import QPoint, QPointF, QSize, Qt, Signal
from qtpy.QtGui import QAction, QKeySequence
from qtpy.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from simview.blocks.graph import SUFFIX
from simview.ui.blockeditor.canvas import DiagramView, ValueLookup
from simview.ui.blockeditor.document import Document
from simview.ui.blockeditor.palette import QuickAdd
from simview.ui.blockeditor.params import ParamPanel
from simview.ui.theme import current_theme, icon, tokens
from simview.ui.theme.tokens import ThemeName


class BlockEditor(QWidget):
    saved = Signal(object)  # Path of the saved .svd file
    status = Signal(str)  # a short message for the status bar

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BlockEditor")
        self.doc = Document(self)
        self.theme: ThemeName = current_theme()
        self.value_lookup: ValueLookup | None = None  # live wire values (set by the window)
        self.default_dir: Callable[[], Path | None] = lambda: None
        self._add_at = QPointF()
        self._select_next: list[str] | None = None

        self.view = DiagramView(self)
        self.params = ParamPanel(self)
        self.params.setMinimumWidth(tokens.SIDE_PANEL_WIDTH[0])
        self.params.setMaximumWidth(tokens.PARAM_PANEL_WIDTH)  # the canvas gets the rest
        self.quick = QuickAdd(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QHBoxLayout()
        s = tokens.SPACING
        bar.setContentsMargins(s[1], s[0], s[1], s[0])
        bar.setSpacing(s[0])
        self.actions_: dict[str, QAction] = {}
        self.buttons: dict[str, QToolButton] = {}
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        spec: list[tuple[str, str, str, Callable[[], object], object] | None] = [
            ("new", "New diagram", "file-plus", self.new, None),
            ("open", "Open diagram…", "folder-open", self.open_dialog, None),
            ("save", "Save diagram", "save", self.save, None),
            None,
            ("undo", "Undo", "undo-2", self.doc.undo, QKeySequence.StandardKey.Undo),
            ("redo", "Redo", "redo-2", self.doc.redo, QKeySequence.StandardKey.Redo),
            None,
            ("group", "Group into a subsystem (Ctrl+G)", "group", self.group, "Ctrl+G"),
            (
                "ungroup",
                "Ungroup a subsystem (Ctrl+Shift+G)",
                "ungroup",
                self.ungroup,
                "Ctrl+Shift+G",
            ),
            ("up", "Up one level", "corner-left-up", self.doc.up, None),
            ("fit", "Fit diagram in view (Ctrl+0)", "maximize", self.view.fit, "Ctrl+0"),
        ]
        for entry in spec:
            if entry is None:
                sep = QLabel("·", self)
                sep.setProperty("role", "caption")
                bar.addWidget(sep)
                continue
            key, tip, ic, slot, shortcut = entry
            act = QAction(icon(ic), tip, self)
            act.triggered.connect(lambda _c=False, f=slot: f())
            if isinstance(shortcut, QKeySequence.StandardKey):
                act.setShortcuts(shortcut)  # every platform binding (Redo: Ctrl+Shift+Z too)
                act.setShortcutContext(ctx)
            elif shortcut is not None:
                act.setShortcut(QKeySequence(shortcut))  # type: ignore[arg-type]
                act.setShortcutContext(ctx)
            self.addAction(act)
            self.actions_[key] = act
            b = QToolButton(self)
            b.setDefaultAction(act)
            b.setIconSize(QSize(tokens.ICON_SIZE_TOOLBAR, tokens.ICON_SIZE_TOOLBAR))
            b.setAutoRaise(True)
            bar.addWidget(b)
            self.buttons[key] = b
        for key, seq, slot in (
            ("delete", QKeySequence.StandardKey.Delete, self.delete_selection),
            ("select_all", QKeySequence.StandardKey.SelectAll, self.select_all),
        ):
            act = QAction(key, self)
            act.setShortcuts(seq)
            act.setShortcutContext(ctx)
            act.triggered.connect(lambda _c=False, f=slot: f())
            self.addAction(act)
            self.actions_[key] = act
        self.crumbs = QLabel(self)
        self.crumbs.setTextFormat(Qt.TextFormat.RichText)
        self.crumbs.linkActivated.connect(self._crumb)
        bar.addSpacing(s[1])
        bar.addWidget(self.crumbs)
        bar.addStretch(1)
        self.problems = QLabel(self)
        self.problems.setProperty("role", "secondary")
        bar.addWidget(self.problems)
        lay.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.addWidget(self.view)
        split.addWidget(self.params)
        split.setStretchFactor(0, 1)
        split.setCollapsible(0, False)
        lay.addWidget(split, 1)

        self.doc.changed.connect(self.redraw)
        self.doc.saved.connect(self.saved)
        self.view.quick_add.connect(self._quick_add)
        self.quick.chosen.connect(self._add)
        self.view.open_subsystem.connect(self.doc.enter)
        self.view.connect_ports.connect(self._connect)
        self.view.moved.connect(self.doc.move)
        self.view.delete_pressed.connect(self.delete_selection)
        self.params.rename.connect(self._rename)
        self.params.param_changed.connect(self._param)
        self.view.scene().selectionChanged.connect(self._selection_changed)
        self.redraw()

    # -- files ------------------------------------------------------------------------------------
    @property
    def path(self) -> Path | None:
        return self.doc.path

    def new(self) -> None:
        self.doc.new()
        self.view.fit()

    def open(self, path: str | Path) -> None:
        try:
            self.doc.open(path)
        except (OSError, ValueError, KeyError) as exc:
            self.status.emit(f"Can't open {Path(path).name}: {exc}")
            return
        self.view.fit()
        self.status.emit(f"Opened {Path(path).name}")

    def open_dialog(self) -> None:
        start = self.default_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Diagram", str(start or ""), f"Block diagrams (*{SUFFIX})"
        )
        if path:
            self.open(path)

    def save(self) -> Path | None:
        """Save to the diagram's file, or ask where (an untitled diagram)."""
        if self.doc.path is None:
            start = self.default_dir()
            name = str(start / f"diagram{SUFFIX}") if start is not None else f"diagram{SUFFIX}"
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Diagram", name, f"Block diagrams (*{SUFFIX})"
            )
            if not path:
                return None
            return self.save_as(path)
        return self.save_as(None)

    def save_as(self, path: str | Path | None) -> Path:
        saved = self.doc.save(path)
        self.status.emit(f"Saved {saved.name}")
        return saved

    # -- edits ------------------------------------------------------------------------------------
    def _quick_add(self, pos: QPointF, global_pos: QPoint) -> None:
        self._add_at = pos
        self.quick.open_at(global_pos)

    def _add(self, type_name: str) -> None:
        self.add_block(type_name, (self._add_at.x(), self._add_at.y()))

    def add_block(self, type_name: str, pos: tuple[float, float]) -> str:
        self._select_next = []
        bid = self.doc.add(type_name, pos)
        self.view.select([bid])
        return bid

    def _connect(self, src: tuple[str, int], dst: tuple[str, int]) -> None:
        try:
            self.doc.connect(src, dst)
        except ValueError as exc:
            self.status.emit(str(exc))

    def delete_selection(self) -> None:
        blocks, wires = self.view.selected_blocks(), self.view.selected_wires()
        if blocks or wires:
            self._select_next = []
            self.doc.delete(blocks, wires)

    def select_all(self) -> None:
        self.view.select(list(self.view.blocks))

    def group(self) -> None:
        ids = self.view.selected_blocks()
        if not ids:
            self.status.emit("Select the blocks to group first.")
            return
        try:
            self._select_next = [self.doc.group(ids)]
        except ValueError as exc:
            self.status.emit(str(exc))
        self.redraw()

    def ungroup(self) -> None:
        subs = [b for b in self.view.selected_blocks() if self.doc.current.blocks[b].is_subsystem]
        if len(subs) != 1:
            self.status.emit("Select one subsystem to ungroup.")
            return
        try:
            self._select_next = self.doc.ungroup(subs[0])
        except ValueError as exc:
            self.status.emit(str(exc))
        self.redraw()

    def _rename(self, old: str, new: str) -> None:
        try:
            self._select_next = [new]
            self.doc.rename(old, new)
        except ValueError as exc:
            self._select_next = None
            self.status.emit(str(exc))
            self._selection_changed()  # put the old name back in the field

    def _param(self, block_id: str, key: str, value: object) -> None:
        self._select_next = [block_id]
        self.doc.set_param(block_id, key, value)

    # -- scene info and theme ---------------------------------------------------------------------
    def set_entities(self, entities: dict[str, tuple[str, ...]]) -> None:
        self.doc.set_entities(entities)

    def set_theme(self, theme_name: ThemeName) -> None:
        self.theme = theme_name
        for key, name in _ICONS.items():
            self.actions_[key].setIcon(icon(name))
        self.redraw()

    # -- drawing ----------------------------------------------------------------------------------
    def redraw(self) -> None:
        keep = self._select_next
        self._select_next = None
        self.view.show_document(self.doc, self.theme, self.value_lookup)
        if keep is not None:
            self.view.select(keep)
        d = self.doc
        self.actions_["undo"].setEnabled(d.can_undo)
        self.actions_["redo"].setEnabled(d.can_redo)
        self.actions_["up"].setEnabled(bool(d.level))
        parts = [d.name + (" •" if d.modified else ""), *d.level]
        links = [
            f'<a href="{len(parts) - 1 - i}">{p}</a>' if i < len(parts) - 1 else f"<b>{p}</b>"
            for i, p in enumerate(parts)
        ]
        self.crumbs.setText(" › ".join(links))
        n = len(d.issues)
        if n:
            self.problems.setProperty("role", "error")
            self.problems.setText(f"{n} problem{'s' if n != 1 else ''}")
            self.problems.setToolTip("\n".join(str(i) for i in d.issues))
        else:
            self.problems.setProperty("role", "secondary")
            self.problems.setText("No problems" if d.current.blocks else "")
            self.problems.setToolTip("")
        self.problems.style().unpolish(self.problems)
        self.problems.style().polish(self.problems)
        self._selection_changed()

    def _crumb(self, link: str) -> None:
        self.doc.up(int(link))

    def _selection_changed(self) -> None:
        ids = self.view.selected_blocks()
        if len(ids) == 1 and ids[0] in self.doc.current.blocks:
            b = self.doc.current.blocks[ids[0]]
            self.params.show_block(b, self.doc.issues_for(b.id))
        elif ids:
            self.params.show_block(None, [], f"{len(ids)} blocks selected. Ctrl+G groups them.")
        else:
            general = self.doc.general_issues()
            self.params.show_block(None, [], "\n".join(general))


_ICONS = {
    "new": "file-plus",
    "open": "folder-open",
    "save": "save",
    "undo": "undo-2",
    "redo": "redo-2",
    "group": "group",
    "ungroup": "ungroup",
    "up": "corner-left-up",
    "fit": "maximize",
}
