"""VW-05: back-projection geometry, range limit, stride, ego mask, and merging cameras."""

import numpy as np
import pytest

from simview import Scene
from simview.perception import BackProject, CameraRig, Frame
from simview.sensors import Camera

from .helpers import Car, run_ticks


def synthetic_frame(depth: float, *, pose=None, w=8, h=6, f=4.0, ego=None) -> Frame:
    k = np.array([[f, 0, (w - 1) / 2], [0, f, (h - 1) / 2], [0, 0, 1.0]])
    return Frame(
        t=0.0,
        seq=0,
        source="cam",
        K=k,
        pose=np.eye(4) if pose is None else pose,
        rgb=np.full((h, w, 3), 7, np.uint8),
        depth=np.full((h, w), depth, np.float32),
        ego=ego,
    )


def test_pixels_land_on_the_plane_at_their_depth():
    frame = synthetic_frame(3.0)
    pts, cols = BackProject(stride=1).project(frame)
    assert pts.shape == (48, 3) and (cols == 7).all()
    np.testing.assert_allclose(pts[:, 2], 3.0)
    # pixel (u, v) -> x = (u - cx) z / f
    np.testing.assert_allclose(pts[0, :2], [(0 - 3.5) * 3 / 4, (0 - 2.5) * 3 / 4])


def test_pose_moves_points_to_the_world():
    pose = np.eye(4)
    pose[:3, :3] = [[0, 0, 1], [-1, 0, 0], [0, -1, 0]]  # optical z = world +x
    pose[:3, 3] = [1, 2, 3]
    pts, _ = BackProject(stride=1).project(synthetic_frame(5.0, pose=pose))
    np.testing.assert_allclose(pts[:, 0], 6.0)


def test_range_limit_invalid_depth_and_stride():
    f = synthetic_frame(10.0)
    assert len(BackProject(max_range=5).project(f)[0]) == 0
    f.depth[0, 0] = np.inf
    f.depth[0, 1] = 0.0
    f.depth[0, 2] = np.nan
    assert len(BackProject(max_range=50, stride=1).project(f)[0]) == 45
    assert len(BackProject(max_range=50, stride=2).project(f)[0]) == 3 * 4 - 2
    with pytest.raises(ValueError):
        BackProject(stride=0)
    with pytest.raises(ValueError):
        BackProject(max_range=1, min_range=2)


def test_ego_box_masks_the_vehicle():
    ego = np.eye(4)
    ego[:3, 3] = [0, 0, 1.0]
    frame = synthetic_frame(1.0, ego=ego)  # points at z = 1 in the world, around the origin
    keep = BackProject(stride=1, ego_box=((-2, -2, -1), (2, 2, 1))).project(frame)[0]
    assert len(keep) == 0
    keep = BackProject(stride=1, ego_box=((5, 5, 5), (6, 6, 6))).project(frame)[0]
    assert len(keep) == 48


def test_box_at_known_distance_from_a_sim_camera():
    scene = Scene(dt=0.01)
    scene.add_box("box", (1.0, 2.0, 2.0), (8.5, 0.0, 1.0), static=True)  # face at x = 8
    ego = scene.add_entity(Car(x0=(0, 0, 1.0, 0, 0)))
    rig = ego.attach(CameraRig([Camera(width=40, height=30, fov=np.radians(50), name="f")]))
    run_ticks(scene, 0)
    cloud = BackProject(stride=1)([rig.streams["ego.f"].latest()])
    assert len(cloud) > 50
    np.testing.assert_allclose(cloud.points[:, 0], 8.0, atol=1e-6)
    assert np.all(np.abs(cloud.points[:, 1]) <= 1.0 + 1e-6)
    assert np.all((cloud.points[:, 2] >= -1e-6) & (cloud.points[:, 2] <= 2.0 + 1e-6))


def test_merges_every_rig_camera_with_its_origin():
    scene = Scene(dt=0.01)
    scene.add_ground()
    ego = scene.add_entity(Car())
    rig = ego.attach(CameraRig.surround(n=8, width=32, height=24))
    run_ticks(scene, 0)
    frames = [s.latest() for s in rig.streams.values()]
    cloud = BackProject(max_range=30, stride=2)(frames)
    assert cloud.origins.shape == (8, 3)
    assert set(np.unique(cloud.origin_index)) == set(range(8))
    np.testing.assert_allclose(cloud.points[:, 2], 0.0, atol=1e-6)  # all ground
    np.testing.assert_allclose(cloud.ego, ego.pose())
    d = np.linalg.norm(cloud.points - cloud.origins[cloud.origin_index], axis=1)
    assert d.max() <= 30 + 1e-9
    assert BackProject()([]) is None
