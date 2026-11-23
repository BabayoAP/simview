"""Baselines and the regression gate (ST-03).

A baseline is a JSON file with every case's verdict per criterion and its metrics. A later run
is compared case by case (`scenario#index`):

- new failure: a criterion that passed in the baseline fails now (or the case errors now);
- newly passing: a criterion that failed in the baseline passes now;
- metric drift: |now - baseline| > atol + rtol·|baseline|, RI-05's tolerance rule, with the
  scenario's `tolerance` as rtol (default 0.1, i.e. 10%).

New failures and drifts are regressions; the gate fails on any of them. Drift in either
direction counts (an improvement also changes behavior), so a deliberate change is accepted by
saving a new baseline (D-144).
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from simview.testing.suite import ERROR, PASSED, SuiteResult

FORMAT = 1


def to_json(result: SuiteResult) -> dict[str, Any]:
    cases = {}
    for c in result.cases:
        cases[c.key] = {
            "status": c.status,
            "seed": c.seed,
            "params": c.params,
            "criteria": {cr.criterion.name: cr.passed for cr in c.criteria},
            "metrics": c.metrics,
        }
    return {"format": FORMAT, "suite": result.suite.name, "cases": cases}


def save_baseline(result: SuiteResult, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_json(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_baseline(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != FORMAT or "cases" not in data:
        raise ValueError(f"{path} is not a SimView test baseline (format {FORMAT})")
    return data


@dataclass(frozen=True)
class Drift:
    case: str
    metric: str
    baseline: float
    now: float

    @property
    def relative(self) -> float:
        return (self.now - self.baseline) / abs(self.baseline) if self.baseline else float("inf")

    def describe(self) -> str:
        return (
            f"{self.case}: {self.metric} {self.baseline:.6g} -> {self.now:.6g} "
            f"({self.relative:+.1%})"
        )


@dataclass
class BaselineDiff:
    new_failures: list[tuple[str, str]] = field(default_factory=list)  # (case, criterion)
    newly_passing: list[tuple[str, str]] = field(default_factory=list)
    drifts: list[Drift] = field(default_factory=list)
    new_errors: list[str] = field(default_factory=list)  # cases that error now, not before
    new_cases: list[str] = field(default_factory=list)  # not in the baseline
    missing_cases: list[str] = field(default_factory=list)  # in the baseline, not run now

    @property
    def regressions(self) -> int:
        return len(self.new_failures) + len(self.drifts) + len(self.new_errors)

    @property
    def differences(self) -> int:
        return (
            self.regressions
            + len(self.newly_passing)
            + len(self.new_cases)
            + len(self.missing_cases)
        )

    def lines(self) -> list[str]:
        out = [f"regression: new failure {case}: {crit}" for case, crit in self.new_failures]
        out += [f"regression: {case} errors (it ran in the baseline)" for case in self.new_errors]
        out += [f"regression: metric drift {d.describe()}" for d in self.drifts]
        out += [f"newly passing {case}: {crit}" for case, crit in self.newly_passing]
        out += [f"new case (not in the baseline) {c}" for c in self.new_cases]
        out += [f"missing case (in the baseline) {c}" for c in self.missing_cases]
        return out

    def summary(self) -> str:
        if not self.differences:
            return "baseline: no differences"
        return (
            f"baseline: {self.regressions} regression{'s' if self.regressions != 1 else ''} "
            f"({len(self.new_failures)} new failures, {len(self.drifts)} metric drifts, "
            f"{len(self.new_errors)} new errors), {len(self.newly_passing)} newly passing"
        )

    def html(self) -> str:
        esc = html.escape
        items = "".join(f"<li>{esc(line)}</li>" for line in self.lines())
        body = f"<ul>{items}</ul>" if items else "<p class=muted>No differences.</p>"
        return f"<section><h2>Against the baseline</h2><p>{esc(self.summary())}</p>{body}</section>"


def compare_baseline(result: SuiteResult, baseline: dict[str, Any]) -> BaselineDiff:
    diff = BaselineDiff()
    base = baseline["cases"]
    now = {c.key: c for c in result.cases}
    diff.missing_cases = sorted(set(base) - set(now))
    for key, case in now.items():
        b = base.get(key)
        if b is None:
            diff.new_cases.append(key)
            continue
        if case.status == ERROR:
            if b["status"] != ERROR:
                diff.new_errors.append(key)
            continue
        for cr in case.criteria:
            was = b["criteria"].get(cr.criterion.name)
            if was is None:
                continue  # a criterion added since the baseline: its result is just reported
            if was and not cr.passed:
                diff.new_failures.append((key, cr.criterion.name))
            elif not was and cr.passed:
                diff.newly_passing.append((key, cr.criterion.name))
        for metric, value in case.metrics.items():
            old = b["metrics"].get(metric)
            if old is None:
                continue
            rtol = case.scenario.tolerance_for(metric)
            if abs(value - old) > case.scenario.atol + rtol * abs(old):
                diff.drifts.append(Drift(key, metric, float(old), float(value)))
    return diff


def gate_passed(result: SuiteResult, diff: BaselineDiff | None) -> bool:
    """Without a baseline every case must pass; with one, there must be no regressions
    (failures already in the baseline are reported but don't fail the gate, D-144)."""
    if diff is None:
        return all(c.status == PASSED for c in result.cases)
    return diff.regressions == 0
