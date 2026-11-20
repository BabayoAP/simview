"""SE-02, SE-10, VP-06, VP-10, DS-06, NF-10 through the main window, headless.

Runs the real sim process; the 3D view is the no-OpenGL stand-in (the GL viewport has its own
tests, marked `gl`). Covers the M4 done-when: the UC-3 IK drag demo follows a dragged target
live, and killing the sim process doesn't take the UI down.
"""

import textwrap
import time
from pathlib import Path

import numpy as np
import pytest

from simview.ui.main_window import MainWindow
from simview.ui.sim_panels import NoViewport

ROOT = Path(__file__).resolve().parents[2]
DRAG = ROOT / "examples" / "ur5_ik_drag.py"


def pump(qapp, until, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


@pytest.fixture
def window(qapp, settings):
    w = MainWindow(settings)
    w.show()
    yield w
    w.close_scene()
    w.close()


def loaded(w):
    return w.scene_tree is not None and w.scene_tree.items != {}


def test_open_scene_fills_the_panels(qapp, window):
    window.load_scene(DRAG)
    pump(qapp, lambda: loaded(window))
    assert isinstance(window.sim_view, NoViewport)  # headless: the stand-in view
    assert set(window.scene_tree.items) == {"ur5"}
    assert window.dt_label.text() == "dt 2 ms"
    assert "ur5_ik_drag.py" in window.windowTitle()


def test_the_3d_view_keeps_the_central_area(qapp, window):
    """DS-03 / §7.2: opening a scene must not collapse the central area (an M4 bug: replacing
    the central widget let the side docks take the whole width)."""
    width = window.centralWidget().width()
    window.load_scene(DRAG)
    pump(qapp, lambda: loaded(window))
    window.plots.add_plot("time", ["tool_error"])
    window.plots.add_plot("time", ["tool_error"])
    qapp.processEvents()
    assert window.central.currentWidget() is window.sim_view
    assert window.centralWidget().width() == width > 0.5 * window.width()
    assert window.docks["plots"].height() < 0.4 * window.height()


def test_selection_is_synced_and_inspector_follows(qapp, window):
    """DS-06 + VP-06: select in the tree -> viewport and inspector agree; joints are sliders."""
    window.load_scene(DRAG)
    pump(qapp, lambda: loaded(window))
    window.scene_tree.items["ur5"].setSelected(True)
    qapp.processEvents()
    assert window.sim_view.selection == "ur5"
    assert len(window.inspector.sliders) == 6
    window.sim_view.select("ur5", emit=True)  # and back from the viewport
    window.sim_view.selected.emit(None)
    qapp.processEvents()
    assert window.scene_tree.selectedItems() == []


def test_dragged_target_is_followed_live(qapp, window):
    """M4 done-when (UC-3): drag the IK target, the tool follows while the sim runs."""
    window.load_scene(DRAG)
    pump(qapp, lambda: loaded(window) and window.client.frame() is not None)
    window.scene_tree.items["ur5"].setSelected(True)
    window.run()
    desc = window.client.description
    goal = desc.targets["goal"].copy()
    goal[:3, 3] += [0.08, -0.06, 0.05]
    window.sim_view.target_moved.emit("goal", goal)  # what the gizmo emits while dragging
    start = window.client.frame().t

    def tool_near_goal():
        f = window.client.frame()
        if f is None or f.t - start < 0.2:
            return False
        return np.linalg.norm(f.markers["ur5"] - goal[:3, 3]) < 5e-3

    pump(qapp, tool_near_goal, timeout=20)
    assert window.inspector.values["shoulder_pan_joint.q"].text() != "—"  # sliders follow


def test_killing_the_sim_keeps_the_ui_and_run_restarts(qapp, window):
    """M4 done-when + NF-10: the sim process dies; the UI reports it and Run starts a new one."""
    window.load_scene(DRAG)
    pump(qapp, lambda: loaded(window))
    window.run()
    window.client.proc.kill()
    pump(qapp, lambda: "exited" in window.console.text())
    assert window.isVisible() and not window.running
    window.run()
    pump(qapp, lambda: window.client.alive and window.client.frame() is not None)
    assert window.running


def test_user_error_shows_a_traceback(qapp, window, tmp_path):
    path = tmp_path / "bad.py"
    path.write_text(
        textwrap.dedent(
            """
            import simview as sv
            scene = sv.Scene()

            @scene.controller()
            def boom(t, state, ctx):
                print("about to fail")
                raise ValueError("bad gain")
            """
        )
    )
    window.load_scene(path)
    pump(qapp, lambda: window.client.frame() is not None)
    window.run()
    pump(qapp, lambda: "ValueError: bad gain" in window.console.text())
    assert "about to fail" in window.console.text()
    assert not window.running and window.client.alive


def test_run_controls_and_speed(qapp, window):
    window.load_scene(DRAG)
    pump(qapp, lambda: loaded(window) and window.client.frame() is not None)
    window.step()
    pump(qapp, lambda: window.client.frame().tick == 1)
    window.speed_box.setCurrentIndex(window.speed_box.findText("Max"))
    window.toggle_run()
    pump(qapp, lambda: window.client.frame().speed == 0 and window.client.frame().tick > 50)
    window.toggle_run()
    assert not window.running
    window.stop()  # reset: the scene file loads again
    pump(qapp, lambda: window.client.frame() is not None and window.client.frame().tick == 0)
    assert "RTF" in window.rtf_label.text()


def test_controls_without_a_scene_explain_themselves(qapp, window):
    for action in (window.run, window.pause, window.step, window.stop):
        action()
    assert "No scene loaded" in window.statusBar().currentMessage()


def test_template_card_loads_its_scene(qapp, settings):
    """D-098: opening the Autonomous Vehicle card loads the template's scene (UC-1 step 1-2)."""
    from simview.ui.app import Controller

    app = Controller(settings)
    app.open_template("av_scenario")
    w = app.window
    try:
        pump(qapp, lambda: loaded(w))
        assert set(w.scene_tree.items) >= {"ego", "npc0", "npc1", "npc2"}
        assert w.scene_path.name == "scene.py"
    finally:
        w.close_scene()
        w.close()
        app.start.close()
