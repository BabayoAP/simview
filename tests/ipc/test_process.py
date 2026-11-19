"""SE-02, SE-10, NF-04, NF-10: the sim process, pacing, latency, and crash isolation.

Each test starts a real sim process (spawned), so these take about a second each.
"""

import textwrap
import time
from pathlib import Path

import numpy as np
import pytest

from simview.ipc import protocol as proto
from simview.ipc.client import SimClient

ROOT = Path(__file__).resolve().parents[2]
PICK = ROOT / "examples" / "ur5_pick.py"


def wait_for(client, event, timeout=60.0):
    end = time.monotonic() + timeout
    seen = []
    while time.monotonic() < end:
        for ev in client.poll():
            seen.append(ev)
            if ev["event"] == event:
                return ev, seen
        time.sleep(0.01)
    raise AssertionError(f"no {event!r} event; got {[e['event'] for e in seen]}")


@pytest.fixture
def client():
    c = SimClient()
    yield c
    c.stop()


def scene_file(tmp_path, body):
    path = tmp_path / "scene.py"
    path.write_text(textwrap.dedent(body))
    return path


BALL = """
    import numpy as np
    import simview as sv

    class Ball(sv.Entity):
        state_names = ("x", "z", "vz")
        def derivative(self, t, x, u):
            return np.array([0.0, x[2], -9.81])

    scene = sv.Scene(dt=1e-3)
    scene.add_entity(Ball([0.0, 10.0, 0.0], name="ball"))
"""


def test_ready_describes_the_scene(client):
    client.start(PICK)
    ev, _ = wait_for(client, proto.READY)
    desc = ev["description"]
    assert {e.name: e.kind for e in desc.entities} == {
        "ur5": "robot",
        "grip": "robot",
        "cube": "body",
    }
    assert desc.has_ground and any(g.kind == "mesh" for g in desc.geoms)
    mesh = next(g for g in desc.geoms if g.kind == "mesh")
    assert mesh.vertices.shape[1] == 3 and mesh.faces.shape[1] == 3
    cube = desc.entity_of_body(desc.body_names.index("cube"))
    assert cube == "cube"
    f = client.frame()
    assert f is not None and f.tick == 0 and not f.running
    assert f.bodies.shape == (len(desc.body_names), 7)


def test_real_time_pacing_and_latency(client):
    """SE-10 at 1.0x, and NF-04: state reaches the UI within 20 ms."""
    client.start(PICK)
    wait_for(client, proto.READY)
    start = client.frame()
    client.play()
    t0, latencies = time.monotonic(), []
    while time.monotonic() - t0 < 1.5:
        client.poll()
        f = client.frame()
        if f is not None and f.running:
            latencies.append(time.monotonic() - f.wall)
        time.sleep(0.003)
    f = client.frame()
    wall = time.monotonic() - t0
    assert f.t - start.t == pytest.approx(wall, rel=0.1)  # paced at real time
    assert np.median(latencies) < 0.020


def test_speed_and_flat_out(client):
    client.start(PICK)
    wait_for(client, proto.READY)
    client.set_speed(0)  # as fast as possible
    client.play()
    time.sleep(1.0)
    client.poll()
    assert client.frame().rtf > 2.0  # faster than real time (machine-dependent)
    client.set_speed(0.5)
    time.sleep(1.0)
    client.poll()
    assert client.frame().rtf == pytest.approx(0.5, abs=0.1)


def test_step_pause_and_reset(client, tmp_path):
    client.start(scene_file(tmp_path, BALL))
    wait_for(client, proto.READY)
    client.step(10)
    time.sleep(0.3)
    client.poll()
    f = client.frame()
    assert f.tick == 10 and not f.running
    assert f.markers["ball"][2] == pytest.approx(10.0 - 0.5 * 9.81 * 0.01**2, abs=1e-6)
    client.reset()
    wait_for(client, proto.READY)
    assert client.frame().tick == 0


def test_user_error_reaches_ui_and_process_survives(client, tmp_path):
    """NF-10: a controller exception arrives as a traceback; the sim stays up and pauses."""
    path = scene_file(
        tmp_path,
        BALL
        + """
    @scene.controller()
    def bad(t, state, ctx):
        print("tick", ctx.tick)
        if t >= 0.005:
            raise RuntimeError("controller blew up")
    """,
    )
    client.start(path)
    wait_for(client, proto.READY)
    client.play()
    ev, seen = wait_for(client, proto.ERROR)
    assert "controller blew up" in ev["traceback"] and "RuntimeError" in ev["traceback"]
    assert any(e["event"] == proto.LOG and "tick 0" in e["text"] for e in seen)  # print forwarded
    time.sleep(0.2)
    client.poll()
    assert client.alive and not client.frame().running


def test_broken_scene_file_reports_error(client, tmp_path):
    client.start(scene_file(tmp_path, "import simview as sv\nscene = sv.Scene(dt=5.0)\n"))
    ev, _ = wait_for(client, proto.ERROR)
    assert "dt must be between" in ev["traceback"]
    assert client.alive


def test_killed_sim_is_reported_and_restartable(client):
    """SE-02 / M4 done-when: killing the sim process doesn't take the UI side down."""
    client.start(PICK)
    wait_for(client, proto.READY)
    client.play()
    client.proc.kill()
    ev, _ = wait_for(client, proto.STOPPED, timeout=10)
    assert ev["exitcode"] != 0 and not client.alive
    assert client.poll() == []  # reported once
    client.step()  # commands to a dead sim are ignored, not raised
    client.start(PICK)
    wait_for(client, proto.READY)


def test_targets_bodies_and_draws(client, tmp_path):
    path = scene_file(
        tmp_path,
        BALL
        + """
    import numpy as np
    scene.add_ground()
    scene.add_box("box", (0.1, 0.1, 0.1), (0, 0, 1), mass=1.0)
    goal = scene.add_target("goal")

    @scene.controller()
    def show(t, state, ctx):
        ctx.draw.point(goal.pose[:3, 3])
        ctx.draw.text((0, 0, 1), "goal", persist=True)
    """,
    )
    client.start(path)
    ev, _ = wait_for(client, proto.READY)
    assert "goal" in ev["description"].targets
    pose = np.eye(4)
    pose[:3, 3] = [0.5, 0.2, 0.3]
    client.set_target("goal", pose)
    client.set_body_pose("box", [1.0, 2.0, 3.0], [1.0, 0, 0, 0])
    client.step(1)
    ev, _ = wait_for(client, proto.DRAWS)
    while True:  # take the newest draws
        later = [e for e in client.poll() if e["event"] == proto.DRAWS]
        if not later:
            break
        ev = later[-1]
    kinds = sorted(d[0] for d in ev["draws"])
    assert kinds == ["point", "text"]
    point = next(d for d in ev["draws"] if d[0] == "point")
    assert point[1][0] == pytest.approx((0.5, 0.2, 0.3))
    f = client.frame()
    np.testing.assert_allclose(f.states["box"][:3], [1.0, 2.0, 3.0 - 9.81 * 1e-6], atol=1e-4)
