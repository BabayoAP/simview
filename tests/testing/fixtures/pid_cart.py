"""A cart on a track pushed to x = 1 m by a PID controller: the scene the scenario-test tests
(ST-01..03) run. Gains, start position and a sensor noise level are scene parameters."""

import numpy as np

import simview as sv
from simview.analysis import step_info
from simview.core.scene import Context

RATE = 100.0  # Hz
TARGET = 1.0  # m


class Cart(sv.Entity):
    state_names = ("x", "v")

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        force = u[0] if len(u) else 0.0
        return np.array([x[1], force - 0.5 * x[1]])  # 1 kg, viscous friction


scene = sv.Scene(dt=1e-3, seed=7)
scene.params.kp = 14.0
scene.params.ki = 0.0
scene.params.kd = 6.0
scene.params.x0 = 0.0  # initial condition
scene.params.noise = 0.0  # position sensor noise [m]
cart = scene.add_entity(Cart([scene.params.x0, 0.0], name="cart"))
pid = {"integral": 0.0, "prev": None}
ts = 1.0 / RATE


@scene.controller(rate=RATE)
def control(t: float, state: sv.Scene, ctx: Context) -> dict[str, list[float]]:
    p = ctx.params
    measured = state["cart"]["x"] + (ctx.rng.normal(0.0, p.noise) if p.noise > 0 else 0.0)
    e = TARGET - measured
    pid["integral"] += e * ts
    deriv = (e - pid["prev"]) / ts if pid["prev"] is not None else 0.0
    pid["prev"] = e
    return {"cart": [p.kp * e + p.ki * pid["integral"] + p.kd * deriv]}


scene.log("err", lambda sim: TARGET - sim.scene["cart"]["x"])


def _settling(run: sv.Run) -> float:
    return step_info(run["cart.x"], run["t"], final=TARGET)["settling_time"]


scene.metric("settling_time", _settling)
scene.metric("overshoot", lambda run: step_info(run["cart.x"], run["t"], final=TARGET)["overshoot"])
