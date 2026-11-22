"""VW-09: perception outputs logged with the run, and read back for playback (D-131, D-132)."""

from __future__ import annotations

import numpy as np
import pyarrow.parquet as pq
import pytest

import simview as sv
from simview.core.scheduler import Sim
from simview.investigate.runs import Catalog
from simview.perception import (
    BackProject,
    BevMap,
    CameraRig,
    Dataset,
    OccupancyGrid,
    Pipeline,
    Record,
    load_snapshots,
    perception_dir,
    snapshot_pipelines,
)
from simview.perception.runlog import IOU_BAND

from .helpers import box_scene


def make_scene(tmp_path=None, **log):
    scene, ego = box_scene()
    rig = ego.attach(CameraRig.surround(n=8, width=32, height=24, rate=10))
    ego.x0[3] = 2.0  # drive forward at 2 m/s
    perceive = scene.add_pipeline(
        Pipeline(
            [BackProject(max_range=30), OccupancyGrid(res=0.2, extent=40), BevMap()],
            inputs=rig,
            name="ego",
            **log,
        )
    )
    if tmp_path is not None:
        scene.add_pipeline(Pipeline([Record(tmp_path / "ds")], inputs=rig, name="rec"))
    return scene, perceive


def test_signals_are_logged_in_the_run_log(tmp_path):
    scene, perceive = make_scene(iou_radius=20.0)
    for name in ("min_obstacle_dist", "occupied_voxels", "iou"):
        assert f"ego.perception.{name}" in scene.channels
    run = sv.run(scene, 1.0, out=tmp_path / "r.parquet")
    grid = perceive["occupancy"].latest()
    assert run["ego.perception.occupied_voxels"][-1] == len(grid.occupied_centers())
    assert run["ego.perception.min_obstacle_dist"][-1] == pytest.approx(
        grid.nearest_obstacle(grid.ego[:2, 3])
    )
    acc = sv.perception.evaluate(grid, scene, z_band=IOU_BAND, radius=20.0, exclude=["ego"])
    assert run["ego.perception.iou"][-1] == pytest.approx(acc.iou)
    assert 0.7 <= acc.iou <= 1.0
    meta = pq.read_schema(run.path).metadata[b"simview"].decode()
    assert '"ego.perception.min_obstacle_dist": "m"' in meta  # unit for plots


def test_no_iou_unless_asked_and_signals_can_be_turned_off():
    scene, _ = make_scene()
    assert "ego.perception.iou" not in scene.channels
    scene, _ = make_scene(signals=False)
    assert not any(c.startswith("ego.perception.") for c in scene.channels)
    with pytest.raises(ValueError, match="already logged"):
        s2, ego = box_scene()
        rig = ego.attach(CameraRig.surround(n=2, width=8, height=6))
        s2.add_pipeline(Pipeline([BackProject(), OccupancyGrid()], inputs=rig, name="a"))
        s2.add_pipeline(Pipeline([BackProject(), OccupancyGrid()], inputs=rig, name="b"))


def test_snapshots_play_back_the_perceived_world_by_time(tmp_path):
    scene, perceive = make_scene(snapshot_every=0.5)
    sim = Sim(scene)
    live = {}
    for _ in range(101):  # snapshots at t = 0, 0.5, 1.0
        if round(sim.t, 6) in (0.0, 0.5, 1.0):
            g = perceive["occupancy"].latest()
            live[round(sim.t, 6)] = (g.occupied_centers().copy(), perceive["bev"].latest().image)
        sim.step()
    perceive.log.write(tmp_path / "x.parquet")
    assert snapshot_pipelines(tmp_path / "x.parquet") == ["ego"]
    snaps = load_snapshots(tmp_path / "x.parquet")
    np.testing.assert_allclose(snaps.times, [0.0, 0.5, 1.0])
    assert snaps.at(-0.1) is None
    for t, (centers, bev) in live.items():
        for when in (t, t + 0.3):
            s = snaps.at(when)
            assert s is not None and s.t == t
            np.testing.assert_allclose(s.centers, centers)
            np.testing.assert_array_equal(s.bev, bev)
    s = snaps.at(1.0)
    assert s.occupancy().sum() == len(s.centers) and s.occupancy().shape == (200, 200, 20)


def test_run_writes_side_files_byte_identical_across_runs(tmp_path):
    data = []
    for k in range(2):
        scene, _ = make_scene(snapshot_every=0.2, camera_every=0.5)
        run = sv.run(scene, 1.0, out=tmp_path / f"r{k}.parquet")
        folder = perception_dir(run)
        assert folder == tmp_path / f"r{k}.perception"
        assert sorted(p.name for p in folder.iterdir()) == ["ego.cameras.parquet", "ego.parquet"]
        data.append([run.path.read_bytes()] + [p.read_bytes() for p in sorted(folder.iterdir())])
    assert data[0] == data[1]  # NF-06: the log and the perception files
    snaps = load_snapshots(tmp_path / "r0.parquet")
    assert len(snaps) == 6
    assert len(snaps.cameras) == 8 and snaps.cameras[0] == "ego.front_main"
    f = snaps.camera_at("ego.front_main", 0.7)
    assert f is not None and f.t == 0.5 and f.rgb.shape == (24, 32, 3)
    assert snaps.camera_at("ego.front_main", -1.0) is None
    # the catalog lists only the run logs, not the side files
    names = {r.path.name for r in Catalog(tmp_path).runs()}
    assert names == {"r0.parquet", "r1.parquet"}


def test_snapshots_off_writes_nothing(tmp_path):
    scene, _ = make_scene(snapshot_every=None)
    run = sv.run(scene, 0.3, out=tmp_path / "r.parquet")
    assert not perception_dir(run).exists()
    with pytest.raises(FileNotFoundError):
        load_snapshots(run)
    with pytest.raises(ValueError, match="positive"):
        Pipeline([BackProject()], snapshot_every=0)


def test_record_writes_its_index_once_at_the_end_and_replays_identically(tmp_path):
    """D-132: Record no longer rewrites cameras.json each step; the run's end writes it, and
    the exported dataset still replays to a byte-identical grid."""
    scene, perceive = make_scene(tmp_path)
    writes = []
    rec = scene.pipelines[1].stages[0]
    sim = Sim(scene)
    flush = rec.writer.flush

    def counted() -> None:
        writes.append(sim.t)
        flush()

    rec.writer.flush = counted
    for _ in range(50):
        sim.step()
    assert writes == []
    sim.close()
    assert len(writes) == 1
    sim.close()  # idempotent
    assert len(writes) == 1
    ds = Dataset(tmp_path / "ds")
    assert len(ds) == 8 * 6
    out = Pipeline([BackProject(max_range=30), OccupancyGrid(res=0.2, extent=40)], name="ego")
    grid = out.run(ds)["ego.occupancy"]
    assert grid.logodds.tobytes() == perceive["occupancy"].latest().logodds.tobytes()


def test_record_flushes_every_n_steps_and_through_sv_run(tmp_path):
    rec = Record(tmp_path / "a", flush_every=2)
    rec.reset()
    scene, ego = box_scene()
    rig = ego.attach(CameraRig.surround(n=2, width=8, height=6, rate=10))
    scene.add_pipeline(Pipeline([rec], inputs=rig, name="rec"))
    sim = Sim(scene)
    for _ in range(10):  # steps at t = 0, 0.1 (flush), so the folder is valid mid-run
        sim.step()
    assert len(Dataset(tmp_path / "a")) == 4
    with pytest.raises(ValueError):
        Record(tmp_path / "b", flush_every=0)
    scene, _ = make_scene(tmp_path)
    sv.run(scene, 0.5, out=tmp_path / "r.parquet")  # sv.run closes the pipelines
    assert len(Dataset(tmp_path / "ds")) == 8 * 6
