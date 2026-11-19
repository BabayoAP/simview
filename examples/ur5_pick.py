"""A UR5 with a two-finger gripper picks up a cube and lifts it 10 cm (UC-3, M3b).

    simview run examples/ur5_pick.py --headless --duration 5.5

Shows the shared MuJoCo world (RB-01), objects (RB-02), mounting a tool (RB-03), position
servos with gravity compensation (RB-05), a scene controller (RB-06), differential-IK control
(RB-07), a quintic lift (RB-09), and a friction grasp (RB-12).
"""

import numpy as np

import simview as sv
from simview.core.scene import Context
from simview.toolboxes import robotics as rb

GRIPPER = """<mujoco model="gripper"><worldbody><body name="palm">
  <geom type="box" size="0.03 0.055 0.01" pos="0 0 0.01" mass="0.2"/>
  <site name="pinch" pos="0 0 0.065"/>
  <body name="finger_l" pos="0 0.045 0.055">
    <joint name="close_l" type="slide" axis="0 -1 0" range="0 0.04" damping="4"/>
    <geom type="box" size="0.01 0.005 0.035" mass="0.02" friction="1.5"/></body>
  <body name="finger_r" pos="0 -0.045 0.055">
    <joint name="close_r" type="slide" axis="0 1 0" range="0 0.04" damping="4"/>
    <geom type="box" size="0.01 0.005 0.035" mass="0.02" friction="1.5"/></body>
</body></worldbody>
<actuator><position joint="close_l" kp="300" kv="8"/>
  <position joint="close_r" kp="300" kv="8"/></actuator></mujoco>"""

CUBE = np.array([0.45, 0.15])  # where the cube sits on the floor (m)

scene = sv.Scene(dt=2e-3, seed=0)
world = scene.physics()
world.cone, world.impratio = "elliptic", 10.0  # grasping settings (D-028)
scene.add_ground()
arm = scene.add_robot("ur5", servos="position", kp=2000.0, kv=200.0, gravity_compensation=True)
grip = scene.add_robot(mjcf=GRIPPER, name="grip", mount=("ur5", "tool0"), gravity_compensation=True)
scene.add_box("cube", (0.04, 0.04, 0.04), (*CUBE, 0.02), mass=0.1, friction=1.0)

home = np.array([0.0, -1.7, 1.9, -1.77, -1.57, 0.0])
arm.x0[:6] = home
arm.set_targets(dict(zip(arm.joint_names, home, strict=True)))

ik = rb.DifferentialIK(arm, frame="grip/pinch", max_step=0.02)
lift = rb.trajectory.quintic(0.03, 0.13, 1.5)
DOWN = np.diag([1.0, -1.0, -1.0])  # gripper pointing at the floor


def goal(z: float) -> np.ndarray:
    return rb.se3.make(DOWN, [*CUBE, z])


@scene.controller(rate=100)
def pick(t: float, state: sv.Scene, ctx: Context) -> None:
    if t < 1.5:
        target = goal(0.15)  # above the cube
    elif t < 3.5:
        target = goal(0.03)  # around it, fingertips clear of the floor
        if t >= 3.0:
            grip.set_targets({"close_l": 0.035, "close_r": 0.035})  # squeeze
    else:
        target = goal(float(lift.at(t - 3.5)[0][0]))  # smooth lift: a jerk would drop it
    arm.set_targets(dict(zip(arm.joint_names, ik.step(target), strict=True)))


scene.log("pinch_z", lambda sim: float(arm.fk(None, "grip/pinch")[2, 3]))
