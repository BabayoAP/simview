"""RB-10: a robot's frames, the parent tree, and transforms between frames."""

import numpy as np

import simview as sv
from simview.toolboxes import robotics as rb
from tests.physics.test_world import GRIPPER


def test_frames_and_tree():
    arm = sv.Scene().add_robot("ur5")
    names = rb.frames(arm)
    for f in ("base_link", "shoulder_link", "wrist_3_link", "flange", "tool0", "base"):
        assert f in names
    tree = rb.frame_tree(arm)
    assert tree["base_link"] is None
    assert tree["tool0"] == "flange" and tree["flange"] == "wrist_3_link"
    assert tree["shoulder_link"] == "base_link_inertia"


def test_transform_between_frames():
    arm = sv.Scene().add_robot("ur5", pos=(0.3, -0.2, 0.1))
    q = np.array([0.2, -1.0, 1.1, -0.3, 0.6, 0.4])
    T = rb.transform(arm, "base_link", "tool0", q)
    np.testing.assert_allclose(rb.se3.make(np.eye(3), [0.3, -0.2, 0.1]) @ T, arm.fk(q), atol=1e-12)
    np.testing.assert_allclose(rb.transform(arm, "tool0", "tool0", q), np.eye(4), atol=1e-12)


def test_mounted_tool_tree_points_into_the_arm():
    scene = sv.Scene()
    scene.add_robot("ur5")
    grip = scene.add_robot(mjcf=GRIPPER, name="grip", mount=("ur5", "tool0"))
    tree = rb.frame_tree(grip)
    assert tree["palm"] == "ur5/tool0" and tree["finger_l"] == "palm" and tree["pinch"] == "palm"
