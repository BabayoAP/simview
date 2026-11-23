"""VW-08 / VW-09 in the app: voxels in the viewport, the Cameras and BEV panels, perceived vs
true geometry, and the perceived world following the timeline (live history and saved runs).

Offscreen: the 3D view is the `NoViewport` stand-in, which records the voxels it would draw.
The voxel rendering itself is covered by `voxel_points`/`voxel_mesh` here and by the GL tests
in test_viewport_gl.py (50k voxels at >= 30 FPS).
"""

from pathlib import Path

import numpy as np
import pytest

from simview.perception.runlog import load_snapshots, perception_dir
from simview.ui.main_window import MainWindow
from simview.ui.perception_panels import BevPanel, CamerasPanel
from simview.ui.theme import tokens
from simview.ui.viewport import model
from tests.ui.test_scene_session import DRAG, loaded, pump

RIG = Path(__file__).resolve().parent / "perception_scene.py"
CAMS = ["ego.cam0", "ego.cam1", "ego.cam2", "ego.cam3"]


@pytest.fixture
def window(qapp, settings, tmp_path, monkeypatch):
    monkeypatch.setenv("SIMVIEW_RUNS", str(tmp_path / "runs"))
    w = MainWindow(settings)
    w.open_reports = False
    w.show()
    yield w
    w.close_scene()
    w.close()


def run_rig(qapp, w, seconds=1.3):
    """Run the rig scene flat out for `seconds` of sim time, then pause."""
    w.load_scene(RIG)
    pump(qapp, lambda: loaded(w) and w.history is not None and w.client.frame() is not None)
    w.speed_box.setCurrentIndex(w.speed_box.findText("Max"))
    w.run()
    pump(qapp, lambda: w.history is not None and w.history.n * 0.01 >= seconds)
    w.pause()
    pump(qapp, lambda: not w.client.frame().running)
    pump(qapp, lambda: w.history.n == w.client.frame().tick + 1)
    # the last logged rows arrive with the final publish
    pump(qapp, lambda: len(w.perception_history.snapshots.get("ego", [])) >= int(seconds / 0.2))


# -- pure: voxel geometry and colors ----------------------------------------------------------
def test_voxel_mesh_has_one_cube_per_voxel_colored_by_height():
    centers = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 1.5], [2.0, 0.0, 3.0], [3.0, 0.0, 9.0]])
    pts = model.voxel_points(centers)
    assert pts.n_points == 4 and pts.point_data["rgb"].dtype == np.uint8
    mesh = model.voxel_mesh(centers, 0.2)
    assert mesh.n_cells == 6 * 4 and mesh.n_points == 8 * 4
    rgb = mesh.cell_data["rgb"].reshape(4, 6, 3)
    assert (rgb == rgb[:, :1]).all()  # each cube one color
    lo, hi = model.hex_rgb(tokens.VIRIDIS[0]), model.hex_rgb(tokens.VIRIDIS[-1])
    np.testing.assert_array_equal(rgb[0, 0], lo)  # z = 0: the low end of viridis
    np.testing.assert_array_equal(rgb[2, 0], hi)  # z = 3 m: the high end
    np.testing.assert_array_equal(rgb[3, 0], hi)  # clamped above the range
    side = 0.2 * tokens.VOXEL_FILL
    b = model.voxel_mesh(centers[:1], 0.2).bounds
    assert b[1] - b[0] == pytest.approx(side, rel=1e-5)
    assert model.voxel_mesh(np.empty((0, 3)), 0.2).n_cells == 0


def test_colormap_interpolates_between_stops():
    mid = model.colormap(np.array([0.5]), 0.0, 1.0)[0]
    np.testing.assert_array_equal(mid, model.hex_rgb(tokens.VIRIDIS[4]))  # 9 stops: middle


# -- panels ------------------------------------------------------------------------------------
def test_cameras_panel_thumbnails_enlarge_on_click(qapp):
    panel = CamerasPanel(lambda: None)
    panel.resize(700, 300)
    assert panel.currentIndex() == CamerasPanel.EMPTY
    assert panel.empty.hint.text() and panel.empty.button.text()
    panel.set_cameras(CAMS)
    assert panel.currentIndex() == CamerasPanel.GRID and list(panel.thumbs) == CAMS
    img = np.zeros((12, 16, 3), dtype=np.uint8)
    img[:, :, 1] = 200
    panel.show_frame("ego.cam2", img)
    panel.thumbs["ego.cam2"].view.clicked.emit()  # a click on the thumbnail
    assert panel.enlarged == "ego.cam2" and panel.currentIndex() == CamerasPanel.ENLARGED
    assert panel.big.image is img
    panel.show_frame("ego.cam2", img[::2, ::2])  # the enlarged view follows new frames
    assert panel.big.image.shape == (6, 8, 3)
    panel.big.clicked.emit()  # a click on the enlarged view goes back to the grid
    assert panel.enlarged is None and panel.currentIndex() == CamerasPanel.GRID
    panel.set_cameras([])
    assert panel.currentIndex() == CamerasPanel.EMPTY


def test_bev_panel_places_the_ego_arrow(qapp):
    panel = BevPanel(lambda: None)
    assert panel.currentIndex() == 0 and panel.empty.hint.text()
    panel.set_available(True)
    img = np.zeros((100, 80), dtype=np.uint8)
    panel.show_bev(img, origin=np.array([-10.0, -20.0]), res=0.5, ego=np.array([0.0, 0.0, 0.3]))
    col, row, yaw = panel.view.ego_px
    assert col == pytest.approx(20.0) and row == pytest.approx(100 - 40.0) and yaw == 0.3
    panel.grab()  # paints without error


# -- in the app, with the real sim process -----------------------------------------------------
def test_panels_show_empty_states_without_a_rig(qapp, window):
    """§7.8: a scene without a rig or pipeline shows hints in the Cameras and BEV panels."""
    w = window
    assert w.cameras_panel.currentIndex() == CamerasPanel.EMPTY  # no scene yet
    w.load_scene(DRAG)
    pump(qapp, lambda: loaded(w))
    assert w.cameras_panel.currentIndex() == CamerasPanel.EMPTY
    assert w.bev_panel.currentIndex() == 0
    assert w.cameras_panel.empty.button.text() and w.bev_panel.empty.hint.text()
    assert w.sim_view.voxel_count == 0


def test_live_frames_reach_the_panels_and_scrubbing_follows_the_timeline(qapp, window):
    """VW-08: live voxels, BEV and thumbnails; VW-09: scrubbing shows the logged snapshot."""
    w = window
    run_rig(qapp, w)
    assert w.cameras_panel.currentIndex() == CamerasPanel.GRID
    assert list(w.cameras_panel.thumbs) == CAMS and w.bev_panel.currentIndex() == 1
    w.to_live()
    pump(qapp, lambda: w.sim_view.voxel_count > 0)
    live = w.client.perception.latest
    assert w.sim_view.voxel_count == len(live["ego.voxels"].data)
    assert w.bev_panel.view.image is not None and w.bev_panel.view.ego_px is not None
    assert all(w.cameras_panel.image(c) is not None for c in CAMS)

    h, snaps = w.history, w.perception_history.get("ego")
    assert snaps is not None and len(snaps) >= 6 and snaps.cameras == CAMS
    early, late = h.index_at(0.25), h.index_at(1.05)
    w.seek(early)
    qapp.processEvents()
    s0 = snaps.at(h.time_of(early))
    assert s0.t == pytest.approx(0.2)
    assert w.sim_view.voxel_count == len(s0.indices)
    assert w.bev_panel.t == pytest.approx(0.2)
    cam0 = snaps.camera_at("ego.cam0", h.time_of(early)).rgb
    np.testing.assert_array_equal(w.cameras_panel.image("ego.cam0"), cam0)
    w.seek(late)
    qapp.processEvents()
    s1 = snaps.at(h.time_of(late))
    assert s1.t == pytest.approx(1.0) and w.bev_panel.t == pytest.approx(1.0)
    assert w.sim_view.voxel_count == len(s1.indices) != len(s0.indices)
    np.testing.assert_allclose(w.sim_view.voxels, s1.centers)
    assert not np.array_equal(w.cameras_panel.image("ego.cam0"), cam0)  # the car moved

    # perceived vs true geometry, from the command palette's actions
    w.actions_.get("view.geometry.perceived").trigger()
    assert w.sim_view.geometry_mode == "perceived"
    w.actions_.get("view.geometry.cycle").trigger()
    assert w.sim_view.geometry_mode == "true"
    w.actions_.get("view.geometry.both").trigger()
    assert w.sim_view.geometry_mode == "both"


def test_saved_run_reopens_with_its_perceived_world(qapp, window):
    """VW-09: saving a live run writes the snapshots; reopening it shows them when scrubbing."""
    w = window
    run_rig(qapp, w, seconds=0.9)
    expected = w.perception_history.get("ego")
    w.stop()
    pump(qapp, lambda: w.runs.runs() != [])
    (run,) = w.runs.runs()
    assert perception_dir(run.path).is_dir()
    saved = load_snapshots(run.path)
    np.testing.assert_array_equal(saved.times, expected.times)
    assert saved.cameras == CAMS and saved[2].ego is not None

    w.open_run(run)
    pump(qapp, lambda: w.opened_run is not None and w.saved_snapshots is not None)
    h = w.history
    i = h.index_at(0.65)
    w.seek(i)
    qapp.processEvents()
    snap = saved.at(h.time_of(i))
    assert snap.t == pytest.approx(0.6)
    np.testing.assert_allclose(w.sim_view.voxels, snap.centers)
    np.testing.assert_array_equal(w.bev_panel.view.image, snap.bev)
    cam = saved.camera_at("ego.cam1", h.time_of(i)).rgb
    np.testing.assert_array_equal(w.cameras_panel.image("ego.cam1"), cam)
