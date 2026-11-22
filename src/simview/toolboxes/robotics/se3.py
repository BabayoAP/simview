"""SE(3) helpers (`sv.robotics.se3`): 4x4 homogeneous transforms and rotation logs."""

from __future__ import annotations

import math

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
    # Closed form where it is well conditioned (NF-02: SciPy's Rotation costs ~0.1 ms a call);
    # near pi the axis comes from the symmetric part, so hand that to SciPy.
    (r00, r01, r02), (r10, r11, r12), (r20, r21, r22) = np.asarray(R, dtype=np.float64).tolist()
    c = min(1.0, max(-1.0, (r00 + r11 + r22 - 1.0) / 2.0))
    if c < -0.99:
        return Rotation.from_matrix(R).as_rotvec()
    angle = math.acos(c)
    s = 0.5 if angle < 1e-9 else angle / (2.0 * math.sin(angle))
    return np.array([(r21 - r12) * s, (r02 - r20) * s, (r10 - r01) * s])


def error(T: np.ndarray, target: np.ndarray) -> np.ndarray:
    """6-vector [dp, dw] in the world frame that moves pose `T` toward `target`."""
    dp = target[:3, 3] - T[:3, 3]
    dw = rot_log(target[:3, :3] @ T[:3, :3].T)
    return np.concatenate([dp, dw])
