"""RB-09: cubic, quintic, and trapezoidal joint trajectories."""

import numpy as np
import pytest

from simview.toolboxes.robotics import trajectory as tj


def finite_diff(traj, t, h=1e-6):
    q_plus, qd_plus, _ = traj.at(t + h)
    q_minus, qd_minus, _ = traj.at(t - h)
    return (q_plus - q_minus) / (2 * h), (qd_plus - qd_minus) / (2 * h)


@pytest.mark.parametrize("make", [tj.cubic, tj.quintic])
def test_polynomial_boundaries_and_derivatives(make):
    q0, q1 = np.array([0.0, 1.0, -0.5]), np.array([1.0, -1.0, 0.5])
    traj = make(q0, q1, 2.0)
    q, qd, _ = traj.at(0.0)
    np.testing.assert_allclose(q, q0)
    np.testing.assert_allclose(qd, 0, atol=1e-12)
    q, qd, _ = traj.at(2.0)
    np.testing.assert_allclose(q, q1)
    np.testing.assert_allclose(qd, 0, atol=1e-12)
    for t in (0.3, 1.0, 1.7):
        v, a = finite_diff(traj, t)
        np.testing.assert_allclose(traj.at(t)[1], v, atol=1e-6)
        np.testing.assert_allclose(traj.at(t)[2], a, atol=1e-4)


def test_cubic_and_quintic_end_conditions():
    c = tj.cubic(0.0, 1.0, 1.0, v0=0.5, v1=-0.5)
    assert c.at(0.0)[1][0] == pytest.approx(0.5) and c.at(1.0)[1][0] == pytest.approx(-0.5)
    qn = tj.quintic(0.0, 1.0, 1.0, a0=2.0, a1=-1.0)
    assert qn.at(0.0)[2][0] == pytest.approx(2.0) and qn.at(1.0)[2][0] == pytest.approx(-1.0)


def test_holds_outside_the_time_range():
    traj = tj.quintic(0.0, 2.0, 1.0)
    assert traj.at(-1.0)[0][0] == 0.0 and traj.at(5.0)[0][0] == 2.0
    assert traj.at(5.0)[1][0] == 0.0 and traj.at(5.0)[2][0] == 0.0


def test_trapezoidal_limits_and_synchronization():
    q0, q1 = np.array([0.0, 0.0, 1.0]), np.array([2.0, -0.5, 1.0])
    traj = tj.trapezoidal(q0, q1, v_max=1.0, a_max=2.0)
    assert traj.duration == pytest.approx(2.0 / 1.0 + 1.0 / 2.0)  # joint 0 cruises
    ts = np.linspace(0, traj.duration, 2001)
    states = [traj.at(t) for t in ts]
    qd = np.array([s[1] for s in states])
    qdd = np.array([s[2] for s in states])
    assert np.abs(qd).max() <= 1.0 + 1e-9 and np.abs(qdd).max() <= 2.0 + 1e-9
    np.testing.assert_allclose(traj.at(traj.duration)[0], q1)
    np.testing.assert_allclose(qd[-1], 0, atol=1e-9)
    # Position is continuous and joint 1 arrives exactly when joint 0 does.
    q = np.array([s[0] for s in states])
    assert np.abs(np.diff(q, axis=0)).max() < 1e-2
    assert abs(q[-2, 1] - q1[1]) > 0  # still moving one sample before the end


def test_trapezoidal_triangular_profile():
    traj = tj.trapezoidal(0.0, 0.1, v_max=10.0, a_max=1.0)  # no room to cruise
    assert traj.duration == pytest.approx(2 * np.sqrt(0.1))
    assert traj.at(traj.duration / 2)[0][0] == pytest.approx(0.05)


def test_trapezoidal_zero_move_and_errors():
    assert tj.trapezoidal(1.0, 1.0, 1.0, 1.0).duration == 0.0
    with pytest.raises(ValueError, match="positive"):
        tj.trapezoidal(0.0, 1.0, 0.0, 1.0)
    with pytest.raises(ValueError, match="positive"):
        tj.cubic(0.0, 1.0, 0.0)
