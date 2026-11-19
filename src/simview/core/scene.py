"""The scene: what gets simulated (SC-04). Built the same way from a script or the GUI."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from simview.core.entity import Entity

if TYPE_CHECKING:
    import numpy as np

    from simview.core.draw import DrawList
    from simview.core.scheduler import Sim
    from simview.physics.mujoco_world import Robot, ServoKind
    from simview.physics.world import Body, World

DT_MIN = 1e-4  # 0.1 ms (SE-01)
DT_MAX = 1e-1  # 100 ms
DT_DEFAULT = 1e-3

E = TypeVar("E", bound=Entity)
LogFn = Callable[["Sim"], float]
# fn(t, state, ctx): `state` is the scene (entities by name), `ctx` the controller context.
# It may return {entity_name: u} to set those entities' inputs (RB-06, PRD §8.3).
ControllerFn = Callable[[float, "Scene", "Context"], "Mapping[str, Any] | None"]


@dataclass
class Context:
    """What a controller gets besides time and state."""

    sim: Sim
    dt: float  # the controller's own period

    @property
    def draw(self) -> DrawList:
        """Debug draws shown in the viewport (VP-07); they last one tick unless persist=True."""
        return self.sim.draw

    @property
    def rng(self) -> np.random.Generator:
        return self.sim.rng

    @property
    def tick(self) -> int:
        return self.sim.tick


@dataclass
class Target:
    """A pose the viewport's gizmo can drag (VP-10), e.g. an IK goal. Read `target.pose` (4x4)
    from a controller; a drag in the UI replaces it. Not physical and not logged."""

    name: str
    pose: np.ndarray


@dataclass
class Visual:
    """A mesh file (STL, OBJ, or GLB/glTF) shown in the viewport but not simulated (VP-01)."""

    name: str
    path: Path
    pose: np.ndarray
    scale: float
    color: str | None


@dataclass
class TrailStyle:
    """VP-04: how long (seconds of sim time) and in what color an entity's trail is drawn."""

    seconds: float
    color: str | None


@dataclass
class Controller:
    fn: ControllerFn
    rate: float | None  # Hz; None runs every tick


class Scene:
    def __init__(self, dt: float = DT_DEFAULT, seed: int = 0) -> None:
        if not DT_MIN <= dt <= DT_MAX:
            raise ValueError(f"dt must be between {DT_MIN} and {DT_MAX} s, got {dt}")
        self.dt = float(dt)
        self.seed = int(seed)
        self.entities: dict[str, Entity] = {}
        self.channels: dict[str, LogFn] = {}
        self.channel_units: dict[str, str] = {}
        self.controllers: list[Controller] = []
        self.world: World | None = None  # the shared MuJoCo world, made on first use (RB-01)
        self.targets: dict[str, Target] = {}
        self.visuals: dict[str, Visual] = {}  # VP-01: mesh files drawn but not simulated
        self.trails: dict[str, TrailStyle] = {}  # VP-04: per-entity trail settings

    def physics(self) -> World:
        """The scene's MuJoCo world (created on first use, so ODE-only scenes never load it)."""
        if self.world is None:
            from simview.physics.world import World

            self.world = World()
        return self.world

    def add_entity(self, entity: E) -> E:
        if entity.name in self.entities:
            raise ValueError(f"an entity named {entity.name!r} already exists; pass name=")
        world = getattr(entity, "world", None)
        if world is not None and world is not self.world:
            # A MuJoCo entity made on its own moves into the scene's shared world.
            world.members.remove(entity)
            self.physics().adopt(entity)
        self.entities[entity.name] = entity
        return entity

    # -- MuJoCo world (RB-01..RB-05) ---------------------------------------------------------
    def add_robot(
        self,
        path: str | Path | None = None,
        *,
        name: str | None = None,
        mjcf: str | None = None,
        pos: Sequence[float] = (0.0, 0.0, 0.0),
        quat: Sequence[float] = (1.0, 0.0, 0.0, 0.0),
        mount: tuple[str, str] | None = None,
        servos: ServoKind | None = None,
        kp: float | Mapping[str, float] = 1000.0,
        kv: float | Mapping[str, float] = 100.0,
        gravity_compensation: bool = False,
        frame: str | None = None,
    ) -> Robot:
        """Add a robot: a URDF/MJCF file, a bundled or library name ("ur5", "panda"), or `mjcf=`.

        `pos`/`quat` (w, x, y, z) place the base; `mount=(robot, body_or_site)` attaches it to
        another robot instead. `servos="position"` (or "velocity") adds a servo to every joint
        without an actuator, with gains `kp`/`kv` (one value, or a dict by joint name).
        `gravity_compensation=True` cancels gravity on the robot's links, as an arm's own
        controller would. `frame` is the default frame for FK/IK (e.g. "tool0").
        """
        from simview.physics.mujoco_world import Robot  # MuJoCo loads only when a robot is used

        robot = Robot(
            path,
            name=name,
            mjcf=mjcf,
            pos=pos,
            quat=quat,
            mount=mount,
            servos=servos,
            kp=kp,
            kv=kv,
            gravity_compensation=gravity_compensation,
            frame=frame,
            world=None if mount is None else self.physics(),
        )
        return self.add_entity(robot)

    def add_ground(self, friction: float | Sequence[float] | None = None) -> None:
        """An infinite ground plane at z = 0."""
        self.physics().add_ground(friction)

    def _add_shape(
        self,
        shape: str,
        name: str,
        size: Sequence[float],
        pos: Sequence[float],
        quat: Sequence[float],
        mass: float | None,
        static: bool,
        friction: float | Sequence[float] | None,
        rgba: Sequence[float] | None,
    ) -> Body | None:
        from simview.physics.world import Shape, _friction, _half_size

        if static == (mass is not None):
            raise ValueError(f"{name}: give mass= for a free object, or static=True, not both")
        if mass is not None and mass <= 0:
            raise ValueError(f"{name}: mass must be positive")
        if name in self.entities:
            raise ValueError(f"an entity named {name!r} already exists")
        item = Shape(
            name=name,
            shape=shape,
            size=_half_size(shape, size),
            pos=[float(v) for v in pos],
            quat=[float(v) for v in quat],
            friction=_friction(friction),
            rgba=None if rgba is None else [float(v) for v in rgba],
            mass=None if static else float(mass),  # type: ignore[arg-type]
        )
        body = self.physics().add_shape(item)
        if body is not None:
            self.entities[name] = body
        return body

    def add_box(
        self,
        name: str,
        size: Sequence[float],
        pos: Sequence[float] = (0.0, 0.0, 0.0),
        *,
        quat: Sequence[float] = (1.0, 0.0, 0.0, 0.0),
        mass: float | None = None,
        static: bool = False,
        friction: float | Sequence[float] | None = None,
        rgba: Sequence[float] | None = None,
    ) -> Body | None:
        """A box with full edge lengths `size` (x, y, z) in metres (RB-02).

        Free with `mass=` (kg): an entity whose pose and velocity are logged. `static=True`
        makes it fixed geometry (returns None). `friction` is MuJoCo's sliding coefficient (or
        all three of sliding, torsional, rolling).
        """
        return self._add_shape("box", name, size, pos, quat, mass, static, friction, rgba)

    def add_sphere(
        self,
        name: str,
        diameter: float,
        pos: Sequence[float] = (0.0, 0.0, 0.0),
        *,
        mass: float | None = None,
        static: bool = False,
        friction: float | Sequence[float] | None = None,
        rgba: Sequence[float] | None = None,
    ) -> Body | None:
        return self._add_shape(
            "sphere", name, [diameter], pos, (1, 0, 0, 0), mass, static, friction, rgba
        )

    def add_cylinder(
        self,
        name: str,
        diameter: float,
        length: float,
        pos: Sequence[float] = (0.0, 0.0, 0.0),
        *,
        quat: Sequence[float] = (1.0, 0.0, 0.0, 0.0),
        mass: float | None = None,
        static: bool = False,
        friction: float | Sequence[float] | None = None,
        rgba: Sequence[float] | None = None,
    ) -> Body | None:
        """Axis along the body's z; `length` is the full height."""
        return self._add_shape(
            "cylinder", name, [diameter, length], pos, quat, mass, static, friction, rgba
        )

    def add_capsule(
        self,
        name: str,
        diameter: float,
        length: float,
        pos: Sequence[float] = (0.0, 0.0, 0.0),
        *,
        quat: Sequence[float] = (1.0, 0.0, 0.0, 0.0),
        mass: float | None = None,
        static: bool = False,
        friction: float | Sequence[float] | None = None,
        rgba: Sequence[float] | None = None,
    ) -> Body | None:
        """Axis along the body's z; `length` is between the centers of the end caps."""
        return self._add_shape(
            "capsule", name, [diameter, length], pos, quat, mass, static, friction, rgba
        )

    def add_visual(
        self,
        name: str,
        path: str | Path,
        pose: Sequence[Sequence[float]] | None = None,
        *,
        scale: float = 1.0,
        color: str | None = None,
    ) -> Visual:
        """Show a mesh file (STL, OBJ, GLB/glTF) at a 4x4 `pose`; it has no physics (VP-01).

        For a simulated mesh, put it in a robot's URDF/MJCF instead. `color` is a theme token
        or color name; without one, GLB files keep their own colors."""
        import numpy as np

        file = Path(path).resolve()
        if not file.is_file():
            raise FileNotFoundError(f"no mesh file at {path}")
        if file.suffix.lower() not in (".stl", ".obj", ".glb", ".gltf", ".ply"):
            raise ValueError(f"{file.name}: visuals can be STL, OBJ, GLB/glTF, or PLY")
        if name in self.visuals:
            raise ValueError(f"a visual named {name!r} already exists")
        matrix = np.eye(4) if pose is None else np.array(pose, dtype=np.float64)
        visual = Visual(name, file, matrix, float(scale), color)
        self.visuals[name] = visual
        return visual

    def trail(self, entity: str, seconds: float = 5.0, color: str | None = None) -> None:
        """VP-04: set an entity's trail length (seconds of sim time; 0 hides it) and color."""
        if seconds < 0:
            raise ValueError("trail length must be >= 0 seconds")
        self.trails[entity] = TrailStyle(float(seconds), color)

    def add_target(self, name: str, pose: Sequence[Sequence[float]] | None = None) -> Target:
        """A draggable pose (VP-10): `pose` is a 4x4 transform (default: identity at the origin)."""
        import numpy as np

        if name in self.targets or not name or "/" in name or "." in name:
            raise ValueError(f"target name {name!r} is taken or has '/' or '.'")
        matrix = np.eye(4) if pose is None else np.array(pose, dtype=np.float64)
        if matrix.shape != (4, 4):
            raise ValueError(f"a target pose is a 4x4 transform, got shape {matrix.shape}")
        target = Target(name, matrix)
        self.targets[name] = target
        return target

    # -- controllers (RB-06) -------------------------------------------------------------------
    def controller(self, rate: float | None = None) -> Callable[[ControllerFn], ControllerFn]:
        """Decorator: run `fn(t, state, ctx)` at `rate` Hz during a run (every tick if None).

        The rate must divide the physics rate (1/dt) exactly. A returned dict `{entity: u}`
        sets those entities' inputs.
        """
        if rate is not None:
            ticks = 1.0 / (rate * self.dt)
            if rate <= 0 or abs(ticks - round(ticks)) > 1e-9 or round(ticks) < 1:
                raise ValueError(f"controller rate {rate} Hz must divide 1/dt = {1 / self.dt} Hz")

        def register(fn: ControllerFn) -> ControllerFn:
            self.controllers.append(Controller(fn, rate))
            return fn

        return register

    def log(self, name: str, fn: LogFn, unit: str = "") -> None:
        """Log a user-tagged channel each tick. `fn(sim)` returns a float (SE-06).
        `unit` (e.g. "m") labels its plot axis (DS-09)."""
        if name in self.channels or "." in name:
            raise ValueError(f"channel name {name!r} is taken or contains '.'")
        self.channels[name] = fn
        self.channel_units[name] = unit

    def __getitem__(self, name: str) -> Entity:
        return self.entities[name]
