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
    "TestScenario",
    "TestSuite",
    "Uniform",
    "aero",
    "analysis",
    "io",
    "make_env",
    "make_vec_env",
    "perception",
    "reproduce",
    "rl",
    "robotics",
    "run",
    "sensors",
    "sweep",
    "testing",
    "vehicles",
]


def __getattr__(name: str) -> object:
    # Toolboxes load on first use, so `import simview` stays fast and MuJoCo-free.
    if name == "sensors":
        import simview.sensors as sensors

        return sensors
    if name == "log_metric":  # ML-03 (no RL extra needed)
        from simview.rl.metrics import log_metric

        return log_metric
    if name in ("make_env", "make_vec_env", "rl"):
        import simview.rl as rl

        return rl if name == "rl" else getattr(rl, name)
    if name == "analysis":
        import simview.analysis as analysis

        return analysis
    if name == "io":
        import simview.io as io

        return io
    if name in ("TestScenario", "TestSuite", "testing"):  # ST-01
        import simview.testing as testing

        return testing if name == "testing" else getattr(testing, name)
    if name == "reproduce":  # RP-02
        from simview.runner.reproduce import reproduce

        return reproduce
    if not name.startswith("_"):
        # Toolbox modules (TB-02): robotics, aero, vehicles, and any installed toolbox's.
        from simview.toolboxes import registry

        try:
            return registry.module(name)
        except KeyError:
            pass
    raise AttributeError(f"module 'simview' has no attribute {name!r}")
