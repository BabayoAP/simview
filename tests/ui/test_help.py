"""D-147: tooltips and help, per docs/UX_GUIDELINES.md.

- every command's tooltip names it and shows its shortcut in the platform's spelling;
- every icon-only button has a tooltip;
- Help menu: Keyboard Shortcuts (built from the live bindings) and the user guide.
The 3D view's heads-up toolbar tooltips need OpenGL: test_viewport_gl.py::test_toolbar_tooltips.
"""

from __future__ import annotations

import time
from pathlib import Path

from qtpy.QtCore import Qt
from qtpy.QtGui import QKeySequence
from qtpy.QtWidgets import QTabBar, QToolButton

from simview.ui.actions import tooltip_text
from simview.ui.help import EXTRA_KEYS, USER_GUIDE_URL
from simview.ui.main_window import MainWindow
from simview.ui.viewport.view import TOOLBAR_TIPS, toolbar_rects

ROOT = Path(__file__).resolve().parents[2]
NATIVE = QKeySequence.SequenceFormat.NativeText


def native(keys: str) -> str:
    return QKeySequence(keys).toString(NATIVE)


def test_tooltip_text_names_the_command_and_its_native_shortcut():
    assert (
        tooltip_text("Open Project…", QKeySequence("Ctrl+O"))
        == f"Open Project ({native('Ctrl+O')})"
    )
    assert tooltip_text("&Save") == "Save"
    assert tooltip_text("Run", QKeySequence()) == "Run"


def test_every_action_tooltip_shows_its_shortcut(qapp, settings):
    w = MainWindow(settings)
    actions = [*w.actions_.all(), *w.block_editor.actions_.values()]
    for a in actions:
        assert a.toolTip(), a.objectName()
        assert a.statusTip(), a.objectName()
        if not a.shortcut().isEmpty():
            assert a.shortcut().toString(NATIVE) in a.toolTip(), a.toolTip()
        assert "…" not in a.toolTip()
    # No hand-written "Ctrl+" left in block editor tooltips (wrong on macOS).
    assert (
        w.block_editor.actions_["group"].toolTip() == f"Group into a subsystem ({native('Ctrl+G')})"
    )
    space = native("Space")
    assert space in w.actions_.get("sim.run").toolTip()
    assert space in w.actions_.get("sim.pause").toolTip()
    w.close()


def icon_only_buttons(widget):
    for b in widget.findChildren(QToolButton):
        if b.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents):
            continue  # decorative glyphs (empty states, template cards)
        if b.objectName().startswith("qt_") or isinstance(b.parent(), QTabBar):
            continue  # Qt's own overflow and tab-scroll arrows
        if b.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly or not b.text():
            yield b


def test_every_icon_only_button_has_a_tooltip(qapp, settings):
    """Checked with a scene open, so the plots, runs, and timeline toolbars exist too."""
    w = MainWindow(settings)
    w.show()
    w.load_scene(ROOT / "examples" / "ur5_ik_drag.py")
    end = time.monotonic() + 30
    while time.monotonic() < end and not (w.scene_tree is not None and w.scene_tree.items):
        qapp.processEvents()
        time.sleep(0.01)
    buttons = list(icon_only_buttons(w))
    assert len(buttons) > 20
    missing = [
        (b.objectName(), type(b.parent()).__name__, type(b.parent().parent()).__name__)
        for b in buttons
        if not b.toolTip()
    ]
    assert not missing
    w.close_scene()
    w.close()


def test_help_menu_and_shortcuts_window(qapp, settings):
    w = MainWindow(settings)
    menus = [a.text() for a in w.menuBar().actions()]
    assert menus[-1] == "Help"
    assert w.actions_.get("help.shortcuts").shortcut() == QKeySequence("Ctrl+/")
    assert w.actions_.get("help.guide").shortcuts()  # F1 / Cmd+? (platform's HelpContents)
    assert USER_GUIDE_URL.endswith("docs/USER_GUIDE.md")
    assert (ROOT / "docs" / "USER_GUIDE.md").is_file()

    w.actions_.get("help.shortcuts").trigger()
    dlg = w._shortcuts
    assert dlg is not None and dlg.isVisible() and not dlg.isModal()
    rows = dict(dlg.rows())
    # Built from the live bindings: every action with a shortcut is listed, with its keys.
    for a in w.actions_.all():
        if not a.shortcut().isEmpty():
            assert a.shortcut().toString(NATIVE) in rows[tooltip_text(a.text())]
    assert rows["Group into a subsystem"] == native("Ctrl+G")
    assert rows["Run File"] == "F5"
    assert native("Ctrl+Shift+Z") in rows["Redo"] and "Backspace" not in rows["Redo"]
    for _, extra in EXTRA_KEYS:
        for name, keys in extra:
            assert rows[name] == keys

    dlg.filter.setText("2d")
    assert [n for n, _ in dlg.rows()] == ["Toggle 2D mode"]
    dlg.filter.setText("")
    assert len(dlg.rows()) == len(rows)
    w.close()


def test_heads_up_toolbar_layout_and_tips():
    """Pure geometry: buttons in a row, centred at the top; every button has a tip."""
    rects = toolbar_rects(800, 600, len(TOOLBAR_TIPS))
    assert len(rects) == 10
    xs = [r[0] for r in rects]
    assert xs == sorted(xs)
    left, right = rects[0][0], rects[-1][1]
    assert abs((left + right) / 2 - 400) < 1
    assert all(r[3] < 600 and r[2] < r[3] for r in rects)
    assert all(TOOLBAR_TIPS.values())
