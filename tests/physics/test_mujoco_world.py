"""SE-03: MuJoCo-backed entities alongside custom ODE models in one scene."""

import mujoco
import numpy as np
import pytest

import simview as sv
from simview.physics.mujoco_world import Robot

G = 9.81
L = 1.0

PENDULUM_MJCF = """
<mujoco model="pendulum">
  <option gravity="0 0 -9.81" integrator="RK4"/>
  <worldbody>
  <body name="arm">
    <joint name="hinge" type="hinge" axis="0 1 0"/>
    <geom type="sphere" size="0.001" pos="0 0 -1" mass="1"/>
  </body>
  </worldbody>
</mujoco>
"""


class OdePendulum(sv.Entity):
    """Point-mass pendulum, theta measured from straight down."""

    state_names = ("theta", "omega")

    def derivative(self, t, x, u):
        return np.array([x[1], -G / L * np.sin(x[0])])


@pytest.fixture
def pendulum_path(tmp_path):
    p = tmp_path / "pendulum.xml"
    p.write_text(PENDULUM_MJCF)
    return p


def test_add_robot_returns_named_entity():
    scene = sv.Scene()
    arm = scene.add_robot("ur5.urdf")
    assert isinstance(arm, Robot)
    assert arm.name == "ur5" and scene["ur5"] is arm
    assert arm.state_names[0] == "shoulder_pan_joint.q"
    assert arm.state_names[6] == "shoulder_pan_joint.v"
    assert len(arm.x) == 12 and arm.u.shape == (6,)


def test_mujoco_and_ode_pendulums_agree(pendulum_path):
    """The same pendulum as an MJCF body and as a custom ODE gives the same motion."""
    scene = sv.Scene(dt=1e-3)
    mj = scene.add_robot(pendulum_path, name="mj")
    scene.add_entity(OdePendulum([0.5, 0.0], name="ode"))
    mj.x0[0] = 0.5
    run = sv.run(scene, 2.0, out=pendulum_path.parent / "p.parquet")
    # Same sign convention: +theta about +y swings the mass toward -x in both.
    np.testing.assert_allclose(run["mj.hinge.q"], run["ode.theta"], atol=1e-4)
    assert run["mj.hinge.q"].min() < -0.49  # it actually swung through


def test_gravity_pulls_unpowered_arm():
    scene = sv.Scene()
    arm = scene.add_robot("ur5")
    arm.x0[: arm.nq] = [0, -np.pi / 2, np.pi / 2, 0, 0, 0]
    sim = sv.core.scheduler.Sim(scene)
    for _ in range(200):
        sim.step()
    assert np.abs(arm.q - arm.x0[: arm.nq]).max() > 1e-2


def test_gravity_compensation_holds_arm():
    """Joint torques equal to the gravity bias hold the arm still (u -> qfrc_applied)."""
    scene = sv.Scene()
    arm = scene.add_robot("ur5")
    q0 = np.array([0.3, -1.0, 1.2, -0.5, 0.8, 0.0])
    arm.x0[: arm.nq] = q0
    d = mujoco.MjData(arm.model)
    d.qpos[:] = q0
    mujoco.mj_forward(arm.model, d)
    arm.u = d.qfrc_bias.copy()
    sim = sv.core.scheduler.Sim(scene)
    for _ in range(200):
        sim.step()
    np.testing.assert_allclose(arm.q, q0, atol=1e-4)


def test_actuated_model_routes_u_to_ctrl(tmp_path):
    p = tmp_path / "motor.xml"
    p.write_text(
        """<mujoco><option gravity="0 0 0"/>
        <worldbody><body><joint name="j" type="hinge" axis="0 0 1"/>
        <geom type="box" size=".1 .1 .1" mass="1"/></body></worldbody>
        <actuator><motor joint="j" gear="1"/></actuator></mujoco>"""
    )
    scene = sv.Scene()
    m = scene.add_robot(p, name="m")
    assert m.u.shape == (1,)
    m.u = np.array([1.0])
    sim = sv.core.scheduler.Sim(scene)
    sim.step()
    assert m["j.v"] > 0


def test_multi_dof_joint_names(tmp_path):
    p = tmp_path / "free.xml"
    p.write_text(
        '<mujoco><worldbody><body name="b"><freejoint name="f"/>'
        '<geom type="sphere" size=".1" mass="1"/></body></worldbody></mujoco>'
    )
    r = Robot(p)
    assert r.state_names[:7] == tuple(f"f.q{i}" for i in range(7))
    assert r.state_names[7:] == tuple(f"f.v{i}" for i in range(6))


def test_wrong_input_size_rejected():
    scene = sv.Scene()
    arm = scene.add_robot("ur5")
    arm.u = np.zeros(3)
    with pytest.raises(ValueError, match="u has shape"):
        sv.core.scheduler.Sim(scene)


def test_derivative_is_not_used():
    with pytest.raises(TypeError, match="MuJoCo-backed"):
        Robot("ur5").derivative(0.0, np.zeros(12), np.zeros(6))


def test_reset_restores_initial_state():
    scene = sv.Scene()
    arm = scene.add_robot("ur5")
    sim = sv.core.scheduler.Sim(scene)
    for _ in range(50):
        sim.step()
    sv.core.scheduler.Sim(scene)  # a new run resets every entity
    np.testing.assert_array_equal(arm.x, arm.x0)


def test_mixed_scene_logs_are_byte_identical(tmp_path):
    """SE-07 with a MuJoCo entity in the scene: same seed + scene -> identical Parquet."""

    def build():
        scene = sv.Scene(dt=1e-3, seed=7)
        scene.add_robot("ur5")
        scene.add_entity(OdePendulum([0.2, 0.0], name="p"))
        scene.log("noise", lambda sim: sim.rng.normal())
        return scene

    a = sv.run(build(), 0.5, out=tmp_path / "a.parquet")
    b = sv.run(build(), 0.5, out=tmp_path / "b.parquet")
    assert "ur5.elbow_joint.q" in a.columns
    assert a.path.read_bytes() == b.path.read_bytes()
