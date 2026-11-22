"""Vision Drive template (VW-11, UC-6) and the M11 done-when checks that need it."""

from __future__ import annotations

import ast

import numpy as np
import pytest

import simview as sv
from simview.core.scheduler import Sim
from simview.investigate.runs import RunData, read_info
from simview.investigate.scenario import Scenario
from simview.runner.headless import load_scene
from simview.templates import FLAGSHIP, scene_path, templates

PATH = scene_path("vision_drive")
RUNS = 20
DURATION = 14.0
CAR = (4.5, 1.8)  # ego box (m); its centre is 1.35 m ahead of the rear axle


def test_vision_drive_is_a_fifth_template_card():
    assert [t.id for t in FLAGSHIP] == ["av_scenario", "drone_delivery", "ur5_ik", "drone_landing"]
    ids = [t.id for t in templates()]
    assert ids[: len(FLAGSHIP) + 1] == [*(t.id for t in FLAGSHIP), "vision_drive"]
    assert PATH is not None and PATH.is_file()


def test_camera_only_and_the_planner_reads_only_the_grid():
    scene = load_scene(PATH)
    ego = scene["ego"]
    assert [type(s).__name__ for s in ego.sensors.values()] == ["CameraRig"]  # no lidar
    assert len(ego.sensors.rig.cameras) == 8
    assert all(type(s).__name__ == "CameraRig" for s in scene.sensors())
    # the planner's code reads the occupancy stream and the ego's own state, nothing else:
    # no scene geometry, world, ray casts, or ground-truth scoring
    tree = ast.parse(PATH.read_text(encoding="utf-8"))
    planner_src = {
        n.name: ast.get_source_segment(PATH.read_text(encoding="utf-8"), n)
        for n in tree.body
        if isinstance(n, ast.FunctionDef)
        and n.name in ("planner", "obstacles", "gap", "clear", "lane_frame")
    }
    assert len(planner_src) == 5
    for name, src in planner_src.items():
        for banned in ("world", "geom", "evaluate", "truth", "Lidar", "OBSTACLES", "stalled"):
            assert banned not in src, (name, banned)
    assert 'ctx.streams["ego.occupancy"]' in planner_src["planner"]


# -- 20 seeded runs (M11 done-when) ------------------------------------------------------------
# One sweep (20 layouts, in parallel processes, ~75 s) shared by the tests below; they are marked
# `slow` so a quick loop can skip them with `-m "not slow"` (D-133).
@pytest.fixture(scope="module")
def sweep(tmp_path_factory):
    out = tmp_path_factory.mktemp("vision_sweep")
    res = sv.sweep(PATH, DURATION, grid={"layout": list(range(RUNS))}, keep_logs=True, out=out)
    assert list(res["status"]) == ["ok"] * RUNS, list(res["error"])
    return res


def obstacle_boxes(layout: int) -> list[tuple[str, np.ndarray, float, np.ndarray]]:
    """Ground truth for the test only: (name, centre xy, yaw, half size xy) of every box geom
    in the scene except the ego's own."""
    import mujoco

    scene = load_scene(PATH, params={"layout": layout})
    sim = Sim(scene)
    world = scene.world
    world.kinematics()
    m, d = world.model, world.data
    ego_body = world.proxy_body(scene["ego"])
    out = []
    for g in range(m.ngeom):
        if int(m.geom_type[g]) != mujoco.mjtGeom.mjGEOM_BOX or int(m.geom_bodyid[g]) == ego_body:
            continue
        rot = d.geom_xmat[g].reshape(3, 3)
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or str(g)
        out.append(
            (
                name,
                d.geom_xpos[g][:2].copy(),
                float(np.arctan2(rot[1, 0], rot[0, 0])),
                m.geom_size[g][:2].copy(),
            )
        )
    del sim
    return out


def corners(c: np.ndarray, yaw: float, half: np.ndarray) -> np.ndarray:
    r = np.array([[np.cos(yaw), -np.sin(yaw)], [np.sin(yaw), np.cos(yaw)]])
    sx, sy = half
    return c + np.array([[sx, sy], [-sx, sy], [-sx, -sy], [sx, -sy]]) @ r.T


def overlap(a: np.ndarray, b: np.ndarray) -> bool:
    """Separating-axis test for two convex quads (4, 2)."""
    for poly in (a, b):
        for i in range(4):
            e = poly[(i + 1) % 4] - poly[i]
            n = np.array([-e[1], e[0]])
            pa, pb = a @ n, b @ n
            if pa.max() < pb.min() or pb.max() < pa.min():
                return False
    return True


@pytest.mark.slow
def test_twenty_seeded_runs_stop_or_steer_clear_of_every_obstacle(sweep):
    """M11: the camera-only ego stops or steers clear of every obstacle in 20 of 20 runs."""
    half_ego = np.array(CAR) / 2
    stopped = passed = 0
    for row in range(RUNS):
        layout = int(sweep["layout"][row])
        run = RunData(read_info(sweep["log"][row]))
        boxes = obstacle_boxes(layout)
        assert len(boxes) >= 6  # parked cars, pedestrian, stalled car (+ barrier)
        x, y, yaw, v = (run[f"ego.{s}"] for s in ("x", "y", "yaw", "v"))
        for k in range(len(x)):
            centre = np.array([x[k], y[k]]) + 1.35 * np.array([np.cos(yaw[k]), np.sin(yaw[k])])
            ego_quad = corners(centre, yaw[k], half_ego)
            for name, c, byaw, half in boxes:
                if np.hypot(*(c - centre)) > 6.0:
                    continue
                assert not overlap(ego_quad, corners(c, byaw, half)), (layout, name, run.t[k])
        if layout % 4 == 3:  # both lanes blocked: must have stopped
            assert v[-1] < 0.3, layout
            stopped += 1
        else:  # passed the stalled car and is back in its lane
            assert x[-1] > 80.0 and abs(run["cte"][-1]) < 0.5, layout
            passed += 1
    assert stopped == 5 and passed == 15


@pytest.mark.slow
def test_occupancy_iou_against_ground_truth_in_vision_drive(sweep):
    """M11: IoU >= 0.7 for the static obstacles within 20 m at 0.2 m voxels (time average of
    the logged `ego.perception.iou` over each run, D-133)."""
    for row in range(RUNS):
        run = RunData(read_info(sweep["log"][row]))
        iou = run["ego.perception.iou"]
        assert np.nanmean(iou) >= 0.7, (int(sweep["layout"][row]), np.nanmean(iou))


@pytest.mark.slow
def test_ri_scenario_finds_close_calls_on_the_perception_signal(sweep):
    """VW-09: RI scenarios can use the perception signals."""
    close = Scenario("close call", "ego.perception.min_obstacle_dist < 4.0 for 0.2 s")
    found = 0
    for row in range(RUNS):
        res = close.scan(RunData(read_info(sweep["log"][row])))
        assert not res.missing
        found += len(res.matches)
    assert found > 0


@pytest.mark.slow
def test_snapshots_are_logged_beside_each_run(sweep):
    snaps = sv.perception.load_snapshots(sweep["log"][0])
    assert snaps.pipeline == "ego" and len(snaps) == int(DURATION / 0.5) + 1
    s = snaps.at(5.0)
    assert s is not None and s.t == 5.0 and len(s.centers) > 0
    assert s.bev is not None and s.bev.shape == (300, 300, 3)
    assert snaps.cameras == []  # camera frames are off by default
