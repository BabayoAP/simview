"""Measure SimView against the PRD's non-functional targets NF-02, NF-03, NF-05, NF-06, NF-07
(M10 performance pass, D-117). NF-01 and NF-04 are measured by the GL and IPC tests.

    python benchmarks/nf_bench.py              # all, quick (NF-07 on a 60 s run, scaled)
    python benchmarks/nf_bench.py nf03 nf07 --full   # NF-07 on the real 10-minute run

Each check runs in a fresh child process, so imports and startup are counted where the target
includes them (NF-05) and memory isn't shared between checks. Prints one line per target and
a Markdown table at the end (pasted into docs/PROGRESS.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UC2 = ROOT / "src" / "simview" / "templates" / "drone_delivery" / "scene.py"
UC3 = ROOT / "examples" / "ur5_pick.py"

# Child-process snippets. Each prints one JSON object on its last line.
RTF = """
import json, sys, time
from simview.runner.headless import load_scene
from simview.runner.run import run
scene = load_scene(sys.argv[1])
scene.dt = float(sys.argv[2])
r = run(scene, float(sys.argv[3]), out=sys.argv[4])
print(json.dumps({"rtf": r.rtf, "wall": r.wall_s, "ticks": r.ticks}))
"""

PEAK_RSS = """
def peak_rss_mb():
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / 2**20 if sys.platform == "darwin" else peak / 2**10
    except ImportError:  # Windows: psutil comes with ipykernel
        import psutil
        return psutil.Process().memory_info().peak_wset / 2**20
"""

MEMORY = (
    """
import json, sys
from simview.runner.headless import load_scene
from simview.runner.run import run
scene = load_scene(sys.argv[1])
scene.dt = float(sys.argv[2])
r = run(scene, float(sys.argv[3]), out=sys.argv[4])
"""
    + PEAK_RSS
    + 'print(json.dumps({"peak_mb": peak_rss_mb(), "rtf": r.rtf}))\n'
)

COLD_START = """
import json, os, sys, time
import psutil
born = psutil.Process().create_time()
from qtpy.QtCore import QTimer
from simview.ui.app import Controller, create_app, default_settings
app = create_app([sys.argv[0]])
controller = Controller(default_settings())
which = sys.argv[1]
if which == "start":
    shown = controller.start
    controller.start.show()
else:
    shown = controller.open_window("untitled", "Untitled")
def usable():
    # The event loop is running and the window has painted: it takes input now.
    print(json.dumps({"seconds": time.time() - born}), flush=True)
    shown.close()
    app.quit()
QTimer.singleShot(0, usable)
app.exec()
os._exit(0)  # skip slow interpreter teardown (VTK, kernel); not part of startup
"""


def child(code: str, *args: str, env: dict[str, str] | None = None) -> dict[str, float]:
    out = subprocess.run(
        [sys.executable, "-c", code, *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, **(env or {})},
        check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"child failed ({out.returncode}):\n{out.stderr[-2000:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def nf02(tmp: Path, full: bool) -> tuple[str, str, bool]:
    r = child(RTF, str(UC3), "1e-3", "10", str(tmp / "uc3.parquet"))
    return f"{r['rtf']:.1f}x (UC-3 pick, dt 1 ms, 10 s)", ">= 20x", r["rtf"] >= 20


def nf03(tmp: Path, full: bool) -> tuple[str, str, bool]:
    r = child(RTF, str(UC2), "1e-3", "30", str(tmp / "uc2.parquet"))
    return f"{r['rtf']:.1f}x (UC-2, dt 1 ms, 30 s)", ">= 10x", r["rtf"] >= 10


def nf05(tmp: Path, full: bool) -> tuple[str, str, bool]:
    env = {"QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "")}
    child(COLD_START, "start", env=env)  # first launch warms the OS file cache
    start = min(child(COLD_START, "start", env=env)["seconds"] for _ in range(3))
    main = min(child(COLD_START, "main", env=env)["seconds"] for _ in range(3))
    text = f"start screen {start:.2f} s, main window {main:.2f} s (best of 3)"
    return text, "<= 4 s", max(start, main) <= 4.0


def nf06(tmp: Path, full: bool) -> tuple[str, str, bool]:
    digests = set()
    for i in range(10):
        path = tmp / f"det{i}.parquet"
        child(RTF, str(UC2), "1e-3", "5", str(path))
        digests.add(hashlib.sha256(path.read_bytes()).hexdigest())
    return f"{len(digests)} distinct log(s) in 10 UC-2 runs (5 s)", "1", len(digests) == 1


def nf07(tmp: Path, full: bool) -> tuple[str, str, bool]:
    seconds = 600.0 if full else 60.0
    r = child(MEMORY, str(UC2), "1e-3", str(seconds), str(tmp / "mem.parquet"))
    peak = r["peak_mb"]
    if full:
        return f"peak {peak:.0f} MB (UC-2, 10 min)", "<= 2048 MB", peak <= 2048
    # The log is preallocated (rows x columns x 8 bytes) and dominates growth: scale it.
    base = child(MEMORY, str(UC2), "1e-3", "1", str(tmp / "mem0.parquet"))["peak_mb"]
    est = base + (peak - base) * 600.0 / (seconds - 1.0)
    text = f"peak {peak:.0f} MB at 60 s, ~{est:.0f} MB est. for 10 min (--full measures it)"
    return text, "<= 2048 MB", est <= 2048


CHECKS = {"nf02": nf02, "nf03": nf03, "nf05": nf05, "nf06": nf06, "nf07": nf07}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("checks", nargs="*", help=f"any of {', '.join(CHECKS)} (default: all)")
    parser.add_argument("--full", action="store_true", help="NF-07 on the full 10-minute run")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # the table's marks
    unknown = set(args.checks) - set(CHECKS)
    if unknown:
        parser.error(f"unknown check(s): {', '.join(sorted(unknown))}")
    rows = []
    with tempfile.TemporaryDirectory() as d:
        for name in args.checks or CHECKS:
            measured, target, ok = CHECKS[name](Path(d), args.full)
            label = f"NF-{name[2:]}"
            print(f"{label}: {measured}  target {target}  {'PASS' if ok else 'MISS'}", flush=True)
            rows.append((label, target, measured, "✅" if ok else "❌"))
    print(
        f"\n{platform.platform()}, {platform.processor() or platform.machine()}, "
        f"Python {platform.python_version()}\n"
    )
    print("| Target | Required | Measured | |\n|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join(row) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
