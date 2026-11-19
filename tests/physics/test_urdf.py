"""IO-01: URDF and MJCF import, including meshes, joints, limits, and inertials."""

import shutil
from pathlib import Path

import mujoco
import numpy as np
import pytest

from simview.physics.urdf import BUNDLED, load_model, resolve

UR5_DIR = BUNDLED / "ur5"
UR5_JOINTS = [
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
]


def name(m, obj, i):
    return mujoco.mj_id2name(m, obj, i)


@pytest.fixture(scope="module")
def ur5():
    return load_model("ur5.urdf")


def test_bundled_robot_found_by_name():
    assert resolve("ur5.urdf") == UR5_DIR / "ur5.urdf"
    assert resolve("ur5") == UR5_DIR / "ur5.urdf"


def test_unknown_robot_raises():
    with pytest.raises(FileNotFoundError, match="no bundled or library robot"):
        resolve("not_a_robot.urdf")


def test_ur5_joints(ur5):
    assert ur5.njnt == 6
    assert [name(ur5, mujoco.mjtObj.mjOBJ_JOINT, j) for j in range(6)] == UR5_JOINTS
    assert all(t == mujoco.mjtJoint.mjJNT_HINGE for t in ur5.jnt_type)


def test_ur5_joint_limits(ur5):
    assert ur5.jnt_limited.all()
    expected = np.array([[-2 * np.pi, 2 * np.pi]] * 6)
    expected[2] = [-np.pi, np.pi]  # elbow
    np.testing.assert_allclose(ur5.jnt_range, expected)


def test_ur5_inertials(ur5):
    masses = {name(ur5, mujoco.mjtObj.mjOBJ_BODY, b): ur5.body_mass[b] for b in range(ur5.nbody)}
    expected = {
        "base_link_inertia": 4.0,
        "shoulder_link": 3.7,
        "upper_arm_link": 8.393,
        "forearm_link": 2.33,
        "wrist_1_link": 1.219,
        "wrist_2_link": 1.219,
        "wrist_3_link": 0.1879,
    }
    for body, mass in expected.items():
        assert masses[body] == pytest.approx(mass)
    # Center of mass of the upper arm, from physical_parameters.yaml.
    b = mujoco.mj_name2id(ur5, mujoco.mjtObj.mjOBJ_BODY, "upper_arm_link")
    np.testing.assert_allclose(ur5.body_ipos[b], [-0.2125, 0.0, 0.11336], atol=1e-12)


def test_ur5_meshes(ur5):
    assert ur5.nmesh == 7
    assert ur5.ngeom == 7  # one collision mesh per link; visual duplicates dropped
    assert all(t == mujoco.mjtGeom.mjGEOM_MESH for t in ur5.geom_type)


def test_static_frames_are_kept(ur5):
    for frame in ("base_link", "base", "flange", "tool0"):
        assert mujoco.mj_name2id(ur5, mujoco.mjtObj.mjOBJ_BODY, frame) >= 0


def copy_ur5(tmp_path: Path, rewrite) -> Path:
    shutil.copytree(UR5_DIR / "meshes", tmp_path / "meshes")
    text = (UR5_DIR / "ur5.urdf").read_text()
    out = tmp_path / "robot.urdf"
    out.write_text(rewrite(text))
    return out


def test_package_uri_meshes(tmp_path):
    path = copy_ur5(tmp_path, lambda s: s.replace('"meshes/', '"package://ur_description/meshes/'))
    assert load_model(path).nmesh == 7


def test_unsupported_mesh_format(tmp_path):
    path = copy_ur5(tmp_path, lambda s: s.replace("base.stl", "base.dae"))
    with pytest.raises(ValueError, match="convert"):
        load_model(path)


def test_missing_mesh(tmp_path):
    path = copy_ur5(tmp_path, lambda s: s.replace("base.stl", "nope.stl"))
    with pytest.raises(FileNotFoundError, match="nope.stl"):
        load_model(path)


def test_urdf_suffix_but_not_urdf(tmp_path):
    path = tmp_path / "x.urdf"
    path.write_text("<mujoco/>")
    with pytest.raises(ValueError, match="not a URDF"):
        load_model(path)


PENDULUM_MJCF = """
<mujoco model="pendulum">
  <compiler angle="radian"/>
  <worldbody>
  <body name="arm">
    <joint name="hinge" type="hinge" axis="0 1 0" range="-3 3" limited="true"/>
    <geom type="sphere" size="0.01" pos="0 0 -1" mass="2"/>
  </body>
  </worldbody>
</mujoco>
"""


def test_mjcf_import(tmp_path):
    path = tmp_path / "pendulum.xml"
    path.write_text(PENDULUM_MJCF)
    m = load_model(path)
    assert m.njnt == 1 and m.jnt_limited[0]
    np.testing.assert_allclose(m.jnt_range[0], [-3, 3])
    assert m.body_mass[1] == pytest.approx(2.0)


def test_mjcf_round_trip_keeps_kinematics(tmp_path, ur5):
    """The UR5 saved by MuJoCo as MJCF loads back with the same structure."""
    ur5 = load_model("ur5.urdf")  # mj_saveLastXML saves the most recently loaded model
    mujoco.mj_saveLastXML(str(tmp_path / "ur5.xml"), ur5)
    again = load_model(tmp_path / "ur5.xml")
    assert (again.njnt, again.nbody, again.nmesh) == (ur5.njnt, ur5.nbody, ur5.nmesh)
    # mj_saveLastXML writes about 6 significant digits.
    np.testing.assert_allclose(again.body_pos, ur5.body_pos, atol=1e-5)
    np.testing.assert_allclose(again.jnt_range, ur5.jnt_range, atol=1e-5)
