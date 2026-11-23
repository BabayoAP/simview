"""The hero demo's block diagram (PRD §10, M10): drone d0 of the Drone Delivery template flies by
`d0_loop.svd` (IMU + GPS -> EKF -> Route follower -> quadrotor) and matches the script loop."""

import shutil

import numpy as np
import pytest

import simview as sv
from simview.blocks.graph import Diagram
from simview.runner.headless import load_scene
from simview.templates import scene_path

SECONDS = 20.0  # past lift-off and well into the cruise
SIGNALS = [f"d0.{s}" for s in ("x", "y", "z", "vx", "vy", "vz")] + [
    "d0_err_x",
    "d0_bound_x",
    "d0_dev",
]


def _run(path, tmp, name):
    scene = load_scene(path)
    return scene, sv.run(scene, SECONDS, out=tmp / f"{name}.parquet")


@pytest.fixture(scope="module")
def both(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dd_diagram")
    src = scene_path("drone_delivery").parent
    script_dir = tmp / "script"
    shutil.copytree(src, script_dir, ignore=shutil.ignore_patterns("runs", "__pycache__"))
    scene_file = script_dir / "scene.py"
    text = scene_file.read_text(encoding="utf-8")
    assert "USE_DIAGRAM = True" in text
    scene_file.write_text(text.replace("USE_DIAGRAM = True", "USE_DIAGRAM = False"), "utf-8")
    diagram = _run(scene_path("drone_delivery"), tmp, "diagram")
    script = _run(scene_file, tmp, "script")
    return diagram, script


def test_the_diagram_has_the_hero_demo_loop():
    d = Diagram.load(scene_path("drone_delivery").parent / "d0_loop.svd")
    assert [b.id for b in d.blocks.values()] == ["imu_gps", "ekf", "route_follower", "quadrotor"]
    chain = {(w.src, w.dst) for w in d.wires}
    assert chain == {("imu_gps", "ekf"), ("ekf", "route_follower"), ("route_follower", "quadrotor")}


def test_d0_flies_by_the_diagram(both):
    (scene, run), _ = both
    assert set(scene.diagrams) == {"d0_loop"}
    assert "d0_loop.ekf.position[0]" in run.columns  # block outputs are logged (BD-08)


def test_diagram_and_script_fly_d0_the_same(both):
    (_, diagram), (s2, script) = both
    assert not s2.diagrams
    for sig in SIGNALS:
        np.testing.assert_allclose(diagram[sig], script[sig], rtol=0, atol=1e-9, err_msg=sig)
    # the other drones are untouched by the change
    np.testing.assert_allclose(diagram["d1.x"], script["d1.x"], rtol=0, atol=1e-9)


def test_two_scenes_in_one_process_keep_their_own_drone(tmp_path):
    # Each block's copy of delivery_loop.py takes the drone of the scene being loaded.
    first = load_scene(scene_path("drone_delivery"))
    second = load_scene(scene_path("drone_delivery"))
    r1 = sv.run(first, 2.0, out=tmp_path / "a.parquet")
    r2 = sv.run(second, 2.0, out=tmp_path / "b.parquet")
    np.testing.assert_array_equal(r1["d0.z"], r2["d0.z"])
    assert r1["d0.z"][-1] > 1.5  # it lifted off: the diagram drove d0, not the scene's twin


def test_the_diagram_checks_clean_without_a_scene():
    # The Diagram tab compiles it with no drone bound: no problems, every port has a shape.
    from simview.blocks.compiler import compile_diagram

    path = scene_path("drone_delivery").parent / "d0_loop.svd"
    compiled = compile_diagram(Diagram.load(path), base=path.parent, ts=1 / 200)
    assert compiled.shapes[("route_follower", 0)] == (4,)
