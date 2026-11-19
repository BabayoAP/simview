"""VP-01..VP-04, VP-06, VP-07, VP-10, DS-04..DS-06 on a real OpenGL viewport.

Marked `gl`: they run with SIMVIEW_GL=1 and a real display (QT_QPA_PLATFORM=windows / cocoa /
xcb, e.g. under xvfb-run on Linux CI). Mouse and key input go through VTK's own event path.
"""

import time
from pathlib import Path

import mujoco
import numpy as np
import pytest

from simview.core.scheduler import Sim
from simview.ipc.protocol import describe
from simview.ipc.shm import Frame
from simview.runner.headless import load_scene
from simview.ui.theme import tokens

pytestmark = pytest.mark.gl
ROOT = Path(__file__).resolve().parents[2]


def frame_of(sim):
    """The state frame the sim process would publish."""
    scene = sim.scene
    m, d = scene.world.model, scene.world.data
    mujoco.mj_kinematics(m, d)
    names = list(scene.entities)
    return Frame(
        tick=sim.tick,
        t=sim.t,
        rtf=1.0,
        running=True,
        wall=time.monotonic(),
        speed=1.0,
        states={n: scene[n].x.copy() for n in names},
        markers={n: scene[n].position() for n in names if scene[n].position() is not None},
        bodies=np.hstack([d.xpos, d.xquat]),
    )


@pytest.fixture
def scene_view(qapp):
    from simview.ui.viewport.view import Viewport

    vp = Viewport("dark")
    vp.resize(900, 650)
    vp.show()
    qapp.processEvents()
    scene = load_scene(ROOT / "examples" / "ur5_pick.py")
    sim = Sim(scene)
    vp.load(describe(scene))
    vp.update_frame(frame_of(sim))
    vp.render()
    qapp.processEvents()
    yield vp, sim
    vp.close_viewport()
    vp.close()


def display_xy(vp, world):
    r = vp.renderer
    r.SetWorldPoint(*world, 1.0)
    r.WorldToDisplay()
    x, y, _ = r.GetDisplayPoint()
    return int(round(x)), int(round(y))


def mouse(vp, event, x, y, ctrl=False, shift=False):
    iren = vp.plotter.iren.interactor
    iren.SetEventInformation(x, y, int(ctrl), int(shift))
    iren.InvokeEvent(event)


def test_scene_renders(scene_view):
    """VP-01 + DS-04: geometry, grid, triad, ViewCube, toolbar, and HUD are drawn."""
    vp, _ = scene_view
    img = vp.plotter.screenshot(return_img=True)
    assert img.std() > 5  # not a blank frame
    assert len(vp.geom_actors) == len(vp.desc.geoms) == 11
    assert vp.grid_actor.GetVisibility() and len(vp.buttons) == 10
    assert "FPS" in vp.hud.GetInput()


def test_bodies_follow_frames_and_trails_grow(scene_view):
    """VP-04: per-entity trails over sim time."""
    vp, sim = scene_view
    before = np.array(vp.entity_actors["cube"][0].user_matrix)
    sim.scene["cube"].x[:3] = [0.2, 0.1, 0.5]
    for _ in range(30):
        sim.step()
        vp.update_frame(frame_of(sim))
    after = np.array(vp.entity_actors["cube"][0].user_matrix)
    assert np.linalg.norm(after[:3, 3] - before[:3, 3]) > 0.1
    assert len(vp.trails["cube"].points) > 10 and vp.trail_actors["cube"].GetVisibility()


def test_click_selects_and_hover_outlines(scene_view, qapp):
    """VP-06 + DS-06: click picks the entity under the cursor; hover and selection outline it."""
    vp, sim = scene_view
    vp.frame_all()
    vp.render()
    x, y = display_xy(vp, sim.scene["cube"].pos)
    got = []
    vp.selected.connect(got.append)
    mouse(vp, "MouseMoveEvent", x, y)
    assert vp.hover == "cube" and len(vp.outline_actors) >= 1
    mouse(vp, "LeftButtonPressEvent", x, y)
    mouse(vp, "LeftButtonReleaseEvent", x, y)
    assert got == ["cube"] and vp.selection == "cube"
    assert vp.body_widget is not None  # VP-10: a selected free body gets the gizmo
    sel = [a for a in vp.outline_actors if a.GetProperty().GetLineWidth() == tokens.OUTLINE_SELECT]
    assert sel and all(vp.overlay.HasViewProp(a) for a in sel)  # drawn on top (§7.5)
    mouse(vp, "LeftButtonPressEvent", 5, 5)  # empty space clears
    mouse(vp, "LeftButtonReleaseEvent", 5, 5)
    assert vp.selection is None


def test_zoom_toward_cursor_and_orbit(scene_view):
    """DS-05 / VP-02: wheel zooms toward the point under the cursor; right-drag orbits."""
    vp, sim = scene_view
    vp.frame_all()
    x, y = display_xy(vp, sim.scene["cube"].pos)
    c0 = vp.camera()
    mouse(vp, "MouseWheelForwardEvent", x, y)
    c1 = vp.camera()
    assert np.linalg.norm(c1.position - sim.scene["cube"].pos) < np.linalg.norm(
        c0.position - sim.scene["cube"].pos
    )
    assert display_xy(vp, sim.scene["cube"].pos) == pytest.approx((x, y), abs=2)
    mouse(vp, "RightButtonPressEvent", 400, 300)
    mouse(vp, "MouseMoveEvent", 460, 300)
    mouse(vp, "RightButtonReleaseEvent", 460, 300)
    assert not np.allclose(vp.camera().forward, c1.forward)


def test_presets_2d_and_fly_keys(scene_view):
    """VP-02, VP-03, §7.8 keys."""
    vp, _ = scene_view
    vp.key("7")
    np.testing.assert_allclose(vp.camera().forward, [0, 0, -1], atol=1e-6)
    from qtpy.QtCore import Qt

    vp.key("", Qt.Key.Key_Tab)  # 2D mode
    assert vp.options["2d"] and vp.camera().parallel and vp.scale_bar.GetVisibility()
    assert not vp.view_cube.GetEnabled() and not vp.view_cube.GetRepresentation().GetVisibility()
    fwd = vp.camera().forward
    mouse(vp, "RightButtonPressEvent", 400, 300)  # right-drag pans in 2D: no rotation
    mouse(vp, "MouseMoveEvent", 480, 340)
    mouse(vp, "RightButtonReleaseEvent", 480, 340)
    np.testing.assert_allclose(vp.camera().forward, fwd, atol=1e-9)
    vp.key("", Qt.Key.Key_Tab)
    assert not vp.options["2d"] and not vp.camera().parallel
    assert vp.view_cube.GetEnabled() and vp.view_cube.GetRepresentation().GetVisibility()
    vp.set_option("fly", True)
    p0 = vp.camera().position
    assert vp.key("w")
    assert np.dot(vp.camera().position - p0, vp.camera().forward) > 0
    assert vp.key("a") and vp.key("f") is True


def test_toolbar_toggles(scene_view):
    """DS-04 heads-up toolbar: grid, frames, trails, display mode, ortho."""
    vp, _ = scene_view
    rep = vp.buttons["grid"].GetRepresentation()
    rep.SetState(0)
    vp.buttons["grid"].InvokeEvent("StateChangedEvent")
    assert not vp.grid_actor.GetVisibility()
    vp.buttons["frames"].GetRepresentation().SetState(1)
    vp.buttons["frames"].InvokeEvent("StateChangedEvent")
    assert all(a.GetVisibility() for a in vp.frame_actors)
    vp.buttons["display"].InvokeEvent("StateChangedEvent")
    assert vp.display_mode == "shaded"
    vp.buttons["ortho"].GetRepresentation().SetState(1)
    vp.buttons["ortho"].InvokeEvent("StateChangedEvent")
    assert vp.camera().parallel


def test_debug_draws(scene_view):
    """VP-07: lines, arrows, points, text, frames appear; a new set replaces the old one."""
    vp, _ = scene_view
    draws = [
        ("line", ((0, 0, 0), (1, 0, 0)), "accent", 2.0, ""),
        ("arrow", ((0, 0, 0), (0, 0.5, 0)), "state.warning", 2.0, ""),
        ("point", ((0.2, 0.2, 0.2),), "accent", 8.0, ""),
        ("text", ((0, 0, 0.5),), "text.primary", 11.0, "goal"),
        ("frame", ((0, 0, 0), (0.1, 0, 0), (0, 0.1, 0), (0, 0, 0.1)), "frame", 0.1, ""),
    ]
    vp.set_draws(draws)
    # batched: lines (incl. the frame axes, same width), arrows, points, labels
    assert len(vp.draw_actors) == 4
    lines = vp.draw_actors[0].mapper.dataset
    # one line + the 3 frame axes, in one batched mesh
    assert lines.n_cells == 1 + 3, (
        f"{type(lines).__name__}: points={lines.n_points} cells={lines.n_cells} "
        f"lines={getattr(lines, 'lines', None)} actors={[type(a.mapper.dataset).__name__ for a in vp.draw_actors]}"
    )
    vp.set_draws([])
    assert vp.draw_actors == []


def test_targets_get_a_gizmo_and_report_moves(qapp):
    """VP-10: an IK target has an always-visible gizmo; its moves are emitted."""
    from simview.ui.viewport.view import Viewport

    vp = Viewport("dark")
    vp.resize(800, 600)
    vp.show()
    scene = load_scene(ROOT / "examples" / "ur5_ik_drag.py")
    vp.load(describe(scene))
    vp.update_frame(frame_of(Sim(scene)))
    assert "goal" in vp.target_actors and len(vp.target_widgets) == 1
    moved = []
    vp.target_moved.connect(lambda n, m: moved.append((n, m)))
    widget = vp.target_widgets[0]
    new = np.array(vp.target_actors["goal"].user_matrix)
    new[:3, 3] += [0.05, 0, 0]
    widget._main_actor.user_matrix = new  # what a drag does to the actor
    widget._release_callback(vp.plotter.iren.interactor, "LeftButtonReleaseEvent")
    assert moved and moved[-1][0] == "goal"
    np.testing.assert_allclose(moved[-1][1], new)
    vp.close_viewport()
    vp.close()


def test_gizmo_release_restores_simview_navigation(scene_view):
    """PyVista's gizmo enables its trackball style on release; SimView's must come back."""
    vp, _ = scene_view
    vp.plotter.enable_trackball_style()
    mouse(vp, "LeftButtonReleaseEvent", 10, 10)
    assert vp.plotter.iren.interactor.GetInteractorStyle() is vp._style


def test_theme_switch(scene_view):
    vp, _ = scene_view
    dark_bg = vp.renderer.GetBackground()
    vp.set_theme("light")
    assert vp.renderer.GetBackground() != dark_bg
    assert len(vp.geom_actors) == 11  # scene rebuilt in the new theme


def test_visuals_world_axes_and_trail_style(qapp, tmp_path):
    """VP-01 (GLB visual, world axes) and VP-04 (trail length and color)."""
    import simview as sv
    from simview.ui.viewport import model
    from simview.ui.viewport.view import Viewport
    from tests.ui.test_visuals import write_glb

    glb = tmp_path / "tri.glb"
    write_glb(glb, [[0, 0, 0], [1, 0, 0], [0, 1, 0]])
    scene = sv.Scene()
    scene.add_ground()
    scene.add_visual("sign", glb, scale=0.5)
    scene.add_box("box", (0.1, 0.1, 0.1), (0, 0, 1), mass=1.0)
    scene.trail("box", seconds=0.05, color="state.warning")
    sim = Sim(scene)
    vp = Viewport("dark")
    vp.resize(800, 600)
    vp.show()
    vp.load(describe(scene))
    assert "sign" in vp.visual_actors and vp.world_axes.GetVisibility()
    vp.set_option("grid", False)
    assert not vp.world_axes.GetVisibility()
    for _ in range(100):
        sim.step()
        vp.update_frame(frame_of(sim))
    trail = vp.trails["box"]
    assert trail.seconds == 0.05 and trail.points[-1][0] - trail.points[0][0] <= 0.05
    want = model.hex_rgb(tokens.color("dark", "state.warning")) / 255.0
    np.testing.assert_allclose(vp.trail_actors["box"].GetProperty().GetColor(), want, atol=1e-6)
    vp.close_viewport()
    vp.close()
