"""Forward kinematics, geometric Jacobian, and damped-least-squares IK (TB-ROBOT).

All three use a scratch `MjData`, so they never disturb a robot's simulated state. Frames are
MuJoCo body names (URDF links, including static ones such as `tool0`). Poses are 4x4 transforms
in the world frame.
"""

from __future__ import annotations

from dataclasses import dataclass

import mujoco
import numpy as np

from simview.physics.mujoco_world import Robot
from simview.toolboxes.robotics import se3

DEFAULT_FRAME = "tool0"


def _body(robot: Robot, frame: str) -> int:
    bid = mujoco.mj_name2id(robot.model, mujoco.mjtObj.mjOBJ_BODY, frame)
    if bid < 0:
        raise KeyError(f"{robot.name} has no frame (body) named {frame!r}")
    return bid


def _scratch(robot: Robot) -> mujoco.MjData:
    data = getattr(robot, "_kin_data", None)
    if data is None:
        data = mujoco.MjData(robot.model)
        robot._kin_data = data  # noqa: SLF001 - cached on the robot, private to this module
    return data


def _posed(robot: Robot, q: np.ndarray | None) -> mujoco.MjData:
    data = _scratch(robot)
    data.qpos[:] = robot.q if q is None else np.asarray(q, dtype=np.float64)
    mujoco.mj_kinematics(robot.model, data)
    mujoco.mj_comPos(robot.model, data)
    return data


def fk(robot: Robot, q: np.ndarray | None = None, frame: str = DEFAULT_FRAME) -> np.ndarray:
    """World pose of `frame` at joint positions `q` (default: the robot's current `q`)."""
    bid = _body(robot, frame)
    data = _posed(robot, q)
    return se3.make(data.xmat[bid].reshape(3, 3), data.xpos[bid])


def jacobian(robot: Robot, q: np.ndarray | None = None, frame: str = DEFAULT_FRAME) -> np.ndarray:
    """6 x nv geometric Jacobian of `frame`'s origin: rows [linear; angular], world frame."""
    bid = _body(robot, frame)
    data = _posed(robot, q)
    jacp = np.zeros((3, robot.model.nv))
    jacr = np.zeros((3, robot.model.nv))
    mujoco.mj_jacBody(robot.model, data, jacp, jacr, bid)
    return np.vstack([jacp, jacr])


@dataclass(frozen=True)
class IKResult:
    q: np.ndarray
    converged: bool
    iterations: int  # Jacobian updates taken
    pos_error: float  # m
    rot_error: float  # rad


def _limits(robot: Robot) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Lower/upper joint limits, and a mask of revolute joints whose range covers [-pi, pi]."""
    m = robot.model
    lo = np.where(m.jnt_limited, m.jnt_range[:, 0], -np.inf)
    hi = np.where(m.jnt_limited, m.jnt_range[:, 1], np.inf)
    hinge = m.jnt_type == int(mujoco.mjtJoint.mjJNT_HINGE)
    return lo, hi, hinge & (lo <= -np.pi) & (hi >= np.pi)


def ik(
    robot: Robot,
    target: np.ndarray,
    q0: np.ndarray | None = None,
    frame: str = DEFAULT_FRAME,
    *,
    max_iters: int = 50,
    pos_tol: float = 1e-6,
    rot_tol: float = 1e-6,
    damping: float = 1e-4,
    error_damping: float = 0.1,
    max_step: float = 1.0,
    stall_window: int = 3,
    stall_ratio: float = 0.8,
    seed: int = 0,
) -> IKResult:
    """Damped least squares, dq = J^T (J J^T + lam^2 I)^-1 e, kept within joint limits.

    - Damping grows with the error, lam^2 = damping^2 + (error_damping * |e|)^2: robust far
      from the target and near singularities, close to Gauss-Newton (fast) near the solution.
    - Each update is scaled so no joint moves more than `max_step` rad.
    - Revolute joints whose range covers [-pi, pi] are wrapped into it instead of clipped.
    - If `stall_window` updates fail to shrink the error below `stall_ratio` x its earlier
      value, the solve is stuck in a local minimum: it restarts from a random configuration
      within the limits, drawn from a generator seeded with `seed` (results are deterministic).

    `max_iters` bounds the total number of updates, counting each restart as one. Starts from
    `q0` (default: the robot's current `q`).
    """
    m = robot.model
    if m.nq != m.nv:
        raise ValueError(f"{robot.name}: IK supports hinge/slide joints only (nq == nv)")
    lo, hi, wrap = _limits(robot)
    sample_lo = np.where(np.isfinite(lo), lo, -np.pi)
    sample_hi = np.where(np.isfinite(hi), hi, np.pi)
    rng = np.random.Generator(np.random.PCG64(seed))
    q = np.array(robot.q if q0 is None else q0, dtype=np.float64)
    history: list[float] = []
    for it in range(max_iters + 1):
        e = se3.error(fk(robot, q, frame), target)
        pe, re = float(np.linalg.norm(e[:3])), float(np.linalg.norm(e[3:]))
        if pe < pos_tol and re < rot_tol:
            return IKResult(q, True, it, pe, re)
        if it == max_iters:
            break
        err = float(np.linalg.norm(e))
        history.append(err)
        if len(history) > stall_window and err > stall_ratio * history[-1 - stall_window]:
            q = np.clip(rng.uniform(sample_lo, sample_hi), lo, hi)
            history = []
            continue
        J = jacobian(robot, q, frame)
        lam2 = damping**2 + (error_damping * err) ** 2
        dq = J.T @ np.linalg.solve(J @ J.T + lam2 * np.eye(6), e)
        biggest = float(np.abs(dq).max())
        if biggest > max_step:
            dq *= max_step / biggest
        q = q + dq
        q[wrap] = np.mod(q[wrap] + np.pi, 2 * np.pi) - np.pi
        q = np.clip(q, lo, hi)
    return IKResult(q, False, max_iters, pe, re)
