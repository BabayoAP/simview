"""Suite outputs (ST-02): a JUnit XML file for CI and an HTML report built from RI-04's pieces.

JUnit layout: one `<testsuite>` per scenario, one `<testcase>` per sample (named by its index
and parameters), a `<failure>` per failed criterion naming the criterion and its evidence
window, an `<error>` when the scene raised. CI systems (GitHub Actions, GitLab, Jenkins) read
this format as-is.
"""

from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from simview.investigate import report as ri_report
from simview.testing.suite import ERROR, FAILED, PASSED, CaseResult, SuiteResult

MAX_REPORTED_RUNS = 20  # failing runs that get a full RI-04 section (plots, stats)


def write_junit(result: SuiteResult, path: str | Path) -> Path:
    path = Path(path)
    root = ET.Element(
        "testsuites",
        name=result.suite.name,
        tests=str(len(result.cases)),
        failures=str(result.count(FAILED)),
        errors=str(result.count(ERROR)),
        time=f"{result.wall_s:.3f}",
    )
    for sc in result.suite.scenarios:
        cases = [c for c in result.cases if c.scenario is sc]
        ts = ET.SubElement(
            root,
            "testsuite",
            name=f"{result.suite.name}.{sc.name}",
            tests=str(len(cases)),
            failures=str(sum(c.status == FAILED for c in cases)),
            errors=str(sum(c.status == ERROR for c in cases)),
            time=f"{sum(c.wall_s for c in cases):.3f}",
        )
        props = ET.SubElement(ts, "properties")
        ET.SubElement(props, "property", name="scene", value=str(sc.scene))
        ET.SubElement(props, "property", name="duration", value=f"{sc.duration:g}")
        ET.SubElement(props, "property", name="seed", value=str(sc.seed))
        for case in cases:
            tc = ET.SubElement(
                ts,
                "testcase",
                classname=f"{result.suite.name}.{sc.name}",
                name=case.label,
                time=f"{case.wall_s:.3f}",
            )
            if case.status == ERROR:
                err = ET.SubElement(tc, "error", message=case.error or "the run failed")
                err.text = case.error
            for cr in case.failures:
                f = ET.SubElement(
                    tc,
                    "failure",
                    message=f"{cr.criterion.name}: {cr.message}",
                    type=cr.criterion.verb,
                )
                lines = [f"criterion: {cr.criterion.text}", f"result: {cr.message}"]
                lines += [f"evidence: {w.start:.3f} to {w.end:.3f} s" for w in cr.windows[:5]]
                lines += [f"seed: {case.seed}", f"log: {case.log or '-'}"]
                f.text = "\n".join(lines)
            if case.log is not None:
                ET.SubElement(tc, "system-out").text = f"log: {case.log}"
    ET.indent(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def _css() -> str:
    c = ri_report._color
    ok, bad = c("state.success"), c("state.error")
    return f".ok {{ color: {ok}; }} .bad {{ color: {bad}; font-weight: 600; }}"


def _status_cell(case: CaseResult) -> str:
    cls = {PASSED: "ok", FAILED: "bad", ERROR: "bad"}[case.status]
    return f"<td class={cls}>{case.status}</td>"


def _case_rows(cases: Sequence[CaseResult]) -> str:
    esc = html.escape
    rows = []
    for c in cases:
        detail = "; ".join(f"{cr.criterion.name}: {cr.message}" for cr in c.failures)
        if c.status == ERROR:
            detail = c.error
        metrics = ", ".join(f"{k} {v:.4g}" for k, v in c.metrics.items())
        rows.append(
            f"<tr><td>{esc(c.label)}</td>{_status_cell(c)}<td>{esc(detail)}</td>"
            f"<td>{esc(metrics)}</td><td>{esc(c.log.name if c.log else '—')}</td></tr>"
        )
    return "".join(rows)


def write_html(result: SuiteResult, path: str | Path, *, baseline_section: str = "") -> Path:
    """One HTML file: the verdicts, then an RI-04 run section (evidence windows shaded) for
    each failing run, up to MAX_REPORTED_RUNS."""
    path = Path(path)
    esc = html.escape
    title = f"Test report: {result.suite.name}"
    verdict = "PASSED" if result.passed else "FAILED"
    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        "<meta name=viewport content='width=device-width, initial-scale=1'>",
        f"<title>{esc(title)}</title><style>{ri_report._css()}{_css()}</style></head><body>",
        f"<h1>{esc(title)}</h1>",
        f"<p class=muted>SimView, {datetime.now().isoformat(timespec='seconds')}. "
        f"{esc(result.summary())}</p>",
        f"<p class={'ok' if result.passed else 'bad'}>{verdict}</p>",
    ]
    if baseline_section:
        parts.append(baseline_section)
    for sc in result.suite.scenarios:
        cases = [c for c in result.cases if c.scenario is sc]
        crit = "".join(f"<li><code>{esc(c.text)}</code></li>" for c in sc.criteria)
        parts.append(
            f"<section><h2>{esc(sc.name)}</h2><p class=muted>{esc(str(sc.scene))}, "
            f"{sc.duration:g} s, seed {sc.seed}</p><ul>{crit}</ul>"
            "<table><tr><th>Case</th><th>Result</th><th>Details</th><th>Metrics</th>"
            f"<th>Log</th></tr>{_case_rows(cases)}</table></section>"
        )
    failing = [c for c in result.cases if c.status == FAILED][:MAX_REPORTED_RUNS]
    for c in failing:
        data = c.run_data()
        if data is None:
            continue
        section = ri_report._run_section(data, [cr.scan_result(data) for cr in c.failures])
        parts.append(
            section.replace(f"<h2>{esc(data.info.name)}</h2>", f"<h2>{esc(c.label)}</h2>", 1)
        )
    parts.append("</body></html>\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")
    return path
