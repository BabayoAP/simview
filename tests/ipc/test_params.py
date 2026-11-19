"""SC-05 across processes: `client.set_param` takes effect on the sim's next tick."""

import numpy as np
import pytest

from simview.ipc import protocol as proto
from simview.ipc.client import SimClient
from tests.ipc.test_process import scene_file, wait_for

CART = """
    import numpy as np
    import simview as sv

    class Cart(sv.Entity):
        state_names = ("x", "v")
        def derivative(self, t, x, u):
            return np.array([x[1], float(u[0]) if len(u) else 0.0])

    scene = sv.Scene(dt=0.01)
    scene.add_entity(Cart([0.0, 0.0], name="cart"))
    scene.params.force = 0.0

    @scene.controller()
    def push(t, state, ctx):
        return {"cart": [ctx.params.force]}
"""


@pytest.fixture
def client():
    c = SimClient()
    yield c
    c.stop()


def test_set_param_applies_on_the_next_tick(client, tmp_path):
    client.start(scene_file(tmp_path, CART))
    ready, _ = wait_for(client, proto.READY)
    assert ready["description"].params == {"force": 0.0}
    assert "params.force" in ready["rows"].signals
    client.step(3)
    client.set_param("force", 2.0)
    ev, _ = wait_for(client, proto.PARAMS)
    assert ev["values"] == {"force": 2.0}
    client.step(1)
    end = wait_for_tick(client, 4)
    assert end.states["cart"][1] == pytest.approx(2.0 * 0.01)  # one tick at the new force


def test_a_rejected_param_reports_and_keeps_the_old_value(client, tmp_path):
    client.start(scene_file(tmp_path, CART))
    wait_for(client, proto.READY)
    client.set_param("forse", 1.0)
    ev, seen = wait_for(client, proto.PARAMS)
    assert ev["values"] == {"force": 0.0}
    logs = [e["text"] for e in seen if e["event"] == proto.LOG]
    assert any("no parameter 'forse'" in t for t in logs)
    assert client.alive


def wait_for_tick(client, tick, timeout=30.0):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        client.poll()
        f = client.frame()
        if f is not None and f.tick == tick:
            return f
        time.sleep(0.01)
    raise AssertionError(f"never reached tick {tick}")


def test_array_params_round_trip(client, tmp_path):
    body = CART + "\n    scene.params.gains = [1.0, 2.0]\n"
    client.start(scene_file(tmp_path, body))
    wait_for(client, proto.READY)
    client.set_param("gains", np.array([5.0, 6.0]))
    ev, _ = wait_for(client, proto.PARAMS)
    np.testing.assert_array_equal(ev["values"]["gains"], [5.0, 6.0])
