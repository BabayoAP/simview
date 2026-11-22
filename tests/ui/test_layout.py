"""DS-03: default layout per §7.4, dockable panels, layout persisted per project."""

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDockWidget, QToolBar

from simview.ui.main_window import DOCKS, MainWindow
from simview.ui.panels import EmptyState

A = Qt.DockWidgetArea


def test_default_panel_areas(qapp, settings):
    w = MainWindow(settings)
    expected = {
        "scene_tree": A.LeftDockWidgetArea,
        "signals": A.LeftDockWidgetArea,
        "inspector": A.RightDockWidgetArea,
        "workspace": A.RightDockWidgetArea,
        "timeline": A.BottomDockWidgetArea,
        "plots": A.BottomDockWidgetArea,
        "console": A.BottomDockWidgetArea,
        "runs": A.BottomDockWidgetArea,  # tabbed with the console (M5b)
        "training": A.BottomDockWidgetArea,  # tabbed with the runs (M9)
    }
    assert {n: w.dockWidgetArea(d) for n, d in w.docks.items()} == expected
    assert w.central.currentWidget() is w.viewport  # a stack: empty state, then 3D view


def test_all_panels_dockable(qapp, settings):
    w = MainWindow(settings)
    for dock in w.docks.values():
        f = dock.features()
        assert f & QDockWidget.DockWidgetFeature.DockWidgetMovable
        assert f & QDockWidget.DockWidgetFeature.DockWidgetFloatable


def test_bottom_row_spans_full_width(qapp, settings):
    w = MainWindow(settings)
    w.show()
    qapp.processEvents()
    tl, sc = w.docks["timeline"].geometry(), w.docks["scene_tree"].geometry()
    assert tl.left() <= sc.left()
    assert tl.top() > sc.top()
    plots, console = w.docks["plots"].geometry(), w.docks["console"].geometry()
    assert plots.top() > tl.top() and plots.left() < console.left()
    w.close()


def test_every_panel_has_empty_state(qapp, settings):
    w = MainWindow(settings)
    # The console is a live prompt (never empty); the editor's hint is its placeholder text,
    # next to its Open button (D-070).
    console = w.docks["console"].widget()
    assert w.console.shell.banner1 and w.editor.editor.placeholderText()
    assert w.editor.buttons["open"].toolTip()
    widgets = [w.viewport, *(d.widget() for d in w.docks.values() if d.widget() is not console)]
    for widget in widgets:
        states = [widget] if isinstance(widget, EmptyState) else widget.findChildren(EmptyState)
        assert states, widget
        for s in states:
            assert s.hint.text() and s.button.text()
    assert len(DOCKS) == 9  # + Runs (M5b), Training (M9)


def test_layout_persists_per_project(qapp, settings):
    a = MainWindow(settings, "proj-a")
    a.show()
    a.docks["inspector"].setFloating(True)
    a.close()  # saves

    again = MainWindow(settings, "proj-a")
    assert again.docks["inspector"].isFloating()
    other = MainWindow(settings, "proj-b")
    assert not other.docks["inspector"].isFloating()


def test_reset_layout(qapp, settings):
    w = MainWindow(settings)
    w.docks["plots"].setFloating(True)
    w.reset_layout()
    assert not w.docks["plots"].isFloating()
    assert w.dockWidgetArea(w.docks["plots"]) == A.BottomDockWidgetArea


def test_content_share_of_work_area(qapp, settings):
    # §7.2.1 content first, measured against the work area between the toolbar and the
    # status bar (D-006). The approved layout measures ~68.9% at 1440x900.
    w = MainWindow(settings)
    w.show()
    qapp.processEvents()
    top = w.findChild(QToolBar).geometry().bottom() + 1
    work = w.width() * (w.statusBar().geometry().top() - top)
    vp, plots = w.viewport.geometry(), w.docks["plots"].geometry()
    content = vp.width() * vp.height() + plots.width() * plots.height()
    assert content / work >= 0.68
    w.close()
