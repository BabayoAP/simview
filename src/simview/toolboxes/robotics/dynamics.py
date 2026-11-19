"""Robot dynamics through MuJoCo (RB-08): inverse dynamics, gravity torques, mass matrix.

Computed on scratch data with the rest of the world as it currently is, over the robot's own
degrees of freedom. Contacts are ignored (as in MuJoCo's `mj_inverse` with no active contacts).
"""

from __future__ import annotations

import mujoco
import numpy as np

from simview.physics.mujoco_world import Robot
from simview.toolboxes.robotics.kinematics import posed


def _full(robot: Robot, values: np.ndarray | None) -> np.ndarray:
    out = np.zeros(robot.model.nv)
    if values is not None:
        out[robot.vidx] = values
    return out


def inverse_dynamics(
    robot: Robot,
    q: np.ndarray | None = None,
    qd: np.ndarray | None = None,
    qdd: np.ndarray | None = None,
) -> np.ndarray:
    """Joint forces that produce accelerations `qdd` at state (`q`, `qd`); defaults are the
    robot's current `q`, zero velocity, and zero acceleration."""
    m = robot.model
    data = posed(robot, q, qd)
    data.qvel[:] = _full(robot, qd)
    data.qacc[:] = _full(robot, qdd)
    mujoco.mj_inverse(m, data)
    return data.qfrc_inverse[robot.vidx].copy()


def gravity_torques(robot: Robot, q: np.ndarray | None = None) -> np.ndarray:
    """Joint forces that hold the robot still at `q` against gravity."""
    return inverse_dynamics(robot, q)


def bias_forces(
    robot: Robot, q: np.ndarray | None = None, qd: np.ndarray | None = None
) -> np.ndarray:
    """Gravity plus Coriolis/centrifugal forces at (`q`, `qd`), minus passive forces."""
    return inverse_dynamics(robot, q, qd if qd is not None else robot.qd)


def mass_matrix(robot: Robot, q: np.ndarray | None = None) -> np.ndarray:
    """The robot's joint-space inertia matrix (nv x nv) at `q`."""
    m = robot.model
    data = posed(robot, q)
    mujoco.mj_crb(m, data)
    full = np.zeros((m.nv, m.nv))
    if hasattr(data, "qM"):  # MuJoCo 3.x: mj_fullM(m, dst, qM)
        mujoco.mj_fullM(m, full, data.qM)
    else:  # MuJoCo 4.x: mj_fullM(m, d, dst)
        mujoco.mj_fullM(m, data, full)
    return full[np.ix_(robot.vidx, robot.vidx)]
