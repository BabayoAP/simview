"""SE-04: Euler, RK4, and adaptive RK45, selectable per model."""

import math

import numpy as np
import pytest

from simview import Entity, Scene, run
from simview.core.integrators import INTEGRATORS, step


def decay(t, x, u):
    return -x


def global_error(name, dt, t_end=1.0):
    x = np.array([1.0])
    for k in range(round(t_end / dt)):
        x = step(name, decay, k * dt, x, np.zeros(0), dt)
    return abs(x[0] - math.exp(-t_end))


@pytest.mark.parametrize(("name", "order"), [("euler", 1), ("rk4", 4)])
def test_convergence_order(name, order):
    ratio = global_error(name, 0.02) / global_error(name, 0.01)
    assert ratio == pytest.approx(2**order, rel=0.1)


def test_rk45_meets_tolerance():
    assert global_error("rk45", 0.01) < 1e-7


def test_rk4_exact_for_constant_acceleration():
    # Free fall is quadratic in t, so RK4 reproduces it to rounding error.
    def fall(t, x, u):
        return np.array([x[1], -9.81])

    x, dt = np.array([1.0, 0.0]), 1e-3
    for k in range(400):
        x = step("rk4", fall, k * dt, x, np.zeros(0), dt)
    t = 0.4
    assert x[0] == pytest.approx(1.0 - 9.81 * t**2 / 2, abs=1e-12)
    assert x[1] == pytest.approx(-9.81 * t, abs=1e-12)


class Decay(Entity):
    state_names = ("x",)

    def derivative(self, t, x, u):
        return -x


def test_integrator_selectable_per_model(tmp_path):
    scene = Scene(dt=0.01)
    for name in INTEGRATORS:
        scene.add_entity(Decay([1.0], name=name, integrator=name))
    result = run(scene, 1.0, out=tmp_path / "r.parquet")
    finals = {name: result[f"{name}.x"][-1] for name in INTEGRATORS}
    exact = math.exp(-1.0)
    assert abs(finals["euler"] - exact) > 1e-3  # first order: visibly off
    assert abs(finals["rk4"] - exact) < 1e-8
    assert abs(finals["rk45"] - exact) < 1e-7


def test_unknown_integrator_rejected():
    with pytest.raises(ValueError, match="integrator"):
        Decay([1.0], integrator="midpoint")
