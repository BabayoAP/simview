"""Scenario testing and regression gates (PRD §5.13: ST-01 to ST-03)."""

from simview.testing.baseline import BaselineDiff, compare_baseline, load_baseline, save_baseline
from simview.testing.scenario import Criterion, SuiteError, TestScenario, TestSuite, load_suite
from simview.testing.suite import CaseResult, SuiteResult, run_suite

__all__ = [
    "BaselineDiff",
    "CaseResult",
    "Criterion",
    "SuiteError",
    "SuiteResult",
    "TestScenario",
    "TestSuite",
    "compare_baseline",
    "load_baseline",
    "load_suite",
    "run_suite",
    "save_baseline",
]
