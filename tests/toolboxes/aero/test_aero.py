"""TB-AERO (PRD 1.3): quadrotor, flight control, wind, routes, EKF / UKF, navigation filter."""

import numpy as np
import pytest

import simview as sv
from simview import Scene
from simview.core.scheduler import Sim
from simview.sensors import GPS, IMU
from simview.toolboxes import aero

G = 9.81


def fly(quad, control, seconds, dt=1e-3):
    """Close the loop by hand (no scene); `control(t)` returns the input."""
    for k in range(int(round(seconds / dt))):
        quad.u = control(k * dt)
        quad.advance(k * dt, dt)


# -- quadrotor -------------------------------------------------------------------------------
def test_no_thrust_falls_and_hover_thrust_holds():
    quad = aero.Quadrotor((0, 0, 10), drag=0.0)
    fly(quad, lambda t: np.zeros(4), 1.0)
    assert quad["z"] == pytest.approx(10 - G / 2, abs=1e-6)
    quad = aero.Quadrotor((0, 0, 10), drag=0.0, mass=1.5)
    fly(quad, lambda t: np.array([quad.hover_thrust, 0, 0, 0]), 2.0)
    assert quad["z"] == pytest.approx(10.0, abs=1e-9)


def test_yaw_torque_spins_up_and_quaternion_stays_unit():
    quad = aero.Quadrotor(inertia=(0.01, 0.01, 0.02), drag=0.0)
    fly(quad, lambda t: np.array([quad.hover_thrust, 0, 0, 0.01]), 1.0)
    assert quad["r"] == pytest.approx(0.01 / 0.02 * 1.0, rel=1e-6)
    assert np.linalg.norm(quad.x[6:10]) == pytest.approx(1.0, abs=1e-12)
    yaw = np.arctan2(quad.rotation()[1, 0], quad.rotation()[0, 0])
    assert yaw == pytest.approx(0.5 * 0.5 * 1.0**2, abs=1e-6)  # 1/2 alpha t^2


def test_inputs_are_clipped():
    quad = aero.Quadrotor(mass=1.0, max_torque=0.2)
    thrust, tau = quad.inputs(np.array([1e3, -5.0, 0.1, 5.0]))
    assert thrust == pytest.approx(2.5 * G) and tau.tolist() == [-0.2, 0.1, 0.2]
    assert quad.inputs(np.array([-1.0]))[0] == 0.0
    with pytest.raises(ValueError):
        aero.Quadrotor(mass=0)


def test_drag_pushes_a_hovering_drone_downwind():
    wind = aero.Wind(mean=(5.0, 0.0, 0.0))
    quad = aero.Quadrotor(drag=0.2, mass=1.0, wind=wind)
    quad.u = np.array([quad.hover_thrust, 0, 0, 0])
    accel = quad.derivative(0.0, quad.x, quad.u)[3:6]
    np.testing.assert_allclose(accel, [0.2 * 5.0, 0, 0], atol=1e-12)


def test_attitude_controller_achieves_the_commanded_acceleration():
    quad = aero.Quadrotor(drag=0.0)
    ctrl = aero.AttitudeController(quad)
    cmd = np.array([2.0, -1.0, 0.5])
    fly(quad, lambda t: ctrl(cmd, yaw=0.3), 1.0)
    achieved = quad.derivative(0.0, quad.x, quad.u)[3:6]
    np.testing.assert_allclose(achieved, cmd, atol=1e-3)
    # D-101: yaw sets the heading the body y axis is perpendicular to
    assert quad.rotation()[:, 1] @ [np.cos(0.3), np.sin(0.3), 0] == pytest.approx(0, abs=1e-4)


def test_attitude_controller_limits_tilt():
    quad = aero.Quadrotor(drag=0.0)
    ctrl = aero.AttitudeController(quad, max_tilt=np.radians(20))
    fly(quad, lambda t: ctrl([50.0, 0, 0]), 1.0)
    tilt = np.arccos(quad.rotation()[2, 2])
    assert tilt == pytest.approx(np.radians(20), abs=1e-3)


def test_position_controller_step():
    quad = aero.Quadrotor(drag=0.1)
    pc = aero.PositionController(quad)
    goal = np.array([5.0, -2.0, 3.0])
    zs = []

    def control(t):
        zs.append(quad.position().copy())
        return pc(goal, quad.position(), quad.velocity())

    fly(quad, control, 8.0)
    assert np.linalg.norm(quad.position() - goal) < 0.02
    overshoot = max(np.array(zs)[:, 0]) - goal[0]
    assert overshoot < 0.3


# -- wind ------------------------------------------------------------------------------------
def gusts(seed, n=20000, dt=0.01):
    scene = Scene(dt=dt, seed=seed)
    wind = scene.add_entity(aero.Wind((3.0, 0.0, 0.0), gust_std=(1.0, 1.0, 0.3), tau=0.2))
    sim = Sim(scene)
    out = []
    for _ in range(n):
        sim.step()
        out.append(wind.velocity())
    return np.array(out)


def test_wind_gust_statistics_and_correlation():
    w = gusts(seed=4)
    np.testing.assert_allclose(w.mean(axis=0), [3.0, 0, 0], atol=0.15)  # ~3 standard errors
    np.testing.assert_allclose(w.std(axis=0), [1.0, 1.0, 0.3], rtol=0.1)
    gx = w[:, 0] - w[:, 0].mean()
    lag1 = (gx[1:] @ gx[:-1]) / (gx @ gx)
    assert lag1 == pytest.approx(np.exp(-0.01 / 0.2), abs=0.01)


def test_wind_repeats_per_seed_and_logs():
    np.testing.assert_array_equal(gusts(1, 50), gusts(1, 50))
    assert not np.array_equal(gusts(1, 50), gusts(2, 50))
    scene = Scene(dt=0.01, seed=0)
    scene.add_entity(aero.Wind((1.0, 2.0, 0.0)))
    run = sv.run(scene, duration=0.1)
    np.testing.assert_allclose(run["wind.wy"], 2.0)


# -- routes ----------------------------------------------------------------------------------
def square_route(**kw):
    pts = [(0, 0, 2), (10, 0, 2), (10, 10, 2), (0, 0, 2)]
    return aero.Route(pts, **kw)


def test_route_distance_and_length():
    r = square_route()
    assert r.length == pytest.approx(20 + np.sqrt(200))
    np.testing.assert_allclose(r.distance([[5, 1, 2], [10, 5, 3], [0, 0, 2]]), [1.0, 1.0, 0.0])
    with pytest.raises(ValueError):
        aero.Route([(0, 0, 0)])


def test_route_follower_visits_waypoints_in_order_and_dwells():
    quad = aero.Quadrotor((0, 0, 2), drag=0.1)
    follower = aero.RouteFollower(square_route(speed=4.0, dwell=2.0), aero.PositionController(quad))
    dev = []

    def control(t):
        dev.append(follower.route.distance(quad.position())[0])
        return follower(t, quad.position(), quad.velocity())

    fly(quad, control, 30.0, dt=2e-3)
    assert follower.done
    times = [t for _, t in follower.arrivals]
    assert [i for i, _ in follower.arrivals] == [0, 1, 2, 3]
    assert np.all(np.diff(times) > 2.0)  # each leg starts after the 2 s dwell
    # leg 1 is 10 m at up to 4 m/s, ramping at 2 m/s^2: 4.5 s, plus lag inside the radius
    assert 4.5 < follower.arrival(1) < 6.0
    assert max(dev) < 0.5  # stays on the route


# -- filters ---------------------------------------------------------------------------------
def cv_model():
    def f(x, u, dt):
        return np.array([x[0] + dt * x[1], x[1]])

    def h(x):
        return x[:1]

    return f, h


def test_ekf_matches_the_linear_kalman_filter():
    f, h = cv_model()
    Q, R = np.diag([1e-4, 1e-3]), np.array([[0.04]])
    ekf = aero.EKF([0, 1], np.eye(2), f, h, Q, R)
    x, P = np.array([0.0, 1.0]), np.eye(2)
    F, H = np.array([[1, 0.1], [0, 1]]), np.array([[1.0, 0.0]])
    for k, z in enumerate([0.12, 0.18, 0.33, 0.41]):
        ekf.predict(0.1)
        ekf.update([z])
        x, P = F @ x, F @ P @ F.T + Q
        K = P @ H.T @ np.linalg.inv(H @ P @ H.T + R)
        x, P = x + K @ (np.array([z]) - H @ x), (np.eye(2) - K @ H) @ P
        np.testing.assert_allclose(ekf.x, x, atol=1e-8, err_msg=f"step {k}")
        np.testing.assert_allclose(ekf.P, P, atol=1e-8)
    assert ekf.nis >= 0


def test_ukf_matches_the_ekf_on_a_linear_model():
    f, h = cv_model()
    args = ([0, 1], np.eye(2), f, h, np.diag([1e-4, 1e-3]), np.array([[0.04]]))
    ekf, ukf = aero.EKF(*args), aero.UKF(*args)
    for z in [0.12, 0.18, 0.33, 0.41]:
        for flt in (ekf, ukf):
            flt.predict(0.1)
            flt.update([z])
    np.testing.assert_allclose(ukf.x, ekf.x, atol=1e-9)
    np.testing.assert_allclose(ukf.P, ekf.P, atol=1e-9)


def test_filters_track_through_a_nonlinear_range_measurement():
    """Range-only fixes from two beacons: both filters converge on a moving point."""
    beacons = np.array([[0.0, 0.0], [10.0, 0.0]])

    def f(x, u, dt):
        return np.array([x[0] + dt * x[2], x[1] + dt * x[3], x[2], x[3]])

    def h(x):
        return np.linalg.norm(beacons - x[:2], axis=1)

    rng = np.random.default_rng(0)
    truth = np.array([3.0, 4.0, 0.5, -0.2])
    filters = [
        cls([4.0, 5.0, 0, 0], np.eye(4), f, h, np.eye(4) * 1e-6, np.eye(2) * 0.01)
        for cls in (aero.EKF, aero.UKF)
    ]
    for _ in range(200):
        truth = f(truth, None, 0.1)
        z = h(truth) + 0.1 * rng.standard_normal(2)
        for flt in filters:
            flt.predict(0.1)
            flt.update(z)
    for flt in filters:
        assert np.linalg.norm(flt.x[:2] - truth[:2]) < 0.1
        assert np.linalg.norm(flt.x[2:] - truth[2:]) < 0.05


def test_numerical_jacobian():
    jac = aero.numerical_jacobian(
        lambda x: np.array([x[0] * x[1], np.sin(x[0])]), np.array([2.0, 3.0])
    )
    np.testing.assert_allclose(jac, [[3.0, 2.0], [np.cos(2.0), 0.0]], atol=1e-7)


def test_nees_single_and_batch():
    P = np.diag([4.0, 1.0])
    assert aero.nees([2.0, 1.0], P) == pytest.approx(2.0)
    out = aero.nees(np.array([[2.0, 0.0], [0.0, 3.0]]), np.stack([P, P]))
    np.testing.assert_allclose(out, [1.0, 9.0])


# -- navigation filter in the loop -------------------------------------------------------------
@pytest.mark.parametrize("kind", ["ekf", "ukf"])
def test_nav_filter_flies_a_route_with_consistent_covariance(kind):
    """GPS + IMU drive the estimate; the drone flies by the estimate. The position error
    stays inside its 3-sigma bound and the NEES is consistent with 3 degrees of freedom."""
    scene = Scene(dt=1e-3, seed=11)
    wind = scene.add_entity(aero.Wind((2.0, 1.0, 0.0), gust_std=1.0, tau=2.0))
    quad = scene.add_entity(aero.Quadrotor((0, 0, 2), name="drone", wind=wind))
    imu = quad.attach(IMU(rate=200, accel_noise=0.05))
    gps = quad.attach(GPS(rate=10, noise_std=0.5))
    nav = aero.NavFilter((0, 0, 2), pos_std=0.5, accel_std=0.1, gps_std=0.5, kind=kind)
    follower = aero.RouteFollower(square_route(speed=3.0, dwell=1.0), aero.PositionController(quad))
    errors, covs = [], []

    @scene.controller(rate=200)
    def navigate(t, s, ctx):
        if ctx.tick > 0:
            nav.predict(1 / 200, imu.accel, quad.rotation())
        if gps.updated(ctx):
            nav.update_gps(gps.position)
        errors.append(nav.position - quad.position())
        covs.append(nav.position_cov)
        return {"drone": follower(t, nav.position, nav.velocity)}

    sim = Sim(scene)
    for _ in range(25_000):
        sim.step()
    e, P = np.array(errors), np.array(covs)
    sigma = np.sqrt(np.diagonal(P, axis1=1, axis2=2))
    assert np.mean(np.abs(e) <= 3 * sigma) > 0.97
    assert 1.5 < np.mean(aero.nees(e, P)) < 4.5
    assert np.sqrt(np.mean(np.sum(e**2, axis=1))) < 0.6  # tighter than one GPS fix
    assert follower.done
