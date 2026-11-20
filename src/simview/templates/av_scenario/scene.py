"""Autonomous Vehicle template (UC-1): a bicycle-model car with lidar and a camera follows its
lane with pure pursuit, keeping its distance to traffic it sees in the lidar scan.

    simview run scene.py --headless --duration 20

Plots to try: ego.v with target_speed, steer, cte, and gap. The viewport shows the
road, the lidar point cloud, the planned path, and every vehicle's trail.
"""

import numpy as np

import simview as sv
from simview.core.scene import Context
from simview.sensors import Camera, Lidar

vh = sv.vehicles

# -- the road and the traffic (scene) --------------------------------------------------------
road = vh.Road(
    vh.join(
        vh.straight((0.0, 0.0), 0.0, 80.0, step=2.0),
        vh.arc((80.0, 60.0), 60.0, -np.pi / 2, np.pi / 2, step=2.0),
        vh.straight((140.0, 60.0), np.pi / 2, 120.0, step=2.0),
    ),
    lanes=2,
    lane_width=3.5,
)
CAR = (4.5, 1.8, 1.5)  # box size (m); the rear axle sits 1.35 m behind the box's center
BODY = {"pos": (1.35, 0.0, 0.75)}

scene = sv.Scene(dt=0.01, seed=0)
scene.add_ground()

ego = scene.add_entity(vh.KinematicBicycle([0.0, -1.75, 0.0, 0.0], name="ego", max_speed=20))
scene.attach_shape(ego, "box", CAR, rgba=(0.04, 0.44, 0.93, 1.0), **BODY)
ego.attach(Lidar(10.0, beams=32, max_range=60.0, noise_std=0.02, pos=(1.35, 0.0, 1.9)))
ego.attach(Camera(10.0, width=160, height=120, pos=(2.0, 0.0, 1.4)))

traffic = [  # (lane, start arc length m, speed m/s or a (t, v) schedule)
    (0, 35.0, [(0.0, 7.0), (8.0, 7.0), (11.0, 2.0), (14.0, 2.0), (17.0, 8.0)]),  # brakes
    (1, 10.0, 12.0),  # overtakes in the left lane
    (1, 70.0, 9.0),
]
for i, (lane, start, speed) in enumerate(traffic):
    npc = scene.add_entity(vh.ScriptedNPC(road.lane(lane), speed, start=start, name=f"npc{i}"))
    scene.attach_shape(npc, "box", CAR, rgba=(0.55, 0.55, 0.58, 1.0), **BODY)
    scene.trail(npc.name, seconds=4.0)
scene.trail("ego", seconds=8.0)

# -- the planner (edit me) -------------------------------------------------------------------
LANE = road.lane(0)
CRUISE = 12.0  # m/s
HEADWAY = 1.5  # s of gap kept to the vehicle ahead
STANDOFF = 6.0  # m, gap kept when stopped
pursuit = vh.PurePursuit(LANE, wheelbase=ego.wheelbase, min_lookahead=4.0, gain=0.4)
plan = {"target": CRUISE, "gap": np.inf}


def gap_ahead(lidar: Lidar, s_ego: float) -> float:
    """Distance along the lane (m) from the lidar to the nearest return inside the lane,
    ignoring ground hits (z < 0.3 m)."""
    s_lidar = s_ego + 1.35
    gap = np.inf
    for p in lidar.points[lidar.points[:, 2] > 0.3]:
        near = LANE.nearest(p)
        if abs(near.cross_track) < 1.4 and near.s > s_lidar:
            gap = min(gap, near.s - s_lidar)
    return gap


@scene.controller(rate=10)
def planner(t: float, state: sv.Scene, ctx: Context) -> dict[str, list[float]]:
    if t == 0:
        road.draw(ctx.draw)
    x, y, yaw, v = ego.x
    lidar = ego.sensors.lidar
    s = LANE.nearest((x, y)).s
    gap = gap_ahead(lidar, s)
    plan["gap"] = gap
    plan["target"] = float(np.clip((gap - STANDOFF) / HEADWAY, 0.0, CRUISE))

    ahead = vh.Path([LANE.point_at(s + d) for d in np.arange(0.0, 30.0, 2.0)])
    ahead.draw(ctx.draw, color="state.success", width=3.0, z=0.05)
    ctx.draw.points(lidar.points, color="accent", size=2.0)
    ctx.draw.point((*pursuit.goal, 0.1), color="state.warning")
    return {"ego": [vh.speed_control(v, plan["target"], kp=1.5), pursuit(x, y, yaw, v)]}


@scene.controller()
def speed_loop(t: float, state: sv.Scene, ctx: Context) -> dict[str, list[float]]:
    """Keep closing the speed loop at 100 Hz between planner updates."""
    x, y, yaw, v = ego.x
    steer = ego.steer
    return {"ego": [vh.speed_control(v, plan["target"], kp=1.5), steer]}


scene.log("steer", lambda sim: ego.steer, "rad")
scene.log("target_speed", lambda sim: plan["target"], "m/s")
scene.log("cte", lambda sim: vh.cross_track_error(LANE, ego.x[:2]), "m")
scene.log("gap", lambda sim: min(plan["gap"], 60.0), "m")
