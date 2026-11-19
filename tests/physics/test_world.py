"""RB-01..RB-05: the shared world, objects, placement and mounting, names, servos and targets."""

import warnings

import mujoco
import numpy as np
import pytest

import simview as sv
from simview.core.scheduler import Sim
from simview.toolboxes.robotics import se3

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


def steps(scene, n):
    sim = Sim(scene)
    for _ in range(n):
        sim.step()
    return sim


# -- RB-01 / RB-02: one world, objects ---------------------------------------------------------
def test_robots_and_objects_share_one_world():
    scene = sv.Scene()
    scene.add_ground()
    arm = scene.add_robot("ur5")
    cube = scene.add_box("cube", (0.04, 0.04, 0.04), (0.5, 0, 0.5), mass=0.1)
    assert arm.world is cube.world is scene.world
    names = [scene.world.model.body(b).name for b in range(scene.world.model.nbody)]
    assert "ur5/tool0" in names and "cube" in names


def test_box_falls_and_rests_on_static_table():
    scene = sv.Scene(dt=2e-3)
    scene.add_ground()
    assert scene.add_box("table", (0.8, 0.8, 0.7), (0, 0, 0.35), static=True) is None
    box = scene.add_box("box", (0.08, 0.08, 0.08), (0, 0, 0.9), mass=0.5)
    steps(scene, 750)
    assert box.pos[2] == pytest.approx(0.74, abs=2e-3)  # table top + half the box
    assert np.abs(box.x[7:]).max() < 1e-2  # at rest


@pytest.mark.parametrize(
    ("adder", "args", "half"),
    [
        ("add_box", ((0.2, 0.1, 0.06),), [0.1, 0.05, 0.03]),
        ("add_sphere", (0.1,), [0.05, 0, 0]),
        ("add_cylinder", (0.1, 0.3), [0.05, 0.15, 0]),
        ("add_capsule", (0.1, 0.3), [0.05, 0.15, 0]),
    ],
)
def test_sizes_are_full_lengths(adder, args, half):
    scene = sv.Scene()
    getattr(scene, adder)("thing", *args, pos=(0, 0, 1), mass=1.0)
    m = scene.world.model
    g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "thing")
    np.testing.assert_allclose(m.geom_size[g], half)
    assert m.body_mass[m.geom_bodyid[g]] == pytest.approx(1.0)


def test_free_object_is_logged(tmp_path):
    scene = sv.Scene()
    scene.add_ground()
    scene.add_sphere("ball", 0.1, (0, 0, 1), mass=1.0, friction=0.5)
    run = sv.run(scene, 0.2, out=tmp_path / "r.parquet")
    for col in ("ball.x", "ball.z", "ball.qw", "ball.vz", "ball.wx"):
        assert col in run.columns
    assert run["ball.z"][-1] < 1.0 - 0.5 * 9.81 * 0.2**2 + 1e-3


def test_object_errors():
    scene = sv.Scene()
    with pytest.raises(ValueError, match="mass= for a free object"):
        scene.add_box("a", (1, 1, 1))
    with pytest.raises(ValueError, match="not both"):
        scene.add_box("a", (1, 1, 1), mass=1.0, static=True)
    with pytest.raises(ValueError, match="positive"):
        scene.add_box("a", (1, 1, 1), mass=-1.0)
    with pytest.raises(ValueError, match="3 positive"):
        scene.add_box("a", (1, 1), mass=1.0)
    with pytest.raises(ValueError, match="without '/'"):
        scene.add_box("a/b", (1, 1, 1), mass=1.0)
    scene.add_box("a", (1, 1, 1), mass=1.0)
    with pytest.raises(ValueError, match="already"):
        scene.add_sphere("a", 1.0, mass=1.0)
    scene.add_ground()
    with pytest.raises(ValueError, match="already has a ground"):
        scene.add_ground()


def test_world_options():
    scene = sv.Scene()
    w = scene.physics()
    w.integrator, w.cone, w.impratio = "rk4", "elliptic", 10.0
    scene.add_box("a", (1, 1, 1), mass=1.0)
    m = scene.world.model
    assert m.opt.integrator == mujoco.mjtIntegrator.mjINT_RK4
    assert m.opt.cone == mujoco.mjtCone.mjCONE_ELLIPTIC and m.opt.impratio == 10.0


# -- RB-03 / RB-04: placement, MJCF strings, mounting, names -------------------------------------
def test_placement_moves_the_base():
    q = np.array([0.2, -1.0, 1.2, -0.5, 0.4, 0.1])
    at_origin = sv.Scene().add_robot("ur5").fk(q)
    rz = np.array([np.cos(np.pi / 4), 0, 0, np.sin(np.pi / 4)])  # 90 deg about z
    placed = sv.Scene().add_robot("ur5", pos=(1.0, 2.0, 0.5), quat=rz).fk(q)
    base = se3.make(np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]]), [1.0, 2.0, 0.5])
    np.testing.assert_allclose(placed, base @ at_origin, atol=1e-9)


def test_free_base_robot_takes_placement_in_x0():
    mjcf = (
        '<mujoco model="cart"><worldbody><body name="b"><freejoint name="f"/>'
        '<geom type="box" size=".1 .1 .1" mass="1"/></body></worldbody></mujoco>'
    )
    cart = sv.Scene().add_robot(mjcf=mjcf, pos=(1.0, 0.0, 0.3))
    np.testing.assert_allclose(cart.x0[:3], [1.0, 0.0, 0.3])


def test_mounted_tool_follows_the_arm():
    scene = sv.Scene()
    arm = scene.add_robot("ur5")
    grip = scene.add_robot(mjcf=GRIPPER, name="grip", mount=("ur5", "tool0"))
    q = np.array([0.4, -1.1, 1.3, -1.0, 0.7, 0.3])
    pinch = arm.fk(q, "grip/pinch")
    np.testing.assert_allclose(
        pinch, arm.fk(q, "tool0") @ se3.make(np.eye(3), [0, 0, 0.065]), atol=1e-9
    )
    assert grip.joint_names == ("close_l", "close_r")
    assert grip.u.shape == (2,)


def test_mount_errors():
    scene = sv.Scene()
    scene.add_robot("ur5")
    with pytest.raises(KeyError, match="cannot mount"):
        scene.add_robot(mjcf=GRIPPER, name="g", mount=("ur5", "nowhere"))


def test_source_errors():
    with pytest.raises(ValueError, match="not both"):
        sv.Scene().add_robot("ur5", mjcf=GRIPPER)
    with pytest.raises(ValueError, match="not both"):
        sv.Scene().add_robot()


def test_world_names_are_prefixed_and_logs_are_not(tmp_path):
    scene = sv.Scene()
    arm = scene.add_robot("ur5")
    m = scene.world.model
    assert m.joint(int(arm.joint_ids[2])).name == "ur5/elbow_joint"
    assert arm.full("elbow_joint") == "ur5/elbow_joint"
    assert arm.full("grip/pinch") == "grip/pinch"
    run = sv.run(scene, 0.01, out=tmp_path / "r.parquet")
    assert "ur5.elbow_joint.q" in run.columns


def test_adjacent_links_do_not_collide():
    arm = sv.Scene().add_robot("ur5")
    d = mujoco.MjData(arm.model)
    mujoco.mj_forward(arm.model, d)
    assert d.ncon == 0  # the shoulder sits on the base without a contact


def test_robot_moves_into_the_scene_world():
    from simview.physics.mujoco_world import Robot

    scene = sv.Scene()
    scene.add_box("cube", (0.1, 0.1, 0.1), (1, 1, 1), mass=1.0)
    arm = Robot("ur5")
    old = arm.world
    scene.add_entity(arm)
    assert arm.world is scene.world and arm not in old.members


def test_unnamed_joints_and_actuators_get_names():
    mjcf = (
        "<mujoco><worldbody><body><joint/><geom size='.1' mass='1'/></body></worldbody>"
        "<actuator><motor joint='joint0'/></actuator></mujoco>"
    )
    # The actuator refers to the generated name, so name it explicitly in the file instead.
    mjcf = mjcf.replace("<joint/>", "<joint name='joint0'/>")
    r = sv.Scene().add_robot(mjcf=mjcf, name="r")
    assert r.joint_names == ("joint0",) and r.actuator_names == ("actuator0",)


# -- RB-05: servos, targets, ramps, raw controls --------------------------------------------
def servo_arm(**kw):
    scene = sv.Scene(dt=2e-3)
    arm = scene.add_robot("ur5", servos="position", kp=2000.0, kv=200.0, **kw)
    return scene, arm


def test_position_servos_reach_targets():
    scene, arm = servo_arm(gravity_compensation=True)
    q = np.array([0.5, -1.2, 1.0, -0.8, 0.6, -0.4])
    arm.set_targets(dict(zip(arm.joint_names, q, strict=True)))
    steps(scene, 1000)
    np.testing.assert_allclose(arm.q, q, atol=1e-3)


def test_target_outside_range_stops_at_limit():
    scene, arm = servo_arm()
    with pytest.warns(UserWarning, match="stops at the limit"):
        arm.set_targets({"elbow_joint": 4.0})
    assert arm.u[2] == pytest.approx(np.pi)


def test_ramp_moves_target_linearly():
    scene, arm = servo_arm(gravity_compensation=True)
    sim = Sim(scene)
    arm.set_targets({"shoulder_pan_joint": 1.0}, ramp=1.0)
    for _ in range(250):  # 0.5 s
        sim.step()
    assert arm.u[0] == pytest.approx(0.498, abs=0.003)
    for _ in range(300):
        sim.step()
    assert arm.u[0] == 1.0


def test_servo_errors():
    scene, arm = servo_arm()
    with pytest.raises(ValueError, match="position servo, not a velocity"):
        arm.set_targets({"elbow_joint": 0.1}, kind="velocity")
    with pytest.raises(KeyError, match="no joint named"):
        arm.set_targets({"knee": 0.1})
    bare = sv.Scene().add_robot("ur5")
    with pytest.raises(KeyError, match='servos="position"'):
        bare.set_targets({"elbow_joint": 0.1})
    with pytest.raises(KeyError, match="no actuator named"):
        arm.set_controls({"nope": 1.0})


def test_velocity_servos_track_speed():
    scene = sv.Scene(dt=2e-3)
    arm = scene.add_robot("ur5", servos="velocity", kv=500.0, gravity_compensation=True)
    arm.set_targets({"shoulder_pan_joint": 0.5}, kind="velocity")
    steps(scene, 500)
    assert arm["shoulder_pan_joint.v"] == pytest.approx(0.5, abs=0.02)


def test_set_controls_is_raw():
    scene = sv.Scene()
    grip = scene.add_robot(mjcf=GRIPPER, name="grip")
    grip.set_controls({"actuator0": 0.03})
    assert grip.u[0] == 0.03
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # raw controls never warn or clamp
        grip.set_controls({"actuator1": 9.0})
