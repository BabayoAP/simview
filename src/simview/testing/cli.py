"""`simview test suite.toml` (ST-02, ST-03): run a suite headless, write JUnit XML and an HTML
report, optionally save or check a baseline. Exit code 0 when the gate passes, 1 when it fails
(a failing case, or with `--baseline` a regression), 2 when the suite can't be run."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from simview.testing.baseline import compare_baseline, gate_passed, load_baseline, save_baseline
from simview.testing.output import write_html, write_junit
from simview.testing.scenario import SuiteError, load_suite
from simview.testing.suite import PASSED, CaseResult, run_suite, slug


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="simview test", description="Run a scenario test suite (PRD §5.13)."
    )
    parser.add_argument("suite", type=Path, help="a suite .toml or .py file")
    parser.add_argument("--out", type=Path, help="output folder (default runs/test-<suite>-<time>)")
    parser.add_argument("--junit", type=Path, help="JUnit XML path (default <out>/junit.xml)")
    parser.add_argument("--report", type=Path, help="HTML report path (default <out>/report.html)")
    parser.add_argument("--workers", type=int, help="parallel processes (default: CPU count)")
    parser.add_argument("--baseline", type=Path, help="compare against this baseline (ST-03)")
    parser.add_argument("--save-baseline", type=Path, help="save the results as a baseline here")
    parser.add_argument(
        "--no-machine-info",
        action="store_true",
        help="leave OS, CPU and hostname out of the run manifests (RP-01)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="print only the summary")
    args = parser.parse_args(argv)
    if args.no_machine_info:
        from simview.runner.manifest import NO_MACHINE_ENV

        os.environ[NO_MACHINE_ENV] = "1"  # inherited by the sweep's worker processes
    try:
        suite = load_suite(args.suite)
        baseline = load_baseline(args.baseline) if args.baseline else None
    except (SuiteError, OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
    out = args.out or Path("runs") / f"test-{slug(suite.name)}-{time.strftime('%Y%m%d-%H%M%S')}"

    def show(case: CaseResult) -> None:
        if args.quiet:
            return
        mark = "ok  " if case.status == PASSED else case.status.upper()
        print(f"{mark} {case.label}")
        for cr in case.failures:
            print(f"     {cr.criterion.name}: {cr.message}")
        if case.error:
            print(f"     {case.error}")

    try:
        result = run_suite(suite, out, workers=args.workers, on_case=show)
    except (FileNotFoundError, SuiteError) as exc:
        print(f"error: {exc}")
        return 2
    diff = compare_baseline(result, baseline) if baseline is not None else None
    junit = write_junit(result, args.junit or out / "junit.xml")
    report = write_html(
        result, args.report or out / "report.html", baseline_section=diff.html() if diff else ""
    )
    print(result.summary())
    if diff is not None:
        print(diff.summary())
        for line in diff.lines():
            print(f"  {line}")
    if args.save_baseline:
        print(f"baseline saved to {save_baseline(result, args.save_baseline)}")
    print(f"JUnit: {junit}\nReport: {report}")
    return 0 if gate_passed(result, diff) else 1
