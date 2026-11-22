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
