"""Shared scenes for the perception tests."""

from __future__ import annotations

import numpy as np

from simview import Entity, Scene
from simview.core.scheduler import Sim


class Car(Entity):
    """Holds still (or moves at constant vx) with a fixed yaw: a stand-in ego."""

    state_names = ("x", "y", "z", "vx", "yaw")

    def __init__(self, x0=(0.0, 0.0, 0.0, 0.0, 0.0), *, name: str = "ego") -> None:
        super().__init__(np.asarray(x0, dtype=float), name=name, integrator="euler")

    def derivative(self, t, x, u):
        return np.array([x[3] * np.cos(x[4]), x[3] * np.sin(x[4]), 0.0, 0.0, 0.0])


BOXES = [  # name, full size, centre: static obstacles within 20 m
    ("b1", (2.0, 2.0, 1.6), (10.0, 0.0, 0.8)),
    ("b2", (1.0, 4.0, 2.0), (-6.0, 5.0, 1.0)),
    ("b3", (3.0, 1.0, 1.0), (2.0, -8.0, 0.5)),
    ("b4", (1.0, 1.0, 1.8), (-4.0, -4.0, 0.9)),
]


def box_scene(dt: float = 0.01) -> tuple[Scene, Car]:
    scene = Scene(dt=dt)
    scene.add_ground()
    for name, size, pos in BOXES:
        scene.add_box(name, size, pos, static=True)
    ego = scene.add_entity(Car())
    return scene, ego


def run_ticks(scene: Scene, n: int) -> Sim:
    sim = Sim(scene)
    for _ in range(n):
        sim.step()
    return sim
