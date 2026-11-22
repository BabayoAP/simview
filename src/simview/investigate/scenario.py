"""Scenarios (RI-02, RI-03): a pattern defined once, scanned over every run.

An expression scenario is a condition over signals that must hold for a minimum time:

    ur5.elbow_joint.v > 2.0 for 0.05 s
    abs(cube.vz) > 0.5 and t > 1 for 20 ms
    `odd name` < 0                         (backticks quote any signal name)

Signal names are the log's columns (`entity.state` or a channel); `t` is time. Allowed: numbers,
comparisons (chains too), + - * / ** %, and / or / not, and the functions in FUNCTIONS. Nothing
else is evaluated (no attribute access, no imports). A Python predicate scenario takes the run
and returns one bool per sample. A match is a time window; a run without a needed signal is
reported as missing it, never as "no match".
"""

from __future__ import annotations

import ast
import json
import operator
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from simview.investigate.runs import Catalog, RunData, RunInfo

FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": np.abs,
    "sqrt": np.sqrt,
    "hypot": np.hypot,
    "min": np.minimum,
    "max": np.maximum,
    "deg": np.rad2deg,
    "rad": np.deg2rad,
}
_DURATION = re.compile(
    r"^(?P<cond>.+?)\s+for\s+(?P<num>[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*(?P<unit>ms|s)\s*$"
)
_QUOTED = re.compile(r"`([^`]+)`")
_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_CMP = {
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}
CACHE_FILE = ".scan-cache.json"
SCENARIOS_FILE = "scenarios.json"


class ScenarioError(ValueError):
    """The expression can't be parsed or uses something that isn't allowed."""


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr}" if head else None
    return None


@dataclass
class _Compiled:
    tree: ast.Expression
    quoted: dict[str, str]  # placeholder -> signal name
    signals: tuple[str, ...]


def _compile(condition: str) -> _Compiled:
    quoted: dict[str, str] = {}

    def keep(m: re.Match[str]) -> str:
        key = f"__q{len(quoted)}"
        quoted[key] = m.group(1)
        return key

    try:
        tree = ast.parse(_QUOTED.sub(keep, condition.strip()), mode="eval")
    except SyntaxError as exc:
        raise ScenarioError(f"can't parse {condition!r}: {exc.msg}") from None
    names: list[str] = []

    def check(node: ast.AST) -> None:
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = _dotted(node)
            if name is None:
                raise ScenarioError(f"{ast.unparse(node)!r} is not a signal name")
            names.append(quoted.get(name, name))
            return
        if isinstance(node, ast.Call):
            fn = node.func
            if not isinstance(fn, ast.Name) or fn.id not in FUNCTIONS or node.keywords:
                raise ScenarioError(f"only these functions are allowed: {', '.join(FUNCTIONS)}")
            for a in node.args:
                check(a)
            return
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                raise ScenarioError(f"only numbers are allowed, not {node.value!r}")
            return
        allowed = (
            ast.Expression,
            ast.BoolOp,
            ast.And,
            ast.Or,
            ast.UnaryOp,
            ast.Not,
            ast.USub,
            ast.UAdd,
            ast.BinOp,
            ast.Compare,
            *_BIN,
            *_CMP,
        )
        if not isinstance(node, allowed):
            raise ScenarioError(f"{type(node).__name__} is not allowed in a scenario")
        for child in ast.iter_child_nodes(node):
            check(child)

    check(tree)
    signals = tuple(dict.fromkeys(n for n in names if n != "t"))
    return _Compiled(tree, quoted, signals)


def _evaluate(node: ast.AST, run: RunData, quoted: dict[str, str]) -> Any:
    ev = lambda n: _evaluate(n, run, quoted)  # noqa: E731
    if isinstance(node, ast.Expression):
        return ev(node.body)
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = _dotted(node)
        assert name is not None
        return run[quoted.get(name, name)]
    if isinstance(node, ast.Constant):  # float, so `9**9**9**9` can't spin on big ints (D-136)
        return np.float64(node.value)
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name)
        return FUNCTIONS[node.func.id](*[ev(a) for a in node.args])
    if isinstance(node, ast.BoolOp):
        combine = np.logical_and if isinstance(node.op, ast.And) else np.logical_or
        out = np.asarray(ev(node.values[0]), dtype=bool)
        for v in node.values[1:]:
            out = combine(out, np.asarray(ev(v), dtype=bool))
        return out
    if isinstance(node, ast.UnaryOp):
        v = ev(node.operand)
        if isinstance(node.op, ast.Not):
            return np.logical_not(v)
        return -v if isinstance(node.op, ast.USub) else +v
    if isinstance(node, ast.BinOp):
        return _BIN[type(node.op)](ev(node.left), ev(node.right))
    if isinstance(node, ast.Compare):
        left = ev(node.left)
        out: Any = True
        for op, right_node in zip(node.ops, node.comparators, strict=True):
            right = ev(right_node)
            out = np.logical_and(out, _CMP[type(op)](left, right))
            left = right
        return out
    raise ScenarioError(f"{type(node).__name__} is not allowed")  # unreachable after _compile


@dataclass(frozen=True)
class Window:
    start: float  # s, first sample where the condition holds
    end: float  # s, last sample where it holds

    @property
    def duration(self) -> float:
        return self.end - self.start


def windows(t: np.ndarray, mask: np.ndarray, min_duration: float, dt: float) -> list[Window]:
    """Runs of consecutive True samples lasting at least `min_duration`. Each sample counts for
    one sample period `dt`, so k samples in a row last k·dt (D-055)."""
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim == 0:
        mask = np.full(len(t), bool(mask))
    edges = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    starts = np.flatnonzero(edges == 1)
    stops = np.flatnonzero(edges == -1) - 1
    out = []
    for i, j in zip(starts, stops, strict=True):
        if t[j] - t[i] + dt >= min_duration - 1e-9:
            out.append(Window(float(t[i]), float(t[j])))
    return out


@dataclass
class Scenario:
    """A pattern to find in runs: an `expression` ("cond for 0.05 s"), or a `predicate`
    (run -> bool per sample) with the `signals` it reads and a `duration`."""

    name: str
    expression: str | None = None
    predicate: Callable[[RunData], np.ndarray] | None = None
    signals: Sequence[str] = ()
    duration: float = 0.0  # s (from "for … s" in an expression)
    _compiled: _Compiled | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (self.expression is None) == (self.predicate is None):
            raise ScenarioError("give a scenario an expression or a predicate, not both")
        if self.expression is not None:
            cond, self.duration = parse_duration(self.expression)
            self._compiled = _compile(cond)
            self.signals = self._compiled.signals

    @property
    def key(self) -> str | None:
        """Identifies the scenario in the scan cache (predicates aren't cached)."""
        return f"{self.name}\x00{self.expression}" if self.expression is not None else None

    def needed(self, run: RunData) -> list[str]:
        return [s for s in self.signals if s not in run]

    def mask(self, run: RunData) -> np.ndarray:
        if self._compiled is not None:
            with np.errstate(all="ignore"):  # NaN comparisons are False, as wanted
                return np.asarray(_evaluate(self._compiled.tree, run, self._compiled.quoted))
        assert self.predicate is not None
        return np.asarray(self.predicate(run), dtype=bool)

    def scan(self, run: RunData) -> ScanResult:
        missing = self.needed(run)
        if missing:
            return ScanResult(run.info, self, [], missing)
        try:
            mask = self.mask(run)
        except KeyError as exc:  # a predicate read a signal the run doesn't have
            return ScanResult(run.info, self, [], [str(exc.args[0])])
        return ScanResult(run.info, self, windows(run.t, mask, self.duration, run.dt), [])


def parse_duration(expression: str) -> tuple[str, float]:
    """("cond", seconds) from "cond for 0.05 s" / "cond for 50 ms" (no "for": 0 s)."""
    m = _DURATION.match(expression.strip())
    if m is None:
        return expression.strip(), 0.0
    value = float(m.group("num")) * (1e-3 if m.group("unit") == "ms" else 1.0)
    return m.group("cond"), value


@dataclass(frozen=True)
class Finding:
    """A traceable claim (RI-03): this run, these signals, this time window."""

    run: RunInfo
    title: str  # e.g. the scenario name
    signals: tuple[str, ...]
    start: float
    end: float
    detail: str = ""

    def describe(self) -> str:
        span = (
            f"{self.start:.3f} s"
            if self.end == self.start
            else (f"{self.start:.3f} to {self.end:.3f} s")
        )
        return f"{self.run.name}: {self.title} at {span} ({', '.join(self.signals)})"


@dataclass
class ScanResult:
    run: RunInfo
    scenario: Scenario
    matches: list[Window]
    missing: list[str]  # signals the scenario needs that the run doesn't log

    @property
    def findings(self) -> list[Finding]:
        return [
            Finding(self.run, self.scenario.name, tuple(self.scenario.signals), w.start, w.end)
            for w in self.matches
        ]


# -- scanning a catalog, with a cache so only new or changed runs are scanned (RI-02) ---------
def _stamp(info: RunInfo) -> list[int]:
    st = info.path.stat()
    return [st.st_mtime_ns, st.st_size]


def scan(
    catalog: Catalog,
    scenarios: Sequence[Scenario],
    runs: Sequence[RunInfo] | None = None,
    *,
    use_cache: bool = True,
) -> list[ScanResult]:
    """Every scenario over every run (or the given ones). Expression results are cached in
    the run folder, keyed by the run file's size and time; a new or rewritten run is scanned."""
    runs = list(runs) if runs is not None else catalog.runs()
    cache_path = catalog.folder / CACHE_FILE
    cache: dict[str, Any] = {}
    if use_cache and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
    out: list[ScanResult] = []
    dirty = False
    for info in runs:
        entry = cache.get(info.path.name)
        stamp = _stamp(info)
        if entry is None or entry.get("stamp") != stamp:
            entry = {"stamp": stamp, "results": {}}
            cache[info.path.name] = entry
            dirty = True
        data: RunData | None = None
        for sc in scenarios:
            hit = entry["results"].get(sc.key) if sc.key is not None else None
            if hit is not None:
                out.append(
                    ScanResult(info, sc, [Window(*w) for w in hit["matches"]], hit["missing"])
                )
                continue
            data = data or RunData(info)
            res = sc.scan(data)
            out.append(res)
            if sc.key is not None:
                entry["results"][sc.key] = {
                    "matches": [[w.start, w.end] for w in res.matches],
                    "missing": res.missing,
                }
                dirty = True
    if use_cache and dirty and catalog.folder.is_dir():
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return out


def load_scenarios(folder: str | Path) -> list[Scenario]:
    """The expression scenarios saved for a run folder (`scenarios.json`)."""
    path = Path(folder) / SCENARIOS_FILE
    if not path.exists():
        return []
    items = json.loads(path.read_text(encoding="utf-8"))
    return [Scenario(i["name"], i["expression"]) for i in items]


def save_scenarios(folder: str | Path, scenarios: Sequence[Scenario]) -> Path:
    path = Path(folder) / SCENARIOS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    items = [{"name": s.name, "expression": s.expression} for s in scenarios if s.expression]
    path.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    return path
