"""VW-01: camera rigs, frames, and their frame conventions."""

import numpy as np
import pytest

import simview as sv
from simview import Scene
from simview.perception import SENSOR_FROM_OPTICAL, CameraRig, Frame
from simview.sensors import Camera

from .helpers import Car, run_ticks


def test_surround_preset_has_the_prd_layout():
    rig = CameraRig.surround()
    names = [c.name for c in rig.cameras]
    assert len(names) == 8
    assert {"front_narrow", "front_wide", "rear"} <= set(names)
    assert sum(n.startswith("left") for n in names) == 2
    assert sum(n.startswith("right") for n in names) == 2
    assert all((c.width, c.height) == (160, 120) for c in rig.cameras)
    assert len(CameraRig.surround(n=5).cameras) == 5


def test_drone_preset_is_a_cube_with_a_down_camera():
    rig = CameraRig.drone()
    assert [c.name for c in rig.cameras] == ["front", "left", "back", "right", "down", "up"]
    down = rig.cameras[4]
    # the down camera's forward (sensor x) axis points to -z
    np.testing.assert_allclose(down.mount[:3, 0], [0, 0, -1], atol=1e-12)
    assert len(CameraRig.drone(n=4).cameras) == 4


def test_custom_rig_checks_names_and_cameras():
    with pytest.raises(ValueError):
        CameraRig([])
    with pytest.raises(ValueError):
        CameraRig([Camera(name="a"), Camera(name="a")])


def test_rig_attaches_like_a_sensor_and_publishes_frames():
    scene = Scene(dt=0.01)
    scene.add_box("wall", (0.2, 10, 10), (5.1, 0, 1.0), static=True, rgba=(1, 0, 0, 1))
    ego = scene.add_entity(Car(x0=(0, 0, 1.0, 0, 0)))
    cam = Camera(width=33, height=25, fov=np.radians(60), name="front")
    rig = ego.attach(CameraRig([cam], rate=10))
    assert ego.sensors.rig is rig
    run_ticks(scene, 1)
    frame = rig.streams["ego.front"].latest()
    assert isinstance(frame, Frame)
    assert frame.source == "ego.front" and frame.seq == 0 and frame.t == 0.0
    assert frame.rgb.shape == (25, 33, 3) and frame.depth.dtype == np.float32
    # K in the OpenCV convention: the centre pixel (16, 12) is the principal point
    np.testing.assert_allclose(frame.K[:2, 2], [16.0, 12.0])
    # depth is z-depth: the whole facing wall reads 5.0 m, not range
    np.testing.assert_allclose(frame.depth, 5.0, rtol=1e-5)
    assert frame.rgb[12, 16, 0] > 200
    # the pose is world-from-optical: z forward = world +x, x right = world -y, y down = -z
    np.testing.assert_allclose(frame.pose[:3, 2], [1, 0, 0], atol=1e-12)
    np.testing.assert_allclose(frame.pose[:3, 0], [0, -1, 0], atol=1e-12)
    np.testing.assert_allclose(frame.pose[:3, 1], [0, 0, -1], atol=1e-12)
    np.testing.assert_allclose(frame.pose[:3, 3], [0, 0, 1.0])
    np.testing.assert_allclose(frame.ego, ego.pose())
    np.testing.assert_allclose(rig.camera_pose("front"), frame.pose)


def test_rig_mount_and_camera_mount_compose():
    scene = Scene(dt=0.01)
    ego = scene.add_entity(Car(x0=(1.0, 2.0, 0.0, 0.0, np.pi / 2)))
    cam = Camera(name="side", pos=(0, 0.5, 0), rpy=(0, 0, np.pi / 2))
    rig = ego.attach(CameraRig([cam], pos=(1.0, 0, 1.5)))
    run_ticks(scene, 0)
    pose = rig.camera_pose("side")
    # ego at (1, 2) facing +y; rig 1 m ahead (world +y) and 1.5 m up; camera 0.5 m to the
    # rig's left (world -x), looking left of the car (world -x)
    np.testing.assert_allclose(pose[:3, 3], [0.5, 3.0, 1.5], atol=1e-12)
    np.testing.assert_allclose(pose[:3, 2], [-1, 0, 0], atol=1e-12)
    # in a run the camera is mounted on the entity at rig mount x camera-in-rig mount
    expected = ego.pose() @ cam.mount @ SENSOR_FROM_OPTICAL
    np.testing.assert_allclose(pose, expected, atol=1e-12)


def test_rig_is_reachable_as_sv_perception():
    assert sv.perception.CameraRig is CameraRig
    assert sv.sensors.CameraRig is CameraRig
