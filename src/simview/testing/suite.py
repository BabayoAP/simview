"""Running a test suite (ST-02): every scenario over its parameter samples, in parallel through
the sweep runner (SE-08), each kept log checked against the scenario's criteria.

Results are deterministic: the sweep draws every sample from the scenario's seed up front and
gives sample i the seed `seed + i`, whatever the worker count, so the same suite gives the same
verdicts every time on one machine (NF-06).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from simview.investigate.runs import RunData, read_info
from simview.runner.montecarlo import sweep
from simview.testing.scenario import CriterionResult, TestScenario, TestSuite

PASSED, FAILED, ERROR = "passed", "failed", "error"


@dataclass
class CaseResult:
    """One sample of one scenario: its parameters, verdict per criterion, and metrics."""

    scenario: TestScenario
    index: int  # the sample's index in the scenario (the sweep's trial number)
    seed: int
    params: dict[str, float]
    status: str  # passed / failed / error
    criteria: list[CriterionResult] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    error: str = ""  # the scene's exception, for status "error"
    log: Path | None = None
    wall_s: float = 0.0

    @property
    def key(self) -> str:
        """Identifies the case across runs of the suite (baselines, ST-03)."""
        return f"{self.scenario.name}#{self.index}"

    @property
    def label(self) -> str:
        values = ", ".join(f"{k}={_fmt(v)}" for k, v in self.params.items())
        return f"{self.scenario.name} #{self.index}" + (f" ({values})" if values else "")

    @property
    def failures(self) -> list[CriterionResult]:
        return [c for c in self.criteria if not c.passed]

    def run_data(self) -> RunData | None:
        return RunData(read_info(self.log)) if self.log is not None and self.log.exists() else None


@dataclass
class SuiteResult:
    suite: TestSuite
    cases: list[CaseResult]
    out: Path
    wall_s: float = 0.0

    @property
    def passed(self) -> bool:
        return all(c.status == PASSED for c in self.cases)

    def count(self, status: str) -> int:
        return sum(c.status == status for c in self.cases)

    def summary(self) -> str:
        n = len(self.cases)
        return (
            f"{self.suite.name}: {n} case{'s' if n != 1 else ''}, {self.count(PASSED)} passed, "
            f"{self.count(FAILED)} failed, {self.count(ERROR)} errors ({self.wall_s:.1f} s)"
        )


def _fmt(v: Any) -> str:  # noqa: ANN401
    return f"{v:.6g}" if isinstance(v, float) else str(v)


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "scenario"


def run_scenario(
    scenario: TestScenario,
    out: Path,
    *,
    workers: int | None = None,
    on_case: Callable[[CaseResult], None] | None = None,
) -> list[CaseResult]:
    """Run one scenario's samples and check each log."""
    sw = sweep(
        scenario.scene,
        scenario.duration,
        params=scenario.params,
        grid=scenario.grid,
        trials=scenario.samples,
        seed=scenario.seed,
        metrics=scenario.metrics,
        workers=workers,
        keep_logs=True,
        out=out,
    )
    skip = {"trial", "seed", "status", "error", "wall_s", "log"}
    cases = []
    for i in range(len(sw)):
        row = {c: sw[c][i] for c in sw.columns}
        params = {p: float(row[p]) for p in sw.params}
        metrics = {m: float(row[m]) for m in sw.metrics if m not in skip and np.isfinite(row[m])}
        case = CaseResult(
            scenario=scenario,
            index=int(row["trial"]),
            seed=int(row["seed"]),
            params=params,
            status=ERROR,
            metrics=metrics,
            error=str(row["error"]),
            log=Path(row["log"]) if row["log"] else None,
            wall_s=float(row["wall_s"]),
        )
        if row["status"] == "ok" and case.log is not None:
            data = RunData(read_info(case.log))
            case.criteria = [c.check(data) for c in scenario.criteria]
            case.status = PASSED if all(c.passed for c in case.criteria) else FAILED
        cases.append(case)
        if on_case is not None:
            on_case(case)
    return cases


def run_suite(
    suite: TestSuite,
    out: str | Path,
    *,
    workers: int | None = None,
    on_case: Callable[[CaseResult], None] | None = None,
) -> SuiteResult:
    """Run every scenario; each one's logs and sweep table go to `out/<scenario>/`."""
    import time

    out = Path(out)
    start = time.perf_counter()
    cases: list[CaseResult] = []
    for sc in suite.scenarios:
        if not Path(sc.scene).is_file():
            raise FileNotFoundError(f"scenario {sc.name!r}: no scene file {sc.scene}")
    folders: set[str] = set()
    for sc in suite.scenarios:
        folder, k = slug(sc.name), 2
        while folder.lower() in folders:  # "a b" and "a-b" share a slug
            folder, k = f"{slug(sc.name)}-{k}", k + 1
        folders.add(folder.lower())
        cases += run_scenario(sc, out / folder, workers=workers, on_case=on_case)
    return SuiteResult(suite, cases, out, time.perf_counter() - start)
