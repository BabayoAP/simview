"""RB-06, RB-07, RB-12: scene controllers, robot controllers, and the M3b done-when pick."""

import numpy as np
import pytest

import simview as sv
from simview.toolboxes import robotics as rb
from tests.physics.test_world import GRIPPER

Q0 = np.array([0.3, -1.2, 1.4, -1.8, -1.57, 0.2])


# -- RB-06: scene.controller --------------------------------------------------------------------
def test_controller_rate_and_context(tmp_path):
    scene = sv.Scene(dt=1e-3, seed=3)
    calls = []

    @scene.controller(rate=100)
    def ctl(t, state, ctx):
        calls.append((t, ctx.tick, ctx.dt, ctx.rng.random()))

    sv.run(scene, 0.5, out=tmp_path / "r.parquet")
    assert len(calls) == 50
    assert calls[1][0] == pytest.approx(0.01) and calls[1][1] == 10 and calls[0][2] == 0.01


def test_controller_every_tick_and_returned_inputs(tmp_path):
    scene = sv.Scene(dt=1e-3)
    arm = scene.add_robot("ur5")
    seen = []

    @scene.controller()
    def hold(t, state, ctx):
        seen.append(state is scene)
        return {"ur5": rb.gravity_torques(arm)}

    sv.run(scene, 0.2, out=tmp_path / "r.parquet")
    assert len(seen) == 200 and all(seen)
    np.testing.assert_allclose(arm.q, arm.x0[:6], atol=1e-6)  # held still


def test_controller_rate_must_divide_physics_rate():
    with pytest.raises(ValueError, match="must divide"):
        sv.Scene(dt=1e-3).controller(rate=300)


# -- RB-07: robot controllers --------------------------------------------------------------------
def inertia_scaled(arm, omega):
    """Per-joint gains kp = omega^2 M_ii, kd = 2 omega M_ii (critically damped at omega rad/s):
    fixed gains strong enough for the shoulder make the light wrist unstable."""
    m = np.diag(rb.mass_matrix(arm, Q0))
    return omega**2 * m, 2 * omega * m


def torque_arm(dt=1e-3):
    scene = sv.Scene(dt=dt)
    arm = scene.add_robot("ur5")
    arm.x0[:6] = Q0
    return scene, arm


def test_joint_impedance_reaches_target_against_gravity(tmp_path):
    scene, arm = torque_arm()
    kp, kd = inertia_scaled(arm, 30.0)
    pid = rb.JointPID(arm, kp=kp, kd=kd)
    q_des = Q0 + np.array([0.2, -0.2, 0.2, 0.1, -0.1, 0.3])

    @scene.controller()
    def ctl(t, state, ctx):
        return {"ur5": pid.step(q_des, dt=ctx.dt)}

    sv.run(scene, 2.0, out=tmp_path / "r.parquet")
    np.testing.assert_allclose(arm.q, q_des, atol=1e-4)


def test_integral_term_removes_steady_state_error(tmp_path):
    scene, arm = torque_arm()
    # No gravity compensation: a PD alone sags; the integral pulls it back.
    kp, kd = inertia_scaled(arm, 20.0)
    pd = rb.JointPID(arm, kp=kp, kd=kd, compensate=False)
    pid = rb.JointPID(arm, kp=kp, kd=kd, ki=2.0 * kp, i_limit=50.0, compensate=False)
    errs = {}
    for name, ctl_obj in (("pd", pd), ("pid", pid)):
        arm.reset()

        @scene.controller()
        def ctl(t, state, ctx, c=ctl_obj):
            return {"ur5": c.step(Q0, dt=ctx.dt)}

        sv.run(scene, 3.0, out=tmp_path / f"{name}.parquet")
        scene.controllers.clear()
        errs[name] = float(np.abs(arm.q - Q0).max())
    assert errs["pid"] < errs["pd"] / 5
    assert np.all(np.abs(pid.integral) <= 50.0)  # anti-windup clamp


def test_operational_space_tracks_a_step_within_1mm(tmp_path):
    """M3b done-when: operational-space control tracks a task-space step to within 1 mm."""
    scene, arm = torque_arm()
    osc = rb.OperationalSpace(arm, kp=400.0, q_null=Q0)
    target = arm.fk(Q0).copy()
    target[:3, 3] += [0.05, -0.05, 0.08]

    @scene.controller()
    def ctl(t, state, ctx):
        return {"ur5": osc.step(target)}

    sv.run(scene, 2.0, out=tmp_path / "r.parquet")
    e = rb.se3.error(arm.fk(), target)
    assert np.linalg.norm(e[:3]) < 1e-3 and np.linalg.norm(e[3:]) < 1e-2


def test_differential_ik_converges_kinematically():
    arm = sv.Scene().add_robot("ur5")
    target = arm.fk(Q0 + 0.3)
    ik = rb.DifferentialIK(arm, gain=1.0, damping=1e-3, max_step=0.1)
    q = Q0.copy()
    for _ in range(200):
        q = ik.step(target, q)
    assert np.linalg.norm(ik.error(target, q)) < 1e-6
    ik.reset()
    assert ik.q_cmd is None


def test_differential_ik_position_only():
    arm = sv.Scene().add_robot("ur5")
    goal = arm.fk(Q0)[:3, 3] + [0.05, 0.0, -0.05]
    ik = rb.DifferentialIK(arm, position_only=True, damping=1e-3, max_step=0.1)
    ik.step(goal, Q0)
    for _ in range(200):
        ik.step(goal)
    assert np.linalg.norm(arm.fk(ik.q_cmd)[:3, 3] - goal) < 1e-6


def test_controllers_need_hinge_or_slide_joints():
    cart = sv.Scene().add_robot(
        mjcf='<mujoco><worldbody><body name="b"><freejoint/><geom size=".1" mass="1"/>'
        "</body></worldbody></mujoco>",
        name="cart",
    )
    for make in (
        lambda: rb.JointPID(cart, 1.0, 1.0),
        lambda: rb.DifferentialIK(cart),
        lambda: rb.OperationalSpace(cart),
    ):
        with pytest.raises(ValueError, match="hinge/slide"):
            make()


# -- RB-12 + M3b done-when: pick up a cube and lift it 10 cm -------------------------------------
def test_pick_and_lift_cube_10cm(tmp_path):
    """A UR5 with a mounted two-finger gripper picks up a 4 cm cube by friction and lifts it
    10 cm under differential-IK control, with a quintic lift ramp."""
    scene = sv.Scene(dt=2e-3)
    world = scene.physics()
    world.cone, world.impratio = "elliptic", 10.0  # D-028: the grasping settings
    scene.add_ground()
    arm = scene.add_robot("ur5", servos="position", kp=2000.0, kv=200.0, gravity_compensation=True)
    grip = scene.add_robot(
        mjcf=GRIPPER, name="grip", mount=("ur5", "tool0"), gravity_compensation=True
    )
    scene.add_box("cube", (0.04, 0.04, 0.04), (0.45, 0.15, 0.02), mass=0.1, friction=1.0)
    home = np.array([0.0, -1.7, 1.9, -1.77, -1.57, 0.0])
    arm.x0[:6] = home
    arm.set_targets(dict(zip(arm.joint_names, home, strict=True)))
    ik = rb.DifferentialIK(arm, frame="grip/pinch", max_step=0.02)
    down = np.diag([1.0, -1.0, -1.0])  # gripper pointing at the floor
    lift = rb.trajectory.quintic(0.03, 0.13, 1.5)

    def goal(z):
        return rb.se3.make(down, [0.45, 0.15, z])

    @scene.controller(rate=100)
    def pick(t, state, ctx):
        if t < 1.5:
            target = goal(0.15)  # above the cube
        elif t < 3.5:
            target = goal(0.03)  # around it, fingertips clear of the floor
            if t >= 3.0:
                grip.set_targets({"close_l": 0.035, "close_r": 0.035})  # squeeze
        else:
            target = goal(float(lift.at(t - 3.5)[0][0]))
        arm.set_targets(dict(zip(arm.joint_names, ik.step(target), strict=True)))

    run = sv.run(scene, 5.5, out=tmp_path / "pick.parquet")
    z = run["cube.z"]
    assert z[0] == pytest.approx(0.02, abs=1e-3)
    assert z[-1] - z[0] >= 0.095  # lifted 10 cm (within 5 mm of slip in the grip)
    assert np.all(grip.q > 0.015) and np.all(grip.q < 0.025)  # fingers stopped on the cube
    assert abs(run["cube.x"][-1] - 0.45) < 0.01 and abs(run["cube.y"][-1] - 0.15) < 0.01
