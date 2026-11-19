"""Transform tree (RB-10): a robot's frames, their parents, and relative transforms."""

from __future__ import annotations

import numpy as np

from simview.physics.mujoco_world import Robot
from simview.toolboxes.robotics import se3
from simview.toolboxes.robotics.kinematics import fk


def _bare(robot: Robot, full: str) -> str:
    return full.removeprefix(f"{robot.name}/")


def frames(robot: Robot) -> list[str]:
    """The robot's frames: its bodies, then its sites, by bare name."""
    m, prefix = robot.model, f"{robot.name}/"
    bodies = [m.body(b).name for b in range(m.nbody) if m.body(b).name.startswith(prefix)]
    sites = [m.site(s).name for s in range(m.nsite) if m.site(s).name.startswith(prefix)]
    return [_bare(robot, n) for n in bodies + sites]


def frame_tree(robot: Robot) -> dict[str, str | None]:
    """{frame: parent frame}; the robot's root frame (and anything mounted above it) maps
    to None, or to the body it is mounted on in another robot (full name)."""
    m, prefix = robot.model, f"{robot.name}/"
    tree: dict[str, str | None] = {}
    for b in range(1, m.nbody):
        name = m.body(b).name
        if not name.startswith(prefix):
            continue
        parent = m.body(int(m.body_parentid[b])).name
        tree[_bare(robot, name)] = (
            None
            if parent == "world"
            else (_bare(robot, parent) if parent.startswith(prefix) else parent)
        )
    for s in range(m.nsite):
        name = m.site(s).name
        if name.startswith(prefix):
            tree[_bare(robot, name)] = _bare(robot, m.body(int(m.site_bodyid[s])).name)
    return tree


def transform(robot: Robot, a: str, b: str, q: np.ndarray | None = None) -> np.ndarray:
    """T_a_b: the pose of frame `b` expressed in frame `a`, at joint positions `q`."""
    return se3.inv(fk(robot, q, a)) @ fk(robot, q, b)
