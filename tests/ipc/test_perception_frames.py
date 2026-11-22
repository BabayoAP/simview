"""VW-08 / PRD §8.5: perception frames go from the sim to the UI through per-stream shared-memory
slots named by FRAMES events; the UI reads only the newest frame (D-134)."""

import numpy as np
import pytest

from simview.ipc import protocol as proto
from simview.ipc.perception import PerceptionIn, PerceptionOut, thumbnail
from simview.ipc.shm import FrameSlot
from simview.perception import BackProject, BevMap, CameraRig, OccupancyGrid, Pipeline
from tests.perception.helpers import box_scene, run_ticks


def test_frame_slot_round_trip_keeps_the_newest_frame():
    w = FrameSlot(1024, create=True)
    try:
        r = FrameSlot(name=w.name)
        assert r.read() is None  # nothing written yet
        a = np.arange(30, dtype=np.float32).reshape(10, 3)
        w.write(0, a, (1.5, 0.2))
        w.write(1, a * 2, (2.0, 0.2))
        f = r.read()
        assert f.seq == 1 and f.meta[0] == 2.0 and f.meta[1] == pytest.approx(0.2)
        np.testing.assert_array_equal(f.data, a * 2)
        img = np.full((4, 5, 3), 7, dtype=np.uint8)
        w.write(2, img)
        g = r.read()
        assert g.data.dtype == np.uint8 and g.data.shape == (4, 5, 3) and (g.data == 7).all()
        with pytest.raises(ValueError):
            w.write(3, np.zeros(10_000, dtype=np.float64))  # bigger than the slot
        r.close()
    finally:
        w.close(unlink=True)


def test_thumbnail_decimates_wide_images():
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    assert thumbnail(img, 320).shape == (240, 320, 3)
    assert thumbnail(img[:, :300], 320).shape == (480, 300, 3)


def test_out_and_in_publish_voxels_bev_cameras_and_history():
    scene, ego = box_scene()
    rig = ego.attach(CameraRig.surround(n=2, width=32, height=24, rate=10))
    scene.add_pipeline(
        Pipeline(
            [BackProject(max_range=20), OccupancyGrid(res=0.25, extent=30), BevMap()],
            inputs=rig,
            name="ego",
            snapshot_every=0.2,
            camera_every=0.2,
        )
    )
    sim = run_ticks(scene, 0)
    out, inp = PerceptionOut(sim), PerceptionIn()
    try:
        assert out.active and set(out.cameras) == {"ego.cam0", "ego.cam1"}
        evs = out.events()
        assert [e["event"] for e in evs] == [proto.FRAMES, proto.SNAPSHOTS]
        kinds = {s: k for s, k, _shm, _seq in evs[0]["frames"]}
        assert kinds == {
            "ego.voxels": proto.VOXELS,
            "ego.bev": proto.BEV,
            "ego.cam0": proto.CAMERA,
            "ego.cam1": proto.CAMERA,
        }
        assert len(evs[1]["snapshots"]) == 1 and len(evs[1]["frames"]) == 2
        assert out.events() == []  # nothing new
        for _ in range(30):  # two more pipeline updates; the UI skips the first
            sim.step()
            more = out.events()
            for e in more:
                if e["event"] == proto.FRAMES:
                    inp.on_event(e)
        got = inp.read()
        assert set(got) == set(kinds)
        vox = inp.latest["ego.voxels"]
        grid = scene.pipelines[0].log.grid()
        assert vox.seq == 3 and vox.res == 0.25 and vox.t == pytest.approx(grid.t)
        np.testing.assert_allclose(vox.data, grid.occupied_centers(), atol=1e-5)
        bev = inp.latest["ego.bev"]
        assert bev.data.ndim == 2 and bev.res > 0 and bev.ego is not None
        assert bev.ego[:2] == pytest.approx(scene["ego"].x[:2])
        assert inp.latest["ego.cam0"].data.shape == (24, 32, 3)
    finally:
        inp.clear()
        out.close()


def test_a_frame_that_outgrows_its_slot_moves_to_a_bigger_one():
    scene, _ = box_scene()
    out, inp = PerceptionOut(run_ticks(scene, 0)), PerceptionIn()
    try:
        empty = np.zeros((0, 3), np.float32)  # no occupied voxels yet
        ev = out._put("p.voxels", proto.VOXELS, empty, (0.0, 0.2))
        inp.on_event({"frames": [ev]})
        assert inp.read() == ["p.voxels"] and inp.latest["p.voxels"].data.shape == (0, 3)
        first = ev[2]
        big = np.ones((5000, 3), np.float32)  # 60 kB > the 4 kB first slot
        ev2 = out._put("p.voxels", proto.VOXELS, big, (0.1, 0.2))
        assert ev2[2] != first and ev2[3] == 1
        assert out.slots["p.voxels"].capacity >= big.nbytes * 1.5 - 1
        inp.on_event({"frames": [ev2]})
        assert inp.read() == ["p.voxels"]
        np.testing.assert_array_equal(inp.latest["p.voxels"].data, big)
        assert first not in inp.slots and inp.names["p.voxels"] == ev2[2]  # old one closed
        # a stale event naming the unlinked slot is skipped, not an error
        inp.on_event({"frames": [("q.voxels", proto.VOXELS, first, 0)]})
        assert inp.read() in ([], ["q.voxels"])  # Windows may keep a mapped slot alive
    finally:
        inp.clear()
        out.close()


def test_slot_metadata_is_bounded():
    w = FrameSlot(64, create=True)
    try:
        with pytest.raises(ValueError, match="metadata"):
            w.write(0, np.zeros(2, np.float32), tuple(range(9)))
    finally:
        w.close(unlink=True)


def _record_scene(tmp_path):
    out = (tmp_path / "ds").as_posix()
    path = tmp_path / "rec_scene.py"
    path.write_text(
        "import simview as sv\n"
        "from simview.perception import CameraRig, Pipeline, Record\n"
        "from tests.perception.helpers import box_scene\n"
        "scene, ego = box_scene()\n"
        "rig = ego.attach(CameraRig.surround(n=1, width=8, height=6))\n"
        f"scene.add_pipeline(Pipeline([Record({out!r}, flush_every=None)], inputs=rig))\n",
        encoding="utf-8",
    )
    return path


def _server(tmp_path):
    import zmq

    from simview.ipc.server import Server

    ctx = zmq.Context.instance()
    ui = ctx.socket(zmq.PAIR)
    port = ui.bind_to_random_port("tcp://127.0.0.1")
    return Server(str(_record_scene(tmp_path)), f"tcp://127.0.0.1:{port}"), ui


def test_server_closes_the_old_sim_when_it_reloads(tmp_path):
    from simview.perception import Dataset

    server, ui = _server(tmp_path)
    try:
        assert server.load()
        server.advance(3)
        assert not (tmp_path / "ds" / "cameras.json").exists()
        assert server.load()  # reset: the first run ends, so its Record index is written
        assert len(Dataset(tmp_path / "ds")) >= 1
    finally:
        server.buffer.close(unlink=True)
        server.perception.close()
        server.sock.close(linger=0)
        server.ctx.term()
        ui.close(linger=0)


def test_server_cleans_up_even_when_its_loop_crashes(tmp_path, monkeypatch):
    import sys

    from simview.perception import Dataset

    server, ui = _server(tmp_path)
    out, err = sys.stdout, sys.stderr

    def crash():
        server.load()
        server.advance(2)
        raise RuntimeError("loop bug")

    monkeypatch.setattr(server, "_loop", crash)
    try:
        with pytest.raises(RuntimeError, match="loop bug"):
            server.run()
        assert server.buffer is None  # closed and unlinked
        assert len(Dataset(tmp_path / "ds")) >= 1  # Sim.close() ran
    finally:
        sys.stdout, sys.stderr = out, err
        ui.close(linger=0)
