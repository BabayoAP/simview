"""UC-2 (PRD 1.3) / M8 done-when: the Drone Delivery template runs end to end (TB-AERO,
SN-01, VP-09)."""

import numpy as np
import pytest

import simview as sv
from simview.runner.headless import load_scene
from simview.templates import scene_path

DRONES = ("d0", "d1", "d2")


@pytest.fixture(scope="module")
def delivery(tmp_path_factory):
    scene = load_scene(scene_path("drone_delivery"))
    run = sv.run(scene, 60.0, out=tmp_path_factory.mktemp("dd") / "dd.parquet")
    return scene, run


def test_template_contents():
    scene = load_scene(scene_path("drone_delivery"))
    assert set(scene.entities) == {"wind", *DRONES}
    for name in DRONES:
        quad = scene[name]
        assert isinstance(quad, sv.aero.Quadrotor) and quad.wind is scene["wind"]
        assert quad.sensors.imu.rate == 200.0 and quad.sensors.gps.rate == 10.0  # UC-2 step 2
    assert {"gps_noise", "imu_noise", "gust"} <= set(scene.params.to_dict())  # M9 sweep knobs


def test_every_drone_delivers_and_comes_home(delivery):
    scene, run = delivery
    for name in DRONES:
        delivered = run[f"{name}_delivered"]
        t_drop = np.nanmin(delivered)
        assert 15.0 < t_drop < 30.0, name  # 45-56 m out at 6 m/s, plus the climb
        assert np.isnan(delivered[: int(t_drop * 1000) - 1]).all()  # NaN until it's made
        home = np.array([run[f"{name}.x"][-1], run[f"{name}.y"][-1], run[f"{name}.z"][-1]])
        pad = scene[name].x0[:3]
        assert np.linalg.norm(home - pad) < 0.5, name
        assert run[f"{name}_dev"].max() < 0.6, name  # on its route through the gusts


def test_estimates_are_consistent(delivery):
    """UC-2 step 6: the estimation error stays inside its +-3 sigma bounds."""
    _, run = delivery
    for name in DRONES:
        e = np.c_[[run[f"{name}_err_{a}"] for a in "xyz"]].T
        b = np.c_[[run[f"{name}_bound_{a}"] for a in "xyz"]].T
        assert np.mean(np.abs(e) <= b) > 0.97, name
        assert np.sqrt(np.mean(run[f"{name}_err"] ** 2)) < 0.4, name  # well under the GPS noise


def test_the_wind_gusts(delivery):
    _, run = delivery
    speed = run["wind_speed"]
    assert speed.mean() == pytest.approx(np.hypot(3.0, 1.5), abs=1.0)
    assert speed.max() > 5.0


def test_same_seed_same_flight():
    def flight():
        return sv.run(load_scene(scene_path("drone_delivery")), 2.0)["d0.x"]

    np.testing.assert_array_equal(flight(), flight())


def test_draws_routes_ellipsoids_and_wind():
    from simview.core.scheduler import Sim

    sim = Sim(load_scene(scene_path("drone_delivery")))
    sim.step()
    kinds = [d.kind for d in sim.draw.snapshot()]
    assert kinds.count("ellipsoid") == 3 and kinds.count("arrow") == 1
    assert kinds.count("line") == 3 * 6  # each route's six legs, persistent
