"""MuJoCo-backed entities (SE-03): rigid-body robots that live in the same Scene as ODE models."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import mujoco
import numpy as np

from simview.core.entity import Entity
from simview.physics.urdf import load_model, resolve

if TYPE_CHECKING:
    from simview.toolboxes.robotics.kinematics import IKResult

# Keyed by int: jnt_type holds np.int32, which doesn't hash like the enum on every platform.
_QPOS_SIZE = {
    int(mujoco.mjtJoint.mjJNT_FREE): 7,
    int(mujoco.mjtJoint.mjJNT_BALL): 4,
    int(mujoco.mjtJoint.mjJNT_SLIDE): 1,
    int(mujoco.mjtJoint.mjJNT_HINGE): 1,
}
_QVEL_SIZE = {
    int(mujoco.mjtJoint.mjJNT_FREE): 6,
    int(mujoco.mjtJoint.mjJNT_BALL): 3,
    int(mujoco.mjtJoint.mjJNT_SLIDE): 1,
    int(mujoco.mjtJoint.mjJNT_HINGE): 1,
}


def _names(prefix: str, n: int) -> list[str]:
    return [prefix] if n == 1 else [f"{prefix}{i}" for i in range(n)]


class Robot(Entity):
    """A MuJoCo model (from URDF or MJCF) as one entity.

    State `x` is `[qpos, qvel]`, named `<joint>.q` / `<joint>.v` (multi-DOF joints get
    `<joint>.q0..` / `<joint>.v0..`). Input `u` goes to the actuators (`ctrl`) if the model has
    any, otherwise it is applied directly as generalized joint forces (`qfrc_applied`).
    MuJoCo steps the model with the scene's `dt`; `integrator` is not used.
    """

    def __init__(self, path: str | Path, *, name: str | None = None) -> None:
        self.path = resolve(path)
        self.model = load_model(self.path)
        self.data = mujoco.MjData(self.model)
        m = self.model
        q_names: list[str] = []
        v_names: list[str] = []
        for j in range(m.njnt):
            jname = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or f"joint{j}"
            q_names += _names(f"{jname}.q", _QPOS_SIZE[int(m.jnt_type[j])])
            v_names += _names(f"{jname}.v", _QVEL_SIZE[int(m.jnt_type[j])])
        self.state_names = (*q_names, *v_names)
        self.joint_names = tuple(
            mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or f"joint{j}" for j in range(m.njnt)
        )
        default = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_MODEL, 0) or self.path.stem
        super().__init__(np.concatenate([m.qpos0, np.zeros(m.nv)]), name=name or default)
        self.u = np.zeros(m.nu if m.nu else m.nv)

    @property
    def nq(self) -> int:
        return int(self.model.nq)

    @property
    def q(self) -> np.ndarray:
        """Joint positions (a view into `x`)."""
        return self.x[: self.model.nq]

    @property
    def qd(self) -> np.ndarray:
        """Joint velocities (a view into `x`)."""
        return self.x[self.model.nq :]

    def set_q(self, q: np.ndarray) -> None:
        self.x[: self.model.nq] = q

    # UC-3 console API: `robot.fk(q)`, `robot.jacobian(q)`, `robot.ik(T)` (Robotics toolbox).
    def fk(self, q: np.ndarray | None = None, frame: str = "tool0") -> np.ndarray:
        from simview.toolboxes.robotics import kinematics

        return kinematics.fk(self, q, frame)

    def jacobian(self, q: np.ndarray | None = None, frame: str = "tool0") -> np.ndarray:
        from simview.toolboxes.robotics import kinematics

        return kinematics.jacobian(self, q, frame)

    def ik(
        self, target: np.ndarray, q0: np.ndarray | None = None, frame: str = "tool0"
    ) -> IKResult:
        """Damped-least-squares IK; returns an `IKResult`. See `sv.robotics.ik` for options."""
        from simview.toolboxes.robotics import kinematics

        return kinematics.ik(self, target, q0, frame)

    def validate(self) -> None:
        expected = self.model.nu if self.model.nu else self.model.nv
        if self.u.shape != (expected,):
            raise ValueError(f"{self.name}.u has shape {self.u.shape}, expected ({expected},)")

    def reset(self) -> None:
        super().reset()
        mujoco.mj_resetData(self.model, self.data)

    def advance(self, t: float, dt: float) -> None:
        m, d = self.model, self.data
        m.opt.timestep = dt
        d.qpos[:] = self.x[: m.nq]
        d.qvel[:] = self.x[m.nq :]
        if m.nu:
            d.ctrl[:] = self.u
        else:
            d.qfrc_applied[:] = self.u
        mujoco.mj_step(m, d)
        self.x = np.concatenate([d.qpos, d.qvel])

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        raise TypeError(f"{self.name} is MuJoCo-backed: it is stepped by MuJoCo, not integrated")
