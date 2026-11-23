"""UC-1 / M8 done-when: the Autonomous Vehicle template runs end to end (TB-VEH, SN-02,
SN-03, VP-08)."""

import numpy as np
import pytest

import simview as sv
from simview.runner.headless import load_scene
from simview.templates import scene_path


@pytest.fixture(scope="module")
def av(tmp_path_factory):
    scene = load_scene(scene_path("av_scenario"))
    run = sv.run(scene, 30.0, out=tmp_path_factory.mktemp("av") / "av.parquet")
    return scene, run


def test_template_contents():
    scene = load_scene(scene_path("av_scenario"))
    assert set(scene.entities) == {"ego", "npc0", "npc1", "npc2"}
    ego = scene["ego"]
    assert isinstance(ego, sv.vehicles.KinematicBicycle)
    assert all(isinstance(scene[f"npc{i}"], sv.vehicles.ScriptedNPC) for i in range(3))
    assert ego.sensors.lidar.beams == 32 and ego.sensors.lidar.rate == 10.0  # UC-1 step 3
    assert ego.sensors.camera.rate == 10.0


def test_follows_the_lane_and_keeps_its_distance(av):
    scene, run = av
    cte, v, gap = run["cte"], run["ego.v"], run["gap"]
    assert np.abs(cte[300:]).max() < 0.15  # pure pursuit holds the lane, bend included
    assert v.max() == pytest.approx(12.0, abs=0.2)  # reaches cruise on the open road
    assert 6.0 < gap.min() < 12.0  # closes in on the braking car, never hits it
    # steady car following behind npc0 (8 m/s): gap = 6 m + 1.5 s * 8 m/s
    assert gap[-200:].mean() == pytest.approx(18.0, abs=0.5)
    assert v[-200:].mean() == pytest.approx(8.0, abs=0.1)
    lane = scene["npc0"].path
    s_ego = np.array([lane.nearest(p).s for p in np.c_[run["ego.x"], run["ego.y"]][::50]])
    assert (run["npc0.s"][::50] - s_ego).min() > 4.5 + 1.35  # bumpers never touch


def test_sensors_see_the_traffic(av):
    scene, _ = av
    ego = scene["ego"]
    lidar, camera = ego.sensors.lidar, ego.sensors.camera
    cars = lidar.points[lidar.points[:, 2] > 0.3]
    assert len(cars) > 5  # returns off the car ahead, not just the ground
    npc0 = scene["npc0"]
    body = npc0.pose()[:3, 3] + npc0.rotation() @ [1.35, 0.0, 0.75]
    assert np.linalg.norm(cars - body, axis=1).max() < 3.0  # all on npc0's box
    assert lidar.points.shape[1] == 3
    assert camera.image.shape == (120, 160, 3)
    assert np.isfinite(camera.depth).any() and np.isinf(camera.depth).any()  # ground and sky


def test_template_runs_from_the_cli(tmp_path):
    from simview.runner.headless import main

    out = tmp_path / "cli.parquet"
    assert (
        main([str(scene_path("av_scenario")), "--headless", "--duration", "2", "--out", str(out)])
        == 0
    )
    assert out.exists()
