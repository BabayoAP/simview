"""Altitude hold written as a script controller. `blocks.py` is the same loop as a block
diagram (`altitude.svd`); M7's check is that both give the same flight within 1e-9.

    simview run examples/drone_altitude/script.py --headless --duration 5
"""

import sys
from pathlib import Path

import simview as sv
from simview.core.scene import Context

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import GAINS, MASS, RATE, TARGET, G, make_scene  # noqa: E402

scene = make_scene()
pid = {"integral": 0.0, "prev": None}
ts = 1.0 / RATE


@scene.controller(rate=RATE)
def altitude(t: float, state: sv.Scene, ctx: Context) -> dict[str, list[float]]:
    e = TARGET - state["drone"]["z"]
    integral = pid["integral"] + e * ts
    deriv = (e - pid["prev"]) / ts if pid["prev"] is not None else 0.0
    raw = GAINS["kp"] * e + GAINS["ki"] * integral + GAINS["kd"] * deriv
    out = min(max(raw, GAINS["lower"]), GAINS["upper"])
    if out != raw and (e * GAINS["ki"] > 0) == (raw - out > 0):
        integral = pid["integral"]  # anti-windup, as in the PID block
    pid["integral"], pid["prev"] = integral, e
    return {"drone": [out + MASS * G]}  # gravity feedforward
