"""TB-ROBOT: FK against UR's published DH parameters, Jacobian, and DLS IK (M3 done-when)."""

import numpy as np
import pytest

import simview as sv
from simview.physics.mujoco_world import Robot
from simview.toolboxes.robotics import fk, ik, jacobian, se3

# UR5 DH parameters published by Universal Robots ("DH parameters for calculations of
# kinematics and dynamics"). Independent of the URDF and of MuJoCo.
DH_A = [0.0, -0.425, -0.39225, 0.0, 0.0, 0.0]
DH_D = [0.089159, 0.0, 0.0, 0.10915, 0.09465, 0.0823]
DH_ALPHA = [np.pi / 2, 0.0, 0.0, np.pi / 2, -np.pi / 2, 0.0]
HOME = np.array([0.0, -np.pi / 2, np.pi / 2, -np.pi / 2, -np.pi / 2, 0.0])


def dh_fk(q):
    """`base` -> `tool0` by DH, then into the world (`base_link`): `base` is `base_link`
    rotated pi about z."""
    T = np.diag([-1.0, -1.0, 1.0, 1.0])
    for a, d, alpha, th in zip(DH_A, DH_D, DH_ALPHA, q, strict=True):
        ct, st, ca, sa = np.cos(th), np.sin(th), np.cos(alpha), np.sin(alpha)
        T = T @ np.array(
            [
                [ct, -st * ca, st * sa, a * ct],
                [st, ct * ca, -ct * sa, a * st],
                [0.0, sa, ca, d],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
    return T


@pytest.fixture(scope="module")
def ur5():
    return Robot("ur5.urdf")


def test_fk_matches_dh_reference(ur5):
    """M3 done-when: FK matches a reference within 1e-6 (1,000 random configurations)."""
    rng = np.random.default_rng(0)
    worst = 0.0
    for _ in range(1000):
        q = rng.uniform(-np.pi, np.pi, 6)
        worst = max(worst, float(np.abs(fk(ur5, q) - dh_fk(q)).max()))
    assert worst < 1e-6


def test_fk_defaults_to_current_q_and_leaves_state_alone(ur5):
    ur5.reset()
    ur5.set_q(HOME)
    x_before = ur5.x.copy()
    np.testing.assert_allclose(fk(ur5), dh_fk(HOME), atol=1e-6)
    fk(ur5, np.zeros(6))
    np.testing.assert_array_equal(ur5.x, x_before)
    ur5.reset()


def test_robot_methods_match_toolbox(ur5):
    q = np.array([0.1, -0.7, 1.1, 0.4, -0.3, 0.9])
    np.testing.assert_array_equal(ur5.fk(q), fk(ur5, q))
    np.testing.assert_array_equal(ur5.jacobian(q), jacobian(ur5, q))
    assert sv.robotics.fk is fk


def test_other_frames(ur5):
    q = np.zeros(6)
    flange = fk(ur5, q, "flange")
    np.testing.assert_allclose(flange[:3, 3], fk(ur5, q)[:3, 3], atol=1e-12)  # same origin
    with pytest.raises(KeyError, match="no frame"):
        fk(ur5, q, "gripper")


def test_jacobian_matches_finite_differences(ur5):
    rng = np.random.default_rng(1)
    h = 1e-7
    for _ in range(20):
        q = rng.uniform(-np.pi, np.pi, 6)
        J = jacobian(ur5, q)
        assert J.shape == (6, 6)
        T = fk(ur5, q)
        for i in range(6):
            dq = np.zeros(6)
            dq[i] = h
            Ti = fk(ur5, q + dq)
            dw = se3.rot_log(Ti[:3, :3] @ T[:3, :3].T)
            num = np.concatenate([(Ti[:3, 3] - T[:3, 3]) / h, dw / h])
            np.testing.assert_allclose(J[:, i], num, atol=1e-5)


def test_ik_converges_on_random_reachable_poses(ur5):
    """M3 done-when: IK converges within 50 iterations for >= 95% of random reachable poses."""
    rng = np.random.default_rng(2)
    n, ok = 300, 0
    for _ in range(n):
        target = fk(ur5, rng.uniform(-np.pi, np.pi, 6))
        res = ik(ur5, target, HOME, max_iters=50)
        if res.converged:
            ok += 1
            assert res.iterations <= 50
            assert np.abs(fk(ur5, res.q) - target).max() < 1e-5
    assert ok / n >= 0.95, f"converged {ok}/{n}"


def test_ik_result_within_limits_and_deterministic(ur5):
    target = fk(ur5, np.array([2.5, -2.0, 2.8, 1.0, -2.9, 3.0]))
    a = ik(ur5, target, HOME)
    b = ik(ur5, target, HOME)
    np.testing.assert_array_equal(a.q, b.q)
    lo, hi = ur5.model.jnt_range.T
    assert np.all(a.q >= lo) and np.all(a.q <= hi)


def test_ik_reports_failure_for_unreachable_pose(ur5):
    target = se3.make(np.eye(3), np.array([5.0, 0.0, 0.0]))  # far outside the 0.85 m reach
    res = ik(ur5, target, HOME)
    assert not res.converged and res.iterations == 50 and res.pos_error > 3.0


def test_ik_starts_from_current_q(ur5):
    ur5.reset()
    ur5.set_q(HOME)
    res = ur5.ik(fk(ur5, HOME))
    assert res.converged and res.iterations == 0
    ur5.reset()


def test_ik_needs_hinge_or_slide_joints(tmp_path):
    p = tmp_path / "free.xml"
    p.write_text(
        '<mujoco><worldbody><body name="tool0"><freejoint/>'
        '<geom type="sphere" size=".1" mass="1"/></body></worldbody></mujoco>'
    )
    with pytest.raises(ValueError, match="nq == nv"):
        ik(Robot(p), np.eye(4))
