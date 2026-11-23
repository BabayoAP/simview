"""Drone Landing template (UC-4): land a quadrotor on the pad from a random start. It's also a
Gymnasium task, so it trains as is:

    env = sv.make_env("drone_landing")                  # or sv.make_vec_env(..., n_envs=8)
    model = PPO("MlpPolicy", env).learn(300_000)

The policy acts at 25 Hz with a desired acceleration (3 numbers in [-1, 1]); the quadrotor's
attitude controller turns that into thrust and torques at 100 Hz, reading the action as
`ctx.action`. Observation: position and velocity relative to the pad (scaled). An episode ends at
touchdown, when the drone leaves the area, or after 10 s. A landing counts as a success inside
0.5 m of the pad centre, slower than 1 m/s down and 0.7 m/s sideways.

Run it without a policy (the start-screen card, or `simview run scene.py --headless`) and a
simple PD lander flies it instead, a baseline to compare a trained policy with.
"""

import numpy as np

import simview as sv
from simview.core.scene import Context
from simview.core.scheduler import Sim

aero = sv.aero

scene = sv.Scene(dt=0.01, seed=0)
scene.add_ground()
scene.add_box("pad", (1.0, 1.0, 0.04), (0.0, 0.0, 0.02), static=True, rgba=(0.0, 0.62, 0.45, 1))

START = (2.5, -2.0, 6.0)  # where the drone starts outside training (training randomizes it)
ACCEL = np.array([3.0, 3.0, 4.0])  # m/s^2 for an action of 1 on each axis
LANDED_Z = 0.05  # m: touchdown height of the drone's centre
AREA, CEILING = 15.0, 15.0  # m: leaving this box ends the episode
PAD_RADIUS, MAX_VZ, MAX_VXY = 0.5, 1.0, 0.7  # a soft landing on the pad
OBS_MAX = 10.0  # observations are clipped to +-10 (scaled units)

drone = scene.add_entity(aero.Quadrotor(START, name="drone", mass=1.0))
scene.attach_shape(drone, "box", (0.5, 0.5, 0.12), rgba=(0.04, 0.44, 0.93, 1.0))
scene.trail("drone", seconds=10.0)
attitude = aero.AttitudeController(drone)


def landed(sim: Sim) -> bool:
    return drone.x[2] <= LANDED_Z


def soft_landing(sim: Sim) -> bool:
    x, y, _z, vx, vy, vz = drone.x[:6]
    return (
        landed(sim) and np.hypot(x, y) < PAD_RADIUS and -vz < MAX_VZ and np.hypot(vx, vy) < MAX_VXY
    )


def out_of_area(sim: Sim) -> bool:
    x, y, z = drone.x[:3]
    return max(abs(x), abs(y)) > AREA or z > CEILING


def pd_lander(pos: np.ndarray, vel: np.ndarray) -> np.ndarray:
    """The baseline: come over the pad, then sink at about 0.5 m/s."""
    a = np.array([-1.2 * pos[0] - 1.8 * vel[0], -1.2 * pos[1] - 1.8 * vel[1], 0.0])
    if np.hypot(pos[0], pos[1]) < 0.3:  # over the pad: descend, slower near the ground
        a[2] = 2.0 * (-min(1.5, 0.3 + 0.4 * pos[2]) - vel[2])
    else:  # not yet: hold at least 3 m
        a[2] = 1.5 * (max(pos[2], 3.0) - pos[2]) - 1.8 * vel[2]
    return np.clip(a / ACCEL, -1.0, 1.0)


@scene.controller()  # every tick: the attitude loop, flying the latest action
def fly(t: float, state: sv.Scene, ctx: Context) -> dict[str, np.ndarray]:
    pos, vel = drone.x[:3], drone.x[3:6]
    if ctx.action is None:  # no policy: the baseline flies, and rests on the pad once down
        if landed(ctx.sim):  # (there's no ground contact model: hold it where it touched down)
            drone.x[2], drone.x[3:6], drone.x[10:13] = LANDED_Z, 0.0, 0.0
            return {"drone": [drone.hover_thrust, 0.0, 0.0, 0.0]}
        action = pd_lander(pos, vel)
    else:
        action = ctx.action
    return {"drone": attitude(np.clip(action, -1.0, 1.0) * ACCEL)}


# -- the RL task (ML-01) -------------------------------------------------------------------------
def obs(sim: Sim) -> np.ndarray:
    return np.clip(np.concatenate([drone.x[:3] / 5.0, drone.x[3:6] / 3.0]), -OBS_MAX, OBS_MAX)


def potential(sim: Sim) -> float:
    """Shaping (potential-based, so it doesn't change the best policy): close and slow is good."""
    return -(float(np.linalg.norm(drone.x[:3])) + 0.5 * float(np.linalg.norm(drone.x[3:6])))


def reset(sim: Sim, rng: np.random.Generator) -> None:
    drone.x[:3] = (rng.uniform(-4.0, 4.0), rng.uniform(-4.0, 4.0), rng.uniform(4.0, 8.0))
    drone.x[3:6] = rng.uniform(-1.0, 1.0, 3)
    sim.task_phi = potential(sim)  # the episode's last potential, for the shaping term


def reward(sim: Sim, action: np.ndarray) -> float:
    phi = potential(sim)
    r = 10.0 * (phi - sim.task_phi) - 0.05 - 0.02 * float(np.sum(np.square(action)))
    sim.task_phi = phi
    if landed(sim):
        r += 100.0 if soft_landing(sim) else -30.0
    elif out_of_area(sim):
        r -= 50.0
    return r


def done(sim: Sim) -> bool:
    return landed(sim) or out_of_area(sim)


try:
    from gymnasium import spaces
except ImportError:  # without the rl extra the scene still runs (with the baseline lander)
    spaces = None

if spaces is not None:
    scene.rl_task(
        obs_fn=obs,
        reward_fn=reward,
        done_fn=done,
        action_space=spaces.Box(-1.0, 1.0, shape=(3,), dtype=np.float32),
        observation_space=spaces.Box(-OBS_MAX, OBS_MAX, shape=(6,), dtype=np.float32),
        rate=25.0,
        max_time=10.0,
        reset_fn=reset,
        success_fn=soft_landing,
    )

scene.log("dist_xy", lambda sim: float(np.hypot(*drone.x[:2])), "m")
scene.log("landed", lambda sim: float(landed(sim)))
scene.metric(
    "landed_on_pad", lambda run: float(run["landed"][-1] > 0 and run["dist_xy"][-1] < PAD_RADIUS)
)
