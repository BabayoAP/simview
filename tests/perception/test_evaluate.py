"""VW-10: accuracy against the scene's true geometry (and the M11 IoU acceptance check)."""

import numpy as np
import pytest

from simview import Scene
from simview.perception import (
    BackProject,
    CameraRig,
    OccupancyGrid,
    Pipeline,
    evaluate,
    truth_grid,
)

from .helpers import BOXES, box_scene, run_ticks


def _centre_mask(grid, fn):
    nx, ny, nz = grid.shape
    i, j, k = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    c = grid.origin + (np.stack([i, j, k], -1) + 0.5) * grid.res
    return fn(c[..., 0], c[..., 1], c[..., 2])


def test_truth_grid_rasterizes_boxes_exactly_on_voxel_boundaries():
    scene = Scene(dt=0.01)
    scene.add_ground()  # planes are ground: skipped
    scene.add_box("b", (2.0, 1.0, 1.0), (3.0, 0.0, 0.5), static=True)
    g = OccupancyGrid(res=0.5, extent=10, height=(0, 2))
    truth = truth_grid(g, scene)
    expected = _centre_mask(g, lambda x, y, z: (abs(x - 3) < 1) & (abs(y) < 0.5) & (z < 1))
    np.testing.assert_array_equal(truth, expected)


def test_truth_grid_other_primitives_and_rotation():
    scene = Scene(dt=0.01)
    scene.add_sphere("s", 2.0, (-3.0, 0.0, 1.0), static=True)
    scene.add_cylinder("c", 1.0, 2.0, (3.0, 3.0, 1.0), static=True)
    scene.add_capsule("k", 1.0, 1.0, (3.0, -3.0, 1.0), static=True)
    q = (np.cos(np.pi / 8), 0, 0, np.sin(np.pi / 8))  # 45 deg about z
    scene.add_box("r", (2.0, 0.2, 1.0), (0.0, 3.0, 0.5), quat=q, static=True)
    g = OccupancyGrid(res=0.1, extent=12, height=(0, 2.5))
    truth = truth_grid(g, scene)

    def at(x, y, z):
        return truth[tuple(np.floor((np.array([x, y, z]) - g.origin) / g.res).astype(int))]

    assert at(-3.0, 0.0, 1.0) and at(-3.0, 0.0, 1.95) and not at(-3.0, 0.0, 2.3)
    assert at(3.0, 3.4, 0.05) and not at(3.0, 3.7, 1.0)
    assert at(3.0, -3.0, 1.9) and not at(3.0, -3.0, 2.2) and not at(3.45, -3.0, 1.95)
    assert at(0.6, 3.6, 0.5) and not at(0.6, 2.4, 0.5)  # along the rotated diagonal


def test_exclude_leaves_out_the_ego_vehicle():
    scene, ego = box_scene()
    scene.attach_shape(ego, "box", (4.0, 2.0, 1.5), pos=(0, 0, 0.75))
    g = OccupancyGrid(res=0.2, extent=40)
    run_ticks(scene, 0)
    with_ego = truth_grid(g, scene)
    without = truth_grid(g, scene, exclude=["ego"])
    assert with_ego.sum() > without.sum()
    assert not without[tuple(np.floor((np.array([0, 0, 0.5]) - g.origin) / 0.2).astype(int))]


def test_metrics_on_a_perfect_and_a_wrong_grid():
    scene = Scene(dt=0.01)
    scene.add_box("b", (2.0, 1.0, 1.0), (3.0, 0.0, 0.5), static=True)
    g = OccupancyGrid(res=0.5, extent=10, height=(0, 2))
    truth = truth_grid(g, scene)
    g.logodds[truth] = 1.0
    g.seen[:] = True
    acc = evaluate(g, scene, pos=(0.0, 0.0))
    assert (acc.iou, acc.precision, acc.recall) == (1.0, 1.0, 1.0)
    assert acc.nearest_error == 0.0 and acc.nearest_true == pytest.approx(np.hypot(2.25, 0.25))
    g.logodds[:] = 0
    g.logodds[0, 0, 0] = 1.0  # one false positive, every true voxel missed
    acc = evaluate(g, scene, pos=(0.0, 0.0))
    assert acc.tp == 0 and acc.fp == 1 and acc.fn == truth.sum() and acc.iou == 0.0


def test_iou_of_a_sim_rig_on_static_boxes_is_at_least_0_7():
    """M11 acceptance: occupancy IoU >= 0.7 for static obstacles within 20 m at 0.2 m voxels."""
    scene, ego = box_scene()
    rig = ego.attach(CameraRig.surround(n=8, width=160, height=120, rate=10))
    scene.add_pipeline(
        Pipeline(
            [BackProject(max_range=40), OccupancyGrid(res=0.2, extent=60)], inputs=rig, name="ego"
        )
    )
    sim = run_ticks(scene, 20)  # three fused frames from a standstill
    grid = sim.streams["ego.occupancy"].latest()
    acc = evaluate(grid, scene, radius=20.0, exclude=["ego"])
    assert acc.iou >= 0.7, acc
    assert acc.precision >= 0.8 and acc.recall >= 0.8
    assert acc.nearest_error <= 0.2 + 1e-9
    near = min(
        np.hypot(*np.maximum(np.abs(np.array(p[:2])) - np.array(s[:2]) / 2, 0)) for _, s, p in BOXES
    )
    assert grid.nearest_obstacle(ego.pose()[:2, 3], within=30) == pytest.approx(near, abs=0.3)
