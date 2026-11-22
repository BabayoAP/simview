"""SimView: build, run, and visualize simulations."""

__version__ = "0.1.0"

from simview.core.entity import Entity  # noqa: E402
from simview.core.scene import Scene  # noqa: E402
from simview.runner.montecarlo import (  # noqa: E402
    Choice,
    Normal,
    SweepResults,
    Uniform,
    sweep,
)
from simview.runner.run import Run, run  # noqa: E402

__all__ = [
    "Choice",
    "Entity",
    "Normal",
    "Run",
    "Scene",
    "SweepResults",
    "Uniform",
    "aero",
    "analysis",
    "io",
    "robotics",
    "run",
    "sensors",
    "sweep",
    "vehicles",
]


def __getattr__(name: str) -> object:
    # Toolboxes load on first use, so `import simview` stays fast and MuJoCo-free.
    if name == "robotics":
        import simview.toolboxes.robotics as robotics

        return robotics
    if name in ("aero", "vehicles"):
        import importlib

        return importlib.import_module(f"simview.toolboxes.{name}")
    if name == "sensors":
        import simview.sensors as sensors

        return sensors
    if name == "analysis":
        import simview.analysis as analysis

        return analysis
    if name == "io":
        import simview.io as io

        return io
    raise AttributeError(f"module 'simview' has no attribute {name!r}")
