"""The parameter editor (BD-01): the selected block's name, type, parameters, and problems.

Values are typed as JSON (`2.5`, `[1, 0]`, `"drone"`) or Python literals; anything else is
taken as text, so `+-` and `drone` work without quotes. A change applies when the field loses
focus or Enter is pressed, as one undo step.
"""

from __future__ import annotations

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from simview.blocks.graph import Block
from simview.blocks.library import BlockError, block_class
from simview.ui.blockeditor.document import format_value, parse_value
from simview.ui.blockeditor.palette import SUBSYSTEM_DOC
from simview.ui.theme import tokens


class ParamPanel(QWidget):
    rename = Signal(str, str)  # old id, new id
    param_changed = Signal(str, str, object)  # block id, key, value

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ParamPanel")
        self.block: Block | None = None
        self.fields: dict[str, QLineEdit] = {}
        self.defaults: dict[str, object] = {}
        lay = QVBoxLayout(self)
        s = tokens.SPACING
        lay.setContentsMargins(s[2], s[2], s[2], s[2])
        lay.setSpacing(s[1])
        self.heading = QLabel(self)
        self.heading.setProperty("role", "panelTitle")
        self.doc = QLabel(self)
        self.doc.setProperty("role", "secondary")
        self.doc.setWordWrap(True)
        self.form_host = QWidget(self)
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(s[1])
        self.problems = QLabel(self)
        self.problems.setProperty("role", "error")
        self.problems.setWordWrap(True)
        self.problems.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.heading)
        lay.addWidget(self.doc)
        lay.addWidget(self.form_host)
        lay.addWidget(self.problems)
        lay.addStretch(1)
        self.show_block(None, [])

    def show_block(self, block: Block | None, problems: list[str], hint: str = "") -> None:
        self.block = block
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = {}
        if block is None:
            self.heading.setText("Parameters")
            self.doc.setText(hint or "Select a block to edit its parameters.")
            self.problems.setText("")
            self.problems.hide()
            return
        self.heading.setText(block.type if not block.is_subsystem else "Subsystem")
        if block.is_subsystem:
            self.doc.setText(SUBSYSTEM_DOC)
            keys: list[str] = []
        else:
            try:
                cls = block_class(block.type)
                self.doc.setText(cls.doc)
                keys = list(cls.defaults)
            except BlockError as exc:
                self.doc.setText(str(exc))
                keys = list(block.params)
        name = QLineEdit(block.id, self)
        name.editingFinished.connect(lambda e=name: self._renamed(e))
        self.form.addRow("Name", name)
        self.fields["__name__"] = name
        defaults = block_class(block.type).defaults if not block.is_subsystem and keys else {}
        self.defaults = dict(defaults)
        for key in keys:
            value = block.params.get(key, defaults.get(key))
            edit = QLineEdit(format_value(value), self)
            edit.setProperty("role", "mono")
            edit.editingFinished.connect(lambda k=key, e=edit: self._changed(k, e))
            self.form.addRow(key, edit)
            self.fields[key] = edit
        self.problems.setText("\n".join(problems))
        self.problems.setVisible(bool(problems))

    def _renamed(self, edit: QLineEdit) -> None:
        if self.block is not None and edit.text().strip() != self.block.id:
            self.rename.emit(self.block.id, edit.text().strip())

    def _changed(self, key: str, edit: QLineEdit) -> None:
        if self.block is None:
            return
        value = parse_value(edit.text())
        if value != self.block.params.get(key, self.defaults.get(key, _MISSING)):
            self.param_changed.emit(self.block.id, key, value)


_MISSING = object()
