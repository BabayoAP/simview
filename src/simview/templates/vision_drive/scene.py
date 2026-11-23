"""Vision Drive template (UC-6, VW-11): the UC-1 car with 8 surround cameras and no lidar. A
perception pipeline fuses the cameras' depth into a 3D occupancy grid; the planner reads only
that grid (`ctx.streams["ego.occupancy"]`), never the scene's true geometry, and follows its
lane, changing lanes around what blocks it or stopping when both lanes are blocked.

    simview run scene.py --headless --duration 14

Plots to try: ego.v with target_speed, cte, ego.perception.min_obstacle_dist, and
ego.perception.iou (perceived voxels against ground truth within 20 m). `layout` places the
obstacles (0 = the default layout; other values jitter them, and every 4th one also blocks
the left lane, so the car has to stop).
"""

import numpy as np

import simview as sv
from simview.core.scene import Context

vh = sv.vehicles

scene = sv.Scene(dt=0.01, seed=0)
scene.params.layout = 0  # obstacle placement (0 = default; others jitter, every 4th blocks both)
scene.params.cruise_speed = 10.0  # m/s
scene.add_ground()

# -- the road and the obstacles (scene) ------------------------------------------------------
road = vh.Road(
    vh.join(
        vh.straight((0.0, 0.0), 0.0, 110.0, step=2.0),
        vh.arc((110.0, 60.0), 60.0, -np.pi / 2, np.pi / 2, step=2.0),
        vh.straight((170.0, 60.0), np.pi / 2, 60.0, step=2.0),
    ),
    lanes=2,
    lane_width=3.5,
)
LANE, LEFT = road.lane(0), road.lane(1)
CAR = (4.5, 1.8, 1.5)  # box size (m); the rear axle sits 1.35 m behind the box's center
BODY = {"pos": (1.35, 0.0, 0.75)}
PEDESTRIAN = (0.6, 0.6, 1.7)
GRAY, RED = (0.55, 0.55, 0.58, 1.0), (0.85, 0.33, 0.25, 1.0)


def layout(variant: int) -> list[tuple[str, tuple[float, float, float], float, float]]:
    """(name, size, arc length s m, offset from the road centre m) of each obstacle."""
    rng = np.random.default_rng(variant)
    jit = (lambda a: float(rng.uniform(-a, a))) if variant else (lambda a: 0.0)
    lane0 = -road.lane_width / 2
    parked = -road.width / 2 - 0.25 - CAR[1] / 2  # on the right shoulder
    out = [
        (f"parked{i}", CAR, s + jit(3.0), parked + jit(0.15))
        for i, s in enumerate((14.0, 24.0, 52.0, 84.0))
    ]
    out.append(("pedestrian", PEDESTRIAN, 36.0 + jit(4.0), lane0 + jit(0.4)))
    if variant % 4 == 3:  # road works across the left lane: the car must stop
        out.append(("barrier", (1.0, 3.0, 1.2), 72.0 + jit(3.0), road.lane_width / 2))
    return out


OBSTACLES = layout(int(scene.params.layout))
for name, size, s, d in OBSTACLES:
    p, yaw = road.centerline.point_at(s), road.centerline.heading_at(s)
    n = np.array([-np.sin(yaw), np.cos(yaw)])
    x, y = p + d * n
    quat = (np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2))
    rgba = RED if name == "pedestrian" else GRAY
    scene.add_box(name, size, (x, y, size[2] / 2), quat=quat, static=True, rgba=rgba)

STALLED_S = 70.0 + (float(np.random.default_rng(1000 + int(scene.params.layout)).uniform(-3, 3)))
stalled = scene.add_entity(vh.ScriptedNPC(LANE, 0.0, start=STALLED_S, name="stalled"))
scene.attach_shape(stalled, "box", CAR, rgba=GRAY, **BODY)

# -- the camera-only ego and its perception pipeline -----------------------------------------
ego = scene.add_entity(vh.KinematicBicycle([0.0, -1.75, 0.0, 0.0], name="ego", max_speed=20))
scene.attach_shape(ego, "box", CAR, rgba=(0.04, 0.44, 0.93, 1.0), **BODY)
rig = ego.attach(sv.perception.CameraRig.surround(n=8, width=160, height=120, rate=10))
perceive = scene.add_pipeline(
    sv.perception.Pipeline(
        [
            sv.perception.BackProject(max_range=30.0, stride=3),
            sv.perception.OccupancyGrid(res=0.2, extent=60.0, height=(0.0, 3.0), rolling=True),
            sv.perception.BevMap(z_band=(0.2, 2.5)),
        ],
        inputs=rig,
        name="ego",
        iou_radius=20.0,  # logs ego.perception.iou (scored against ground truth, never planned on)
    )
)
scene.trail("ego", seconds=8.0)

# -- the planner (edit me): reads only the occupancy grid ------------------------------------
CRUISE = float(scene.params.cruise_speed)
HALF = CAR[1] / 2 + 0.5  # m, half-width of the corridor kept clear of obstacles
FRONT, REAR = 3.6, 0.9  # m, bumpers ahead of / behind the rear axle
STANDOFF = 4.0  # m, gap kept to an obstacle when stopped
HEADWAY = 1.2  # s
BRAKE = 3.0  # m/s^2, planned deceleration
LOOK = 28.0  # m ahead of the front bumper where an obstacle triggers a lane change
pursuit = [
    vh.PurePursuit(lane, wheelbase=ego.wheelbase, min_lookahead=5.0, gain=0.5)
    for lane in (LANE, LEFT)
]
plan = {"lane": 0, "target": 0.0, "gap": np.inf}


LANE_S = np.arange(0.0, LANE.length, 0.5)  # lane 0 sampled every 0.5 m (map data, not obstacles)
LANE_XY = np.array([LANE.point_at(v) for v in LANE_S])
LANE_HEAD = np.array([LANE.heading_at(v) for v in LANE_S])


def lane_frame(points: np.ndarray, s0: float) -> tuple[np.ndarray, np.ndarray]:
    """Arc length along lane 0 and lateral offset from it (+ left) of points (N, 2), using
    the lane samples from s0 - 10 to s0 + 45 m."""
    w = slice(max(int((s0 - 10.0) / 0.5), 0), int((s0 + 45.0) / 0.5) + 1)
    ss, samples, heads = LANE_S[w], LANE_XY[w], LANE_HEAD[w]
    d2 = ((points[:, None, :] - samples[None, :, :]) ** 2).sum(axis=2)
    i = np.argmin(d2, axis=1)
    rel = points - samples[i]
    c, s = np.cos(heads[i]), np.sin(heads[i])
    return ss[i] + rel[:, 0] * c + rel[:, 1] * s, c * rel[:, 1] - s * rel[:, 0]


def obstacles(grid: sv.perception.OccupancyGrid, s_ego: float) -> tuple[np.ndarray, np.ndarray]:
    """Perceived obstacle voxels near the lane, as (s, d) in lane 0's frame."""
    c = grid.occupied_centers()
    x, y = ego.x[0], ego.x[1]
    keep = (c[:, 2] > 0.3) & (c[:, 2] < 2.2) & (np.hypot(c[:, 0] - x, c[:, 1] - y) < 45.0)
    if not keep.any():
        return np.zeros(0), np.zeros(0)
    return lane_frame(c[keep, :2], s_ego)


def gap(s: np.ndarray, d: np.ndarray, center: float, s_ego: float) -> float:
    """Free distance from the front bumper to the first obstacle in the corridor around
    `center` (obstacles beside the car count too, giving a gap <= 0)."""
    hit = (np.abs(d - center) < HALF) & (s > s_ego - REAR)
    return float(np.min(s[hit]) - s_ego - FRONT) if hit.any() else np.inf


def clear(s: np.ndarray, d: np.ndarray, center: float, a: float, b: float) -> bool:
    return not bool(np.any((np.abs(d - center) < HALF) & (s > a) & (s < b)))


@scene.controller(rate=10)
def planner(t: float, state: sv.Scene, ctx: Context) -> dict[str, list[float]]:
    if t == 0:
        road.draw(ctx.draw)
    x, y, yaw, v = ego.x
    near = LANE.nearest((x, y))
    s_ego, d_ego = near.s, near.cross_track
    grid = ctx.streams["ego.occupancy"].latest()
    s, d = obstacles(grid, s_ego) if grid is not None else (np.zeros(0), np.zeros(0))
    centers = (0.0, road.lane_width)
    front = s_ego + FRONT
    gaps = [gap(s, d, c, s_ego) for c in centers]
    if plan["lane"] == 0:
        if (
            gaps[0] < LOOK
            and gaps[1] > gaps[0] + 10.0
            and clear(s, d, centers[1], s_ego - 6, front)
        ):
            plan["lane"] = 1
    elif clear(s, d, centers[0], s_ego - 7.0, front + 20.0):
        plan["lane"] = 0
    lane = plan["lane"]
    here = gap(s, d, d_ego, s_ego)  # straight ahead of where the car is now
    g = min(gaps[lane], here)
    room = max(g - STANDOFF, 0.0)
    plan["gap"] = g
    plan["target"] = float(min(CRUISE, room / HEADWAY, np.sqrt(2.0 * BRAKE * room)))

    ahead = vh.Path([(LANE, LEFT)[lane].point_at(s_ego + k) for k in np.arange(0.0, 30.0, 2.0)])
    ahead.draw(ctx.draw, color="state.success", width=3.0, z=0.05)
    steer = pursuit[lane](x, y, yaw, v)
    ctx.draw.point((*pursuit[lane].goal, 0.1), color="state.warning")
    return {"ego": [vh.speed_control(v, plan["target"], kp=2.0), steer]}


@scene.controller()
def speed_loop(t: float, state: sv.Scene, ctx: Context) -> dict[str, list[float]]:
    """Keep closing the speed loop at 100 Hz between planner updates."""
    return {"ego": [vh.speed_control(ego.x[3], plan["target"], kp=2.0), ego.steer]}


scene.log("steer", lambda sim: ego.steer, "rad")
scene.log("target_speed", lambda sim: plan["target"], "m/s")
scene.log("cte", lambda sim: vh.cross_track_error(LANE, ego.x[:2]), "m")
scene.log("lane", lambda sim: float(plan["lane"]))
scene.log("gap", lambda sim: min(plan["gap"], 60.0), "m")
