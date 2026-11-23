"""Drone Delivery template (UC-2, PRD 1.3): three quadrotors fly depot -> drop-off -> depot
through gusty wind. Each one estimates its position and velocity from a noisy IMU and GPS with
an EKF and flies its route by that estimate, not by the truth.

    simview run scene.py --headless --duration 60

Plots to try: d0_err_x with d0_bound_x (estimation error inside +-3 sigma), d0_dev (route
deviation), wind_speed, and d0_delivered (the drop-off time once it's made). The viewport
shows the routes, every drone's trail, and each estimate's 3-sigma covariance ellipsoid.
"""

import numpy as np

import simview as sv
from simview.core.scene import Context
from simview.sensors import GPS, IMU

aero = sv.aero

scene = sv.Scene(dt=1e-3, seed=0)
scene.add_ground()

# -- tunable parameters (live from the console; swept by Monte Carlo in M9) -------------------
scene.params.gps_noise = 0.8  # m, GPS position noise (1 sigma)
scene.params.imu_noise = 0.05  # m/s^2, accelerometer noise per sample
scene.params.gust = 1.5  # m/s, gust strength (1 sigma per axis)
scene.params.cruise_speed = 6.0  # m/s
scene.params.cruise_alt = 15.0  # m
p = scene.params

# -- the world ---------------------------------------------------------------------------------
DEPOT = np.array([0.0, 0.0])
DROPS = {"d0": (40.0, 25.0), "d1": (-30.0, 45.0), "d2": (20.0, -40.0)}
PADS = {"d0": (-3.0, 0.0), "d1": (0.0, 0.0), "d2": (3.0, 0.0)}
COLORS = {"d0": (0.04, 0.44, 0.93, 1.0), "d1": (0.9, 0.62, 0.0, 1.0), "d2": (0.0, 0.62, 0.45, 1.0)}
DROP_ALT, DWELL = 3.0, 3.0  # m and s: hover low over the drop-off for the hand-over
IMU_RATE, GPS_RATE = 200.0, 10.0

scene.add_box("depot", (10.0, 4.0, 0.1), (0.0, 0.0, 0.05), static=True, rgba=(0.3, 0.3, 0.32, 1))
for name, (x, y) in DROPS.items():
    scene.add_box(f"{name}_pad", (2.0, 2.0, 0.1), (x, y, 0.05), static=True, rgba=COLORS[name])
for i, (x, y, h) in enumerate([(15, 10, 8), (-12, 20, 10), (30, -15, 6), (-20, -18, 9)]):
    scene.add_box(f"building{i}", (8.0, 8.0, h), (x, y, h / 2), static=True)

wind = scene.add_entity(aero.Wind((3.0, 1.5, 0.0), gust_std=(p.gust, p.gust, 0.3 * p.gust)))


def route_for(name: str) -> aero.Route:
    """Lift off from the pad, cruise to the drop-off, descend and hover, then fly home."""
    pad, drop, alt = np.array(PADS[name]), np.array(DROPS[name]), p.cruise_alt
    points = [
        (*pad, 1.0),
        (*pad, alt),
        (*drop, alt),
        (*drop, DROP_ALT),
        (*drop, alt),
        (*pad, alt),
        (*pad, 1.0),
    ]
    dwell = [0.0, 0.0, 0.0, DWELL, 0.0, 0.0, 0.0]
    return aero.Route(points, speed=p.cruise_speed, dwell=dwell, arrive_radius=0.6)


DROP_INDEX = 3  # the route waypoint where the parcel is handed over


class Drone:
    """One delivery drone: the quadrotor, its sensors, its EKF, and its route follower."""

    def __init__(self, name: str) -> None:
        self.name = name
        start = (*PADS[name], 1.0)
        self.quad = scene.add_entity(aero.Quadrotor(start, name=name, mass=1.5, wind=wind))
        scene.attach_shape(self.quad, "box", (0.6, 0.6, 0.15), rgba=COLORS[name])
        scene.trail(name, seconds=30.0)
        self.imu = self.quad.attach(IMU(IMU_RATE, accel_noise=p.imu_noise))
        self.gps = self.quad.attach(GPS(GPS_RATE, noise_std=p.gps_noise))
        self.route = route_for(name)
        self.reset()

    def reset(self) -> None:
        """A fresh filter and follower (called at t = 0, so every run starts the same)."""
        self.nav = aero.NavFilter(
            (*PADS[self.name], 1.0),
            pos_std=p.gps_noise,
            vel_std=0.1,
            accel_std=2 * p.imu_noise,
            gps_std=p.gps_noise,
        )
        self.follower = aero.RouteFollower(self.route, aero.PositionController(self.quad))
        # what the plots show, updated at the controller rate (the estimate only changes then)
        self.err, self.bound, self.dev = np.zeros(3), np.full(3, 3 * p.gps_noise), 0.0

    def step(self, t: float, ctx: Context) -> np.ndarray:
        if ctx.tick > 0:
            self.nav.predict(1.0 / IMU_RATE, self.imu.accel, self.quad.rotation())
        if self.gps.updated(ctx):
            self.nav.update_gps(self.gps.position)
        truth = self.quad.position()
        self.err = self.nav.position - truth
        self.bound = 3.0 * np.sqrt(np.diag(self.nav.position_cov))
        self.dev = float(self.route.distance(truth)[0])
        return self.follower(t, self.nav.position, self.nav.velocity)


drones = [Drone(name) for name in DROPS]


# -- flight software (edit me) -----------------------------------------------------------------
@scene.controller(rate=IMU_RATE)
def flight(t: float, state: sv.Scene, ctx: Context) -> dict[str, np.ndarray]:
    if ctx.tick == 0:
        for d in drones:
            d.reset()
    return {d.name: d.step(t, ctx) for d in drones}


@scene.controller(rate=20)
def show(t: float, state: sv.Scene, ctx: Context) -> None:
    """Routes once (persistent), then each estimate's 3-sigma ellipsoid and the wind."""
    if ctx.tick == 0:
        for d in drones:
            color = "#{:02x}{:02x}{:02x}".format(*(int(255 * c) for c in COLORS[d.name][:3]))
            pts = d.route.waypoints
            for a, b in zip(pts[:-1], pts[1:], strict=True):
                ctx.draw.line(a, b, color=color, width=1.5, persist=True)
    for d in drones:
        ctx.draw.ellipsoid(d.nav.position, d.nav.position_cov, sigma=3.0, color="state.warning")
    w = wind.velocity()
    ctx.draw.arrow((0.0, 0.0, 20.0), (w[0], w[1], 20.0 + w[2]), color="accent")


# -- logged channels -----------------------------------------------------------------------------
for _d in drones:
    n = _d.name
    for axis, i in (("x", 0), ("y", 1), ("z", 2)):
        scene.log(f"{n}_err_{axis}", lambda sim, d=_d, i=i: float(d.err[i]), "m")
        scene.log(f"{n}_bound_{axis}", lambda sim, d=_d, i=i: float(d.bound[i]), "m")
    scene.log(f"{n}_err", lambda sim, d=_d: float(np.linalg.norm(d.err)), "m")
    scene.log(f"{n}_dev", lambda sim, d=_d: d.dev, "m")
    scene.log(
        f"{n}_delivered",
        lambda sim, d=_d: d.follower.arrival(DROP_INDEX) or float("nan"),
        "s",
    )
scene.log("wind_speed", lambda sim: float(np.linalg.norm(wind.velocity())), "m/s")


# -- per-run metrics (Monte Carlo results, SE-08) -------------------------------------------------
def _delivery_time(run: sv.Run) -> float:
    """When the last drone made its drop-off (NaN if one never did)."""
    return float(np.max([run[f"{d.name}_delivered"][-1] for d in drones]))  # NaN wins


scene.metric("delivery_time", _delivery_time)
scene.metric(
    "delivered", lambda run: sum(np.isfinite(run[f"{d.name}_delivered"][-1]) for d in drones)
)
scene.metric(
    "rms_error",
    lambda run: sv.analysis.rmse(np.concatenate([run[f"{d.name}_err"] for d in drones])),
)
scene.metric("max_deviation", lambda run: max(float(run[f"{d.name}_dev"].max()) for d in drones))
