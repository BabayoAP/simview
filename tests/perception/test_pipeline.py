"""VW-04 (+ VW-03 export): pipelines in a run and offline, with identical outputs."""

import numpy as np
import pytest

import simview as sv
from simview import Scene
from simview.perception import (
    BackProject,
    BevMap,
    CameraRig,
    Dataset,
    OccupancyGrid,
    Pipeline,
    Record,
)

from .helpers import box_scene, run_ticks


def test_callable_stages_chain_and_publish_streams():
    calls = []

    def count(frames):
        calls.append(len(frames))
        return len(frames)

    def double(n):
        return 2 * n

    p = Pipeline([count, double], name="p")
    assert list(p.outputs) == ["p.count", "p.double"]
    p.process(["a", "b"], 0.5)
    p.process([], 0.6)  # nothing new: no step
    assert calls == [2]
    assert p["double"].latest() == 4 and p["p.double"].t == 0.5
    assert Pipeline([lambda x: None, double], name="q").process([1], 0) is None


def test_pipeline_checks():
    with pytest.raises(ValueError):
        Pipeline([])
    with pytest.raises(ValueError):
        Pipeline([BevMap(), BevMap()])
    with pytest.raises(ValueError):
        Pipeline([BevMap()], name="a.b")
    scene = Scene(dt=0.01)
    with pytest.raises(ValueError):
        scene.add_pipeline(Pipeline([BevMap()], rate=3))  # doesn't divide 100 Hz
    scene.add_pipeline(Pipeline([BevMap()], name="x"))
    with pytest.raises(ValueError):
        scene.add_pipeline(Pipeline([BevMap()], name="x"))


def test_unknown_input_stream_fails_at_start():
    scene, _ = box_scene()
    scene.add_pipeline(Pipeline([BackProject()], inputs="ego.nope"))
    with pytest.raises(ValueError, match="no stream named"):
        run_ticks(scene, 0)


def test_pipeline_runs_at_its_rate_in_the_tick():
    scene, ego = box_scene()
    rig = ego.attach(CameraRig.surround(n=2, width=8, height=6, rate=10))
    steps = []

    def note(frames):
        steps.append(sorted({f.t for f in frames}))
        return frames

    scene.add_pipeline(Pipeline([note], rate=5, inputs=rig, name="slow"))
    run_ticks(scene, 40)  # 0.4 s
    # rate 5: steps at t = 0, 0.2, 0.4; each takes every frame since the last step
    assert [[round(t, 3) for t in s] for s in steps] == [[0.0], [0.1, 0.2], [0.3, 0.4]]


def make_scene(tmp_path=None):
    scene, ego = box_scene()
    rig = ego.attach(CameraRig.surround(n=8, width=32, height=24, rate=10))
    ego.x0[3] = 2.0  # drive forward at 2 m/s so the poses change
    perceive = scene.add_pipeline(
        Pipeline(
            [BackProject(max_range=30), OccupancyGrid(res=0.2, extent=40), BevMap()],
            inputs=rig,
            name="ego",
        )
    )
    if tmp_path is not None:
        scene.add_pipeline(Pipeline([Record(tmp_path / "ds")], inputs=rig, name="rec"))
    return scene, perceive


def test_run_is_deterministic():
    grids = []
    for _ in range(2):
        scene, perceive = make_scene()
        sim = run_ticks(scene, 30)
        grid = sim.streams["ego.occupancy"].latest()
        assert grid.version == 4  # t = 0, 0.1, 0.2, 0.3
        grids.append(grid.logodds.tobytes())
    assert grids[0] == grids[1]


def test_exported_run_replays_offline_to_a_byte_identical_grid(tmp_path):
    scene, perceive = make_scene(tmp_path)
    sim = run_ticks(scene, 50)
    live = sim.streams["ego.occupancy"].latest()
    live_bytes, live_bev = live.logodds.tobytes(), sim.streams["ego.bev"].latest().image.copy()
    assert live.occupancy.any()
    ds = Dataset(tmp_path / "ds")
    assert len(ds.cameras) == 8 and len(ds) == 8 * 6
    out = perceive.run(ds)
    assert out["ego.occupancy"].logodds.tobytes() == live_bytes
    np.testing.assert_array_equal(out["ego.bev"].image, live_bev)
    # a fresh copy of the pipeline over the same data gives the same grid again
    again = Pipeline([BackProject(max_range=30), OccupancyGrid(res=0.2, extent=40)], name="ego")
    assert again.run(ds)["ego.occupancy"].logodds.tobytes() == live_bytes


def test_offline_run_takes_plain_frames():
    scene, ego = box_scene()
    rig = ego.attach(CameraRig.surround(n=2, width=16, height=12, rate=10))
    run_ticks(scene, 0)
    frames = [s.latest() for s in rig.streams.values()]
    out = Pipeline([BackProject(), OccupancyGrid(res=0.5, extent=30)], rate=10).run(frames)
    assert out["perception.occupancy"].version == 1


def test_sv_perception_is_registered_like_a_toolbox_module():
    from simview.toolboxes import registry

    assert sv.perception.Pipeline is Pipeline
    assert "perception" in registry.toolboxes()
    assert registry.toolboxes()["perception"].error is None
