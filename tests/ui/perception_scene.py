"""A small camera-rig scene for the perception UI tests (VW-08, VW-09): a slowly moving car with
a 4-camera ring and a fast pipeline that logs snapshots and camera frames every 0.2 s."""

import numpy as np

import simview as sv


class Car(sv.Entity):
    state_names = ("x", "y", "z", "vx", "yaw")

    def __init__(self) -> None:
        super().__init__(np.array([0.0, 0.0, 0.0, 1.0, 0.0]), name="ego", integrator="euler")

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        return np.array([x[3] * np.cos(x[4]), x[3] * np.sin(x[4]), 0.0, 0.0, 0.0])


scene = sv.Scene(dt=0.01, seed=0)
scene.add_ground()
scene.add_box("b1", (2.0, 2.0, 1.6), (8.0, 0.0, 0.8), static=True)
scene.add_box("b2", (1.0, 4.0, 2.0), (-5.0, 4.0, 1.0), static=True)
ego = scene.add_entity(Car())
rig = ego.attach(sv.perception.CameraRig.surround(n=4, width=48, height=36, rate=10))
scene.add_pipeline(
    sv.perception.Pipeline(
        [
            sv.perception.BackProject(max_range=20.0),
            sv.perception.OccupancyGrid(res=0.25, extent=30.0, height=(0.0, 3.0), rolling=True),
            sv.perception.BevMap(),
        ],
        inputs=rig,
        name="ego",
        snapshot_every=0.2,
        camera_every=0.2,
    )
)
