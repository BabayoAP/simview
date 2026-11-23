"""Measure the M11 target "`vision_drive` runs headless at >= 1x real time" (D-133).

    python benchmarks/vision_bench.py              # 14 s run of layout 0, 3 repeats
    python benchmarks/vision_bench.py --repeats 5 --duration 20

Each repeat runs in a fresh child process (like nf_bench.py) and reports the real-time factor of
the whole run: 8 cameras ray cast at 10 Hz, back-projection, fusion into the occupancy grid, BEV,
the planner, the logged perception signals (incl. IoU), and the snapshots written beside the log.
Prints the median and a pass/fail line.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "src" / "simview" / "templates" / "vision_drive" / "scene.py"

RTF = """
import json, sys
from simview.runner.headless import load_scene
from simview.runner.run import run
scene = load_scene(sys.argv[1])
r = run(scene, float(sys.argv[2]), out=sys.argv[3])
print(json.dumps({"rtf": r.rtf, "wall": r.wall_s}))
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--duration", type=float, default=14.0)
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    rtfs = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(args.repeats):
            out = Path(tmp) / f"run{i}.parquet"
            proc = subprocess.run(
                [sys.executable, "-c", RTF, str(SCENE), str(args.duration), str(out)],
                capture_output=True,
                text=True,
                check=True,
            )
            res = json.loads(proc.stdout.strip().splitlines()[-1])
            rtfs.append(res["rtf"])
            print(f"run {i}: {res['wall']:.2f} s wall for {args.duration} s -> {res['rtf']:.2f}x")
    med = statistics.median(rtfs)
    ok = med >= 1.0
    print(f"vision_drive RTF median {med:.2f}x (target >= 1x): {'PASS' if ok else 'FAIL'}")
    cpu = platform.processor() or platform.machine()
    print(f"machine: {cpu}, Python {platform.python_version()}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
