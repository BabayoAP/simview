"""UC-3 / M10: every flagship start-screen card opens a scene; the UR5 one drags with IK."""

import numpy as np

import simview as sv
from simview.runner.headless import load_scene
from simview.templates import FLAGSHIP, scene_path


def test_every_flagship_template_has_a_scene():
    assert [t.id for t in FLAGSHIP] == ["av_scenario", "drone_delivery", "ur5_ik", "drone_landing"]
    assert all(t.scene is not None and t.scene.is_file() for t in FLAGSHIP)


def test_ur5_follows_a_moved_target(tmp_path):
    scene = load_scene(scene_path("ur5_ik"))
    goal = scene.targets["goal"]
    pose = goal.pose.copy()
    pose[:3, 3] += (0.05, 0.05, -0.05)
    goal.pose = pose  # what a gizmo drag does
    run = sv.run(scene, 2.0, out=tmp_path / "ur5.parquet")
    assert run["tool_error"][0] > 0.05
    assert np.all(run["tool_error"][-50:] < 1e-3)
