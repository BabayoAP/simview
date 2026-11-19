"""SE-01 dt range, scene and entity validation, SE-07 RNG."""

import numpy as np
import pytest

from simview import Entity, Scene
from simview.core.rng import make_rng
from simview.core.scheduler import Sim, tick_count


class Point(Entity):
    state_names = ("x", "v")

    def derivative(self, t, x, u):
        return np.array([x[1], 0.0])


@pytest.mark.parametrize("dt", [1e-4, 1e-3, 1e-1])
def test_dt_in_range(dt):
    assert Scene(dt=dt).dt == dt


@pytest.mark.parametrize("dt", [5e-5, 0.2, 0.0, -1e-3])
def test_dt_out_of_range(dt):
    with pytest.raises(ValueError, match="dt"):
        Scene(dt=dt)


def test_default_dt_is_1ms():
    assert Scene().dt == 1e-3


def test_duplicate_entity_name_rejected():
    scene = Scene()
    scene.add_entity(Point([0, 1]))
    with pytest.raises(ValueError, match="already exists"):
        scene.add_entity(Point([0, 1]))
    scene.add_entity(Point([0, 1], name="other"))
    assert list(scene.entities) == ["point", "other"]


def test_bad_channel_name_rejected():
    scene = Scene()
    scene.log("a", lambda sim: 0.0)
    with pytest.raises(ValueError):
        scene.log("a", lambda sim: 0.0)
    with pytest.raises(ValueError):
        scene.log("b.c", lambda sim: 0.0)


def test_x0_shape_checked():
    with pytest.raises(ValueError, match="x0"):
        Point([0.0])


def test_derivative_shape_checked():
    class Bad(Point):
        def derivative(self, t, x, u):
            return np.zeros(3)

    scene = Scene()
    scene.add_entity(Bad([0, 1]))
    with pytest.raises(ValueError, match="shape"):
        Sim(scene)


def test_state_access_by_name():
    p = Point([2.0, 3.0])
    assert p["x"] == 2.0 and p["v"] == 3.0


def test_fixed_step_clock_does_not_drift():
    scene = Scene(dt=1e-4)
    scene.add_entity(Point([0, 1]))
    sim = Sim(scene)
    for _ in range(10_000):
        sim.step()
    assert sim.t == 1.0
    assert scene["point"]["x"] == pytest.approx(1.0, abs=1e-12)


def test_tick_count():
    assert tick_count(1.0, 1e-3) == 1000
    assert tick_count(0.3, 0.1) == 3
    with pytest.raises(ValueError):
        tick_count(0.0015, 1e-3)
    with pytest.raises(ValueError):
        tick_count(0.0, 1e-3)


def test_rng_is_seeded_generator():
    a, b = make_rng(7), make_rng(7)
    assert isinstance(a, np.random.Generator)
    assert np.array_equal(a.normal(size=5), b.normal(size=5))
    assert not np.array_equal(make_rng(8).normal(size=5), make_rng(7).normal(size=5))


def test_sim_exposes_rng_and_resets_state():
    scene = Scene(seed=3)
    p = scene.add_entity(Point([0, 1]))
    sim = Sim(scene)
    sim.step()
    assert p["x"] > 0
    sim2 = Sim(scene)
    assert p["x"] == 0.0
    assert sim2.rng.random() == make_rng(3).random()
