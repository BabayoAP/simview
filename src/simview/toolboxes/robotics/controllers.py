"""Robot controllers (RB-07): joint PID / impedance, differential IK, operational space.

Each controller is a small object you call from a `@scene.controller` function:

- `JointPID.step(q_des)` and `OperationalSpace.step(target)` return joint forces: set them as
  the robot's input (`robot.u = tau`) on a torque-driven robot (no servos).
- `DifferentialIK.step(target)` returns joint position targets for a position-servo robot:
  `robot.set_targets(dict(zip(joints, q)))`, or feed them to a `JointPID`.
"""

from __future__ import annotations

import numpy as np

from simview.physics.mujoco_world import Robot
from simview.toolboxes.robotics import se3
from simview.toolboxes.robotics.dynamics import bias_forces, mass_matrix
from simview.toolboxes.robotics.kinematics import fk, jacobian


def _gains(value: float | np.ndarray, n: int) -> np.ndarray:
    return np.broadcast_to(np.asarray(value, dtype=np.float64), (n,)).copy()


class JointPID:
    """tau = kp e + ki int(e) + kd (qd_des - qd) [+ gravity and Coriolis compensation].

    With `ki=0` this is a joint impedance (spring-damper) controller. The integral is clamped
    to +-`i_limit` (anti-windup). Call `step` once per controller period `dt`.
    """

    def __init__(
        self,
        robot: Robot,
        kp: float | np.ndarray,
        kd: float | np.ndarray,
        ki: float | np.ndarray = 0.0,
        *,
        i_limit: float | np.ndarray = np.inf,
        compensate: bool = True,
    ) -> None:
        n = robot.nv
        if robot.nq != n:
            raise ValueError(f"{robot.name}: joint control needs hinge/slide joints (nq == nv)")
        self.robot = robot
        self.kp, self.kd, self.ki = _gains(kp, n), _gains(kd, n), _gains(ki, n)
        self.i_limit = _gains(i_limit, n)
        self.compensate = compensate
        self.integral = np.zeros(n)

    def reset(self) -> None:
        self.integral[:] = 0.0

    def step(
        self, q_des: np.ndarray, qd_des: np.ndarray | None = None, dt: float = 0.0
    ) -> np.ndarray:
        r = self.robot
        e = np.asarray(q_des, dtype=np.float64) - r.q
        ed = (np.zeros(r.nv) if qd_des is None else np.asarray(qd_des)) - r.qd
        self.integral = np.clip(self.integral + e * dt, -self.i_limit, self.i_limit)
        tau = self.kp * e + self.ki * self.integral + self.kd * ed
        if self.compensate:
            tau = tau + bias_forces(r)
        return tau


class DifferentialIK:
    """Task-space control by joint position targets: q_cmd <- q_cmd + dq, with
    dq = J^T (J J^T + damping^2 I)^-1 (gain * pose_error), clipped to `max_step` rad per joint
    and to the joint limits. One damped-least-squares step per call.

    Steps integrate from the previous command, not the measured joints: a servo always lags its
    target, and stepping from the measured q would make the arm creep (D-030). The first call
    (or one after `reset()`) starts from the robot's current q.
    """

    def __init__(
        self,
        robot: Robot,
        frame: str | None = None,
        *,
        gain: float = 1.0,
        damping: float = 0.05,
        max_step: float = 0.05,
        position_only: bool = False,
    ) -> None:
        if robot.nq != robot.nv:
            raise ValueError(f"{robot.name}: differential IK needs hinge/slide joints")
        self.robot, self.frame = robot, frame
        self.gain, self.damping, self.max_step = gain, damping, max_step
        self.position_only = position_only
        self.q_cmd: np.ndarray | None = None

    def reset(self) -> None:
        self.q_cmd = None

    def error(self, target: np.ndarray, q: np.ndarray | None = None) -> np.ndarray:
        e = se3.error(fk(self.robot, q, self.frame), target)
        return e[:3] if self.position_only else e

    def step(self, target: np.ndarray, q: np.ndarray | None = None) -> np.ndarray:
        """Joint position targets one step closer to `target` (a 4x4 pose, or a 3-vector
        position with `position_only=True`), from `q` (default: the previous command)."""
        r = self.robot
        if q is None:
            q = r.q.copy() if self.q_cmd is None else self.q_cmd
        q = np.asarray(q, dtype=np.float64)
        if self.position_only and np.shape(target) == (3,):
            target = se3.make(np.eye(3), np.asarray(target))
        J = jacobian(r, q, self.frame)
        if self.position_only:
            J = J[:3]
        e = self.gain * self.error(target, q)
        dq = J.T @ np.linalg.solve(J @ J.T + self.damping**2 * np.eye(len(e)), e)
        biggest = float(np.abs(dq).max(initial=0.0))
        if biggest > self.max_step:
            dq *= self.max_step / biggest
        lim = r.joint_limits()
        self.q_cmd = np.clip(q + dq, lim[:, 0], lim[:, 1])
        return self.q_cmd.copy()


class OperationalSpace:
    """Operational-space (task-space impedance) control:

        tau = J^T Lambda (kp e - kd J qd) + bias + N^T (kp_null (q_null - q) - kd_null qd)

    with Lambda = (J M^-1 J^T)^-1, and N the dynamically consistent null-space projector,
    which keeps a redundant arm (e.g. a 7-joint Panda) near `q_null` without disturbing the
    task. `e` is the 6-D pose error to `target` (position and orientation).
    """

    def __init__(
        self,
        robot: Robot,
        frame: str | None = None,
        *,
        kp: float | np.ndarray = 400.0,
        kd: float | np.ndarray | None = None,
        kp_null: float = 10.0,
        kd_null: float | None = None,
        q_null: np.ndarray | None = None,
    ) -> None:
        if robot.nq != robot.nv:
            raise ValueError(f"{robot.name}: operational-space control needs hinge/slide joints")
        self.robot, self.frame = robot, frame
        self.kp = _gains(kp, 6)
        self.kd = 2 * np.sqrt(self.kp) if kd is None else _gains(kd, 6)  # critically damped
        self.kp_null = kp_null
        self.kd_null = 2 * np.sqrt(kp_null) if kd_null is None else kd_null
        self.q_null = robot.q.copy() if q_null is None else np.asarray(q_null, dtype=np.float64)

    def step(self, target: np.ndarray) -> np.ndarray:
        r = self.robot
        M = mass_matrix(r)
        Minv = np.linalg.inv(M)
        J = jacobian(r, None, self.frame)
        e = se3.error(fk(r, None, self.frame), target)
        Lam = np.linalg.pinv(J @ Minv @ J.T, rcond=1e-6)
        f = Lam @ (self.kp * e - self.kd * (J @ r.qd))
        tau = J.T @ f + bias_forces(r)
        Jbar = Minv @ J.T @ Lam  # dynamically consistent pseudo-inverse
        N = np.eye(r.nv) - J.T @ Jbar.T
        tau_null = self.kp_null * (self.q_null - r.q) - self.kd_null * r.qd
        return tau + N @ (M @ tau_null)
