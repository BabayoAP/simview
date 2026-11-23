"""SN-01..SN-03 sensors and VP-08 / VP-09 draw data (headless; the GL look is in
tests/ui/test_viewport_gl.py)."""

import numpy as np
import pytest

import simview as sv
from simview import Entity, Scene
from simview.core.draw import ellipsoid_axes
from simview.core.scheduler import Sim
from simview.sensors import GPS, IMU, Camera, Lidar, Seeker, rbe, rbe_to_position


class Mover(Entity):
    """Constant acceleration `a` (world) and constant yaw rate `w`."""

    state_names = ("x", "y", "z", "vx", "vy", "vz", "yaw")

    def __init__(self, x0=None, *, a=(0.0, 0.0, 0.0), w=0.0, name=None):
        super().__init__(np.zeros(7) if x0 is None else x0, name=name, integrator="euler")
        self.a, self.w = np.asarray(a, dtype=float), float(w)

    def derivative(self, t, x, u):
        return np.concatenate([x[3:6], self.a, [self.w]])


def run_ticks(scene, n):
    sim = Sim(scene)
    for _ in range(n):
        sim.step()
    return sim


# ---------------------------------------------------------------- SN-01: IMU
def test_imu_at_rest_reads_gravity_reaction():
    scene = Scene(dt=1e-3)
    imu = scene.add_entity(Mover()).attach(IMU(rate=100))
    run_ticks(scene, 50)
    np.testing.assert_allclose(imu.accel, [0, 0, 9.81], atol=1e-9)
    np.testing.assert_allclose(imu.gyro, 0, atol=1e-12)
    assert imu.az == pytest.approx(9.81)


def test_imu_reads_acceleration_and_yaw_rate_in_its_frame():
    scene = Scene(dt=1e-3)
    m = scene.add_entity(Mover(a=(2.0, 0.0, 0.0), w=0.5))
    imu = m.attach(IMU(rate=100))
    run_ticks(scene, 200)
    yaw = m["yaw"]
    world_f = np.array([2.0, 0.0, 9.81])
    rot = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    np.testing.assert_allclose(imu.accel, rot.T @ world_f, atol=1e-6)
    np.testing.assert_allclose(imu.gyro, [0, 0, 0.5], atol=1e-9)


def test_imu_bias_and_noise_statistics():
    scene = Scene(dt=1e-3, seed=3)
    imu = scene.add_entity(Mover()).attach(
        IMU(
            rate=1000,
            accel_noise=0.2,
            gyro_noise=0.01,
            accel_bias=(0.1, 0, 0),
            gyro_bias=(0, 0, 0.02),
        )
    )
    sim = Sim(scene)
    samples = []
    for _ in range(4000):
        sim.step()
        samples.append(imu.value.copy())
    s = np.array(samples)
    np.testing.assert_allclose(s.mean(axis=0), [0.1, 0, 9.81, 0, 0, 0.02], atol=0.015)
    np.testing.assert_allclose(s.std(axis=0), [0.2] * 3 + [0.01] * 3, rtol=0.05)


def test_sensor_holds_between_samples_and_flags_updates():
    scene = Scene(dt=1e-3)
    m = scene.add_entity(Mover(np.array([0, 0, 0, 1.0, 0, 0, 0])))
    gps = m.attach(GPS(rate=10))  # every 100 ticks
    sim = Sim(scene)
    for _ in range(150):
        sim.step()
    assert gps.tick == 100 and not gps.updated(sim)
    assert gps.x == pytest.approx(0.1)  # position at t = 0.1 s, held since
    for _ in range(50):
        sim.step()
    assert gps.updated(sim) and gps.x == pytest.approx(0.2)


def test_noise_is_seeded_and_per_sensor():
    """Same seed, same noise; adding another sensor doesn't change this one's (D-091)."""

    def readings(extra):
        scene = Scene(dt=1e-3, seed=7)
        m = scene.add_entity(Mover())
        if extra:
            m.attach(IMU(rate=1000, accel_noise=1.0, name="other"))
        gps = m.attach(GPS(rate=1000, noise_std=1.0))
        sim = Sim(scene)
        out = []
        for _ in range(20):
            sim.step()
            out.append(gps.position)
        return np.array(out)

    a = readings(False)
    np.testing.assert_array_equal(a, readings(False))
    np.testing.assert_array_equal(a, readings(True))
    assert a.std() > 0.3


# ---------------------------------------------------------------- SN-01: GPS, seeker
def test_gps_follows_the_mount_offset():
    scene = Scene(dt=1e-3)
    x0 = np.array([1.0, 2.0, 3.0, 0, 0, 0, np.pi / 2])
    gps = scene.add_entity(Mover(x0)).attach(GPS(pos=(1.0, 0.0, 0.5)))
    run_ticks(scene, 1)
    np.testing.assert_allclose(gps.position, [1.0, 3.0, 3.5], atol=1e-12)  # x mount -> world y


def test_gps_noise_std():
    scene = Scene(dt=1e-3, seed=1)
    gps = scene.add_entity(Mover()).attach(GPS(rate=1000, noise_std=(0.5, 0.5, 2.0)))
    sim = Sim(scene)
    s = []
    for _ in range(4000):
        sim.step()
        s.append(gps.position)
    np.testing.assert_allclose(np.std(s, axis=0), [0.5, 0.5, 2.0], rtol=0.05)


def test_rbe_round_trip():
    rng = np.random.default_rng(0)
    for d in rng.normal(size=(50, 3)) * 10:
        np.testing.assert_allclose(rbe_to_position(rbe(d)), d, atol=1e-9)


def test_seeker_measures_range_bearing_elevation_to_its_target():
    scene = Scene(dt=1e-3)
    chaser = scene.add_entity(Mover(name="chaser"))
    scene.add_entity(Mover(np.array([3.0, 4.0, 12.0, 0, 0, 0, 0]), name="target"))
    seeker = chaser.attach(Seeker(target="target"))
    run_ticks(scene, 1)
    np.testing.assert_allclose(
        [seeker.range, seeker.bearing, seeker.elevation],
        [13.0, np.arctan2(4, 3), np.arctan2(12, 5)],
        atol=1e-12,
    )


def test_seeker_without_target_fails_at_start():
    scene = Scene()
    scene.add_entity(Mover()).attach(Seeker())
    with pytest.raises(ValueError, match="no target"):
        Sim(scene)


def test_sensor_channels_are_logged():
    scene = Scene(dt=1e-3)
    scene.add_entity(Mover(name="car")).attach(GPS(rate=100))
    run = sv.run(scene, duration=0.05)
    assert run["car.gps.x"].shape == run["car.x"].shape


def test_sensor_names_and_rates_are_checked():
    m = Mover()
    m.attach(GPS())
    with pytest.raises(ValueError, match="already has"):
        m.attach(GPS())
    with pytest.raises(ValueError, match="state named"):
        m.attach(GPS(name="x"))
    with pytest.raises(ValueError, match="positive"):
        GPS(rate=0)


# ---------------------------------------------------------------- SN-03: lidar
def lidar_scene(**kw):
    scene = Scene(dt=1e-3)
    scene.add_ground()
    scene.add_box("wall", (0.2, 4.0, 2.0), (5.1, 0.0, 1.0), static=True)  # face at x = 5
    car = scene.add_entity(Mover(np.array([0, 0, 1.0, 0, 0, 0, 0]), name="car"))
    scene.attach_shape(car, "box", (1.0, 1.0, 0.5))  # its own body must not block the beams
    lidar = car.attach(Lidar(**kw))
    return scene, lidar


def test_lidar_ranges_to_wall_and_ground():
    scene, lidar = lidar_scene(beams=3, vertical_fov=(-np.pi / 2, 0.0))
    run_ticks(scene, 1)
    front = np.argmin(np.abs(lidar.azimuths))
    assert lidar.ranges[2, front] == pytest.approx(5.0, abs=1e-6)  # level beam, wall
    assert lidar.ranges[0, front] == pytest.approx(1.0, abs=1e-6)  # straight down, ground
    assert np.isinf(lidar.ranges[2, np.argmin(np.abs(lidar.azimuths - np.pi / 2))])  # sideways
    assert len(lidar.points) == np.isfinite(lidar.ranges).sum()
    np.testing.assert_allclose(lidar.points[:, 2].min(), 0.0, atol=1e-6)  # ground hits at z = 0


def test_lidar_respects_max_range_and_noise():
    scene, lidar = lidar_scene(beams=1, vertical_fov=(0.0, 0.0), max_range=4.0)
    run_ticks(scene, 1)
    assert np.isinf(lidar.ranges).all()
    scene, lidar = lidar_scene(beams=1, vertical_fov=(0.0, 0.0), noise_std=0.05)
    sim = Sim(scene)
    front = np.argmin(np.abs(lidar.azimuths))
    r = []
    for _ in range(1000):
        sim.step()
        if lidar.updated(sim):
            r.append(lidar.ranges[0, front])
    assert np.mean(r) == pytest.approx(5.0, abs=0.03)
    assert np.std(r) == pytest.approx(0.05, rel=0.3)


def test_lidar_scan_shape_and_argument_checks():
    lidar = Lidar(beams=16, horizontal_resolution=np.radians(2.0))
    assert lidar.ranges.shape == (16, 180) and lidar.directions.shape == (16 * 180, 3)
    np.testing.assert_allclose(np.linalg.norm(lidar.directions, axis=1), 1.0)
    with pytest.raises(ValueError):
        Lidar(beams=0)
    with pytest.raises(ValueError):
        Lidar(max_range=-1)


# ---------------------------------------------------------------- SN-02: camera
def test_camera_sees_a_colored_box_with_correct_depth():
    scene = Scene(dt=1e-3)
    scene.add_box("red", (0.2, 2.0, 2.0), (5.1, 0.0, 1.0), static=True, rgba=(1, 0, 0, 1))
    car = scene.add_entity(Mover(np.array([0, 0, 1.0, 0, 0, 0, 0]), name="car"))
    cam = car.attach(Camera(width=64, height=48, fov=np.radians(40)))
    run_ticks(scene, 1)
    assert cam.image.shape == (48, 64, 3) and cam.image.dtype == np.uint8
    center = cam.image[24, 32].astype(int)
    assert center[0] > 200 and center[1] < 30 and center[2] < 30  # facing red, fully lit
    assert cam.depth[24, 32] == pytest.approx(5.0 / np.cos(np.arctan(0.5 / cam.focal)), rel=1e-3)
    # the box spans +-1 m at 5 m (about +-11.3 deg); the edge of a 40 deg view is sky
    np.testing.assert_array_equal(
        cam.image[24, 0], (np.array([0.62, 0.74, 0.86]) * 255).astype(np.uint8)
    )
    assert np.isinf(cam.depth[24, 0])


def test_camera_intrinsics():
    cam = Camera(width=160, height=120, fov=np.radians(90))
    k = cam.intrinsics
    assert k[0, 0] == pytest.approx(80.0) and k[1, 1] == pytest.approx(80.0)
    assert (k[0, 2], k[1, 2]) == (80.0, 60.0)
    with pytest.raises(ValueError):
        Camera(fov=np.pi)


def test_camera_is_deterministic():
    def image():
        scene = Scene(dt=1e-3)
        scene.add_ground()
        scene.add_box("b", (1, 1, 1), (4, 0.5, 0.5), static=True)
        car = scene.add_entity(Mover(np.array([0, 0, 1.0, 0, 0, 0, 0.2]), name="car"))
        cam = car.attach(Camera(width=32, height=24, rpy=(0, 0.2, 0)))
        run_ticks(scene, 1)
        return cam.image

    np.testing.assert_array_equal(image(), image())


# ---------------------------------------------------------------- VP-08 / VP-09 draw data
def test_lidar_points_draw_as_a_cloud():
    scene, lidar = lidar_scene(beams=8)

    @scene.controller(rate=10)
    def show(t, s, ctx):
        ctx.draw.points(lidar.points, color="accent")

    sim = run_ticks(scene, 1)  # sensors sample at the start, so tick 0 already has a scan
    (cloud,) = [d for d in sim.draw.snapshot() if d.kind == "cloud"]
    assert cloud.data.dtype == np.float32 and cloud.data.shape == (len(lidar.points), 3)
    assert len(cloud.data) > 0 and cloud.color == "accent"


def test_point_cloud_shape_is_checked():
    sim = Sim(Scene())
    with pytest.raises(ValueError, match=r"\(N, 3\)"):
        sim.draw.points(np.zeros((5, 2)))


def test_ellipsoid_axes_match_the_covariance():
    rng = np.random.default_rng(2)
    a = rng.normal(size=(3, 3))
    cov = a @ a.T
    axes = ellipsoid_axes(cov, sigma=2.0)
    np.testing.assert_allclose(axes @ axes.T, 4.0 * cov, atol=1e-10)  # sum of v v^T = s^2 P
    np.testing.assert_allclose(ellipsoid_axes(np.diag([4.0, 1.0, -1e-12]), 1.0)[:, 0], 0, atol=1e-6)
    with pytest.raises(ValueError):
        ellipsoid_axes(np.eye(2), 1.0)
    with pytest.raises(ValueError):
        ellipsoid_axes(np.eye(3), 0.0)


def test_ellipsoid_draw_carries_center_and_axes():
    sim = Sim(Scene())
    sim.draw.ellipsoid((1, 2, 3), np.diag([1.0, 4.0, 9.0]), sigma=3.0)
    (e,) = sim.draw.snapshot()
    assert e.kind == "ellipsoid" and e.points[0] == (1.0, 2.0, 3.0)
    np.testing.assert_allclose(sorted(np.linalg.norm(e.data, axis=0)), [3.0, 6.0, 9.0])
