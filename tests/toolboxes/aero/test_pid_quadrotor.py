"""D-081: M7's check rerun with the 6-DOF quadrotor. The altitude PID from
`examples/drone_altitude/` drives an `sv.aero.Quadrotor` (collective thrust only), once as a
block diagram (`altitude.svd`) and once as a script; both flights match within 1e-9."""

import sys
from pathlib import Path

import numpy as np

import simview as sv
from simview.toolboxes.aero import Quadrotor

EX = Path(__file__).resolve().parents[3] / "examples" / "drone_altitude"
sys.path.insert(0, str(EX))
from model import GAINS, MASS, RATE, TARGET, G  # noqa: E402

DURATION = 5.0


def quad_scene() -> sv.Scene:
    scene = sv.Scene(dt=1e-3, seed=0)
    scene.add_entity(Quadrotor(name="drone", mass=MASS))
    return scene


def script_scene() -> sv.Scene:
    scene = quad_scene()
    pid = {"integral": 0.0, "prev": None}
    ts = 1.0 / RATE

    @scene.controller(rate=RATE)
    def altitude(t, state, ctx):  # the same law as examples/drone_altitude/script.py
        e = TARGET - state["drone"]["z"]
        integral = pid["integral"] + e * ts
        deriv = (e - pid["prev"]) / ts if pid["prev"] is not None else 0.0
        raw = GAINS["kp"] * e + GAINS["ki"] * integral + GAINS["kd"] * deriv
        out = min(max(raw, GAINS["lower"]), GAINS["upper"])
        if out != raw and (e * GAINS["ki"] > 0) == (raw - out > 0):
            integral = pid["integral"]
        pid["integral"], pid["prev"] = integral, e
        return {"drone": [out + MASS * G]}

    return scene


def diagram_scene() -> sv.Scene:
    scene = quad_scene()
    scene.add_diagram(EX / "altitude.svd", rate=RATE)
    return scene


def test_pid_diagram_flies_the_6dof_quadrotor_like_the_script(tmp_path):
    script = sv.run(script_scene(), duration=DURATION, out=tmp_path / "s.parquet")
    blocks = sv.run(diagram_scene(), duration=DURATION, out=tmp_path / "b.parquet")
    for col in ("drone.z", "drone.vz", "drone.x", "drone.y", "drone.qw"):
        assert np.max(np.abs(script[col] - blocks[col])) <= 1e-9, col
    z = blocks["drone.z"]
    assert abs(z[-1] - TARGET) < 0.1 and z.max() > 1.5  # climbs to the target and holds
    # Thrust only, no torque: the 6-DOF body stays level and over its start point.
    assert np.max(np.abs(blocks["drone.x"])) < 1e-9 and np.max(np.abs(blocks["drone.y"])) < 1e-9
    assert np.min(blocks["drone.qw"]) > 1 - 1e-9
