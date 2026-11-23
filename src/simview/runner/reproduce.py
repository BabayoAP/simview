"""`simview reproduce <run>` (RP-02): re-run a run from its manifest and say whether the new log
is identical, or where it first diverges (RI-05), and what changed in the environment.

    simview reproduce runs/20261122-101500-seed0.parquet

Exit code 0: identical. 1: diverged. 2: could not be reproduced (no scene file, the scene fails
to load, an imported log). The scene is re-run headless with the run's seed, start parameters
and duration (from the log's metadata); signals are compared exactly (atol 0) unless
`--atol` / `--rtol` are given.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from simview.investigate.compare import Comparison, compare
from simview.investigate.runs import RunData, RunInfo, read_info
from simview.runner.manifest import build_manifest, differences, read_manifest


class ReproduceError(RuntimeError):
    """The run can't be re-run (no scene file, an imported log, the scene fails to load)."""


@dataclass
class Reproduction:
    run: RunInfo
    identical: bool
    first_signal: str | None = None  # the first diverging signal (earliest time, then name)
    first_time: float | None = None  # s
    notes: list[str] = field(default_factory=list)  # row count / signal set mismatches
    environment: list[str] = field(default_factory=list)  # manifest vs now (RP-02)
    has_manifest: bool = True
    comparison: Comparison | None = None
    new_log: Path | None = None  # kept only when asked

    def describe(self) -> str:
        lines = [f"{self.run.name}: " + ("identical" if self.identical else "DIVERGED")]
        if self.first_signal is not None:
            lines.append(f"  first divergence: {self.first_signal} at {self.first_time:.6g} s")
        lines += [f"  {n}" for n in self.notes]
        if not self.has_manifest:
            lines.append("  no manifest (run made before RP-01): environment not compared")
        elif self.environment:
            lines.append("  environment differences:")
            lines += [f"    {d}" for d in self.environment]
        else:
            lines.append("  environment: no differences")
        return "\n".join(lines)


def reproduce(
    run: str | Path,
    *,
    atol: float = 0.0,
    rtol: float = 0.0,
    keep: str | Path | None = None,
) -> Reproduction:
    """Re-run `run` (a Parquet log) from its manifest and compare. `keep` saves the new log
    there instead of a temporary folder."""
    from simview.runner.headless import load_scene
    from simview.runner.run import run as run_scene

    path = Path(run)
    if not path.is_file():
        raise ReproduceError(f"no run log {path}")
    info = read_info(path)
    if info.source == "import":
        raise ReproduceError(f"{info.name} is an imported log; there is no scene to re-run")
    if not info.scene or not Path(info.scene).is_file():
        raise ReproduceError(f"{info.name}: its scene file {info.scene or '(none)'} is not found")
    manifest = read_manifest(path)
    try:
        scene = load_scene(info.scene, params=info.params, seed=info.seed)
    except Exception as exc:
        raise ReproduceError(f"{info.scene} failed to load: {exc}") from exc
    tmp = Path(tempfile.mkdtemp(prefix="simview-reproduce-"))
    try:
        out = Path(keep) if keep is not None else tmp / "reproduced.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        new = run_scene(scene, info.duration, out=out)
        new_data, old_data = RunData(read_info(new.path)), RunData(info)
        result = _compare(info, old_data, new_data, atol, rtol)
        now = build_manifest(scene, log=new.path)
        if manifest is not None:
            result.environment = differences(manifest, now)
        else:
            result.has_manifest = False
        result.new_log = new.path if keep is not None else None
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _compare(info: RunInfo, old: RunData, new: RunData, atol: float, rtol: float) -> Reproduction:
    c = compare(new, old, atol=atol, rtol=rtol)
    notes = []
    if len(new.t) != len(old.t):
        notes.append(f"samples: {len(old.t)} (run) vs {len(new.t)} (now)")
    elif not np.array_equal(new.t, old.t):
        notes.append("sample times differ")
    if c.only_in_baseline:
        notes.append(f"no longer logged: {', '.join(c.only_in_baseline)}")
    if c.only_in_run:
        notes.append(f"newly logged: {', '.join(c.only_in_run)}")
    diverged = sorted(c.diverged, key=lambda d: (d.first_divergence, d.signal))
    first = diverged[0] if diverged else None
    return Reproduction(
        run=info,
        identical=not diverged and not notes,
        first_signal=first.signal if first else None,
        first_time=first.first_divergence if first else None,
        notes=notes,
        comparison=c,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="simview reproduce",
        description="Re-run a run from its manifest and check the result is identical (RP-02).",
    )
    parser.add_argument("run", type=Path, help="the run's Parquet log")
    parser.add_argument("--atol", type=float, default=0.0, help="absolute tolerance (default 0)")
    parser.add_argument("--rtol", type=float, default=0.0, help="relative tolerance (default 0)")
    parser.add_argument("--keep", type=Path, help="save the re-run's log here")
    args = parser.parse_args(argv)
    try:
        result = reproduce(args.run, atol=args.atol, rtol=args.rtol, keep=args.keep)
    except ReproduceError as exc:
        print(f"cannot reproduce: {exc}")
        return 2
    print(result.describe())
    return 0 if result.identical else 1
