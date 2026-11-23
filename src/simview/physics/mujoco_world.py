"""MuJoCo-backed robots (SE-03) in the scene's shared world (RB-01, RB-03..RB-05)."""

from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import mujoco
import numpy as np

from simview.core.entity import Entity
from simview.physics.urdf import resolve, urdf_to_mujoco_xml

if TYPE_CHECKING:
    from simview.physics.world import World
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
_HINGE_OR_SLIDE = (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE))
ServoKind = Literal["position", "velocity"]
DEFAULT_KP = 1000.0  # N·m/rad for generated position servos
DEFAULT_KV = 100.0  # N·m·s/rad


def _names(prefix: str, n: int) -> list[str]:
    return [prefix] if n == 1 else [f"{prefix}{i}" for i in range(n)]


def _per_joint(value: float | Mapping[str, float], joint: str, default: float) -> float:
    if isinstance(value, Mapping):
        return float(value.get(joint, default))
    return float(value)


class Robot(Entity):
    """A robot from a URDF or MJCF file (or an MJCF string) as one entity.

    - State `x` is `[qpos, qvel]` of the robot's own joints, logged as `<robot>.<joint>.q` /
      `.v` (multi-DOF joints: `.q0..`, `.v0..`).
    - Input `u`: one value per actuator if the robot has actuators (`ctrl`), otherwise one joint
      force per degree of freedom (`qfrc_applied`). URDF robots get position or velocity servos
      with `servos=` (RB-05).
    - Placement: `pos`/`quat` (w, x, y, z) place the base; `mount=("arm", "tool0")` attaches this
      robot to another robot's body or site instead (RB-03).
    - In the world, names are `<robot>/<name>`; methods take bare names (RB-04).

    A robot made on its own (`Robot("ur5")`) gets a private world; `scene.add_robot` puts it
    in the scene's shared world.
    """

    def __init__(
        self,
        source: str | Path | None = None,
        *,
        name: str | None = None,
        mjcf: str | None = None,
        pos: Sequence[float] = (0.0, 0.0, 0.0),
        quat: Sequence[float] = (1.0, 0.0, 0.0, 0.0),
        mount: tuple[str, str] | None = None,
        servos: ServoKind | None = None,
        kp: float | Mapping[str, float] = DEFAULT_KP,
        kv: float | Mapping[str, float] = DEFAULT_KV,
        gravity_compensation: bool = False,
        frame: str | None = None,
        world: World | None = None,
    ) -> None:
        if (source is None) == (mjcf is None):
            raise ValueError("give a robot file or name, or an MJCF string with mjcf=, not both")
        self.path = resolve(source) if source is not None else None
        self.mjcf = mjcf
        self.placement = ([float(v) for v in pos], [float(v) for v in quat])
        self.mount = mount
        self.servos = servos
        self.kp, self.kv = kp, kv
        self.gravity_compensation = gravity_compensation

        alone = self._child_spec().compile()
        default_name = mujoco.mj_id2name(alone, mujoco.mjtObj.mjOBJ_MODEL, 0) or (
            self.path.stem if self.path else "robot"
        )
        self.joint_names: tuple[str, ...] = tuple(
            alone.joint(j).name or f"joint{j}" for j in range(alone.njnt)
        )
        q_names: list[str] = []
        v_names: list[str] = []
        for j, jname in enumerate(self.joint_names):
            q_names += _names(f"{jname}.q", _QPOS_SIZE[int(alone.jnt_type[j])])
            v_names += _names(f"{jname}.v", _QVEL_SIZE[int(alone.jnt_type[j])])
        self.state_names = (*q_names, *v_names)
        hinge, slide = int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE)
        units: dict[str, str] = {}
        for j, jname in enumerate(self.joint_names):
            kind = int(alone.jnt_type[j])
            if kind == hinge:
                units |= {f"{jname}.q": "rad", f"{jname}.v": "rad/s"}
            elif kind == slide:
                units |= {f"{jname}.q": "m", f"{jname}.v": "m/s"}
        self.state_units = units
        self.actuator_names: tuple[str, ...] = tuple(
            alone.actuator(a).name or f"actuator{a}" for a in range(alone.nu)
        )
        self._nq = int(alone.nq)
        super().__init__(
            np.concatenate([alone.qpos0, np.zeros(alone.nv)]), name=name or default_name
        )
        self.u = np.zeros(alone.nu if alone.nu else alone.nv)
        self._ramps: dict[int, tuple[float, float, float, float]] = {}
        self._placed = False
        self.default_frame = frame or self._guess_frame(alone)
        self.world: World | None = None
        if world is None:
            from simview.physics.world import World

            world = World()
        world.adopt(self)

    # -- building the MuJoCo model ----------------------------------------------------------
    def _child_spec(self) -> mujoco.MjSpec:
        """A fresh spec of this robot alone, with generated servos and gravity compensation."""
        if self.mjcf is not None:
            spec = mujoco.MjSpec.from_string(self.mjcf)
        elif self.path is not None and self.path.suffix.lower() == ".urdf":
            spec = mujoco.MjSpec.from_string(urdf_to_mujoco_xml(self.path))
        else:
            spec = mujoco.MjSpec.from_file(str(self.path))
        # Unnamed joints and actuators get stable names so they can be found in a shared world.
        for k, joint in enumerate(spec.joints):
            joint.name = joint.name or f"joint{k}"
        for k, act in enumerate(spec.actuators):
            act.name = act.name or f"actuator{k}"
        # Adjacent links never collide (the URDF/ROS convention). MuJoCo already skips
        # parent-child pairs, except when the parent is welded to the world (D-029).
        for body in spec.bodies[1:]:
            parent = body.parent
            if parent is not None and parent.name and parent.name != "world":
                spec.add_exclude(bodyname1=parent.name, bodyname2=body.name)
        if self.gravity_compensation:
            for body in spec.bodies[1:]:
                body.gravcomp = 1.0
        if self.servos is not None:
            driven = {a.target for a in spec.actuators}
            for joint in spec.joints:
                if joint.type not in _HINGE_OR_SLIDE or joint.name in driven or not joint.name:
                    continue
                act = spec.add_actuator(
                    name=joint.name, target=joint.name, trntype=mujoco.mjtTrn.mjTRN_JOINT
                )
                kp = _per_joint(self.kp, joint.name, DEFAULT_KP)
                kv = _per_joint(self.kv, joint.name, DEFAULT_KV)
                if self.servos == "position":
                    act.set_to_position(kp=kp, kv=kv)
                    if joint.range[1] > joint.range[0]:
                        act.ctrlrange = list(joint.range)
                        act.ctrllimited = mujoco.mjtLimited.mjLIMITED_TRUE
                else:
                    act.set_to_velocity(kv=kv)
        return spec

    @staticmethod
    def _guess_frame(model: mujoco.MjModel) -> str:
        for candidate in ("tool0", "attachment_site", "pinch", "hand", "ee", "end_effector"):
            if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, candidate) >= 0:
                return candidate
            if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, candidate) >= 0:
                return candidate
        return model.body(model.nbody - 1).name

    def attach_to(self, spec: mujoco.MjSpec) -> None:
        """Attach this robot to the world spec (called by `World.spec`)."""
        child = self._child_spec()
        pos, quat = self.placement
        if self.mount is None:
            frame = spec.worldbody.add_frame(pos=pos, quat=quat)
        else:
            owner, where = self.mount
            full = f"{owner}/{where}"
            body = spec.body(full)
            if body is not None:
                frame = body.add_frame(pos=pos, quat=quat)
            else:
                site = spec.site(full)
                if site is None:
                    raise KeyError(f"cannot mount {self.name}: no body or site named {full!r}")
                frame = site.parent.add_frame(pos=list(site.pos), quat=list(site.quat))
        spec.attach(child, prefix=f"{self.name}/", frame=frame)

    def bind(self, model: mujoco.MjModel) -> None:
        """Find this robot's joints, dofs, and actuators in the compiled world."""
        prefix = f"{self.name}/"
        self.joint_ids = np.array(
            [j for j in range(model.njnt) if model.joint(j).name.startswith(prefix)], dtype=int
        )
        self.qidx = np.concatenate(
            [
                np.arange(model.jnt_qposadr[j], model.jnt_qposadr[j] + _QPOS_SIZE[int(t)])
                for j, t in zip(self.joint_ids, model.jnt_type[self.joint_ids], strict=True)
            ]
            or [np.zeros(0, dtype=int)]
        )
        self.vidx = np.concatenate(
            [
                np.arange(model.jnt_dofadr[j], model.jnt_dofadr[j] + _QVEL_SIZE[int(t)])
                for j, t in zip(self.joint_ids, model.jnt_type[self.joint_ids], strict=True)
            ]
            or [np.zeros(0, dtype=int)]
        )
        self.act_ids = np.array(
            [a for a in range(model.nu) if model.actuator(a).name.startswith(prefix)], dtype=int
        )
        if not self._placed:
            # Placement can move a free base: take the compiled initial pose once.
            self.x0[: self._nq] = model.qpos0[self.qidx]
            self.x[: self._nq] = self.x0[: self._nq]
            self._placed = True

    # -- state ------------------------------------------------------------------------------
    @property
    def model(self) -> mujoco.MjModel:
        """The compiled world this robot lives in."""
        assert self.world is not None
        return self.world.model

    @property
    def data(self) -> mujoco.MjData:
        assert self.world is not None
        return self.world.data

    @property
    def nq(self) -> int:
        return self._nq

    @property
    def nv(self) -> int:
        return len(self.x) - self._nq

    @property
    def q(self) -> np.ndarray:
        """Joint positions (a view into `x`)."""
        return self.x[: self._nq]

    @property
    def qd(self) -> np.ndarray:
        """Joint velocities (a view into `x`)."""
        return self.x[self._nq :]

    def set_q(self, q: np.ndarray) -> None:
        self.x[: self._nq] = q

    def full(self, name: str) -> str:
        """World name of one of this robot's joints, bodies, sites, or actuators.

        A name that already contains "/" is a full world name, so a frame of a mounted tool
        (e.g. "grip/pinch") can be used with the arm's kinematics and controllers."""
        return name if "/" in name else f"{self.name}/{name}"

    def joint_limits(self) -> np.ndarray:
        """(n_joints, 2) ranges; unlimited joints are (-inf, inf)."""
        m = self.model
        lim = m.jnt_range[self.joint_ids].copy()
        lim[~m.jnt_limited[self.joint_ids].astype(bool)] = (-np.inf, np.inf)
        return lim

    # -- driving (RB-05) --------------------------------------------------------------------
    def _actuator_for(self, joint: str) -> int:
        """Index into `u` of the servo driving `joint` (cached per compiled model)."""
        m = self.model
        cache = self.__dict__.get("_actuator_cache")
        if cache is None or cache[0] is not m:
            cache = (m, {})
            self.__dict__["_actuator_cache"] = cache
        hit = cache[1].get(joint)
        if hit is not None:
            return hit
        jid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, self.full(joint))
        if jid < 0:
            raise KeyError(f"{self.name} has no joint named {joint!r}")
        for k, a in enumerate(self.act_ids):
            if m.actuator_trntype[a] == mujoco.mjtTrn.mjTRN_JOINT and m.actuator_trnid[a, 0] == jid:
                cache[1][joint] = k
                return k
        raise KeyError(
            f'joint {joint!r} of {self.name} has no actuator: add servos="position" to '
            f'add_robot, or a <position joint="{joint}" kp="..."/> to the MJCF'
        )

    def servo_kind(self, joint: str) -> str:
        """'position', 'velocity', or 'other' for the actuator on `joint`."""
        a = self.act_ids[self._actuator_for(joint)]
        bias = self.model.actuator_biasprm[a]
        if self.model.actuator_biastype[a] == mujoco.mjtBias.mjBIAS_AFFINE and bias[1] < 0:
            return "position"
        if self.model.actuator_biastype[a] == mujoco.mjtBias.mjBIAS_AFFINE and bias[2] < 0:
            return "velocity"
        return "other"

    def set_targets(
        self,
        targets: Mapping[str, float],
        *,
        kind: ServoKind = "position",
        ramp: float | None = None,
    ) -> None:
        """Servo targets by joint name (radians or metres; rad/s for velocity servos).

        Position targets outside the joint's range stop at the limit, with a warning. With
        `ramp=seconds`, the target moves linearly from its current value over that time.
        """
        world_t = self.world.t if self.world is not None else 0.0
        for joint, value in targets.items():
            k = self._actuator_for(joint)
            have = self.servo_kind(joint)
            if have != kind:
                raise ValueError(f"{self.name}.{joint} has a {have} servo, not a {kind} servo")
            v = float(value)
            if kind == "position":
                jid = self.model.actuator_trnid[self.act_ids[k], 0]
                if self.model.jnt_limited[jid]:
                    lo, hi = self.model.jnt_range[jid]
                    if not lo <= v <= hi:
                        warnings.warn(
                            f"{self.name}.{joint} target {v:.4g} is outside [{lo:.4g}, {hi:.4g}]; "
                            "it stops at the limit",
                            stacklevel=2,
                        )
                        v = float(np.clip(v, lo, hi))
            if ramp is not None and ramp > 0:
                self._ramps[k] = (float(self.u[k]), v, world_t, world_t + ramp)
            else:
                self._ramps.pop(k, None)
                self.u[k] = v

    def set_controls(self, controls: Mapping[str, float]) -> None:
        """Raw actuator inputs by actuator name (e.g. a gripper's single actuator)."""
        for actuator, value in controls.items():
            aid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, self.full(actuator))
            hits = np.flatnonzero(self.act_ids == aid)
            if aid < 0 or len(hits) == 0:
                raise KeyError(f"{self.name} has no actuator named {actuator!r}")
            self._ramps.pop(int(hits[0]), None)
            self.u[int(hits[0])] = float(value)

    def apply_inputs(self, data: mujoco.MjData, t: float) -> None:
        """Called by the world before each step: ramps, then `u` into MuJoCo."""
        for k, (u0, u1, t0, t1) in list(self._ramps.items()):
            s = min(1.0, max(0.0, (t - t0) / (t1 - t0)))
            self.u[k] = u0 + s * (u1 - u0)
            if s >= 1.0:
                del self._ramps[k]
        if len(self.act_ids):
            data.ctrl[self.act_ids] = self.u
        else:
            data.qfrc_applied[self.vidx] += self.u

    def position(self) -> np.ndarray:
        """The default frame's position (VP-04: the trail follows the end effector)."""
        from simview.toolboxes.robotics.kinematics import fk

        return fk(self)[:3, 3].copy()

    # -- entity hooks -----------------------------------------------------------------------
    def validate(self) -> None:
        expected = len(self.act_ids) if len(self.act_ids) else self.nv
        if self.u.shape != (expected,):
            raise ValueError(f"{self.name}.u has shape {self.u.shape}, expected ({expected},)")

    def reset(self) -> None:
        super().reset()
        self._ramps.clear()

    def advance(self, t: float, dt: float) -> None:
        pass  # the world steps every member together

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        raise TypeError(f"{self.name} is MuJoCo-backed: it is stepped by MuJoCo, not integrated")

    # -- UC-3 console API (Robotics toolbox) --------------------------------------------------
    def fk(self, q: np.ndarray | None = None, frame: str | None = None) -> np.ndarray:
        from simview.toolboxes.robotics import kinematics

        return kinematics.fk(self, q, frame)

    def jacobian(self, q: np.ndarray | None = None, frame: str | None = None) -> np.ndarray:
        from simview.toolboxes.robotics import kinematics

        return kinematics.jacobian(self, q, frame)

    def ik(
        self, target: np.ndarray, q0: np.ndarray | None = None, frame: str | None = None
    ) -> IKResult:
        """Damped-least-squares IK; returns an `IKResult`. See `sv.robotics.ik` for options."""
        from simview.toolboxes.robotics import kinematics

        return kinematics.ik(self, target, q0, frame)
