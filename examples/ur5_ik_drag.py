"""UC-3: drag the UR5's end-effector target and watch damped-least-squares IK follow live.

    simview            # then File > Open Scene… and pick this file, and press Space

Drag the gizmo on the blue target sphere: the arm's tool follows it, the Inspector's joint
sliders track the joints, and the debug draw shows the goal frame and the remaining error.
"""

import numpy as np

import simview as sv
from simview.core.scene import Context
from simview.toolboxes import robotics as rb

scene = sv.Scene(dt=2e-3, seed=0)
scene.add_ground()
arm = scene.add_robot("ur5", servos="position", kp=2000.0, kv=200.0, gravity_compensation=True)

home = np.array([0.0, -1.7, 1.9, -1.77, -1.57, 0.0])
arm.x0[:6] = home
arm.set_targets(dict(zip(arm.joint_names, home, strict=True)))
goal = scene.add_target("goal", arm.fk(home))  # starts at the tool, so nothing moves until dragged

ik = rb.DifferentialIK(arm, max_step=0.02)


@scene.controller(rate=100)
def follow(t: float, state: sv.Scene, ctx: Context) -> None:
    arm.set_targets(dict(zip(arm.joint_names, ik.step(goal.pose), strict=True)))
    tool = arm.fk()
    ctx.draw.frame(goal.pose, scale=0.08)
    ctx.draw.line(tool[:3, 3], goal.pose[:3, 3], color="state.warning")


scene.log(
    "tool_error", lambda sim: float(np.linalg.norm(arm.fk()[:3, 3] - goal.pose[:3, 3])), unit="m"
)
