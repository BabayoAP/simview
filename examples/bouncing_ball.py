"""A ball dropped onto the ground: the M2 headless demo.

    simview run examples/bouncing_ball.py --headless --duration 5

The ground is a stiff spring-damper acting only while the ball is below h = 0, so the whole
bounce is one smooth-enough ODE (no event handling needed).
"""

import numpy as np

import simview as sv

G = 9.81  # m/s^2


class BouncingBall(sv.Entity):
    state_names = ("h", "v")  # height [m], vertical velocity [m/s]

    def __init__(
        self,
        h0: float = 1.0,
        mass: float = 1.0,
        stiffness: float = 1e4,
        damping: float = 20.0,
        **kwargs: object,
    ) -> None:
        super().__init__([h0, 0.0], **kwargs)  # type: ignore[arg-type]
        self.mass, self.k, self.c = mass, stiffness, damping

    def derivative(self, t: float, x: np.ndarray, u: np.ndarray) -> np.ndarray:
        h, v = x
        contact = max(0.0, -self.k * h - self.c * v) if h < 0 else 0.0
        return np.array([v, -G + contact / self.mass])


scene = sv.Scene(dt=1e-3, seed=42)
ball = scene.add_entity(BouncingBall(name="ball"))
# A noisy height sensor reading, drawn from the run's seeded RNG (SE-07).
scene.log("h_measured", lambda sim: sim.scene["ball"]["h"] + sim.rng.normal(0.0, 0.01))
