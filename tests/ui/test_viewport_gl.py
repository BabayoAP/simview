"""VP-01..VP-04, VP-06, VP-07, VP-10, DS-04..DS-06 on a real OpenGL viewport.

Marked `gl`: they run with SIMVIEW_GL=1 and a real display (QT_QPA_PLATFORM=windows / cocoa /
xcb, e.g. under xvfb-run on Linux CI). Mouse and key input go through VTK's own event path.
"""

import os
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
    assert len(vp.trails["cube"].points) > 10 and vp.trail_actor.GetVisibility()


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


def test_toolbar_tooltips(scene_view):
    """D-147: every heads-up toolbar icon has a tooltip on hover; toggles show their state."""
    from simview.ui.viewport.view import TOOLBAR_TIPS, toolbar_rects

    vp, _ = scene_view
    assert set(vp.buttons) == set(TOOLBAR_TIPS)
    w, h = vp.plotter.render_window.GetSize()
    rects = dict(zip(vp.buttons, toolbar_rects(w, h, len(vp.buttons)), strict=True))
    x0, x1, y0, y1 = rects["2d"]
    cx, cy = int((x0 + x1) / 2), int((y0 + y1) / 2)
    assert vp.toolbar_key_at(cx, cy) == "2d"
    assert vp.toolbar_tip("2d") == "2D mode (Tab) (off)"
    mouse(vp, "MouseMoveEvent", cx, cy)
    assert vp._tip_key == "2d"
    mouse(vp, "MouseMoveEvent", w // 2, h // 2)
    assert vp._tip_key is None
    assert vp.toolbar_tip("frame_all") == "Frame all (A)"


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
    assert len(vp.draw_meshes) == 4
    assert vp.draw_meshes[0].n_cells == 1 + 3  # one line + the 3 frame axes, batched
    assert vp.draw_meshes[2].n_points == 1 and vp.draw_meshes[3].n_points == 1
    vp.set_draws([])
    assert vp.draw_actors == [] and vp.draw_meshes == []


def test_point_clouds_and_ellipsoids_render(scene_view):
    """VP-08 / VP-09: a cloud keeps all its points; an ellipsoid's shell spans its semi-axes."""
    vp, _ = scene_view
    cloud = np.random.default_rng(0).normal(size=(5000, 3)).astype(np.float32)
    axes = np.diag([0.3, 0.2, 0.1])
    vp.set_draws(
        [
            ("cloud", (), "accent", 2.0, "", cloud),
            ("ellipsoid", ((0.5, 0.0, 0.5),), "state.warning", 3.0, "", axes),
            ("cloud", (), "accent", 2.0, "", np.zeros((0, 3), np.float32)),  # empty: skipped
        ]
    )
    vp.render()
    assert len(vp.draw_actors) == 2
    pts, shell = vp.draw_meshes
    assert pts.n_points == 5000
    np.testing.assert_allclose(
        shell.bounds, (0.2, 0.8, -0.2, 0.2, 0.4, 0.6), atol=5e-3
    )  # faceted shell
    vp.set_draws([])
    assert vp.draw_actors == []


def test_200k_point_cloud_renders_at_30_fps(scene_view):
    """VP-08: a 200k-point cloud (e.g. a dense lidar scan) replaced and drawn every frame."""
    vp, _ = scene_view
    rng = np.random.default_rng(1)
    clouds = [rng.uniform(-5, 5, size=(200_000, 3)).astype(np.float32) for _ in range(3)]
    vp.set_draws([("cloud", (), "accent", 2.0, "", clouds[0])])
    vp.render()  # warm up
    times = []
    for i in range(30):
        start = time.perf_counter()
        vp.set_draws([("cloud", (), "accent", 2.0, "", clouds[i % 3])])
        vp.render()
        times.append(time.perf_counter() - start)
    # CI runners render OpenGL in software (about 60 ms here), so there the bound is loose.
    budget = 1 / 30 if not os.environ.get("CI") else 0.15
    assert np.median(times) < budget, f"median frame {np.median(times) * 1e3:.1f} ms"


def test_voxels_render_and_toggle_perceived_vs_true(scene_view):
    """VW-08: occupied voxels drawn as cubes colored by height; perceived / true / both."""
    vp, _ = scene_view
    blank = vp.plotter.screenshot(return_img=True)
    vp.set_geometry_mode("perceived")
    assert not any(a.GetVisibility() for a in vp.geom_actors)
    centers = np.stack(np.meshgrid(np.arange(10), np.arange(10), [0.1]), -1).reshape(-1, 3) * 0.1
    vp.set_voxels(centers, 0.1)
    vp.frame_all()
    vp.render()
    assert vp.voxel_actor.GetVisibility() and vp.voxel_count == 100
    assert np.abs(vp.plotter.screenshot(return_img=True).astype(int) - blank).sum() > 0
    vp.set_geometry_mode("true")
    assert not vp.voxel_actor.GetVisibility() and all(a.GetVisibility() for a in vp.geom_actors)
    vp.set_geometry_mode("both")
    assert vp.voxel_actor.GetVisibility()
    vp.set_voxels(None)
    assert not vp.voxel_actor.GetVisibility()


def test_50k_voxels_render_at_30_fps(scene_view):
    """VW-08: 50k occupied voxels, replaced in place and drawn every frame, at >= 30 FPS."""
    vp, _ = scene_view
    rng = np.random.default_rng(2)
    grids = [
        (rng.integers(0, 150, size=(50_000, 3)) * [0.2, 0.2, 0.02]).astype(np.float32)
        for _ in range(3)
    ]
    vp.set_voxels(grids[0], 0.2)
    vp.frame_all()
    vp.render()  # warm up
    times = []
    for i in range(30):
        start = time.perf_counter()
        vp.set_voxels(grids[i % 3], 0.2)
        vp.render()
        times.append(time.perf_counter() - start)
    budget = 1 / 30 if not os.environ.get("CI") else 0.15  # software GL on CI runners
    assert np.median(times) < budget, f"median frame {np.median(times) * 1e3:.1f} ms"


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


def test_target_gizmo_drags_with_real_mouse_events(qapp, recwarn):
    """VP-10: hover, press, move, release on a gizmo arrow through VTK's event path moves the
    target. PyVista's callbacks need the style's `_parent`; without it every move raised."""
    from simview.ui.viewport.view import Viewport

    vp = Viewport("dark")
    vp.resize(800, 600)
    vp.show()
    qapp.processEvents()
    scene = load_scene(ROOT / "examples" / "ur5_ik_drag.py")
    vp.load(describe(scene))
    vp.update_frame(frame_of(Sim(scene)))
    vp.render()
    qapp.processEvents()
    moved = []
    vp.target_moved.connect(lambda n, m: moved.append((n, m)))
    widget = vp.target_widgets[0]
    start = np.array(vp.target_actors["goal"].user_matrix)
    arrow = widget._arrows[0]  # the x arrow
    tip = np.array(arrow.GetCenter())
    x, y = display_xy(vp, tip)
    mouse(vp, "MouseMoveEvent", x, y)  # hover highlights the handle
    assert widget._selected_actor is arrow
    mouse(vp, "LeftButtonPressEvent", x, y)
    mouse(vp, "MouseMoveEvent", x + 60, y)
    mouse(vp, "LeftButtonReleaseEvent", x + 60, y)
    assert moved and moved[-1][0] == "goal"
    assert not np.allclose(moved[-1][1], start)
    assert not [w for w in recwarn if "Encountered issue in callback" in str(w.message)]
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
    rgb = vp.trail_actor.mapper.GetInput().point_data["rgb"]
    assert (rgb == model.hex_rgb(tokens.color("dark", "state.warning"))).all()
    vp.close_viewport()
    vp.close()


def test_recorded_trails_replace_the_live_ones(scene_view):
    """VP-05 + VP-04: a scrubbed frame draws the trail recorded up to that moment."""
    vp, sim = scene_view
    name = next(iter(vp.trails))
    path = np.column_stack([np.linspace(0, 0.3, 50), np.zeros(50), np.full(50, 0.2)])
    vp.update_frame(frame_of(sim), {name: path})
    np.testing.assert_allclose(vp.trails[name].polyline().points, path)
    vp.render()


def test_scrubbing_redraws_the_real_viewport_within_100_ms(qapp, settings):
    """M5 done-when on the OpenGL viewport: a scrub re-poses the arm, trails, draws, HUD, and
    the plot cursor, and renders, within 100 ms."""
    from simview.ui.main_window import MainWindow
    from simview.ui.viewport.view import Viewport
    from tests.ui.test_scene_session import DRAG, loaded, pump

    w = MainWindow(settings)
    w.show()
    try:
        w.load_scene(DRAG)
        pump(qapp, lambda: loaded(w) and w.history is not None and w.history.n >= 1)
        assert isinstance(w.sim_view, Viewport)
        w.speed_box.setCurrentIndex(w.speed_box.findText("Max"))
        w.run()
        pump(qapp, lambda: w.history.n >= 500)
        w.pause()
        plot = w.plots.add_plot("time", ["ur5.shoulder_pan_joint.q"])
        w.plots.refresh()
        h = w.history
        times = []
        for i in (10, h.n // 2, h.n // 3, 200, 450):
            start = time.perf_counter()
            w.timeline.slider.setValue(i)  # seek -> show_time -> viewport render
            qapp.processEvents()
            times.append(time.perf_counter() - start)
            assert w.sim_view.frame.tick == int(h.ticks[i])
            assert plot.cursor.value() == pytest.approx(h.time_of(i))
        # The development machine's GPU: about 55-75 ms (D-050). CI runners render OpenGL in
        # software (0.3-1.3 s a frame), so there only correctness is checked.
        if not os.environ.get("CI"):
            assert float(np.median(times)) < 0.100, times
    finally:
        w.close_scene()
        w.close()


def test_nf01_twenty_entities_and_a_50k_cloud_frame_time(qapp):
    """NF-01: a 20-entity scene with a 50k-point cloud; entities move every frame. The 60 fps
    target is for the reference GPU (GTX 1660 / M1); this dev box's GTX 1050 Ti does ~48 fps, so
    the test is a 30 fps regression floor and prints the number (D-138)."""
    import simview as sv
    from simview.ui.viewport.view import Viewport

    scene = sv.Scene(dt=1e-3)
    scene.add_ground()
    for i in range(20):
        quad = scene.add_entity(sv.aero.Quadrotor((i % 5 * 2.0, i // 5 * 2.0, 1.0), name=f"q{i}"))
        scene.attach_shape(quad, "box", (0.6, 0.6, 0.15))
        scene.trail(f"q{i}", seconds=5.0)
    sim = Sim(scene)
    vp = Viewport("dark")
    vp.resize(1280, 720)
    vp.show()
    qapp.processEvents()
    vp.load(describe(scene))
    cloud = np.random.default_rng(2).uniform(-5, 5, size=(50_000, 3)).astype(np.float32)
    vp.set_draws([("cloud", (), "accent", 2.0, "", cloud)])
    for _ in range(5):  # warm up
        sim.step()
        vp.update_frame(frame_of(sim))
        vp.render()
    times = []
    for _ in range(60):
        for _ in range(16):  # ~one 60 Hz frame of sim time
            sim.step()
        frame = frame_of(sim)
        start = time.perf_counter()
        vp.update_frame(frame)
        vp.render()
        times.append(time.perf_counter() - start)
    vp.close_viewport()
    vp.close()
    print(f"NF-01 median frame {np.median(times) * 1e3:.1f} ms")
    budget = 1 / 30 if not os.environ.get("CI") else 0.15  # CI renders in software
    assert np.median(times) < budget, f"median frame {np.median(times) * 1e3:.1f} ms"
