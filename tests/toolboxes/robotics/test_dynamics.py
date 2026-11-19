"""RB-08: inverse dynamics, gravity torques, and the mass matrix."""

import mujoco
import numpy as np

import simview as sv
from simview.toolboxes import robotics as rb


def test_inverse_dynamics_matches_forward_dynamics():
    """M3b done-when: applying ID torques reproduces the requested accelerations within 1e-6."""
    arm = sv.Scene().add_robot("ur5")
    rng = np.random.default_rng(0)
    worst = 0.0
    for _ in range(50):
        q, qd, qdd = rng.uniform(-np.pi, np.pi, 6), rng.normal(size=6), rng.normal(size=6)
        tau = rb.inverse_dynamics(arm, q, qd, qdd)
        d = mujoco.MjData(arm.model)
        d.qpos[arm.qidx], d.qvel[arm.vidx], d.qfrc_applied[arm.vidx] = q, qd, tau
        mujoco.mj_forward(arm.model, d)
        worst = max(worst, float(np.abs(d.qacc[arm.vidx] - qdd).max()))
    assert worst < 1e-6


def test_gravity_torques_equal_mujoco_bias_at_rest():
    arm = sv.Scene().add_robot("ur5")
    q = np.array([0.3, -1.0, 1.2, -0.5, 0.8, 0.0])
    d = mujoco.MjData(arm.model)
    d.qpos[arm.qidx] = q
    mujoco.mj_forward(arm.model, d)
    np.testing.assert_allclose(rb.gravity_torques(arm, q), d.qfrc_bias[arm.vidx], atol=1e-9)


def test_gravity_compensation_flag_cancels_gravity():
    arm = sv.Scene().add_robot("ur5", gravity_compensation=True)
    np.testing.assert_allclose(
        rb.gravity_torques(arm, np.array([0.3, -1.0, 1.2, 0, 0, 0])), 0, atol=1e-9
    )


def test_mass_matrix_is_symmetric_positive_definite_and_matches_mujoco():
    arm = sv.Scene().add_robot("ur5")
    q = np.array([0.1, -0.9, 1.1, -0.4, 0.5, 0.2])
    M = rb.mass_matrix(arm, q)
    np.testing.assert_allclose(M, M.T, atol=1e-12)
    assert np.all(np.linalg.eigvalsh(M) > 0)
    # M qdd = tau - bias: check against inverse dynamics with zero velocity.
    qdd = np.array([0.5, -0.2, 0.3, 0.1, -0.4, 0.2])
    np.testing.assert_allclose(
        M @ qdd, rb.inverse_dynamics(arm, q, None, qdd) - rb.gravity_torques(arm, q), atol=1e-9
    )


def test_dynamics_leave_the_simulated_state_alone():
    arm = sv.Scene().add_robot("ur5")
    before = arm.x.copy(), arm.data.qpos.copy()
    rb.inverse_dynamics(arm, np.ones(6), np.ones(6), np.ones(6))
    rb.mass_matrix(arm, np.ones(6))
    np.testing.assert_array_equal(arm.x, before[0])
    np.testing.assert_array_equal(arm.data.qpos, before[1])
