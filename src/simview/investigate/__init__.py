"""Run investigation (PRD §5.11, RI-01..RI-06): find out why a run went wrong.

from simview import investigate as inv

catalog = inv.Catalog("runs")                      # every run's log in a folder (RI-01)
fast = inv.Scenario("fast elbow", "ur5.elbow_joint.v > 2.0 for 0.05 s")   # RI-02
results = inv.scan(catalog, [fast])                 # cached: only new runs are read
for r in results:
    for f in r.findings:                            # run, signals, window (RI-03)
        print(f.describe())
runs = [catalog.open(r) for r in catalog.runs()]
inv.write_report(runs, results, "report.html")       # RI-04
inv.compare(catalog.open("a"), catalog.open("b"), atol=1e-6)                       # RI-05
inv.import_log("robot.csv", catalog, mapping={"ur5.shoulder_pan_joint.q": "j1"})  # RI-06
"""

from simview.investigate.compare import Comparison, SignalDiff, compare
from simview.investigate.importer import import_log
from simview.investigate.report import write_report
from simview.investigate.runs import Catalog, RunData, RunInfo, read_info
from simview.investigate.scenario import (
    Finding,
    ScanResult,
    Scenario,
    ScenarioError,
    Window,
    load_scenarios,
    save_scenarios,
    scan,
    windows,
)

__all__ = [
    "Catalog",
    "Comparison",
    "Finding",
    "RunData",
    "RunInfo",
    "ScanResult",
    "Scenario",
    "ScenarioError",
    "SignalDiff",
    "Window",
    "compare",
    "import_log",
    "load_scenarios",
    "read_info",
    "save_scenarios",
    "scan",
    "windows",
    "write_report",
]
