"""Security review regressions (D-136): data files and IPC messages never run code, and
files named by data stay inside the folder they came with."""

import json
import pickle
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import zmq

from simview.ipc import protocol as proto
from simview.ipc.shm import FrameSlot

ROOT = Path(__file__).resolve().parents[1]
RAN: list[str] = []


class _Payload:
    """Unpickling this records that code ran."""

    def __reduce__(self):
        return (RAN.append, ("pwned",))


@pytest.fixture
def pair():
    ctx = zmq.Context.instance()
    a, b = ctx.socket(zmq.PAIR), ctx.socket(zmq.PAIR)
    port = a.bind_to_random_port("tcp://127.0.0.1")
    b.connect(f"tcp://127.0.0.1:{port}")
    yield a, b
    a.close(linger=0)
    b.close(linger=0)


def _wait(sock):
    assert sock.poll(2000), "no message"


# -- IPC ----------------------------------------------------------------------------------------
def test_signed_messages_round_trip(pair):
    a, b = pair
    key = proto.new_key()
    proto.send(a, key, {"cmd": "step", "n": 3, "x": np.arange(3.0)})
    _wait(b)
    msg = proto.recv(b, key)
    assert msg["cmd"] == "step" and msg["n"] == 3
    np.testing.assert_array_equal(msg["x"], [0, 1, 2])


def test_unsigned_or_forged_messages_are_dropped_unread(pair):
    a, b = pair
    key = proto.new_key()
    RAN.clear()
    a.send(pickle.dumps(_Payload()))  # plain send_pyobj-style message
    _wait(b)
    assert proto.recv(b, key) is None
    proto.send(a, proto.new_key(), _Payload())  # signed with another key
    _wait(b)
    assert proto.recv(b, key) is None
    data = pickle.dumps(_Payload())
    a.send_multipart([b"\x00" * 32, data])  # a made-up signature
    _wait(b)
    assert proto.recv(b, key) is None
    assert RAN == []


def test_sim_socket_listens_on_loopback_only_with_a_session_key():
    from simview.ipc.client import SimClient

    client = SimClient()
    client.start(ROOT / "examples" / "bouncing_ball.py")
    try:
        endpoint = client.sock.getsockopt(zmq.LAST_ENDPOINT).decode()
        assert endpoint.startswith("tcp://127.0.0.1:")
        assert len(client.key) == proto.KEY_BYTES
        deadline = time.monotonic() + 30
        while client.description is None and time.monotonic() < deadline:
            client.poll()  # the sim answers with messages signed under the same key
            time.sleep(0.01)
        assert client.description is not None
    finally:
        client.stop()


# -- shared memory --------------------------------------------------------------------------
def test_frame_slot_rejects_a_header_that_does_not_fit():
    slot = FrameSlot(64, create=True)
    try:
        slot.write(1, np.arange(4, dtype=np.float32))
        reader = FrameSlot(name=slot.name)
        assert reader.read().data.tolist() == [0, 1, 2, 3]
        for i, bad in ((2, 10**9), (3, 99), (4, 7), (5, -1)):
            saved = int(slot.ints[i])
            slot.ints[i] = bad  # nbytes, dtype code, ndim, a dimension
            assert reader.read() is None
            slot.ints[i] = saved
        reader.close()
    finally:
        slot.close(unlink=True)


# -- data files ---------------------------------------------------------------------------------
@pytest.mark.parametrize("escape", ["../outside.png", "ABS"])
def test_dataset_files_must_stay_inside_the_folder(tmp_path, escape):
    from simview.perception import Dataset, DatasetError, write_dataset
    from tests.perception.test_dataset import make_frames

    ds = tmp_path / "ds"
    write_dataset(ds, make_frames(n_cams=1, n=1, depth=False))
    meta = json.loads((ds / "cameras.json").read_text(encoding="utf-8"))
    outside = tmp_path / "outside.png"
    outside.write_bytes((ds / meta["cameras"][0]["frames"][0]["rgb"]).read_bytes())
    meta["cameras"][0]["frames"][0]["rgb"] = str(outside) if escape == "ABS" else escape
    (ds / "cameras.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(DatasetError, match="outside the dataset folder"):
        Dataset(ds)


def test_dataset_writer_refuses_a_camera_name_with_a_drive(tmp_path):
    from simview.perception import DatasetWriter
    from tests.perception.test_dataset import make_frames

    (f,) = make_frames(n_cams=1, n=1, depth=False)
    f.source = "C:evil"
    with DatasetWriter(tmp_path / "ds") as w, pytest.raises(ValueError, match="folder name"):
        w.add(f)


@pytest.mark.parametrize("key", ["scene", "script", "diagram"])
@pytest.mark.parametrize("rel", ["../evil.py", "ABS", 5])
def test_project_files_must_stay_inside_the_project(tmp_path, key, rel):
    from simview.io import project

    p = project.create(tmp_path / "demo")
    manifest = p.path / project.MANIFEST
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data[key] = str(tmp_path / "evil.py") if rel == "ABS" else rel
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(project.ProjectError, match="inside the project"):
        project.load(p.path)


def test_project_relative_files_still_load(tmp_path):
    from simview.io import project

    p = project.create(tmp_path / "demo")
    p.scene = "scenes/scene.py"
    p.save()
    assert project.load(p.path).scene == "scenes/scene.py"


def test_scenario_constants_cannot_spin_on_huge_integers():
    from simview.investigate.scenario import Scenario

    run = {"x": np.zeros(3)}
    start = time.perf_counter()
    mask = Scenario("big", "x > 9**9**9**9").mask(run)
    assert time.perf_counter() - start < 1.0
    assert not mask.any()


def test_menagerie_refuses_files_outside_the_robot_folder(tmp_path, monkeypatch):
    from simview.toolboxes.robotics import library

    monkeypatch.setenv("SIMVIEW_CACHE", str(tmp_path))
    written: list[Path] = []

    def fake_download(rel, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("<mujoco/>", encoding="utf-8")
        written.append(dest)

    monkeypatch.setattr(library, "_download", fake_download)
    monkeypatch.setattr(library, "_referenced", lambda _p, _f: ["../../../evil.xml"])
    with pytest.raises(library.FetchError, match="outside"):
        library.fetch("panda")
    base = library.robot_dir("panda").resolve()
    assert all(p.resolve().is_relative_to(base) for p in written)


def test_report_escapes_run_names_and_scenarios(tmp_path):
    from simview.investigate import Catalog, Scenario, scan, write_report
    from tests.investigate.test_runs import make_runs

    (run,) = make_runs(tmp_path, seeds=(1,))
    side = Path(run.path).with_suffix(".run.json")
    side.write_text(json.dumps({"scene": "<script>alert(1)</script>"}), encoding="utf-8")
    cat = Catalog(tmp_path)
    results = scan(cat, [Scenario("<img src=x onerror=alert(2)>", "t > 0")])
    out = write_report([cat.open(Path(run.path).name)], results, tmp_path / "r.html")
    page = out.read_text(encoding="utf-8")
    assert "<script" not in page and "<img" not in page
    assert "&lt;script&gt;alert(1)" in page and "&lt;img src=x" in page


# -- the app: replaying a run loads its scene ---------------------------------------------------
@pytest.fixture
def window(qapp, settings, tmp_path, monkeypatch):
    from simview.ui.main_window import MainWindow

    monkeypatch.setenv("SIMVIEW_RUNS", str(tmp_path / "runs"))
    w = MainWindow(settings)
    w.open_reports = False
    yield w
    w.close()


def test_a_run_naming_a_foreign_scene_asks_before_running_it(window, tmp_path, monkeypatch):
    evil = tmp_path / "elsewhere" / "scene.py"
    evil.parent.mkdir()
    evil.write_text("raise SystemExit('ran')\n", encoding="utf-8")
    asked, loaded = [], []
    monkeypatch.setattr(window, "confirm_run_scene", lambda p: asked.append(p) or False)
    monkeypatch.setattr(window, "load_scene", loaded.append)
    run = SimpleNamespace(name="r", scene=str(evil), path=tmp_path / "r.parquet")
    window.open_run(run)
    assert asked == [evil] and loaded == []

    template = next((ROOT / "src" / "simview" / "templates").glob("*/scene.py"))
    window.open_run(SimpleNamespace(name="t", scene=str(template), path=tmp_path / "t.parquet"))
    assert asked == [evil] and loaded == [template]  # SimView's own templates: no question
