"""Messages between the UI and the sim process (SE-02), and the scene description.

Commands (UI -> sim) and events (sim -> UI) are small dicts sent with ZeroMQ `send_pyobj`
(both ends are this program, on this machine). The scene description is plain data built once
in the sim process, so the viewport can draw the scene without importing MuJoCo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from simview.core.scene import Scene

# Commands, UI -> sim: {"cmd": name, ...}
PLAY, PAUSE, STEP, RESET, SPEED, TARGET, BODY_POSE, QUIT = (
    "play",
    "pause",
    "step",
    "reset",
    "speed",
    "target",
    "body_pose",
    "quit",
)
# Replay a saved or imported run's log (RI-01, RI-06): {"cmd": REPLAY, "path": str}. The sim
# reloads the scene (READY), then sends {"event": REPLAYED, "rows", "dt", "path"}.
REPLAY, REPLAYED = "replay", "replayed"
# Live parameters (SC-05): {"cmd": PARAM, "name": str, "value": float | array}. The sim applies
# it before its next tick and answers {"event": PARAMS, "values": {name: value}} (also on a
# rejected value, so the UI's copy stays right).
PARAM, PARAMS = "param", "params"
# Events, sim -> UI: {"event": name, ...}
READY, ERROR, LOG, DRAWS, STOPPED = "ready", "error", "log", "draws", "stopped"
# Per-tick history rows (VP-05, DA-01): {"event": ROWS, "rows": (n, width) float64 array}.
# Rows replace any the UI holds from the first row's tick on (a re-recorded tick, or a reset).
ROWS = "rows"

# MuJoCo shows geom groups 0-2 by default; Menagerie puts collision-only geoms in group 3.
VISIBLE_GROUPS = (0, 1, 2)


@dataclass(frozen=True)
class Geom:
    body: int  # index into the frame's body poses
    kind: str  # "plane", "box", "sphere", "cylinder", "capsule", "ellipsoid", "mesh"
    size: tuple[float, ...]  # MuJoCo half sizes
    pos: tuple[float, float, float]  # in the body frame
    quat: tuple[float, float, float, float]  # w, x, y, z, in the body frame
    rgba: tuple[float, float, float, float]
    vertices: np.ndarray | None = None  # (n, 3) for meshes
    faces: np.ndarray | None = None  # (m, 3)


@dataclass(frozen=True)
class EntityInfo:
    name: str
    kind: str  # "robot", "body", or "entity" (custom ODE model)
    state_names: tuple[str, ...]
    bodies: tuple[int, ...]  # MuJoCo bodies that belong to it (for picking)
    has_marker: bool


@dataclass
class Description:
    dt: float
    seed: int = 0
    entities: list[EntityInfo] = field(default_factory=list)
    geoms: list[Geom] = field(default_factory=list)
    body_names: list[str] = field(default_factory=list)
    targets: dict[str, np.ndarray] = field(default_factory=dict)
    has_ground: bool = False
    # VP-01 visuals: name -> (file path, 4x4 pose, scale, color or None)
    visuals: dict[str, tuple[str, np.ndarray, float, str | None]] = field(default_factory=dict)
    # VP-04 trail settings: entity -> (seconds, color or None)
    trails: dict[str, tuple[float, str | None]] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)  # SC-05: values when loaded
    diagrams: dict[str, str | None] = field(default_factory=dict)  # name -> .svd path (M7)
    scopes: dict[str, list[str]] = field(default_factory=dict)  # BD-08: scope -> signals

    def entity_of_body(self, body: int) -> str | None:
        for e in self.entities:
            if body in e.bodies:
                return e.name
        return None


_GEOM_KINDS = {
    0: "plane",
    2: "sphere",
    3: "capsule",
    4: "ellipsoid",
    5: "cylinder",
    6: "box",
    7: "mesh",
}


def describe(scene: Scene) -> Description:
    """Plain-data description of everything the viewport draws."""
    desc = Description(
        dt=scene.dt,
        seed=scene.seed,
        targets={k: v.pose.copy() for k, v in scene.targets.items()},
        visuals={
            k: (str(v.path), v.pose.copy(), v.scale, v.color) for k, v in scene.visuals.items()
        },
        trails={k: (v.seconds, v.color) for k, v in scene.trails.items()},
        params=scene.params.to_dict(),
        diagrams={
            k: (str(d.diagram.path) if d.diagram.path is not None else None)
            for k, d in scene.diagrams.items()
        },
        scopes={k: v for d in scene.diagrams.values() for k, v in d.scopes.items()},
    )
    world = scene.world
    if world is not None:
        m = world.model
        desc.body_names = [m.body(b).name for b in range(m.nbody)]
        for g in range(m.ngeom):
            kind = _GEOM_KINDS.get(int(m.geom_type[g]))
            if kind is None or int(m.geom_group[g]) not in VISIBLE_GROUPS:
                continue
            if kind == "plane":
                desc.has_ground = True
                continue
            verts = faces = None
            if kind == "mesh":
                mid = int(m.geom_dataid[g])
                va, vn = int(m.mesh_vertadr[mid]), int(m.mesh_vertnum[mid])
                fa, fn = int(m.mesh_faceadr[mid]), int(m.mesh_facenum[mid])
                verts = np.array(m.mesh_vert[va : va + vn], dtype=np.float32)
                faces = np.array(m.mesh_face[fa : fa + fn], dtype=np.int32)
            rgba = m.geom_rgba[g]
            if int(m.geom_matid[g]) >= 0:
                rgba = m.mat_rgba[int(m.geom_matid[g])]
            desc.geoms.append(
                Geom(
                    body=int(m.geom_bodyid[g]),
                    kind=kind,
                    size=tuple(float(v) for v in m.geom_size[g]),
                    pos=tuple(float(v) for v in m.geom_pos[g]),  # type: ignore[arg-type]
                    quat=tuple(float(v) for v in m.geom_quat[g]),  # type: ignore[arg-type]
                    rgba=tuple(float(v) for v in rgba),  # type: ignore[arg-type]
                    vertices=verts,
                    faces=faces,
                )
            )
    for e in scene.entities.values():
        kind, bodies = "entity", ()
        if hasattr(e, "attach_to"):
            kind = "robot"
            prefix = f"{e.name}/"
            bodies = tuple(i for i, n in enumerate(desc.body_names) if n.startswith(prefix))
        elif world is not None and e in world.members:
            kind = "body"
            bodies = tuple(i for i, n in enumerate(desc.body_names) if n == e.name)
        desc.entities.append(
            EntityInfo(e.name, kind, tuple(e.state_names), bodies, e.position() is not None)
        )
    return desc


def draws_payload(draws: list[Any]) -> list[tuple]:
    """Draw records as plain tuples for sending."""
    return [(d.kind, d.points, d.color, d.size, d.text) for d in draws]
