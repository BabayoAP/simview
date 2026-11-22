"""Forward kinematics, geometric Jacobian, and damped-least-squares IK (TB-ROBOT).

All of them work on a scratch `MjData`, so they never disturb the simulated state. The rest of
the world (other robots, a free base) is posed as it currently is; only the robot's own joints
take the `q` you pass. Frames are the robot's body or site names, bare (`"tool0"`) or full
(`"ur5/tool0"`); the default is the robot's `default_frame`. Poses are 4x4 world transforms.
"""

from __future__ import annotations

from dataclasses import dataclass

import mujoco
import numpy as np

from simview.physics.mujoco_world import Robot
from simview.toolboxes.robotics import se3


def resolve_frame(robot: Robot, frame: str | None) -> tuple[mujoco.mjtObj, int]:
    """(object type, id) of a body or site of `robot` (cached per compiled model)."""
    model = robot.model
    cache = getattr(robot, "_frames", None)
    if cache is None or cache[0] is not model:
        cache = (model, {})
        robot._frames = cache  # noqa: SLF001 - private to the robotics toolbox
    hit = cache[1].get(frame)
    if hit is not None:
        return hit
    full = robot.full(frame or robot.default_frame)
    for obj in (mujoco.mjtObj.mjOBJ_BODY, mujoco.mjtObj.mjOBJ_SITE):
        i = mujoco.mj_name2id(model, obj, full)
        if i >= 0:
            cache[1][frame] = (obj, i)
            return obj, i
    raise KeyError(f"{robot.name} has no frame (body or site) named {frame!r}")


def scratch(robot: Robot) -> mujoco.MjData:
    """A scratch MjData for the robot's current world model (rebuilt if the world recompiled)."""
    cached = getattr(robot, "_scratch", None)
    if cached is None or cached[0] is not robot.model:
        cached = (robot.model, mujoco.MjData(robot.model))
        robot._scratch = cached  # noqa: SLF001 - private to the robotics toolbox
    return cached[1]


def posed(
    robot: Robot,
    q: np.ndarray | None = None,
    qd: np.ndarray | None = None,
    *,
    com: bool = True,
) -> mujoco.MjData:
    """Scratch data with the world's current state, the robot at `q` (and `qd`), kinematics done
    (and the centre-of-mass quantities Jacobians and dynamics need, unless `com=False`)."""
    data = scratch(robot)
    data.qpos[:] = robot.data.qpos
    data.qvel[:] = 0.0
    for member in robot.world.members if robot.world is not None else []:
        nq = len(member.qidx)  # type: ignore[attr-defined]
        data.qpos[member.qidx] = member.x[:nq]  # type: ignore[attr-defined]
    data.qpos[robot.qidx] = robot.q if q is None else np.asarray(q, dtype=np.float64)
    if qd is not None:
        data.qvel[robot.vidx] = qd
    mujoco.mj_kinematics(robot.model, data)
    if com:
        mujoco.mj_comPos(robot.model, data)
    return data


def fk(robot: Robot, q: np.ndarray | None = None, frame: str | None = None) -> np.ndarray:
    """World pose of `frame` at joint positions `q` (default: the robot's current `q`)."""
    obj, i = resolve_frame(robot, frame)
    data = posed(robot, q, com=False)  # poses only: no centre-of-mass pass (NF-02)
    if obj == mujoco.mjtObj.mjOBJ_BODY:
        return se3.make(data.xmat[i].reshape(3, 3), data.xpos[i])
    return se3.make(data.site_xmat[i].reshape(3, 3), data.site_xpos[i])


def jacobian(robot: Robot, q: np.ndarray | None = None, frame: str | None = None) -> np.ndarray:
    """6 x nv geometric Jacobian of `frame`'s origin over the robot's own joints:
    rows [linear; angular], world frame."""
    obj, i = resolve_frame(robot, frame)
    data = posed(robot, q)
    jacp = np.zeros((3, robot.model.nv))
    jacr = np.zeros((3, robot.model.nv))
    if obj == mujoco.mjtObj.mjOBJ_BODY:
        mujoco.mj_jacBody(robot.model, data, jacp, jacr, i)
    else:
        mujoco.mj_jacSite(robot.model, data, jacp, jacr, i)
    return np.vstack([jacp, jacr])[:, robot.vidx]


@dataclass(frozen=True)
class IKResult:
    q: np.ndarray
    converged: bool
    iterations: int  # Jacobian updates taken
    pos_error: float  # m
    rot_error: float  # rad


def _limits(robot: Robot) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Lower/upper joint limits, and a mask of revolute joints whose range covers [-pi, pi]."""
    lim = robot.joint_limits()
    lo, hi = lim[:, 0], lim[:, 1]
    hinge = robot.model.jnt_type[robot.joint_ids] == int(mujoco.mjtJoint.mjJNT_HINGE)
    return lo, hi, hinge & (lo <= -np.pi) & (hi >= np.pi)


def ik(
    robot: Robot,
    target: np.ndarray,
    q0: np.ndarray | None = None,
    frame: str | None = None,
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
    if robot.nq != robot.nv:
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
