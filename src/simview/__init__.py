"""SimView: build, run, and visualize simulations."""

__version__ = "0.1.0"

from simview.core.entity import Entity  # noqa: E402
from simview.core.scene import Scene  # noqa: E402
from simview.runner.run import Run, run  # noqa: E402

__all__ = ["Entity", "Run", "Scene", "robotics", "run"]


def __getattr__(name: str) -> object:
    # Toolboxes load on first use, so `import simview` stays fast and MuJoCo-free.
    if name == "robotics":
        import simview.toolboxes.robotics as robotics

        return robotics
    raise AttributeError(f"module 'simview' has no attribute {name!r}")
