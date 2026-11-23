"""`simview run scene.py --headless` (SE-05 CLI) and loading `scene.py` files (SC-04)."""

from __future__ import annotations

import argparse
import runpy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from simview.core.params import overrides
from simview.core.scene import Scene
from simview.runner.run import run


def load_scene(
    path: str | Path,
    *,
    params: Mapping[str, Any] | None = None,
    seed: int | None = None,
) -> Scene:
    """Execute a scene file and return its module-level `scene` (a `simview.Scene`).

    `params` replaces the values the file declares (`scene.params.gust = 1.5`) while the file
    runs, so code that reads them during setup sees the new values (D-106). Naming a parameter
    the file doesn't declare is an error. `seed` replaces the scene's seed."""
    with overrides(params or {}) as used:
        namespace = runpy.run_path(str(path), run_name="__simview_scene__")
    scene = namespace.get("scene")
    if not isinstance(scene, Scene):
        raise TypeError(f"{path} must define a module-level `scene = simview.Scene(...)`")
    unknown = sorted(set(params or {}) - used)
    if unknown:
        known = ", ".join(scene.params) or "none"
        raise KeyError(f"{path} declares no parameter {', '.join(unknown)} (declared: {known})")
    if seed is not None:
        scene.seed = int(seed)
    scene.file = Path(path).resolve()
    return scene


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simview run", description="Run a scene file.")
    parser.add_argument("scene", type=Path, help="path to a scene.py file")
    parser.add_argument("--headless", action="store_true", help="no rendering (required for now)")
    parser.add_argument("--duration", type=float, default=10.0, help="seconds (default 10)")
    parser.add_argument("--seed", type=int, help="override the scene's seed")
    parser.add_argument("--out", type=Path, help="Parquet log path (default runs/<time>.parquet)")
    parser.add_argument(
        "--no-machine-info",
        action="store_true",
        help="leave OS, CPU and hostname out of the run manifest (RP-01)",
    )
    args = parser.parse_args(argv)
    if args.no_machine_info:
        import os

        from simview.runner.manifest import NO_MACHINE_ENV

        os.environ[NO_MACHINE_ENV] = "1"
    if not args.headless:
        parser.error("live runs arrive with the viewport (M4); pass --headless")
    scene = load_scene(args.scene)
    if args.seed is not None:
        scene.seed = args.seed
    result = run(scene, args.duration, out=args.out)
    print(f"{result.ticks} ticks in {result.wall_s:.2f} s (RTF {result.rtf:.1f}x) -> {result.path}")
    return 0
