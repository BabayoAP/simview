"""One shared MuJoCo world per scene (RB-01): robots, objects, and static geometry in one model.

The world is rebuilt from its items whenever one is added (scenes are small, so compiling is
cheap), and stepped once per tick by the scheduler. Each member entity (a robot or a free
object) owns its slice of the state: its `x` is copied into MuJoCo before each step and read
back after, so code that edits `x` takes effect on the next tick (D-019).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import mujoco
import numpy as np

from simview.core.entity import Entity

if TYPE_CHECKING:
    from simview.physics.mujoco_world import Robot

Vec3 = Sequence[float]
Quat = Sequence[float]  # w, x, y, z

GEOM_TYPES = {
    "box": mujoco.mjtGeom.mjGEOM_BOX,
    "sphere": mujoco.mjtGeom.mjGEOM_SPHERE,
    "cylinder": mujoco.mjtGeom.mjGEOM_CYLINDER,
    "capsule": mujoco.mjtGeom.mjGEOM_CAPSULE,
}
INTEGRATORS = {
    "euler": mujoco.mjtIntegrator.mjINT_EULER,
    "rk4": mujoco.mjtIntegrator.mjINT_RK4,
    "implicit": mujoco.mjtIntegrator.mjINT_IMPLICIT,
    "implicitfast": mujoco.mjtIntegrator.mjINT_IMPLICITFAST,
}
CONES = {"pyramidal": mujoco.mjtCone.mjCONE_PYRAMIDAL, "elliptic": mujoco.mjtCone.mjCONE_ELLIPTIC}
DEFAULT_FRICTION = (1.0, 0.005, 0.0001)  # MuJoCo's sliding, torsional, rolling defaults


def _half_size(shape: str, size: Sequence[float]) -> list[float]:
    """Full sizes in metres (RB-02) -> MuJoCo's half sizes.

    box: (x, y, z) edge lengths; sphere: (diameter,); cylinder and capsule: (diameter, length),
    where a capsule's length is between the centers of its end caps.
    """
    s = [float(v) for v in size]
    expected = {"box": 3, "sphere": 1, "cylinder": 2, "capsule": 2}[shape]
    if len(s) != expected or min(s) <= 0:
        raise ValueError(f"{shape} size must be {expected} positive full lengths in metres")
    return [v / 2 for v in s]


def _friction(friction: float | Sequence[float] | None) -> list[float]:
    if friction is None:
        return list(DEFAULT_FRICTION)
    if isinstance(friction, (int, float)):
        return [float(friction), *DEFAULT_FRICTION[1:]]
    return [float(v) for v in friction]


@dataclass
class Shape:
    """A primitive shape: the geometry of a free `Body` or of a static part of the world."""

    name: str
    shape: str
    size: list[float]
    pos: list[float]
    quat: list[float]
    friction: list[float]
    rgba: list[float] | None = None
    mass: float | None = None  # None: static
    collides: bool = True  # False: drawn and seen by rays, but never in contact (road paint)

    def add_to(self, spec: mujoco.MjSpec, parent: mujoco.MjsBody | None = None) -> None:
        if parent is not None:  # a proxy's solid, placed in its mocap body's frame
            geom_pos, geom_quat = self.pos, self.quat
        elif self.mass is None:
            parent, geom_pos, geom_quat = spec.worldbody, self.pos, self.quat
        else:
            parent = spec.worldbody.add_body(name=self.name, pos=self.pos, quat=self.quat)
            parent.add_freejoint(name=self.name)
            geom_pos, geom_quat = [0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]
        geom = parent.add_geom(
            name=self.name,
            type=GEOM_TYPES[self.shape],
            size=self.size + [0.0] * (3 - len(self.size)),
            pos=geom_pos,
            quat=geom_quat,
            friction=self.friction,
        )
        if self.mass is not None:
            geom.mass = self.mass
        if self.rgba is not None:
            geom.rgba = self.rgba
        if not self.collides:
            geom.contype = geom.conaffinity = 0


class Body(Entity):
    """A free rigid object in the world (RB-02). State: position, orientation, velocities."""

    state_names = (
        *("x", "y", "z", "qw", "qx", "qy", "qz"),
        *("vx", "vy", "vz", "wx", "wy", "wz"),
    )
    state_units = {
        **dict.fromkeys(("x", "y", "z"), "m"),
        **dict.fromkeys(("vx", "vy", "vz"), "m/s"),
        **dict.fromkeys(("wx", "wy", "wz"), "rad/s"),
    }

    def __init__(self, shape: Shape) -> None:
        super().__init__([*shape.pos, *shape.quat, *[0.0] * 6], name=shape.name)
        self.shape = shape
        self.world: World | None = None
        self.qidx = np.zeros(0, dtype=np.int64)
        self.vidx = np.zeros(0, dtype=np.int64)

    @property
    def pos(self) -> np.ndarray:
        return self.x[:3]

    @property
    def quat(self) -> np.ndarray:
        """Orientation quaternion (w, x, y, z)."""
        return self.x[3:7]

    def position(self) -> np.ndarray:
        return self.x[:3].copy()

    def bind(self, model: mujoco.MjModel) -> None:
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, self.name)
        self.qidx = np.arange(model.jnt_qposadr[jid], model.jnt_qposadr[jid] + 7)
        self.vidx = np.arange(model.jnt_dofadr[jid], model.jnt_dofadr[jid] + 6)

    def validate(self) -> None:
        pass

    def advance(self, t: float, dt: float) -> None:
        pass  # the world steps every member together

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        raise TypeError(f"{self.name} is stepped by MuJoCo, not integrated")


@dataclass
class World:
    """The scene's MuJoCo world. Items are compiled in the order they were added."""

    gravity: tuple[float, float, float] = (0.0, 0.0, -9.81)
    # World options belong to the world, not to robot files: a file's own <option> is not used
    # once it is attached. "implicitfast" is MuJoCo's recommendation for servo-driven robots.
    integrator: str = "implicitfast"
    # Friction cone and impratio: "elliptic" with impratio 10 (MuJoCo's advice for grasping,
    # and what Menagerie grippers ask for) lets objects stick in a grip without slipping.
    cone: str = "pyramidal"
    impratio: float = 1.0
    statics: list[Shape] = field(default_factory=list)
    members: list[Entity] = field(default_factory=list)
    ground: dict[str, object] | None = None
    # D-090: custom-model entities with a solid that follows their pose (mocap bodies)
    proxies: list[tuple[Entity, Shape]] = field(default_factory=list)
    _mocap: list[tuple[Entity, int]] = field(default_factory=list)
    t: float = 0.0
    _model: mujoco.MjModel | None = None
    _data: mujoco.MjData | None = None
    _on_compile: list[Callable[[mujoco.MjModel], None]] = field(default_factory=list)

    # -- building -------------------------------------------------------------------------
    def _names(self) -> set[str]:
        return (
            {s.name for s in self.statics}
            | {m.name for m in self.members}
            | {e.name for e, _ in self.proxies}
        )

    def _check_name(self, name: str) -> None:
        if not name or "/" in name or "." in name:
            raise ValueError(f"name {name!r} must be non-empty without '/' or '.'")
        if name in self._names():
            raise ValueError(f"the world already has an item named {name!r}")

    def add_ground(self, friction: float | Sequence[float] | None = None) -> None:
        if self.ground is not None:
            raise ValueError("the world already has a ground")
        self.ground = {"friction": _friction(friction)}
        self.compile()

    def add_shape(self, shape: Shape) -> Body | None:
        self._check_name(shape.name)
        if shape.mass is None:
            self.statics.append(shape)
            self.compile()
            return None
        body = Body(shape)
        self.adopt(body)
        return body

    def add_proxy(self, entity: Entity, shape: Shape) -> None:
        """A kinematic solid that follows a custom-model entity's `pose()` (D-090)."""
        self._check_name(entity.name)
        self.proxies.append((entity, shape))
        self.compile()

    def proxy_body(self, entity: Entity) -> int:
        """The MuJoCo body id of an entity's proxy, or -1."""
        for e, bid in self._mocap:
            if e is entity:
                return bid
        return -1

    def adopt(self, member: Entity) -> None:
        """Add a robot or a free body; its `x0` keeps any placement it already has."""
        self._check_name(member.name)
        self.members.append(member)
        member.world = self  # type: ignore[attr-defined]
        self.compile()

    def spec(self) -> mujoco.MjSpec:
        from simview.physics.mujoco_world import Robot

        spec = mujoco.MjSpec()
        spec.option.gravity = list(self.gravity)
        spec.option.integrator = INTEGRATORS[self.integrator]
        spec.option.cone = CONES[self.cone]
        spec.option.impratio = self.impratio
        if self.ground is not None:
            spec.worldbody.add_geom(
                name="ground",
                type=mujoco.mjtGeom.mjGEOM_PLANE,
                size=[0.0, 0.0, 1.0],
                friction=self.ground["friction"],
            )
        for shape in self.statics:
            shape.add_to(spec)
        for m in self.members:
            if isinstance(m, Robot):
                m.attach_to(spec)
            elif isinstance(m, Body):
                m.shape.add_to(spec)
        for e, shape in self.proxies:
            body = spec.worldbody.add_body(name=e.name, mocap=True)
            shape.add_to(spec, parent=body)
        return spec

    def compile(self) -> mujoco.MjModel:
        model = self.spec().compile()
        self._model, self._data = model, mujoco.MjData(model)
        for m in self.members:
            m.bind(model)  # type: ignore[attr-defined]
        self._mocap = [
            (e, mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, e.name)) for e, _ in self.proxies
        ]
        for fn in self._on_compile:
            fn(model)
        return model

    @property
    def model(self) -> mujoco.MjModel:
        return self._model if self._model is not None else self.compile()

    @property
    def data(self) -> mujoco.MjData:
        if self._data is None:
            self.compile()
        assert self._data is not None
        return self._data

    # -- running --------------------------------------------------------------------------
    def reset(self) -> None:
        """Start of a run: MuJoCo state from the members' `x` (already reset to `x0`)."""
        mujoco.mj_resetData(self.model, self.data)
        self.t = 0.0
        self.load_state()
        mujoco.mj_forward(self.model, self.data)

    def load_state(self) -> None:
        m, d = self.model, self.data
        for e in self.members:
            nq = len(e.qidx)  # type: ignore[attr-defined]
            d.qpos[e.qidx] = e.x[:nq]  # type: ignore[attr-defined]
            d.qvel[e.vidx] = e.x[nq:]  # type: ignore[attr-defined]
        for e, bid in self._mocap:
            pose = e.pose()
            mid = int(m.body_mocapid[bid])
            d.mocap_pos[mid] = pose[:3, 3]
            mujoco.mju_mat2Quat(d.mocap_quat[mid], pose[:3, :3].ravel())

    def kinematics(self) -> None:
        """Bring body and geom poses up to the current state (before ray casts)."""
        self.load_state()
        mujoco.mj_kinematics(self.model, self.data)

    def step(self, t: float, dt: float) -> None:
        from simview.physics.mujoco_world import Robot

        m, d = self.model, self.data
        m.opt.timestep = dt
        self.t = t
        self.load_state()
        d.qfrc_applied[:] = 0.0
        for r in self.members:
            if isinstance(r, Robot):
                r.apply_inputs(d, t)
        mujoco.mj_step(m, d)
        for e in self.members:
            e.x = np.concatenate([d.qpos[e.qidx], d.qvel[e.vidx]])  # type: ignore[attr-defined]
        self.t = t + dt

    def robots(self) -> list[Robot]:
        from simview.physics.mujoco_world import Robot

        return [m for m in self.members if isinstance(m, Robot)]
