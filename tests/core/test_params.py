"""SC-05: live parameters, in the core (no sim process)."""

import json

import numpy as np
import pyarrow.parquet as pq
import pytest

import simview as sv
from simview.core.params import Params
from simview.core.scheduler import Sim


class Cart(sv.Entity):
    """x' = v, v' = u: a controller pushes it with the force `params.force`."""

    state_names = ("x", "v")

    def derivative(self, t, x, u):
        return np.array([x[1], float(u[0]) if len(u) else 0.0])


def cart_scene():
    scene = sv.Scene(dt=0.01)
    scene.add_entity(Cart([0.0, 0.0], name="cart"))
    scene.params.force = 0.0
    scene.params.gains = [1.0, 2.0]

    @scene.controller()
    def push(t, state, ctx):
        return {"cart": [ctx.params.force]}

    return scene


def test_change_takes_effect_on_the_next_tick():
    scene = cart_scene()
    sim = Sim(scene)
    for _ in range(5):
        sim.step()
    assert scene["cart"].x[1] == 0.0
    sim.params.force = 3.0
    sim.step()  # the very next tick uses the new value
    assert scene["cart"].x[1] == pytest.approx(3.0 * 0.01)
    assert sim.params is scene.params


def test_values_keep_their_kind_and_names_are_fixed_once_running():
    scene = cart_scene()
    sim = Sim(scene)
    sim.params.force = 2  # ints become floats
    assert isinstance(sim.params.force, float)
    sim.params["gains"] = np.array([3.0, 4.0])
    np.testing.assert_array_equal(sim.params.gains, [3.0, 4.0])
    with pytest.raises(TypeError, match="shape"):
        sim.params.gains = [1.0, 2.0, 3.0]
    with pytest.raises(TypeError, match="array"):
        sim.params.gains = 1.0
    with pytest.raises(TypeError, match="number"):
        sim.params.force = [1.0]
    with pytest.raises(TypeError):
        sim.params.force = "fast"
    with pytest.raises(AttributeError, match="declare it in the scene file"):
        sim.params.forse = 1.0  # a typo is an error, not a silent no-op
    with pytest.raises(AttributeError):
        sim.params.nothing  # noqa: B018
    with pytest.raises(AttributeError, match="valid"):
        sim.params.set("_private", 1.0)
    assert "force" in sim.params and len(sim.params) == 2 and list(sim.params) == ["force", "gains"]
    assert "force=2.0" in repr(sim.params)


def test_params_object_basics():
    p = Params()
    p.a = 1.5
    d = p.to_dict()
    assert d == {"a": 1.5} and "a" in dir(p)
    import copy

    assert copy.copy(p).a == 1.5  # no recursion through __getattr__


def test_scalar_params_are_logged_and_start_values_go_in_metadata(tmp_path):
    scene = cart_scene()

    @scene.controller()
    def bump(t, state, ctx):
        if ctx.tick == 50:
            ctx.params.force = 1.0

    run = sv.run(scene, duration=1.0, out=tmp_path / "run.parquet")
    force = run["params.force"]
    assert force[50] == 0.0 and force[51] == 1.0  # the row after the change shows it
    assert "params.gains" not in run.columns  # arrays are not logged
    meta = json.loads(pq.read_schema(run.path).metadata[b"simview"])
    assert meta["params"] == {"force": 0.0, "gains": [1.0, 2.0]}
