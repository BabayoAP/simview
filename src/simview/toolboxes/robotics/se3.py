"""SE(3) helpers (`sv.robotics.se3`): 4x4 homogeneous transforms and rotation logs."""

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation


def make(R: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Homogeneous transform from a 3x3 rotation and a 3-vector position."""
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = p
    return T


def inv(T: np.ndarray) -> np.ndarray:
    R, p = T[:3, :3], T[:3, 3]
    return make(R.T, -R.T @ p)


def rot_log(R: np.ndarray) -> np.ndarray:
    """Axis-angle vector w (|w| = angle in [0, pi]) with exp([w]x) = R."""
    return Rotation.from_matrix(R).as_rotvec()


def error(T: np.ndarray, target: np.ndarray) -> np.ndarray:
    """6-vector [dp, dw] in the world frame that moves pose `T` toward `target`."""
    dp = target[:3, 3] - T[:3, 3]
    dw = rot_log(target[:3, :3] @ T[:3, :3].T)
    return np.concatenate([dp, dw])
