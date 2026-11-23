"""Test scenarios (ST-01): a scene, its parameters, a duration, and pass/fail criteria.

Criteria are RI-02 expressions with a verb (D-142):

    must_not: ego.min_ttc < 1.0 for 0.1 s     fails if the pattern occurs anywhere in the run
    must: drone_1.delivered > 0.5 within 120 s fails unless it occurs, starting by 120 s
    must: arm.settled > 0.5                   fails unless it occurs at all

`must` asks for existence, `must_not` for absence; "always P" is `must_not: not (P)`. A run that
doesn't log a signal a criterion reads fails that criterion ("missing signals"), never passes.

Parameters: constants, distributions (`Uniform`, `Normal`, `Choice`, sampled per sample) or
grid lists (every combination). Initial conditions are scene parameters too: scene files read
`scene.params` while they build the scene (D-106), so a start position is just a parameter.

A suite is a TOML file (stdlib `tomllib`) or a Python file defining `suite = TestSuite(...)`:

    name = "Drone delivery checks"

    [[scenario]]
    name = "gusty delivery"
    scene = "../src/simview/templates/drone_delivery/scene.py"   # relative to this file
    duration = 40
    samples = 4                       # runs per grid point
    seed = 0
    metrics = ["delivery_time"]       # recorded for baselines (ST-03)
    tolerance = 0.1                   # relative drift allowed against a baseline
    criteria = [
        "must: d0.delivered > 0.5 within 35 s",
        "must_not: d0.z < 0.2 and t > 5 for 0.5 s",
    ]
    [scenario.params]
    gust = { uniform = [0.5, 3.0] }
    gps_noise = { normal = [0.8, 0.2], lo = 0.0 }
    [scenario.grid]
    cruise_speed = [5.0, 7.0]         # or { linspace = [5.0, 7.0, 3] }
"""

from __future__ import annotations

import re
import runpy
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from simview.investigate.runs import RunData
from simview.investigate.scenario import (
    Finding,
    ScanResult,
    Scenario,
    ScenarioError,
    Window,
)
from simview.runner.montecarlo import Choice, Normal, Uniform

_VERB = re.compile(r"^\s*(must_not|must)\s*:\s*(.+?)\s*$", re.S)
_WITHIN = re.compile(
    r"^(?P<pat>.+?)\s+within\s+(?P<num>[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*(?P<unit>ms|s)\s*$",
    re.S,
)


class SuiteError(ValueError):
    """A suite or scenario definition is invalid (with the file and field in the message)."""


# -- criteria --------------------------------------------------------------------------------
@dataclass
class Criterion:
    """One pass/fail check over a run (see the module docstring for the syntax)."""

    text: str  # "must_not: ..." / "must: ... within 120 s"
    name: str = ""  # defaults to the text
    verb: str = field(init=False)
    pattern: Scenario = field(init=False, repr=False)  # the RI-02 pattern it looks for
    within: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        m = _VERB.match(self.text)
        if m is None:
            raise SuiteError(f"criterion {self.text!r} must start with 'must:' or 'must_not:'")
        self.verb, body = m.group(1), m.group(2)
        w = _WITHIN.match(body)
        if w is not None:
            if self.verb == "must_not":
                raise SuiteError(f"criterion {self.text!r}: 'within' only goes with 'must:'")
            body = w.group("pat")
            self.within = float(w.group("num")) * (1e-3 if w.group("unit") == "ms" else 1.0)
        self.name = self.name or self.text.strip()
        try:
            self.pattern = Scenario(self.name, body)
        except (ScenarioError, SyntaxError) as exc:
            raise SuiteError(f"criterion {self.text!r}: {exc}") from None

    @property
    def signals(self) -> tuple[str, ...]:
        return tuple(self.pattern.signals)

    def check(self, run: RunData) -> CriterionResult:
        res = self.pattern.scan(run)
        if res.missing:
            return CriterionResult(self, False, [], f"missing signals: {', '.join(res.missing)}")
        t_end = float(run.t[-1]) if len(run.t) else 0.0
        if self.verb == "must_not":
            if not res.matches:
                return CriterionResult(self, True, [], "")
            first = res.matches[0]
            more = f" (+{len(res.matches) - 1} more)" if len(res.matches) > 1 else ""
            msg = f"occurred at {first.start:.3f} to {first.end:.3f} s{more}"
            return CriterionResult(self, False, res.matches, msg)
        limit = self.within if self.within is not None else t_end
        if any(w.start <= limit + 1e-9 for w in res.matches):
            return CriterionResult(self, True, [], "")
        span = Window(float(run.t[0]) if len(run.t) else 0.0, min(limit, t_end))
        when = f"by {limit:g} s" if self.within is not None else "in the run"
        late = [w for w in res.matches if w.start > limit]
        msg = f"never held {when}" + (f" (first at {late[0].start:.3f} s)" if late else "")
        return CriterionResult(self, False, [span], msg)


@dataclass
class CriterionResult:
    criterion: Criterion
    passed: bool
    windows: list[
        Window
    ]  # the evidence (RI-03): matches of a must_not, the searched span of a must
    message: str

    def findings(self, run: RunData) -> list[Finding]:
        c = self.criterion
        return [
            Finding(run.info, c.name, c.signals, w.start, w.end, self.message) for w in self.windows
        ]

    def scan_result(self, run: RunData) -> ScanResult:
        """As an RI-02 scan result, so RI-04 report sections can plot the evidence."""
        missing = self.message.removeprefix("missing signals: ").split(", ")
        is_missing = self.message.startswith("missing signals: ")
        return ScanResult(
            run.info, self.criterion.pattern, self.windows, missing if is_missing else []
        )


# -- scenarios and suites --------------------------------------------------------------------
@dataclass
class TestScenario:
    """A scene run over parameter samples and checked against criteria (ST-01)."""

    __test__ = False  # not a pytest class

    name: str
    scene: str | Path
    duration: float
    criteria: Sequence[str | Criterion] = ()
    params: Mapping[str, Any] = field(default_factory=dict)
    grid: Mapping[str, Sequence[float]] = field(default_factory=dict)
    samples: int = 1
    seed: int = 0
    metrics: Sequence[str] | None = None  # None: every metric the scene declares
    tolerance: float | Mapping[str, float] = 0.1  # relative metric drift vs a baseline (ST-03)
    atol: float = 1e-9

    def __post_init__(self) -> None:
        if not self.name or "/" in self.name:
            raise SuiteError(f"scenario name {self.name!r} must be non-empty, without '/'")
        if self.duration <= 0:
            raise SuiteError(f"scenario {self.name!r}: duration must be positive")
        if self.samples < 1:
            raise SuiteError(f"scenario {self.name!r}: samples must be >= 1")
        self.criteria = [c if isinstance(c, Criterion) else Criterion(c) for c in self.criteria]
        if not self.criteria:
            raise SuiteError(f"scenario {self.name!r} has no criteria")
        names = [c.name for c in self.criteria]
        if len(set(names)) != len(names):
            raise SuiteError(f"scenario {self.name!r}: criterion names must be unique")
        self.scene = Path(self.scene)

    def tolerance_for(self, metric: str) -> float:
        if isinstance(self.tolerance, Mapping):
            return float(self.tolerance.get(metric, 0.1))
        return float(self.tolerance)


@dataclass
class TestSuite:
    __test__ = False

    name: str
    scenarios: Sequence[TestScenario]
    path: Path | None = None  # the file it was loaded from

    def __post_init__(self) -> None:
        if not self.scenarios:
            raise SuiteError(f"suite {self.name!r} has no scenarios")
        names = [s.name for s in self.scenarios]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise SuiteError(f"suite {self.name!r}: duplicate scenario names {', '.join(dup)}")


# -- loading ---------------------------------------------------------------------------------
def _param(where: str, value: Any) -> Any:  # noqa: ANN401
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, Mapping):
        kinds = [k for k in ("uniform", "normal", "choice") if k in value]
        if len(kinds) != 1:
            raise SuiteError(f"{where}: give one of uniform / normal / choice, got {dict(value)}")
        args = value[kinds[0]]
        try:
            if kinds[0] == "uniform":
                lo, hi = args
                return Uniform(float(lo), float(hi))
            if kinds[0] == "normal":
                mean, std = args
                return Normal(float(mean), float(std), value.get("lo"), value.get("hi"))
            return Choice([float(v) for v in args])
        except (TypeError, ValueError) as exc:
            raise SuiteError(f"{where}: {exc}") from None
    if isinstance(value, list):
        try:
            return np.array(value, dtype=np.float64).tolist()  # an array parameter
        except (TypeError, ValueError):
            pass
    raise SuiteError(f"{where}: a number, a list of numbers, or a uniform/normal/choice table")


def _grid(where: str, value: Any) -> list[float]:  # noqa: ANN401
    if isinstance(value, Mapping) and "linspace" in value:
        try:
            lo, hi, n = value["linspace"]
            return [float(v) for v in np.linspace(float(lo), float(hi), int(n))]
        except (TypeError, ValueError) as exc:
            raise SuiteError(f"{where}: linspace needs [lo, hi, n] ({exc})") from None
    if isinstance(value, list) and value and all(isinstance(v, int | float) for v in value):
        return [float(v) for v in value]
    raise SuiteError(f"{where}: a non-empty list of numbers or {{ linspace = [lo, hi, n] }}")


_SCENARIO_KEYS = {
    "name",
    "scene",
    "duration",
    "criteria",
    "params",
    "grid",
    "samples",
    "seed",
    "metrics",
    "tolerance",
    "atol",
}


def _scenario_from_toml(raw: Mapping[str, Any], base: Path, file: Path, k: int) -> TestScenario:
    where = f"{file.name}: scenario {raw.get('name', k + 1)!r}"
    unknown = sorted(set(raw) - _SCENARIO_KEYS)
    if unknown:
        raise SuiteError(f"{where}: unknown keys {', '.join(unknown)}")
    for key in ("name", "scene", "duration", "criteria"):
        if key not in raw:
            raise SuiteError(f"{where}: missing {key!r}")
    criteria: list[Criterion] = []
    for c in raw["criteria"]:
        if isinstance(c, str):
            criteria.append(Criterion(c))
        elif isinstance(c, Mapping) and ("must" in c) != ("must_not" in c):
            verb = "must" if "must" in c else "must_not"
            criteria.append(Criterion(f"{verb}: {c[verb]}", name=str(c.get("name", ""))))
        else:
            raise SuiteError(f"{where}: a criterion is a string or {{ name, must | must_not }}")
    scene = Path(raw["scene"])
    if not scene.is_absolute():
        scene = (base / scene).resolve()
    params = {n: _param(f"{where}: params.{n}", v) for n, v in raw.get("params", {}).items()}
    grid = {n: _grid(f"{where}: grid.{n}", v) for n, v in raw.get("grid", {}).items()}
    try:
        return TestScenario(
            name=str(raw["name"]),
            scene=scene,
            duration=float(raw["duration"]),
            criteria=criteria,
            params=params,
            grid=grid,
            samples=int(raw.get("samples", 1)),
            seed=int(raw.get("seed", 0)),
            metrics=list(raw["metrics"]) if "metrics" in raw else None,
            tolerance=raw.get("tolerance", 0.1),
            atol=float(raw.get("atol", 1e-9)),
        )
    except SuiteError as exc:
        raise SuiteError(f"{file.name}: {exc}") from None


def load_suite(path: str | Path) -> TestSuite:
    """A suite from a `.toml` file or a `.py` file that defines `suite = TestSuite(...)`."""
    path = Path(path).resolve()
    if not path.is_file():
        raise SuiteError(f"no suite file {path}")
    if path.suffix.lower() == ".py":
        ns = runpy.run_path(str(path), run_name="__simview_suite__")
        suite = ns.get("suite")
        if not isinstance(suite, TestSuite):
            raise SuiteError(f"{path.name} must define `suite = simview.TestSuite(...)`")
        for sc in suite.scenarios:
            if not Path(sc.scene).is_absolute():
                sc.scene = (path.parent / sc.scene).resolve()
        suite.path = path
        return suite
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SuiteError(f"{path.name}: {exc}") from None
    unknown = sorted(set(raw) - {"name", "scenario"})
    if unknown:
        raise SuiteError(f"{path.name}: unknown top-level keys {', '.join(unknown)}")
    items = raw.get("scenario", [])
    scenarios = [_scenario_from_toml(s, path.parent, path, k) for k, s in enumerate(items)]
    return TestSuite(str(raw.get("name", path.stem)), scenarios, path)
