"""DS-11: the §7.8 keyboard shortcuts. Viewport keys (F / A, 1 / 3 / 7 / 0, Tab) need OpenGL
and are checked in test_viewport_gl.py::test_presets_2d_and_fly_keys. Ctrl+1–4 belong to the
workspace presets (DS-12, v1); until then Ctrl+1 / Ctrl+2 switch the 3D view and the diagram
(D-082, D-120). Qt maps Ctrl to Cmd on macOS."""

from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtGui import QKeySequence
from qtpy.QtTest import QTest
from qtpy.QtWidgets import QLineEdit

from simview.ui.main_window import MainWindow

SECTION_7_8 = {
    "palette.open": "Ctrl+K",
    "sim.toggle": "Space",
    "sim.step": ".",
    "sim.step_back": ",",
    "view.3d": "Ctrl+1",
    "view.diagram": "Ctrl+2",
}


def test_main_window_binds_the_section_7_8_shortcuts(qapp, settings):
    w = MainWindow(settings)
    for action_id, keys in SECTION_7_8.items():
        assert w.actions_.get(action_id).shortcut() == QKeySequence(keys), action_id
    w.close()


def test_undo_redo_are_ctrl_z_and_ctrl_shift_z(qapp, settings):
    w = MainWindow(settings)
    editor = w.block_editor
    undo = editor.actions_["undo"].shortcuts()
    redo = editor.actions_["redo"].shortcuts()
    assert QKeySequence("Ctrl+Z") in undo
    assert QKeySequence("Ctrl+Shift+Z") in redo
    w.close()


def test_space_types_in_text_fields_instead_of_running(qapp, settings):
    w = MainWindow(settings)
    w.show()
    calls: list[bool] = []
    w.actions_.get("sim.toggle").triggered.connect(lambda *_: calls.append(True))
    field = QLineEdit(w)
    field.show()
    field.setFocus()
    qapp.processEvents()
    QTest.keyClick(field, Qt.Key.Key_Space)
    assert field.text() == " " and not calls
    w.close()
