"""Entities with custom Python dynamics (SE-03 custom models, SE-04)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, TypeVar

import numpy as np

from simview.core.integrators import INTEGRATORS, IntegratorName, step

if TYPE_CHECKING:
    from simview.core.scene import Scene
    from simview.sensors.base import Sensor

S = TypeVar("S", bound="Sensor")


class Sensors(dict[str, "Sensor"]):
    """An entity's sensors by name, also as attributes: `ego.sensors.lidar` (SN-01..SN-03)."""

    def __getattr__(self, name: str) -> Sensor:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"no sensor named {name!r}; attached: {list(self)}") from None


def quat_matrix(q: Sequence[float] | np.ndarray) -> np.ndarray:
    """Rotation matrix of a quaternion (w, x, y, z); it doesn't need to be unit length."""
    w, x, y, z = np.asarray(q, dtype=np.float64) / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def yaw_matrix(yaw: float) -> np.ndarray:
    c, s = np.cos(yaw), np.sin(yaw)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


class Entity:
    """A custom dynamics model. Subclasses set `state_names` and implement `derivative`.

    `x` is the current state during a run; it is reset to `x0` when a run starts.
    `u` is the input vector passed to `derivative` (empty until controllers or blocks drive it).
    """

    state_names: tuple[str, ...] = ()
    # Units of named states for plot labels (DS-09), e.g. {"h": "m", "v": "m/s"}; optional.
    state_units: Mapping[str, str] = {}

    def __init__(
        self,
        x0: Sequence[float] | np.ndarray,
        *,
        name: str | None = None,
        integrator: IntegratorName = "rk4",
    ) -> None:
        if integrator not in INTEGRATORS:
            raise ValueError(f"integrator must be one of {INTEGRATORS}, got {integrator!r}")
        x0 = np.array(x0, dtype=np.float64)
        if x0.ndim != 1 or len(x0) != len(self.state_names):
            raise ValueError(
                f"{type(self).__name__}: x0 has shape {x0.shape}, "
                f"expected ({len(self.state_names)},) for states {self.state_names}"
            )
        self.name = name or type(self).__name__.lower()
        self.integrator: IntegratorName = integrator
        self.x0 = x0
        self.x = x0.copy()
        self.u = np.zeros(0)
        self.sensors = Sensors()
        self.scene: Scene | None = None  # set by `scene.add_entity`

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def position(self) -> np.ndarray | None:
        """Where the viewport draws this entity's marker and trail (VP-04), or None.

        The default uses states named x, y, z (any missing one is 0) if there is an x or y;
        override it for other layouts (e.g. a ball whose height state is `h`)."""
        names = self.state_names
        if "x" not in names and "y" not in names:
            return None
        return np.array([self[n] if n in names else 0.0 for n in ("x", "y", "z")])

    def rotation(self) -> np.ndarray:
        """The body's orientation as a 3x3 rotation (body to world), used by attached sensors.

        The default reads states qw, qx, qy, qz (a quaternion) or yaw (or psi, a rotation
        about z); without them it's the identity."""
        names = self.state_names
        if "qw" in names:
            return quat_matrix([self[n] for n in ("qw", "qx", "qy", "qz")])
        for n in ("yaw", "psi"):
            if n in names:
                return yaw_matrix(self[n])
        return np.eye(3)

    def velocity(self) -> np.ndarray:
        """World-frame velocity of `position()`: states vx, vy, vz (missing ones are 0)."""
        names = self.state_names
        return np.array([self[n] if n in names else 0.0 for n in ("vx", "vy", "vz")])

    def pose(self) -> np.ndarray:
        """4x4 body-to-world transform from `position()` (origin if None) and `rotation()`."""
        m = np.eye(4)
        m[:3, :3] = self.rotation()
        p = self.position()
        if p is not None:
            m[:3, 3] = p
        return m

    def attach(self, sensor: S) -> S:
        """Mount a sensor on this entity (SN-01..SN-03); read it as `entity.sensors.<name>`.
        Its readings are logged as `<entity>.<sensor>.<field>` channels."""
        if sensor.entity is not None:
            raise ValueError(f"sensor {sensor.name!r} is already attached to {sensor.entity.name}")
        if sensor.name in self.sensors or sensor.name in self.state_names:
            raise ValueError(f"{self.name} already has a sensor or state named {sensor.name!r}")
        sensor.entity = self
        self.sensors[sensor.name] = sensor
        if self.scene is not None:
            self.scene._add_sensor(sensor)
        return sensor

    def validate(self) -> None:
        """Called once when a run starts, after `reset`. Raises if the model is malformed."""
        dx = np.asarray(self.derivative(0.0, self.x, self.u))
        if dx.shape != self.x.shape:
            raise ValueError(
                f"{self.name}.derivative returned shape {dx.shape}, not {self.x.shape}"
            )

    def advance(self, t: float, dt: float) -> None:
        """Move `x` forward one tick. Custom models integrate `derivative`; physics-backed
        entities (MuJoCo, SE-03) override this to step their engine instead."""
        self.x = step(self.integrator, self.derivative, t, self.x, self.u, dt)

    def reset(self) -> None:
        self.x = self.x0.copy()

    def __getitem__(self, state: str) -> float:
        """Current value of one named state, e.g. `ball["h"]`."""
        return float(self.x[self.state_names.index(state)])
