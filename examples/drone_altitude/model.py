"""Vertical drone dynamics shared by the script and block-diagram versions (UC-2 preview;
the 6-DOF quadrotor arrives with the Aerospace toolbox in M8)."""

import numpy as np

import simview as sv

MASS = 1.2  # kg
G = 9.81  # m/s^2
RATE = 100  # Hz, the altitude controller
GAINS = {"kp": 8.0, "ki": 2.0, "kd": 4.0, "lower": -MASS * G, "upper": 15.0}
TARGET = 2.0  # m


class Lift(sv.Entity):
    """z'' = thrust / m - g, thrust = u[0]."""

    state_names = ("z", "vz")
    state_units = {"z": "m", "vz": "m/s"}

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        thrust = float(u[0]) if len(u) else 0.0
        return np.array([x[1], thrust / MASS - G])


def make_scene() -> sv.Scene:
    scene = sv.Scene(dt=1e-3, seed=0)
    scene.add_entity(Lift([0.0, 0.0], name="drone"))
    return scene
