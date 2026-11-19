"""TB-ROBOT SE(3) helpers."""

import numpy as np
from scipy.spatial.transform import Rotation

from simview.toolboxes.robotics import se3


def random_T(rng):
    return se3.make(Rotation.random(random_state=rng).as_matrix(), rng.normal(size=3))


def test_inverse():
    rng = np.random.default_rng(0)
    for _ in range(10):
        T = random_T(rng)
        np.testing.assert_allclose(T @ se3.inv(T), np.eye(4), atol=1e-12)


def test_rot_log_round_trips_including_near_pi():
    for angle in (0.0, 1e-9, 0.5, 3.0, np.pi - 1e-9):
        w = angle * np.array([1.0, -2.0, 0.5]) / np.linalg.norm([1.0, -2.0, 0.5])
        R = Rotation.from_rotvec(w).as_matrix()
        np.testing.assert_allclose(Rotation.from_rotvec(se3.rot_log(R)).as_matrix(), R, atol=1e-9)


def test_error_is_zero_at_target_and_points_toward_it():
    rng = np.random.default_rng(1)
    T = random_T(rng)
    np.testing.assert_allclose(se3.error(T, T), 0.0, atol=1e-12)
    target = T.copy()
    target[:3, 3] += [0.1, 0.0, 0.0]
    np.testing.assert_allclose(se3.error(T, target), [0.1, 0, 0, 0, 0, 0], atol=1e-12)
